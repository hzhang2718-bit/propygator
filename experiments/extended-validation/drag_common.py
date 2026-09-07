"""Leg-independent primitives for Part 2's drag drivers (reference-only).

The GRACE-FO and Swarm drivers differ in their truth reader, their geometry and
their maneuver screen, but they run the SAME five configurations, read the SAME
per-day RMS and print the SAME tables. Everything that does not depend on which
body is flying lives here, so the two legs cannot drift apart in the one place
it would matter -- the definition of "day N".

**THE PER-DAY RULE.** Day N is the RMS over ``[N-1 d, N d]`` ALONE, never
accumulated from t0 (contract, "Every RMS in this study is a per-day value").
An RMS accumulated over 0-N d is dominated by its early, still well-fitted
portion, so it understates the error at exactly the horizon a forecast is read
at. :func:`day_bounds` is the single definition of that slice; nothing else in
Part 2 may compute one. Day 1 spans indices ``0 .. 1440`` inclusive, which is
the frozen v0.7.2 1-day arc exactly -- that is what keeps the "removed
fraction" table comparable across the two studies.

Imports ``propygator`` (JVM-free at import) but starts no JVM at import time.
Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies.
"""

from __future__ import annotations

import sys
import time as _time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Callable, Sequence

import numpy as np

_STUDY = Path(__file__).resolve().parent
_REPO = _STUDY.parents[1]
_FROZEN = _STUDY.parent / "real-world-validation"
for _p in (str(_STUDY / "gracefo"), str(_FROZEN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import ric_components  # noqa: E402
from common import rms as _rms  # noqa: E402
from gracefo_ext_common import SUBSAMPLE_S, force_config  # noqa: E402

from propygator import (  # noqa: E402
    Frame,
    InPlaneTracking,
    IntegratorConfig,
    SpacecraftConfig,
    State,
    propagate_numerical,
)

SAMPLES_PER_DAY = int(round(86400.0 / SUBSAMPLE_S))  # 1440 at the 60 s grid

# t0 round-trip bound, copied VERBATIM from run_screen.py::T0_ROUNDTRIP_TOL_M --
# see the argument there (1,152 measured epochs, median 5.6e-9 m, worst
# 2.99e-8 m, so 5e-8 m clears the worst case by 1.7x). A WIRING check, never a
# physical measurement. Do not tune.
T0_ROUNDTRIP_TOL_M = 5e-8

# Truth-grid continuity bound, copied VERBATIM from
# run_screen.py::GRID_CONTINUITY_TOL_S. Every diff in Part 2 aligns propagated
# samples to truth BY ARRAY INDEX against a uniform t0 + k*SUBSAMPLE_S grid, so
# one missing truth epoch shifts every later comparison by a full step (~456 km
# of along-track) with nothing raising. Do not tune.
GRID_CONTINUITY_TOL_S = 1e-6

# The conservative floor the drag signal is read against: LAGEOS held ~4 m/day
# on the same force set with drag off (v0.7.2, run_gracefo.py:832). A drag-off
# run that does not clear it by an order of magnitude is not a drag window.
CONSERVATIVE_FLOOR_M_PER_DAY = 4.0


def pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def display_path(path: Path) -> str:
    """Repo-relative, forward-slashed, so the evidence is machine-independent."""
    try:
        return path.relative_to(_REPO).as_posix()
    except ValueError:
        return str(path)


def check_cssi_observed(idx: dict[str, float], window_name: str) -> None:
    """Refuse a window any of whose days sit on CSSI daily-PREDICTED rows.

    Those rows carry a FLAT PLACEHOLDER ap/Kp, so a storm window past the
    OBSERVED block would contain no storm in the model and would read as a
    propagator failure rather than as a storm (contract, windows bounded at
    2026-05-09). Shared by both legs deliberately: they run the same ten windows
    against the same CSSI file, so a leg that merely printed the aggregates
    would emit a full, plausible-looking storm file while the other refused.
    """
    if idx["n_predicted"]:
        raise SystemExit(
            f"{window_name}: {idx['n_predicted']:.0f} day(s) sit on CSSI "
            f"daily-PREDICTED rows, which carry a flat placeholder ap/Kp -- a "
            f"storm there would contain no storm in the model"
        )


# --- the per-day slice --------------------------------------------------------
def day_bounds(day: int) -> tuple[int, int]:
    """Inclusive sample index range of day ``day`` on the t0 + k*60 s grid.

    Day 1 is ``(0, 1440)`` -- t0 through t0 + 24 h inclusive, which is the
    frozen v0.7.2 1-day arc sample-for-sample. Consecutive days therefore share
    one boundary sample out of 1441; that is deliberate, so every day is the
    closed interval its label names and day 1 stays comparable across studies.
    """
    if day < 1:
        raise ValueError(f"day must be >= 1, got {day}")
    return (day - 1) * SAMPLES_PER_DAY, day * SAMPLES_PER_DAY


def ric_rms(
    diff: np.ndarray, eph, i0: int, i1: int
) -> tuple[float, float, float, float]:
    """Radial / along / cross / 3D RMS of a residual over ``[i0, i1]`` inclusive.

    Earth-fixed RIC, the frozen study's convention
    (``ric_components(..., earth_fixed=True)``).
    """
    sl = slice(i0, i1 + 1)
    ric = ric_components(
        diff[sl], eph.positions_m[sl], eph.velocities_ms[sl], earth_fixed=True
    )
    return (
        _rms(ric[:, 0]),
        _rms(ric[:, 1]),
        _rms(ric[:, 2]),
        _rms(np.linalg.norm(diff[sl], axis=1)),
    )


def along_track(diff: np.ndarray, eph, i0: int, i1: int) -> np.ndarray:
    """Signed along-track residual component over ``[i0, i1]`` inclusive."""
    sl = slice(i0, i1 + 1)
    return ric_components(
        diff[sl], eph.positions_m[sl], eph.velocities_ms[sl], earth_fixed=True
    )[:, 1]


# --- propagation --------------------------------------------------------------
def propagate_itrf(
    state0: State,
    span_s: float,
    spacecraft: SpacecraftConfig,
    *,
    drag: bool = True,
    attitude: InPlaneTracking | None = None,
) -> np.ndarray:
    """Propagate ``span_s`` and return ITRF positions on the t0 + k*60 s grid.

    A guard trip returns a SHORT trajectory, and every caller slices the result
    against a full-length truth array. Caught here so the failure names its
    cause instead of surfacing as a numpy shape error deep inside a fit -- and
    7 days through a storm is where that stops being hypothetical.
    """
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=SUBSAMPLE_S,
        force_models=force_config(drag),
        spacecraft=spacecraft,
        attitude=attitude,
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    if traj.metadata.get("terminated"):
        raise SystemExit(
            f"propagation terminated early: {traj.metadata.get('termination_reason')} "
            f"at {traj.metadata.get('termination_epoch')} -- the arc is short of "
            f"{span_s / 86400.0:.2f} d, so every per-day RMS below it would cover "
            f"less than the day it names"
        )
    return traj.to_frame(Frame.ITRF).positions


# --- the degree-5 maneuver screen ---------------------------------------------
# THE PRE-REGISTERED TIER-2 RULE, carried verbatim from v0.7.2
# run_gracefo.py:575-586 and from this study's run_screen.py:107-109. The
# contract requires it fixed before screening begins and never revisited after
# seeing a number; re-fitting it and then reporting success is explicitly
# forbidden as circular. Both constants print into every results header, so a
# drift between the copies shows up as a diff between two committed files.
# Change them in one place only by amending the contract.
TIER2_FRACTION = 0.10
TIER2_POLY_DEGREE = 5


def deg5_departure(along: np.ndarray) -> tuple[float, float, bool]:
    """The degree-5 departure test. Returns ``(signal, departure, clean)``.

    A burn is a slope discontinuity: fit the smooth drag growth with a degree-5
    polynomial and report the largest departure from it. Known limitation,
    recorded rather than tuned around: this gate went 0-for-2 against the two
    known-real burns in Chunk 2 (0.8 % and 1.9 % against its 10 % bar), because
    it normalizes by an UNFITTED Cd = 2.3 along-track error that reaches tens of
    kilometres. A CLEAN here is weak evidence, not a quiet window (contract
    amendment 2026-08-21).
    """
    t_rel = np.arange(along.size) * SUBSAMPLE_S
    coef = np.polyfit(t_rel, along, TIER2_POLY_DEGREE)
    departure = float(np.max(np.abs(along - np.polyval(coef, t_rel))))
    signal = float(np.max(np.abs(along)))
    return signal, departure, departure < TIER2_FRACTION * max(signal, 1.0)


# --- shipped-table conditions + the axis check --------------------------------
def arc_conditions(
    eph,
    n_arc: int,
    *,
    a_ref_m2: float,
    a_ram_m2: float,
    a_side_x_m2: float,
    a_side_z_m2: float,
    step: int = 60,
) -> dict[str, float]:
    """Arc-mean radius/density and what the shipped tables predict there.

    The same CSSI-driven NRLMSISE-00 the drag force consumes, queried on the
    truth positions -- a diagnostic input, not a propagation. Face-flow angles
    under ``InPlaneTracking(ecef)`` are constant by construction (ram theta=0,
    leeward theta=pi, all four sides theta=pi/2), so the arc mean varies only
    through the tables' (radius, density) inputs along the orbit.

    Also carries the AXIS CHECK: the face-sum ``Sigma Cd_i*A_i`` under each of
    the three possible body-axis-on-wind mappings. The wired +Y mapping must be
    the smallest -- a long thin box flying smallest-face-forward. A wrong
    box/attitude mapping would realize a very different drag with nothing
    raising.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.models.earth.atmosphere import NRLMSISE00
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

    from gracefo_ext_common import box_table, sphere_table
    from propygator.core import bodies

    cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
    atm = NRLMSISE00(cssi, bodies._sun(), bodies._earth())
    itrf = Frame.ITRF.to_orekit()
    idx = np.arange(0, n_arc, step)
    rad = np.linalg.norm(eph.positions_m[idx], axis=1)
    rho = np.array(
        [
            float(
                atm.getDensity(
                    eph.epochs[i].to_orekit(), Vector3D(*eph.positions_m[i]), itrf
                )
            )
            for i in idx
        ]
    )
    pairs = [(float(a), float(b)) for a, b in zip(rad, rho)]
    sph, box = sphere_table(), box_table()
    cd_sphere = float(np.mean([sph(a, b) for a, b in pairs]))
    cd_ram = float(np.mean([box(a, b, 0.0) for a, b in pairs]))
    cd_side = float(np.mean([box(a, b, np.pi / 2) for a, b in pairs]))
    cd_lee = float(np.mean([box(a, b, np.pi) for a, b in pairs]))

    sides_total = 2.0 * (a_side_x_m2 + a_side_z_m2)
    cda_box = (cd_ram + cd_lee) * a_ram_m2 + cd_side * sides_total
    wrong_x = (cd_ram + cd_lee) * a_side_x_m2 + cd_side * 2.0 * (
        a_ram_m2 + a_side_z_m2
    )
    wrong_z = (cd_ram + cd_lee) * a_side_z_m2 + cd_side * 2.0 * (
        a_ram_m2 + a_side_x_m2
    )
    return {
        "n_samples": float(len(idx)),
        "r_mean": float(np.mean(rad)),
        "rho_mean": float(np.mean(rho)),
        "rho_min": float(np.min(rho)),
        "rho_max": float(np.max(rho)),
        "cd_sphere": cd_sphere,
        "cd_ram": cd_ram,
        "cd_side": cd_side,
        "cd_lee": cd_lee,
        "cda_sphere": cd_sphere * a_ref_m2,
        "cda_box": cda_box,
        "cda_box_wrong_x": wrong_x,
        "cda_box_wrong_z": wrong_z,
        "axis_ok": float(cda_box < min(wrong_x, wrong_z)),
    }


def print_conditions(c: dict[str, float], *, a_ref_m2: float) -> None:
    """The arc-conditions + axis-check block, identical on both legs."""
    print(
        f"  arc-mean conditions over {c['n_samples']:.0f} samples: r "
        f"{c['r_mean'] / 1e3:.1f} km, rho {c['rho_mean']:.3e} kg/m^3 "
        f"(min {c['rho_min']:.3e}, max {c['rho_max']:.3e})"
    )
    print(
        f"  shipped tables there: sphere Cd {c['cd_sphere']:.3f} -> CdA "
        f"{c['cda_sphere']:.4f} m^2 on A_ref {a_ref_m2:.7f}"
    )
    print(
        f"  box per-face Cd: ram {c['cd_ram']:.3f} / side {c['cd_side']:.3f} / "
        f"leeward {c['cd_lee']:.3f} -> face-sum CdA {c['cda_box']:.4f} m^2"
    )
    print("  [axis check]  Sigma Cd_i*A_i by which body face rides the wind:")
    print(
        f"    +Y ram, the wired mapping : {c['cda_box']:7.3f} m^2  <- must be smallest"
    )
    print(f"    +X ram (nadir/zenith face): {c['cda_box_wrong_x']:7.3f} m^2  (wrong)")
    print(f"    +Z ram (slant-side face)  : {c['cda_box_wrong_z']:7.3f} m^2  (wrong)")
    ok = bool(c["axis_ok"])
    print(f"    wired mapping smallest: {'PASS' if ok else 'FAIL'}")
    if not ok:
        raise SystemExit(
            "axis check FAILED -- the wired box/attitude mapping is not the "
            "smallest face-sum, so the box is not flying smallest-face-forward. "
            "Fix before reading any number below."
        )


# --- the five configurations --------------------------------------------------
ConfigSpec = tuple[str, str, SpacecraftConfig, bool, "InPlaneTracking | None"]


def run_configs(
    state0: State,
    eph,
    specs: Sequence[ConfigSpec],
    *,
    arc_days: float,
    n_arc: int,
    span_override_s: dict[str, float] | None = None,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Propagate every configuration once and return its residual + wall time.

    ``specs`` are ``(id, label, spacecraft, drag, attitude)``. Each is ONE
    propagation over the arc; the per-day numbers are read off it afterwards and
    are never re-propagated (contract -- and the easiest way to accidentally
    triple the study's cost). ``span_override_s`` lets one configuration run
    longer than the arc (the Swarm leg propagates its Cd = 2.3 run over the full
    load so it doubles as the polynomial screen); every read still slices to
    ``n_arc``.
    """
    diffs: dict[str, np.ndarray] = {}
    walls: dict[str, float] = {}
    for cfg_id, label, spacecraft, drag, attitude in specs:
        span = (span_override_s or {}).get(cfg_id, arc_days * 86400.0)
        t_wall = _time.perf_counter()
        pos = propagate_itrf(state0, span, spacecraft, drag=drag, attitude=attitude)
        walls[cfg_id] = _time.perf_counter() - t_wall
        if len(pos) < n_arc:
            raise SystemExit(
                f"{cfg_id}: propagation returned {len(pos)} samples, need {n_arc}"
            )
        m = min(len(pos), len(eph.epochs))
        diffs[cfg_id] = pos[:m] - eph.positions_m[:m]
        print(f"    {label:<24} {walls[cfg_id]:6.0f} s wall")
    return diffs, walls


def print_day_table(
    diffs: dict[str, np.ndarray],
    labels: dict[str, str],
    eph,
    days: Sequence[int],
) -> dict[str, dict[int, tuple[float, float, float, float]]]:
    """The per-day RIC table, days 1..N, for every configuration.

    Returns ``{config_id: {day: (radial, along, cross, 3D)}}`` so the caller can
    emit the machine-readable rows from the same numbers it printed.
    """
    out: dict[str, dict[int, tuple[float, float, float, float]]] = {}
    print(
        f"  {'config':<20}{'day':>5}{'radial':>12}{'along':>14}"
        f"{'cross':>12}{'3D':>14}"
    )
    for cfg_id, diff in diffs.items():
        out[cfg_id] = {}
        for day in days:
            i0, i1 = day_bounds(day)
            rr = ric_rms(diff, eph, i0, i1)
            out[cfg_id][day] = rr
            name = labels[cfg_id] if day == days[0] else ""
            print(
                f"  {name:<20}{day:>5}{rr[0]:>12.2f}{rr[1]:>14.2f}"
                f"{rr[2]:>12.2f}{rr[3]:>14.2f}"
            )
    return out


def print_read_block(
    per_day: dict[str, dict[int, tuple[float, float, float, float]]],
    labels: dict[str, str],
    horizons: Sequence[int],
    *,
    show_removed: bool,
    quote_v072: bool,
) -> None:
    """The ``[read]`` block: drag signal against the floor, then removed fraction.

    SHARED BY BOTH LEGS. It was copy-pasted at first and had already drifted --
    only the GRACE-FO copy carried the conservative-floor NOTE -- so a weak-drag
    Swarm window printed no warning where the equivalent GRACE-FO window did.
    ``horizons`` is what the run actually computed, not the contract constant, so
    a smoke arc cannot advertise days it never read.
    """
    print(f"[read]  the contract's horizons, days {', '.join(map(str, horizons))}")
    floor = CONSERVATIVE_FLOOR_M_PER_DAY
    d1_off = per_day["drag_off"][1][3]
    print(
        f"  drag signal: day-1 drag-off 3D RMS {d1_off:.1f} m against the ~{floor:.0f} "
        f"m/day conservative floor -> {d1_off / floor:.0f}x"
    )
    if d1_off < 10.0 * floor:
        print(
            "  NOTE: the drag signal does not clear the conservative floor by an "
            "order of magnitude -- read every comparison below with that in mind"
        )
    if not show_removed:
        return
    print(
        "  removed fraction of the drag-off signal, per day (no verdict "
        "column -- this part has no benchmark):"
    )
    print(f"    {'config':<20}" + "".join(f"{f'day {d}':>12}" for d in horizons))
    for cfg_id in ("cd_2p3", "sphere", "box"):
        cells = ""
        for day in horizons:
            off = per_day["drag_off"][day][3]
            removed = (off - per_day[cfg_id][day][3]) / off if off > 0 else float("nan")
            cells += f"{100.0 * removed:>11.0f}%"
        print(f"    {labels[cfg_id]:<20}{cells}")
    if quote_v072:
        print(
            "  the day-1 column is what compares to the frozen v0.7.2 table "
            "(Cd=2.3 86/67/56 %, sphere 53/80/63 %, box -24/79/96 % for "
            "quiet/active/storm) -- day 1 is identical under both conventions, so "
            "that comparison survives the per-day rule exactly. Reading days 3 or "
            "7 against it would not be like-for-like."
        )


def print_machine_rows(
    leg: str,
    window: str,
    band: str,
    sat: str,
    per_day: dict[str, dict[int, tuple[float, float, float, float]]],
) -> None:
    """Fixed-token rows for ``summarize_drag.py``.

    A SEPARATE, DELIBERATELY BORING BLOCK. The human tables above are free to be
    reformatted; the summary parses only these lines, so a cosmetic edit to a
    table can never silently change what the cross-window summary reports.
    """
    print("[machine]  fixed-token rows for summarize_drag.py -- do not reformat")
    for cfg_id, days in per_day.items():
        for day, rr in days.items():
            print(
                f"  MROW {leg} {window} {band} {sat} {cfg_id} {day} "
                f"{rr[0]:.4f} {rr[1]:.4f} {rr[2]:.4f} {rr[3]:.4f}"
            )


def print_fit_block(
    scan: Sequence[tuple[float, float]],
    best_cd: float,
    n_evals: int,
    bracket: float,
    *,
    cd_hi: float,
    n_coarse: int,
    a_ref_m2: float,
    mass_kg: float,
    tol: float,
    wall_s: float,
) -> bool:
    """The fit report, including the coarse scan. Returns True if RAILED.

    THE COARSE SCAN IS PRINTED, NOT JUST THE WINNER. Those evaluations are
    already paid for, and the table is the only way a reader can see whether the
    7-day objective was single-welled -- golden section otherwise papers over a
    second well.
    """
    print(f"  coarse scan ({n_coarse} evaluations over [{scan[0][0]:.2f}, {cd_hi:.2f}])")
    print(f"    {'Cd':>10}{'along RMS (m)':>18}")
    for cd, val in scan[:n_coarse]:
        print(f"    {cd:>10.4f}{val:>18.3f}")
    b_fit = best_cd * a_ref_m2 / mass_kg
    railed = best_cd >= cd_hi - 0.05
    print(
        f"  fitted Cd = {best_cd:.5f} on A_ref = {a_ref_m2:.7f} m^2, "
        f"B = Cd*A/m = {b_fit:.6e} m^2/kg"
    )
    print(
        f"  {n_evals} evals, tol {tol}, bracket width {bracket:.5f}, "
        f"ceiling {cd_hi}" + (" -- RAILED" if railed else "") + f"  ({wall_s:.0f} s wall)"
    )
    if railed:
        print(
            f"  RAILED at the {cd_hi} scan edge -- read as 'fitted Cd > {cd_hi}' "
            f"(a density-bias bound, not a converged fit)"
        )
    return railed


def make_recording_objective(
    inner: Callable[[float], float], scan: list[tuple[float, float]]
) -> Callable[[float], float]:
    """Wrap a fit objective so every (Cd, value) pair is recorded for the report."""

    def objective(cd: float) -> float:
        val = inner(cd)
        scan.append((cd, val))
        return val

    return objective
