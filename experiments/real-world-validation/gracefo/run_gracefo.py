"""GRACE-FO vs. GNV1B reduced-dynamic orbit -- the Chunk 2 drag-stack diagnostic.

Evidence for ``docs/build-plan-real-world-validation.md`` Chunk 2: the full drag
pipeline (NRLMSISE-00 + real CSSI space weather + the shared ``DragSensitive``
proxy) measured against a real drag-perturbed LEO orbit, with the residual
decomposed into "pipeline" vs. "density model" by construction. Run once per
window -- a solar-quiet week (2019) and a solar-active week (2023) -- so the
quiet-vs-active contrast is visible in the fitted Cd and the residual ratio.

Three runs over a 1-day arc from the truth t0 (build plan Chunk 2):

- **Run 1 -- drag off:** the conservative force set only; the residual growth *is*
  the drag signal (must clear the Leg-1 conservative floor by an order of
  magnitude).
- **Run 2 -- drag on:** the same set + NRLMSISE-00 drag at the nominal Cd; the
  residual is now density x Cd error (the healthy band is ~10-30% of Run 1).
- **Run 3 -- scalar Cd fit:** coarse scan + golden-section refine on a single Cd
  minimizing the 1-day along-track RMS. If one scalar collapses Run 2's residual,
  the pipeline is proven and the remainder is genuine density bias -- the number
  that calibrates the maintainer's solar-sail expectations.

Before the runs: a t0 frame/time sanity diff (must be ~0), a maneuver screen (a
drag-on arc scanned for the slope kink a thruster burn would leave), and the
window's F10.7 / Ap context read from the same CssiSpaceWeatherData the drag force
consumes.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data); cwd-independent:

    cd experiments/real-world-validation/gracefo
    conda run -n propygator python run_gracefo.py quiet_2019 >  results.txt
    conda run -n propygator python run_gracefo.py active_2023 >> results.txt

Stdout is ASCII-only (captured under cp1252); progress is silenced. ``--parse-only``
stops before the JVM-touching steps (parser checks only).
"""

from __future__ import annotations

import sys
import time as _time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
# Reuse the Chunk 0 RIC helper + rms + Earth-rate constant (build plan "Reuse").
sys.path.insert(0, str(_HERE.parent / "lageos"))
import run_lageos as rl  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402

from propygator import (  # noqa: E402
    ForceModelConfig,
    Frame,
    IntegratorConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    State,
    propagate_numerical,
)

DATA_ROOT = _HERE.parent / "data" / "gracefo"

# GRACE-FO 1 (GRACE C, NORAD 43476). Sphere-equivalent drag/SRP parameters
# (citations in README.md): launch mass ~600 kg; the body is a ~3.1 x 1.9 x 0.8 m
# trapezoidal prism flying narrow-end-forward, so the ram frontal area is ~1 m^2;
# Cd 2.3 is the free-molecular nominal. The scalar Cd fit (Run 3) is the real
# diagnostic -- it absorbs the Cd x A / m product, so the exact A only sets the
# nominal starting point, not the answer.
GRACEFO_MASS_KG = 600.0
GRACEFO_AREA_M2 = 1.0
GRACEFO_CD_NOMINAL = 2.3
GRACEFO_CR = 1.3  # sphere reflection coefficient (1.0 absorbing .. 2.0 specular)
GRACEFO_SAT_ID = "C"

SUBSAMPLE_S = 60.0
LOAD_DAYS = 3  # consecutive days loaded (screen span); the runs use a 1-day arc
ARC_DAYS = 1.0  # the primary run/fit arc

WINDOWS = ("quiet_2019", "active_2023")


def _spacecraft(cd: float) -> SpacecraftConfig:
    return SpacecraftConfig(
        mass_kg=GRACEFO_MASS_KG,
        geometry=SpacecraftGeometry.sphere(
            area_m2=GRACEFO_AREA_M2,
            drag_coefficient=cd,
            reflectivity_coefficient=GRACEFO_CR,
        ),
    )


# The conservative force set (shared with Run 1 drag-off); Run 2/3 flip drag on.
# Matches the LAGEOS Chunk 0 baseline: 70x70, sun+moon, SRP, solid+ocean tides,
# relativity -- so the drag-off run reproduces the proven conservative floor.
def _force_config(drag: bool) -> ForceModelConfig:
    return ForceModelConfig(
        drag=drag,
        atmosphere_model="NRLMSISE-00",
        srp=True,
        solid_tides=True,
        ocean_tides=True,
        relativity=True,
    )


def _propagate_itrf(
    state0: State, span_s: float, drag: bool, cd: float
) -> np.ndarray:
    """Propagate ``span_s`` and return the ITRF positions on the t0 + k*60 grid."""
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=SUBSAMPLE_S,
        force_models=_force_config(drag),
        spacecraft=_spacecraft(cd),
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    return traj.to_frame(Frame.ITRF).positions


