"""Swarm maneuver probe: does the truth ephemeris contain an ENERGY STEP?

Written 2026-08-22 after window 4 came back with a railed Cd fit and a day-7
"inversion" that the degree-5 polynomial screen passed as CLEAN. The polynomial
is the Swarm leg's only maneuver gate, and it normalizes a departure by the peak
along-track signal -- so a maneuver large enough to inflate that signal hides
inside its own denominator. Window 4 Swarm A departed its degree-5 fit by
73,403 m, 760x the worst clean Swarm window, and still scored 6.5 % against the
10 % bar.

This probe tests the one thing drag cannot do: **change orbital energy upward.**
Atmospheric drag removes energy monotonically, so a rise in semi-major axis --
or any step at all -- is a maneuver, a data defect, or nothing.

METHOD, per satellite per window
    1. Parse the delivered SP3 at its NATIVE 10 s grid (not the study's 60 s
       subsample) through the same ``swarm_sp3`` reader the drag driver uses.
    2. Quasi-inertial velocity ``v_i = v_ecef + omega_e x r``. The delivered
       V-records are Earth-fixed (measured; see ``swarm_sp3``), and vis-viva
       needs an inertial speed.
    3. Osculating semi-major axis by vis-viva, ``a = 1/(2/r - v_i^2/mu)``.
    4. **One-revolution boxcar**, width set from that satellite's own measured
       nodal period. This step is not optional: the raw osculating ``a`` carries
       ~10 km of J2 short-period ripple, which buries the ~2 km step being
       hunted. The boxcar is the only reason the signal is visible at all.
    5. Difference the smoothed series one revolution apart, and score that
       against a robust (median / MAD) noise scale.

DETECTION RULE, fixed before the sweep and not tuned: robust ``|z| > 20``. The
measured gap makes the exact value irrelevant -- clean satellite-windows top out
near 4 sigma and the one detection sits above 250, so anything from 10 to 100
returns the identical verdict. Absolute metres are printed beside every z so no
reader has to take the sigma on faith.

WHAT THIS PROBE DOES NOT DO. It is sharper than the polynomial for the maneuvers
that matter here, but it is not a replacement for it and not an exact gate the
way GRACE-FO's THR1B is:

- it sees ENERGY changes, so a pure cross-track or inclination burn is invisible
- a bad POD day could in principle mimic a step
- it says nothing about safe-mode entries or attitude anomalies, which is
  precisely what the contract keeps the polynomial for

The two are complementary. Neither subsumes the other.

SCOPE. The 8 loaded days of each frozen window -- exactly the span Part 2's drag
rows rest on, and all that is downloaded for Swarm.

``mu`` below is a diagnostic constant, not a force model: the probe never
propagates, and only DIFFERENCES in ``a`` carry the verdict, so the choice
between WGS84 and EGM96 mu shifts every number by ~1e-5 m and no conclusion.

JVM-FREE -- it reads files and does arithmetic, so it needs no Orekit and no
orekit-data. Reference-only: not shipped, not in CI, outside ``testpaths``.
Not registered in ``run_all.py``; this is recorded evidence, not a gated group.

    conda run -n propygator python probe_energy_step.py
    conda run -n propygator python probe_energy_step.py moderate_2022_04

Writes ``results_energy_step.txt`` beside itself (ASCII, CRLF, matching the
study's committed evidence) and echoes the same report to stdout.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_SWARM = _HERE.parent
_STUDY = _SWARM.parent
_FROZEN = _STUDY.parent / "real-world-validation"
for _p in (str(_SWARM), str(_STUDY), str(_STUDY / "gracefo"), str(_FROZEN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from drag_common import display_path, pkg_version  # noqa: E402
from gracefo_ext_common import LOAD_DAYS  # noqa: E402
from swarm_common import DATA_ROOT  # noqa: E402
from swarm_sp3 import (  # noqa: E402
    NATIVE_INTERVAL_S,
    SAT_IDS,
    find_swarm_files,
    parse_swarm_sp3,
)
from windows import WINDOWS, resolve  # noqa: E402

MU_M3_S2 = 3.986004418e14  # WGS84; diagnostic only -- see the module docstring
OMEGA_EARTH_RAD_S = 7.292115e-5

# Pre-registered, not tuned. See the module docstring: the clean/detected gap is
# three orders of magnitude wide, so the exact cut carries no weight.
Z_STEP = 20.0

DEFAULT_OUT = "results_energy_step.txt"


# --- kinematics ---------------------------------------------------------------
def osculating_sma(positions_m: np.ndarray, velocities_ms: np.ndarray) -> np.ndarray:
    """Vis-viva semi-major axis from ITRF position and EARTH-FIXED velocity."""
    v_inertial = velocities_ms.copy()
    v_inertial[:, 0] -= OMEGA_EARTH_RAD_S * positions_m[:, 1]
    v_inertial[:, 1] += OMEGA_EARTH_RAD_S * positions_m[:, 0]
    r = np.linalg.norm(positions_m, axis=1)
    v2 = np.einsum("ij,ij->i", v_inertial, v_inertial)
    return 1.0 / (2.0 / r - v2 / MU_M3_S2)


def ascending_nodes(t_s: np.ndarray, z_m: np.ndarray) -> np.ndarray:
    """Ascending-node crossing times, linearly interpolated.

    Frame-free to the precision that matters here: polar motion tilts the ITRF
    z-axis off the inertial one by well under an arcsecond.
    """
    up = np.nonzero((z_m[:-1] < 0.0) & (z_m[1:] >= 0.0))[0]
    return t_s[up] + (t_s[up + 1] - t_s[up]) * (-z_m[up] / (z_m[up + 1] - z_m[up]))


def one_rev_mean(
    t_s: np.ndarray, a_m: np.ndarray, period_s: float
) -> tuple[np.ndarray, np.ndarray]:
    """Boxcar ``a`` over one nodal revolution; returns (centred times, means)."""
    dt = t_s[1] - t_s[0]
    n = max(1, int(round(period_s / dt)))
    smooth = np.convolve(a_m, np.ones(n) / n, mode="valid")
    centres = t_s[n - 1 :] - 0.5 * (n - 1) * dt
    return centres, smooth


# --- the screen ---------------------------------------------------------------
def screen(
    centres_s: np.ndarray, smooth_m: np.ndarray, period_s: float
) -> dict[str, float]:
    """Score the one-revolution change in the smoothed ``a`` robustly.

    The change is attributed to the MIDPOINT of the pair it differences, not to
    its late end -- otherwise every reported epoch sits half a revolution late.
    """
    dt = centres_s[1] - centres_s[0]
    lag = max(1, int(round(period_s / dt)))
    delta = smooth_m[lag:] - smooth_m[:-lag]
    at = 0.5 * (centres_s[lag:] + centres_s[:-lag])
    median = float(np.median(delta))
    mad = float(np.median(np.abs(delta - median)))
    sigma = 1.4826 * mad if mad > 0.0 else 1.0
    z = (delta - median) / sigma
    i = int(np.argmax(np.abs(z)))
    return {
        "median_m": median,
        "sigma_m": sigma,
        "worst_m": float(delta[i]),
        "worst_z": float(z[i]),
        "worst_t_s": float(at[i]),
        "stepped": abs(z[i]) > Z_STEP,
    }


def characterize(
    centres_s: np.ndarray,
    smooth_m: np.ndarray,
    node_times_s: np.ndarray,
    period_s: float,
    event_t_s: float,
) -> dict[str, float]:
    """Level, epoch, duration and implied dV of a detected step."""

    def level(lo: float, hi: float) -> float:
        m = (centres_s >= event_t_s + lo) & (centres_s <= event_t_s + hi)
        return float(np.mean(smooth_m[m]))

    pre = level(-2.0 * period_s, -1.0 * period_s)
    post = level(1.0 * period_s, 2.0 * period_s)
    delta_a = post - pre

    def crossing(fraction: float) -> float:
        """First time the smoothed curve reaches ``pre + fraction*delta_a``."""
        target = pre + fraction * delta_a
        m = (centres_s >= event_t_s - 2.0 * period_s) & (
            centres_s <= event_t_s + 2.0 * period_s
        )
        seg_t, seg_a = centres_s[m], smooth_m[m]
        hit = np.nonzero((seg_a >= target) if delta_a > 0 else (seg_a <= target))[0]
        return float(seg_t[hit[0]]) if hit.size else float("nan")

    # A single impulse smeared by a boxcar of width W is a ramp of width W, so
    # its 10-90 rise is exactly 0.8*W. Any excess is the burn's own duration.
    rise_10_90 = crossing(0.9) - crossing(0.1)
    duration = max(0.0, rise_10_90 / 0.8 - period_s)

    def mean_period(lo: float, hi: float) -> float:
        mids = 0.5 * (node_times_s[:-1] + node_times_s[1:])
        m = (mids >= event_t_s + lo) & (mids <= event_t_s + hi)
        return float(np.mean(np.diff(node_times_s)[m]))

    v_circ = float(np.sqrt(MU_M3_S2 / pre))
    return {
        "epoch_t_s": crossing(0.5),
        "pre_m": pre,
        "post_m": post,
        "delta_a_m": delta_a,
        "period_pre_s": mean_period(-4.0 * period_s, -1.0 * period_s),
        "period_post_s": mean_period(1.0 * period_s, 4.0 * period_s),
        "duration_s": duration,
        "dv_ms": 0.5 * v_circ * delta_a / pre,
    }


# --- one satellite-window -----------------------------------------------------
def run_sat(window, sat: str, data_root: Path) -> dict:
    """Screen one satellite over one window. Returns a row dict."""
    files = find_swarm_files(data_root / window.name, sat, window.days[:LOAD_DAYS])
    eph = parse_swarm_sp3(files, sat_id=sat, subsample_s=NATIVE_INTERVAL_S)

    # The parser has already asserted a uniform grid and seam continuity, so the
    # time base is exact by construction; one spot check keeps that honest
    # without building 69,120 Epoch differences.
    n = len(eph.epochs)
    t = np.arange(n, dtype=float) * NATIVE_INTERVAL_S
    span = eph.epochs[-1].seconds_since(eph.epochs[0])
    if abs(span - t[-1]) > 1e-6:
        raise SystemExit(
            f"{window.name} Swarm {sat}: grid spans {span:.3f} s, expected "
            f"{t[-1]:.3f} s -- the uniform-grid assumption does not hold"
        )

    a = osculating_sma(eph.positions_m, eph.velocities_ms)
    nodes = ascending_nodes(t, eph.positions_m[:, 2])
    period = float(np.mean(np.diff(nodes)))
    centres, smooth = one_rev_mean(t, a, period)
    result = screen(centres, smooth, period)

    row = {
        "window": window,
        "sat": sat,
        "n_records": n,
        "n_revs": len(nodes) - 1,
        "period_s": period,
        "alt_km": float(np.mean(np.linalg.norm(eph.positions_m, axis=1))) / 1e3
        - 6378.137,
        "net_da_m": float(a[-1] - a[0]),
        "epoch0": eph.epochs[0],
        **result,
    }
    if result["stepped"]:
        row["detail"] = characterize(
            centres, smooth, nodes, period, result["worst_t_s"]
        )
    return row


# --- report -------------------------------------------------------------------
_HEADER = (
    f"  {'win':>3}  {'window':<17s}  {'sat':<3}  {'alt km':>7}  {'sigma m':>7}  "
    f"{'worst m':>10}  {'z':>8}  verdict"
)


def format_row(row: dict) -> str:
    return (
        f"  {row['window'].index:>3}  {row['window'].name:<17s}  {row['sat']:<3}  "
        f"{row['alt_km']:7.1f}  {row['sigma_m']:7.2f}  {row['worst_m']:+10.1f}  "
        f"{row['worst_z']:+8.1f}  {'STEP' if row['stepped'] else 'clean'}"
    )


def format_detail(row: dict) -> list[str]:
    d = row["detail"]
    t0 = row["epoch0"]
    epoch = t0.shifted_by(d["epoch_t_s"])
    return [
        f"[detection]  window {row['window'].index:02d} {row['window'].name},"
        f" Swarm {row['sat']}",
        f"  step epoch        {epoch.to_iso()} TAI"
        f"   (t0 + {d['epoch_t_s'] / 86400.0:.4f} d)",
        f"  one-rev-mean a    {d['pre_m'] / 1e3:.3f} km -> {d['post_m'] / 1e3:.3f}"
        f" km   (da = {d['delta_a_m']:+.1f} m)",
        f"  nodal period      {d['period_pre_s']:.2f} s -> {d['period_post_s']:.2f}"
        f" s   (dT = {d['period_post_s'] - d['period_pre_s']:+.2f} s)",
        f"  implied dV        {d['dv_ms']:+.3f} m/s along-track, near-circular",
        f"  thrust duration   ~{d['duration_s']:.0f} s"
        f" (~{d['duration_s'] / row['period_s']:.2f} rev) beyond the boxcar ramp"
        f" -- {'extended or multi-burn' if d['duration_s'] > 600 else 'impulse-like'}",
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "window", nargs="?", help="one window name; default screens all ten"
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument(
        "--out",
        type=Path,
        default=_HERE / DEFAULT_OUT,
        help=f"report destination (default {DEFAULT_OUT} beside this script)",
    )
    args = parser.parse_args()

    windows = (resolve(args.window),) if args.window else WINDOWS
    data_root = args.data_root.resolve()

    lines: list[str] = []

    def emit(text: str = "") -> None:
        lines.append(text)
        print(text)

    emit("=" * 78)
    emit("Extended validation -- Swarm energy-step maneuver probe")
    emit("=" * 78)
    emit(f"[versions] propygator {pkg_version('propygator')}, numpy {np.__version__}")
    emit("[what]  one-revolution-mean semi-major axis from the delivered SP3 truth.")
    emit("  Drag removes energy monotonically, so a STEP is a maneuver, a data")
    emit("  defect, or nothing -- it is the one thing drag cannot produce.")
    emit("[why]   the degree-5 polynomial is this leg's only gate, and it")
    emit("  normalizes by the peak along-track signal, so a maneuver big enough")
    emit("  to inflate that signal hides inside its own denominator.")
    emit("[limits]  ENERGY only -- a pure cross-track or inclination burn is")
    emit("  invisible here, and a bad POD day could mimic a step. This does not")
    emit("  replace the polynomial, which catches safe-mode and attitude events.")
    emit(f"[detection]  robust |z| > {Z_STEP:.0f} on the one-revolution change in")
    emit("  the smoothed a, median/MAD scale. Pre-registered, NOT tuned: clean")
    emit("  windows top out near 4 sigma and the detection sits above 250, so any")
    emit("  cut from 10 to 100 gives the identical verdict.")
    emit(f"[scope]  the {LOAD_DAYS} loaded days of each frozen window, at the native")
    emit(
        f"  {NATIVE_INTERVAL_S:.0f} s grid -- exactly the span Part 2's drag rows"
        " rest on."
    )
    emit(f"[data root]  {display_path(data_root)}")
    emit("-" * 78)
    emit(_HEADER)

    rows: list[dict] = []
    skipped: list[str] = []
    for window in windows:
        for sat in SAT_IDS:
            try:
                row = run_sat(window, sat, data_root)
            except SystemExit as exc:
                reason = str(exc).split(".")[0]
                skipped.append(
                    f"  win {window.index:02d} {window.name} Swarm {sat}: {reason}"
                )
                emit(
                    f"  {window.index:>3}  {window.name:<17s}  {sat:<3}  "
                    f"{'-':>7}  {'-':>7}  {'-':>10}  {'-':>8}  SKIPPED"
                )
                continue
            rows.append(row)
            emit(format_row(row))

    emit("-" * 78)
    stepped = [r for r in rows if r["stepped"]]
    for row in stepped:
        for line in format_detail(row):
            emit(line)
        emit()

    if skipped:
        emit("[skipped]  no verdict -- the window's files do not cover the load")
        for line in skipped:
            emit(line)
        emit()

    clean_z = [abs(r["worst_z"]) for r in rows if not r["stepped"]]
    emit(
        f"[summary]  {len(rows)} satellite-window(s) screened, {len(stepped)} STEP, "
        f"{len(skipped)} skipped"
    )
    emit(
        f"  worst clean deviation {max(clean_z, default=0.0):.1f} sigma"
        f" against the {Z_STEP:.0f} cut"
    )
    for row in stepped:
        emit(
            f"  STEP: window {row['window'].index:02d} {row['window'].name} Swarm "
            f"{row['sat']}, da {row['detail']['delta_a_m']:+.1f} m at "
            f"{row['worst_z']:+.1f} sigma"
        )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\r\n")
    print(f"\nwrote {display_path(args.out)}", file=sys.stderr)


if __name__ == "__main__":
    main()