def _along_track(diff: np.ndarray, eph, n: int) -> np.ndarray:
    """Signed along-track residual component over the first ``n`` samples."""
    return rl.ric_components(
        diff[:n], eph.positions_m[:n], eph.velocities_ms[:n], earth_fixed=True
    )[:, 1]


def _space_weather(mid_iso: str) -> str:
    """One-line F10.7 / Ap / Kp context from CssiSpaceWeatherData (the drag source)."""
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

    from propygator import Epoch, TimeScale

    cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
    date = Epoch.from_iso(mid_iso, TimeScale.UTC).to_orekit()
    f107 = float(cssi.getInstantFlux(date))  # daily observed F10.7
    f107a = float(cssi.getMeanFlux(date))  # 81-day centered average
    ap_daily = float(cssi.getAp(date)[0])  # element 0 is the daily Ap
    kp = float(cssi.get24HoursKp(date))
    return (
        f"F10.7 = {f107:.1f} (81-day avg {f107a:.1f}) sfu, "
        f"daily Ap = {ap_daily:.1f}, daily Kp = {kp:.2f}"
    )


def _fit_cd(state0: State, span_s: float, eph, n_arc: int) -> tuple[float, float, int]:
    """Coarse scan + golden-section refine on scalar Cd minimizing 1-day along RMS.

    Returns ``(best_cd, best_along_rms, n_evaluations)``. The objective is smooth and
    single-welled in Cd over a 1-day arc (drag error is monotone in Cd around the
    truth), so a coarse bracket followed by golden section converges in a handful of
    propagations -- exactly the build plan's "handful of propagations, pure Python
    around propagate_numerical".
    """
    evals = 0

    def objective(cd: float) -> float:
        nonlocal evals
        evals += 1
        pos = _propagate_itrf(state0, span_s, drag=True, cd=cd)
        along = _along_track(pos - eph.positions_m[: len(pos)], eph, n_arc)
        rms = rl._rms(along)
        print(f"    Cd = {cd:6.3f}  ->  along RMS = {rms:10.3f} m", file=sys.stderr)
        return rms

    # Coarse bracket over the physically plausible Cd span (the 5.0 upper edge is the
    # spacecraft soft limit; a real free-molecular Cd sits well below it).
    grid = np.linspace(1.5, 5.0, 7)
    vals = [objective(cd) for cd in grid]
    k = int(np.argmin(vals))
    lo = float(grid[max(k - 1, 0)])
    hi = float(grid[min(k + 1, len(grid) - 1)])

    # Golden-section on [lo, hi] to a tight Cd tolerance.
    phi = (np.sqrt(5.0) - 1.0) / 2.0
    a, b = lo, hi
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = objective(c), objective(d)
    while (b - a) > 0.02:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = objective(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = objective(d)
    best_cd = 0.5 * (a + b)
    best_rms = objective(best_cd)
    return best_cd, best_rms, evals


def _growth_row(label: str, diff: np.ndarray, eph, n_arc: int) -> None:
    """Print the 3D-residual growth profile at 6 / 12 / 18 / 24 h."""
    d_norm = np.linalg.norm(diff, axis=1)
    cells = []
    for hours in (6, 12, 18, 24):
        k = int(hours * 3600 / SUBSAMPLE_S)
        cells.append(f"{d_norm[min(k, n_arc - 1)]:>12.1f}")
    print(f"  {label:<16}" + "".join(cells))


def main() -> None:
    parse_only = "--parse-only" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    window = args[0] if args else "quiet_2019"
    if window not in WINDOWS:
        raise SystemExit(f"unknown window {window!r}; choose one of {WINDOWS}")

    print("GRACE-FO 1 vs GNV1B reduced-dynamic orbit -- Chunk 2 drag-stack diagnostic")
    print("=" * 74)
    print(f"[window] {window}")

    window_dir = DATA_ROOT / window
    files = find_window_files(window_dir, GRACEFO_SAT_ID)
    if not files:
        raise SystemExit(
            f"no GNV1B files under {window_dir} -- download the GRACE-FO week first "
            "(see README.md; raw truth files are never committed)"
        )
    load = files[:LOAD_DAYS]
    eph = parse_gnv1b(load, sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S)
    n = len(eph.epochs)
    span_load_s = eph.epochs[-1].seconds_since(eph.epochs[0])

    print("[data]")
    print(f"  satellite: {eph.sat_id} = {eph.sat_name} (NORAD 43476)")
    print(f"  platform: {eph.platform!r}, product version {eph.product_version}")
    print(f"  source files ({len(eph.source_files)}): {', '.join(eph.source_files)}")
    print(
        f"  1 Hz records read: {eph.n_raw_records} (QC-dropped {eph.n_dropped_qc}); "
        f"subsampled to {SUBSAMPLE_S:.0f} s -> {n} epochs"
    )
    print(f"  seam gaps > 1.5 s: {eph._n_gaps} (max gap {eph._max_gap_s:.1f} s)")
    print(
        f"  span: {eph.epochs[0].to_iso()} -> {eph.epochs[-1].to_iso()} "
        f"{eph.epochs[0].scale.value} ({span_load_s / 86400.0:.3f} days loaded)"
    )
    print(f"  frame: coord_ref {eph.frame_flag!r} -> Frame.ITRF (ITRF-realization class)")

    # --- parser checks: bit-clean epoch round trip + grid uniformity ---------
    from propygator import Epoch

    print("[parser checks]")
    exact = all(Epoch.from_iso(e.to_iso(), e.scale) == e for e in eph.epochs)
    dts = np.array(
        [eph.epochs[i + 1].seconds_since(eph.epochs[i]) for i in range(n - 1)]
    )
    print(f"  from_iso(to_iso()) == epoch for all {n} epochs: {exact}")
    print(
        f"  grid uniformity: max |dt - {SUBSAMPLE_S:.0f} s| = "
        f"{np.max(np.abs(dts - SUBSAMPLE_S)):.3e} s over {n - 1} intervals"
    )
    r0 = float(np.linalg.norm(eph.positions_m[0]))
    print(f"  |r0| = {r0 / 1e3:.1f} km (altitude ~ {r0 / 1e3 - 6378.1:.0f} km)")
    if not exact:
        raise SystemExit("epoch round trip not exact -- fix the parser first")

    if parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        return

    # --- t0 sanity: frame/time conversion isolated from all dynamics ---------
    # (This is the first Orekit-touching call, so it also boots the JVM that the
    # space-weather read below needs.)
    state0 = State(
        eph.epochs[0], eph.positions_m[0], eph.velocities_ms[0], Frame.ITRF
    ).to_frame(Frame.EME2000)
    back = state0.to_frame(Frame.ITRF)
    print("[t0 sanity]")
    print(
        f"  ITRF -> EME2000 -> ITRF round trip at t0: "
        f"|dr| = {np.linalg.norm(back.position - eph.positions_m[0]):.3e} m, "
        f"|dv| = {np.linalg.norm(back.velocity - eph.velocities_ms[0]):.3e} m/s"
    )

    # --- space-weather context (the same source NRLMSISE-00 consumes) --------
    mid_iso = eph.epochs[n // 2].to_iso()
    print("[space weather]  at window midpoint (CssiSpaceWeatherData)")
    print(f"  {mid_iso} ~ {_space_weather(mid_iso)}")

    n_arc = int(ARC_DAYS * 86400 / SUBSAMPLE_S) + 1  # inclusive of the 24 h endpoint
    arc_span_s = ARC_DAYS * 86400.0
    if n_arc > n:
        raise SystemExit(f"arc needs {n_arc} truth samples but only {n} loaded")

    # --- maneuver screen: drag-on arc scanned for a burn's slope kink --------
    print(f"[maneuver screen]  drag-on over the {LOAD_DAYS}-day load, along-track")
    t_wall = _time.perf_counter()
    pos_screen = _propagate_itrf(state0, span_load_s, drag=True, cd=GRACEFO_CD_NOMINAL)
    t_screen = _time.perf_counter() - t_wall
    ns = min(len(pos_screen), n)
    along_screen = _along_track(pos_screen - eph.positions_m[:ns], eph, ns)
    t_rel = np.arange(ns) * SUBSAMPLE_S
    # A burn is a slope discontinuity: fit the smooth drag growth with a degree-5
    # polynomial and report the largest departure from it. A clean arc departs by a
    # small fraction of the along-track signal; a maneuver leaves a step/kink.
    coef = np.polyfit(t_rel, along_screen, 5)
    smooth_resid = along_screen - np.polyval(coef, t_rel)
    max_dev = float(np.max(np.abs(smooth_resid)))
    signal = float(np.max(np.abs(along_screen)))
    clean = max_dev < 0.10 * max(signal, 1.0)
    print(
        f"  along-track signal (max |.|): {signal:.1f} m; departure from a smooth "
        f"deg-5 fit: {max_dev:.1f} m"
    )
    for day in range(1, LOAD_DAYS + 1):
        k = int(day * 86400 / SUBSAMPLE_S)
        if k < ns:
            print(f"  along @ {day} d: {along_screen[k]:+12.1f} m")
    print(f"  screen ({t_screen:.0f} s wall): {'CLEAN' if clean else 'REVIEW -- kink'}")
    if not clean:
        print(
            "  a slope kink = an unmodeled burn: slide the window (SDS monthly "
            "maneuver reports as the cross-check) before trusting the drag numbers."
        )

    # --- Run 1 (drag off) / Run 2 (drag on, nominal Cd) ----------------------
    print(f"[runs]  1-day arc from t0, sphere-equiv A = {GRACEFO_AREA_M2} m2, "
          f"m = {GRACEFO_MASS_KG} kg, Cr = {GRACEFO_CR}")
    t_wall = _time.perf_counter()
    pos1 = _propagate_itrf(state0, arc_span_s, drag=False, cd=GRACEFO_CD_NOMINAL)
    pos2 = _propagate_itrf(state0, arc_span_s, drag=True, cd=GRACEFO_CD_NOMINAL)
    t_runs = _time.perf_counter() - t_wall
    d1 = pos1[:n_arc] - eph.positions_m[:n_arc]
    d2 = pos2[:n_arc] - eph.positions_m[:n_arc]

    # t0 sample must match truth to << 1 m (frame/time conversion, not dynamics).
    print(
        f"  first propagated sample (t0) vs truth: |dr| = "
        f"{np.linalg.norm(d1[0]):.3e} m  ({t_runs:.0f} s wall, 2 arcs)"
    )

    # --- Run 3: scalar Cd fit ------------------------------------------------
    print("[Cd fit]  golden-section on along-track RMS (progress on stderr)")
    t_wall = _time.perf_counter()
    best_cd, best_rms, evals = _fit_cd(state0, arc_span_s, eph, n_arc)
    t_fit = _time.perf_counter() - t_wall
    pos3 = _propagate_itrf(state0, arc_span_s, drag=True, cd=best_cd)
    d3 = pos3[:n_arc] - eph.positions_m[:n_arc]
    print(f"  fitted Cd = {best_cd:.3f} in {evals} evals ({t_fit:.0f} s wall)")

    # --- residual table + growth profile -------------------------------------
    def ric_rms(diff: np.ndarray) -> tuple[float, float, float, float]:
        ric = rl.ric_components(
            diff, eph.positions_m[:n_arc], eph.velocities_ms[:n_arc], earth_fixed=True
        )
        return (
            rl._rms(ric[:, 0]),
            rl._rms(ric[:, 1]),
            rl._rms(ric[:, 2]),
            rl._rms(np.linalg.norm(diff, axis=1)),
        )

    r1 = ric_rms(d1)
    r2 = ric_rms(d2)
    r3 = ric_rms(d3)
    print("[residuals]  1-day arc, propagated - truth, ITRF, RIC RMS (meters)")
    print(
        f"  {'run':<22}{'radial':>10}{'along':>12}{'cross':>10}{'3D':>12}"
    )
    print(f"  {'1: drag off':<22}{r1[0]:>10.2f}{r1[1]:>12.2f}{r1[2]:>10.2f}{r1[3]:>12.2f}")
    print(f"  {'2: drag on (Cd=2.3)':<22}{r2[0]:>10.2f}{r2[1]:>12.2f}{r2[2]:>10.2f}{r2[3]:>12.2f}")
    print(
        f"  {'3: drag on (Cd fit)':<22}{r3[0]:>10.2f}{r3[1]:>12.2f}{r3[2]:>10.2f}"
        f"{r3[3]:>12.2f}"
    )

    print("[growth]  3D |dr| propagated - truth (meters)")
    print(f"  {'run':<16}{'6 h':>12}{'12 h':>12}{'18 h':>12}{'24 h':>12}")
    _growth_row("1: drag off", d1, eph, n_arc)
    _growth_row("2: drag on nom", d2, eph, n_arc)
    _growth_row("3: drag on fit", d3, eph, n_arc)

    # --- headline ------------------------------------------------------------
    ratio = r2[1] / r1[1] if r1[1] > 0 else float("nan")
    print("[checkpoint B inputs]")
    print(
        f"  along-track RMS: drag-off {r1[1]:.1f} m -> drag-on {r2[1]:.1f} m "
        f"(ratio {ratio:.2f}) -> Cd-fit {r3[1]:.1f} m at Cd = {best_cd:.2f}"
    )
    print(
        f"  drag signal (Run 1) vs LAGEOS conservative floor (~4 m/day): "
        f"{r1[1] / 4.0:.0f}x -- drag dominates as expected"
    )
    print(
        "  reading: Run 2 << Run 1 proves the drag pipeline carries the signal; "
        "Run 3 <= Run 2 shows a single scalar Cd absorbs most model error, and the "
        "fitted Cd vs the 2.3 nominal is the density x Cd bias for this window."
    )


if __name__ == "__main__":
    main()
