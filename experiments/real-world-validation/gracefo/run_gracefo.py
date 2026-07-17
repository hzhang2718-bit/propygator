"""GRACE-FO vs. GNV1B reduced-dynamic orbit -- the Chunk 2 + 2b drag diagnostics.

Evidence for ``docs/build-plan-real-world-validation.md`` Chunks 2, 2b and 2c:
the full drag pipeline (NRLMSISE-00 + real CSSI space weather + the shared
``DragSensitive`` proxy) measured against a real drag-perturbed LEO orbit, with
the residual decomposed into "pipeline" vs. "density model" by construction. Run
once per window -- a solar-quiet week (2019), a solar-active week (2023), and
the Chunk 2c Gannon-storm window (May 2024) -- so the quiet/active/storm
contrast is visible in the fitted Cd and the residual ratio.

Five runs over a 1-day arc from the truth t0 (Chunk 2 runs 1-3, Chunk 2b 4-5):

- **Run 1 -- drag off:** the conservative force set only; the residual growth *is*
  the drag signal (must clear the Leg-1 conservative floor by an order of
  magnitude).
- **Run 2 -- drag on:** the same set + NRLMSISE-00 drag at the nominal Cd; the
  residual is now density x Cd error (the healthy band is ~10-30% of Run 1).
- **Run 3 -- scalar Cd fit:** coarse scan + golden-section refine on a single Cd
  minimizing the 1-day along-track RMS. If one scalar collapses Run 2's residual,
  the pipeline is proven and the remainder is genuine density bias -- the number
  that calibrates the maintainer's solar-sail expectations.
- **Run 4 -- sphere table (no fit):** ``VariableCd.sphere_default()`` on the exact
  ram area A_ram = 1.027 m^2; attitude-independent (a sphere's Cd is isotropic).
- **Run 5 -- box table (no fit):** ``BoxFaceCd.default()`` on the base-averaged
  GRACE-FO rectangle at real dimensions (0.780 x 3.123 x 1.3165 m), flown
  wind-aligned with ``InPlaneTracking(velocity_reference="ecef")`` -- body +Y
  held exactly on the wind, so every face-flow angle is constant by construction
  (ram theta=0, leeward theta=pi, all four sides theta=pi/2).

Runs 4-5 answer the pre-flight-Cd question (what do the shipped tables predict
before any flight data comes back?) and are **density-limited by construction**:
an orbit residual constrains only the rho*Cd*A product, so a no-fit table run
exposes NRLMSISE-00's density bias, it does not test the Cd in isolation. The
Cd-table diagnostic block therefore restates every Cd on the common A_ram
reference beside the Run 3 fitted Cd and the DSMC physical band (Mehta 2013;
arXiv 2503.21651), with each printed number labeled as exactly one quantity
(the build plan's flagged reference-area ISSUE fix; the retained scratch
``probes/probe_tables.py`` mixed references and is superseded).

**Chunk 2c (storm window):** the same battery over the 2024-05-11 Gannon-storm
day (daily Ap 271, 3-hourly ap to 400 -- the strongest storm of the GRACE-FO
era) breaks the two-window degeneracy in the table reading: the physical Cd is
near-constant across windows, so the fitted-Cd swing is a density-bias
measurement, and the storm decides whether the box table's persistent
over-prediction is density bias (its sign flips) or genuine geometric over-drag
(it persists). It is also the only window exercising NRLMSISE-00's ap-driven
storm terms (the committed windows sit at daily Ap 2-4). Storm expectations: the
scalar-Cd fit will NOT collapse the residual to the quiet/active Run-3 class
(the density bias varies hour-to-hour inside the arc), and the maneuver screen's
deg-5 kink test documents the storm signature rather than a burn (the SDS
monthly reports are the actual-burn cross-check).

Before the runs: a t0 frame/time sanity diff (must be ~0), a maneuver screen (a
drag-on arc scanned for the slope kink a thruster burn would leave), and
per-loaded-day F10.7 / Ap context plus the arc-max 3-hourly ap, read from the
same CssiSpaceWeatherData the drag force consumes.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data); cwd-independent:

    cd experiments/real-world-validation/gracefo
    conda run -n propygator python run_gracefo.py quiet_2019 >  results.txt
    conda run -n propygator python run_gracefo.py active_2023 >> results.txt
    conda run -n propygator python run_gracefo.py storm_2024 >> results.txt

Stdout is ASCII-only (captured under cp1252); progress is silenced. ``--parse-only``
stops before the JVM-touching steps (parser checks only). ``--emit-fixture``
prints the Chunk 4 pinned-test literals (t0 PV + 600 s day-1 truth PV) and
exits -- JVM-free; the source of the in-file fixtures in
``tests/propagation/test_real_world_gracefo.py`` and
``tests/tle/test_fitter_real_world.py`` (one fixture serves both).
``--start-date=YYYY-MM-DD`` overrides the window's first loaded day (Chunk 2c's
optional onset arc: ``--start-date=2024-05-10``). ``--fixed-cd=X`` adds one
no-fit propagation at a Cd calibrated elsewhere, with a 3-hourly signed
along-track profile -- on the onset arc, ``--fixed-cd=3.405`` (the active_2023
fitted value) is the "storm-surprise" case: how fast a pre-storm-calibrated
prediction diverges when the storm arrives.
"""

from __future__ import annotations

import sys
import time as _time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
# Shared study analysis kit (the Chunk 0 RIC helper + rms; build plan "Reuse")
# and the GRACE-FO leg configuration (constants, geometry, factories).
from common import ric_components, rms as _rms  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402
from gracefo_common import (  # noqa: E402
    A_RAM_M2,
    A_SIDE_X_M2,
    A_SIDE_Z_M2,
    BOX_X_M,
    BOX_Y_M,
    BOX_Z_M,
    DATA_ROOT,
    DSMC_CD_BAND,
    GRACEFO_AREA_M2,
    GRACEFO_CD_NOMINAL,
    GRACEFO_CR,
    GRACEFO_MASS_KG,
    GRACEFO_SAT_ID,
    LENGTH_CORRECTION_M,
    SUBSAMPLE_S,
    box_spacecraft,
    force_config,
    sphere_spacecraft,
)

from propygator import (  # noqa: E402
    BoxFaceCd,
    Frame,
    InPlaneTracking,
    IntegratorConfig,
    SpacecraftConfig,
    State,
    VariableCd,
    propagate_numerical,
)

LOAD_DAYS = 3  # consecutive days loaded (screen span); the runs use a 1-day arc
ARC_DAYS = 1.0  # the primary run/fit arc

# window -> first loaded day (a tarball-name date filter; None = all files).
# The runs load the first LOAD_DAYS files that survive the filter, so the filter
# picks t0. --start-date=YYYY-MM-DD overrides it at the command line.
WINDOWS: dict[str, str | None] = {
    "quiet_2019": None,  # F10.7 ~ 70, daily Ap ~ 2 (deep solar minimum)
    "active_2023": None,  # F10.7 ~ 190, daily Ap ~ 4 (solar max, storm-free)
    # Chunk 2c -- Gannon storm: skip the on-disk 2024-05-10 onset day so t0
    # opens the full-storm arc (2024-05-11: daily Ap 271, 3-hourly ap to 400,
    # Kp 9). --start-date=2024-05-10 selects the optional onset arc instead.
    "storm_2024": "2024-05-11",
}

# Cd-fit coarse-scan upper edge. The shipped _SOFT_CD_LIMIT = 5 only *warns*,
# and a storm-window fitted Cd is a density-bias absorber rather than a
# physical Cd, so the storm scan runs to 8 (a fit railing there is itself a
# finding -- a lower bound on NRLMSISE-00's storm density under-prediction).
CD_FIT_HI_DEFAULT = 5.0
CD_FIT_HI_STORM = 8.0


def _propagate_itrf(
    state0: State,
    span_s: float,
    drag: bool,
    cd: float = GRACEFO_CD_NOMINAL,
    spacecraft: SpacecraftConfig | None = None,
    attitude: InPlaneTracking | None = None,
) -> np.ndarray:
    """Propagate ``span_s`` and return the ITRF positions on the t0 + k*60 grid.

    ``spacecraft`` overrides the sphere-equivalent ``sphere_spacecraft(cd)`` (the Chunk
    2b table runs); ``attitude=None`` keeps the propagator's default mode.
    """
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=SUBSAMPLE_S,
        force_models=force_config(drag),
        spacecraft=spacecraft if spacecraft is not None else sphere_spacecraft(cd),
        attitude=attitude,
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    return traj.to_frame(Frame.ITRF).positions


def _along_track(diff: np.ndarray, eph, n: int) -> np.ndarray:
    """Signed along-track residual component over the first ``n`` samples."""
    return ric_components(
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


def _ap_max_over_arc(eph, n_arc: int, step: int = 30) -> float:
    """Max 3-hourly ap over the arc -- NRLMSISE-00's storm driver (getAp()[1]).

    At daily Ap 2-4 (the quiet/active windows) this is a near-constant few; in
    the Chunk 2c storm window it is the live proof the storm reaches the model.
    """
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

    cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
    return max(
        float(cssi.getAp(eph.epochs[k].to_orekit())[1]) for k in range(0, n_arc, step)
    )


def _arc_density(eph, n_arc: int, step: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """NRLMSISE-00 density + geocentric radius on every ``step``-th arc sample.

    The same CSSI-driven model the drag force consumes, queried on the truth
    positions/epochs (a diagnostic input, not a propagation).
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.models.earth.atmosphere import NRLMSISE00
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

    from propygator.core import bodies

    cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
    atm = NRLMSISE00(cssi, bodies._sun(), bodies._earth())
    itrf = Frame.ITRF.to_orekit()
    idx = np.arange(0, n_arc, step)
    r = np.linalg.norm(eph.positions_m[idx], axis=1)
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
    return r, rho


def _table_diagnostics(
    eph,
    n_arc: int,
    best_cd: float,
    sphere_table: VariableCd,
    box_table: BoxFaceCd,
) -> dict:
    """The Chunk 2b Cd-table diagnostic block, on the common A_ram reference.

    Every printed number is labeled as exactly one quantity (the build plan's
    flagged reference-area ISSUE): the raw face-sum Sigma Cd_i*A_i -- which for
    ``BoxFaceCd`` *is* the along-wind effective Cd*A, because each face's
    tabulated Cd is referenced to that face's full area with the incidence
    projection already baked in -- versus the dimensionless Cd referenced to the
    common A_ram = 1.027 m^2. Face-flow angles under InPlaneTracking(ecef) are
    constant by construction (body +Y held exactly on the wind): ram theta=0,
    leeward theta=pi, all four sides theta=pi/2 -- so the arc-mean varies only
    through the tables' (radius, density) inputs along the orbit.
    """
    r, rho = _arc_density(eph, n_arc)
    w = rho / rho.sum()  # density weights, the closer proxy for the drag impulse
    a_sides = 2.0 * (A_SIDE_X_M2 + A_SIDE_Z_M2)

    cd_sphere = np.array([sphere_table(float(ri), float(di)) for ri, di in zip(r, rho)])
    cd_ram = np.array([box_table(float(ri), float(di), 0.0) for ri, di in zip(r, rho)])
    cd_side = np.array(
        [box_table(float(ri), float(di), np.pi / 2) for ri, di in zip(r, rho)]
    )
    cd_lee = np.array(
        [box_table(float(ri), float(di), np.pi) for ri, di in zip(r, rho)]
    )
    cda_sphere = cd_sphere * A_RAM_M2  # the sphere's reference area IS A_ram
    cda_box = (cd_ram + cd_lee) * A_RAM_M2 + cd_side * a_sides
    cda_fit = best_cd * GRACEFO_AREA_M2  # Run 3's product, on the driver's 1.0 m^2

    out = {
        "cda_sphere_mean": float(np.mean(cda_sphere)),
        "cda_sphere_w": float(np.sum(w * cda_sphere)),
        "cda_box_mean": float(np.mean(cda_box)),
        "cda_box_w": float(np.sum(w * cda_box)),
        "cda_fit": cda_fit,
        "cd_sphere_aram": float(np.mean(cda_sphere)) / A_RAM_M2,
        "cd_box_aram": float(np.mean(cda_box)) / A_RAM_M2,
        "cd_fit_aram": cda_fit / A_RAM_M2,
    }

    print("[Cd tables]  shipped a-priori tables at arc conditions (Chunk 2b)")
    print(
        f"  NRLMSISE-00 over the arc ({len(rho)} samples): rho mean {rho.mean():.3e} "
        f"kg/m^3 (min {rho.min():.3e}, max {rho.max():.3e})"
    )
    print(
        "  face-flow angles under InPlaneTracking(ecef), constant by construction:"
    )
    print(
        f"    ram +Y theta=0 (A {A_RAM_M2:.3f} m^2), leeward -Y theta=pi, "
        f"4 sides theta=pi/2 (2x{A_SIDE_X_M2:.3f} + 2x{A_SIDE_Z_M2:.3f} "
        f"= {a_sides:.2f} m^2)"
    )
    print(
        f"  per-face box Cd at arc-mean conditions: ram {cd_ram.mean():.3f}, "
        f"side {cd_side.mean():.3f}, leeward {cd_lee.mean():.3f}"
    )
    print("  quantity labels -- each number below is exactly one thing:")
    print(
        "    [CdA] = raw face-sum Sigma Cd_i*A_i in m^2 = along-wind effective "
        "Cd*A (identical by table construction: incidence is baked into each face Cd)"
    )
    print(f"    [Cd]  = dimensionless Cd referenced to the common A_ram = {A_RAM_M2:.3f} m^2")
    print(
        f"  sphere_default : [CdA] {out['cda_sphere_mean']:.3f} m^2 arc-mean "
        f"(rho-weighted {out['cda_sphere_w']:.3f})   [Cd] {out['cd_sphere_aram']:.2f}"
    )
    print(
        f"  box_face_default: [CdA] {out['cda_box_mean']:.3f} m^2 arc-mean "
        f"(rho-weighted {out['cda_box_w']:.3f})   [Cd] {out['cd_box_aram']:.2f}"
    )
    print(
        f"  fitted (Run 3)  : [CdA] {cda_fit:.3f} m^2 (= Cd {best_cd:.3f} on the "
        f"driver's {GRACEFO_AREA_M2} m^2)   [Cd] {out['cd_fit_aram']:.2f}"
    )
    print(
        f"  DSMC physical band on the frontal reference: Cd "
        f"{DSMC_CD_BAND[0]}-{DSMC_CD_BAND[1]} (Mehta 2013; arXiv 2503.21651)"
    )

    # Axis-convention live check (build plan Verify 1, figures recomputed here
    # rather than trusted from the superseded scratch probe): the face-sum if the
    # wrong body axis rode the wind. The wired +Y mapping must be the smallest --
    # a long thin box flying smallest-face-forward.
    cdr, cds, cdl = cd_ram.mean(), cd_side.mean(), cd_lee.mean()
    wrong_x = (cdr + cdl) * A_SIDE_X_M2 + cds * 2.0 * (A_RAM_M2 + A_SIDE_Z_M2)
    wrong_z = (cdr + cdl) * A_SIDE_Z_M2 + cds * 2.0 * (A_RAM_M2 + A_SIDE_X_M2)
    print("  [axis check]  Sigma Cd_i*A_i by which body face rides the wind:")
    print(f"    +Y ram, the wired mapping : {out['cda_box_mean']:6.2f} m^2  <- must be smallest")
    print(f"    +X ram (nadir/zenith face): {wrong_x:6.2f} m^2  (wrong mapping)")
    print(f"    +Z ram (slant-side face)  : {wrong_z:6.2f} m^2  (wrong mapping)")
    ok = out["cda_box_mean"] < min(wrong_x, wrong_z)
    print(f"    wired mapping smallest: {'PASS' if ok else 'FAIL -- fix before reading on'}")
    return out


def _fit_cd(
    state0: State,
    span_s: float,
    eph,
    n_arc: int,
    cd_hi: float = CD_FIT_HI_DEFAULT,
) -> tuple[float, float, int]:
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
        rms = _rms(along)
        print(f"    Cd = {cd:6.3f}  ->  along RMS = {rms:10.3f} m", file=sys.stderr)
        return rms

    # Coarse bracket over the plausible Cd span. The default 5.0 upper edge is
    # the spacecraft soft-warn limit (a real free-molecular Cd sits well below
    # it); the storm window scans wider -- there the fitted Cd absorbs a
    # storm-size density bias and may legitimately exceed 5 (warns, allowed).
    grid = np.linspace(1.5, cd_hi, 7)
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


def emit_fixture(eph, window: str) -> None:
    """Print the Chunk 4 pinned-test literals: t0 PV + 600 s day-1 truth PV.

    Every 10th sample of the 60 s truth grid over day 1 (145 samples, offsets
    k*600 s). Positions feed the drag-ratio pin; positions + velocities feed
    the fitter test's ``Trajectory.from_arrays``. ``repr`` floats round-trip
    exactly.
    """

    def row(a) -> str:
        return repr(tuple(float(v) for v in a))  # plain-float repr, exact round-trip

    idx = range(0, 1441, 10)
    t0 = eph.epochs[0]
    print("# --- pinned fixture generated by run_gracefo.py --emit-fixture ---")
    print(f"# source: {window} GNV1B, {eph.sat_name}, see gracefo/README.md")
    print(f'T0_ISO = "{t0.to_iso()}"  # {t0.scale.value}, ITRF')
    print("STEP_S = 600.0  # truth sample spacing below (day 1)")
    print("TRUTH_POS_M = (")
    for i in idx:
        print(f"    {row(eph.positions_m[i])},")
    print(")")
    print("TRUTH_VEL_MS = (")
    for i in idx:
        print(f"    {row(eph.velocities_ms[i])},")
    print(")")


def main() -> None:
    parse_only = "--parse-only" in sys.argv
    start_date = None
    fixed_cd = None
    for a in sys.argv[1:]:
        if a.startswith("--start-date="):
            start_date = a.split("=", 1)[1]
        elif a.startswith("--fixed-cd="):
            fixed_cd = float(a.split("=", 1)[1])
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    window = args[0] if args else "quiet_2019"
    if window not in WINDOWS:
        raise SystemExit(f"unknown window {window!r}; choose one of {tuple(WINDOWS)}")
    if start_date is None:
        start_date = WINDOWS[window]
    is_storm = window.startswith("storm")

    if "--emit-fixture" in sys.argv:
        files = find_window_files(DATA_ROOT / window, GRACEFO_SAT_ID)
        if start_date is not None:
            files = [f for f in files if f.name >= f"gracefo_1B_{start_date}"]
        if len(files) < 2:
            raise SystemExit(f"--emit-fixture needs 2 days under {DATA_ROOT / window}")
        # 2 days so the day-1 arc's t0 + 86400 s endpoint (day 2's first record)
        # is on the grid; same t0 as the normal runs.
        eph = parse_gnv1b(files[:2], sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S)
        emit_fixture(eph, window)
        return

    chunks = "2 + 2b + 2c" if is_storm else "2 + 2b"
    print(
        f"GRACE-FO 1 vs GNV1B reduced-dynamic orbit -- Chunk {chunks} drag diagnostics"
    )
    print("=" * 74)
    print(f"[window] {window}" + (f" (first loaded day {start_date})" if start_date else ""))

    window_dir = DATA_ROOT / window
    files = find_window_files(window_dir, GRACEFO_SAT_ID)
    if start_date is not None:
        # Tarball names embed the ISO date, so a lexical bound selects the day.
        files = [f for f in files if f.name >= f"gracefo_1B_{start_date}"]
    if not files:
        raise SystemExit(
            f"no GNV1B files under {window_dir}"
            + (f" on/after {start_date}" if start_date else "")
            + " -- download the GRACE-FO week first "
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

    n_arc = int(ARC_DAYS * 86400 / SUBSAMPLE_S) + 1  # inclusive of the 24 h endpoint
    arc_span_s = ARC_DAYS * 86400.0
    if n_arc > n:
        raise SystemExit(f"arc needs {n_arc} truth samples but only {n} loaded")

    # --- space-weather context (the same source NRLMSISE-00 consumes) --------
    # Per-loaded-day daily context + the arc-max 3-hourly ap: the proof a storm
    # actually reaches the model (Chunk 2c Verify 1). Near-constant for the
    # quiet/active windows.
    print("[space weather]  per loaded day (CssiSpaceWeatherData)")
    per_day = int(86400 / SUBSAMPLE_S)
    for day in range(LOAD_DAYS):
        k = min(day * per_day + per_day // 2, n - 1)  # local noon of each day
        day_iso = eph.epochs[k].to_iso()
        print(f"  {day_iso[:10]} ~ {_space_weather(day_iso)}")
    print(
        f"  max 3-hourly ap over the {ARC_DAYS:.0f}-day arc: "
        f"{_ap_max_over_arc(eph, n_arc):.0f}"
    )

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
    if is_storm:
        print(
            "  storm window: a real storm onset is itself a slope kink, so the "
            "deg-5 departure documents the storm signature, not a burn -- the "
            "SDS monthly report is the actual-maneuver cross-check."
        )
    elif not clean:
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
    cd_hi = CD_FIT_HI_STORM if is_storm else CD_FIT_HI_DEFAULT
    t_wall = _time.perf_counter()
    best_cd, best_rms, evals = _fit_cd(state0, arc_span_s, eph, n_arc, cd_hi=cd_hi)
    t_fit = _time.perf_counter() - t_wall
    pos3 = _propagate_itrf(state0, arc_span_s, drag=True, cd=best_cd)
    d3 = pos3[:n_arc] - eph.positions_m[:n_arc]
    print(f"  fitted Cd = {best_cd:.3f} in {evals} evals ({t_fit:.0f} s wall)")
    if best_cd >= cd_hi - 0.05:
        print(
            f"  NOTE: fit railed at the {cd_hi} scan edge -- read as "
            f"'fitted Cd > {cd_hi}' (a density-bias bound, not a converged fit)"
        )

    # --- Chunk 2b: Runs 4 & 5 -- the a-priori Cd-table probe ------------------
    sphere_table = VariableCd.sphere_default()
    box_table = BoxFaceCd.default()
    diag = _table_diagnostics(eph, n_arc, best_cd, sphere_table, box_table)

    print("[runs 4-5]  no-fit shipped Cd tables, same force set + 1-day arc")
    ipt = InPlaneTracking(velocity_reference="ecef")
    t_wall = _time.perf_counter()
    pos4 = _propagate_itrf(
        state0,
        arc_span_s,
        drag=True,
        spacecraft=sphere_spacecraft(sphere_table, area_m2=A_RAM_M2),
    )
    t4 = _time.perf_counter() - t_wall
    t_wall = _time.perf_counter()
    pos5 = _propagate_itrf(
        state0,
        arc_span_s,
        drag=True,
        spacecraft=box_spacecraft(box_table),
        attitude=ipt,
    )
    t5 = _time.perf_counter() - t_wall
    d4 = pos4[:n_arc] - eph.positions_m[:n_arc]
    d5 = pos5[:n_arc] - eph.positions_m[:n_arc]
    print(
        f"  run 4: sphere_default on A_ram = {A_RAM_M2:.3f} m^2, default attitude "
        f"({t4:.0f} s wall)"
    )
    print(
        f"  run 5: box_face_default on {BOX_X_M} x {BOX_Y_M} x {BOX_Z_M} m box, "
        f"InPlaneTracking(ecef) ({t5:.0f} s wall)"
    )

    # --- residual table + growth profile -------------------------------------
    def ric_rms(diff: np.ndarray) -> tuple[float, float, float, float]:
        ric = ric_components(
            diff, eph.positions_m[:n_arc], eph.velocities_ms[:n_arc], earth_fixed=True
        )
        return (
            _rms(ric[:, 0]),
            _rms(ric[:, 1]),
            _rms(ric[:, 2]),
            _rms(np.linalg.norm(diff, axis=1)),
        )

    r1 = ric_rms(d1)
    r2 = ric_rms(d2)
    r3 = ric_rms(d3)
    r4 = ric_rms(d4)
    r5 = ric_rms(d5)
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
    print(f"  {'4: sphere table':<22}{r4[0]:>10.2f}{r4[1]:>12.2f}{r4[2]:>10.2f}{r4[3]:>12.2f}")
    print(f"  {'5: box table (IPT)':<22}{r5[0]:>10.2f}{r5[1]:>12.2f}{r5[2]:>10.2f}{r5[3]:>12.2f}")

    print("[growth]  3D |dr| propagated - truth (meters)")
    print(f"  {'run':<16}{'6 h':>12}{'12 h':>12}{'18 h':>12}{'24 h':>12}")
    _growth_row("1: drag off", d1, eph, n_arc)
    _growth_row("2: drag on nom", d2, eph, n_arc)
    _growth_row("3: drag on fit", d3, eph, n_arc)
    _growth_row("4: sphere table", d4, eph, n_arc)
    _growth_row("5: box table", d5, eph, n_arc)

    # One-line reading of the no-fit runs (build plan Chunk 2b).
    over4 = diag["cda_sphere_w"] / diag["cda_fit"]
    over5 = diag["cda_box_w"] / diag["cda_fit"]
    print(
        f"  reading: the no-fit tables carry {over4:.2f}x (sphere) / {over5:.2f}x "
        f"(box) the fitted rho*Cd*A product; the along-track residual is that "
        f"mismatch expressed through the drag pipeline -- density-limited by "
        f"construction, not a table defect."
    )

    # --- Chunk 2b consistency: predicted vs realized along-track @ 24 h ------
    # The propagation-level axis/wiring check: along-residual is ~linear in the
    # drag mismatch, so run k's signed along @ 24 h should be ~ -(s_k - 1) times
    # Run 1's (drag-off), with s_k = CdA_k / CdA_fit (rho-weighted arc means).
    # A wrong box<->attitude face mapping would realize a very different s.
    along1_24 = float(_along_track(d1, eph, n_arc)[-1])
    along4_24 = float(_along_track(d4, eph, n_arc)[-1])
    along5_24 = float(_along_track(d5, eph, n_arc)[-1])
    pred4 = -(over4 - 1.0) * along1_24
    pred5 = -(over5 - 1.0) * along1_24
    print("[consistency]  predicted vs realized signed along-track @ 24 h")
    print(
        f"  run 4 sphere: s = {over4:.2f} -> predicted {pred4:+9.1f} m, "
        f"realized {along4_24:+9.1f} m"
    )
    print(
        f"  run 5 box   : s = {over5:.2f} -> predicted {pred5:+9.1f} m, "
        f"realized {along5_24:+9.1f} m"
    )
    print(
        "  agreement here confirms the box/attitude axis mapping live (Verify 1) "
        "-- the realized drag matches the hand-summed face table."
    )

    # --- Optional fixed-Cd run (--fixed-cd=X): the "storm-surprise" case ------
    # One no-fit propagation at a Cd calibrated elsewhere (e.g. the active_2023
    # fitted 3.405) -- on the Chunk 2c onset arc this measures how fast a
    # pre-storm-calibrated prediction diverges when the storm arrives. The
    # 3-hourly signed along-track profile localizes the breakaway (Gannon onset
    # ~17:00 UT on the 2024-05-10 onset arc).
    if fixed_cd is not None:
        t_wall = _time.perf_counter()
        posf = _propagate_itrf(state0, arc_span_s, drag=True, cd=fixed_cd)
        tf = _time.perf_counter() - t_wall
        df = posf[:n_arc] - eph.positions_m[:n_arc]
        rf = ric_rms(df)
        alongf = _along_track(df, eph, n_arc)
        print(
            f"[fixed-Cd run]  Cd = {fixed_cd} held fixed, no fit -- the "
            f"storm-surprise case ({tf:.0f} s wall)"
        )
        print(
            f"  RIC RMS (m): radial {rf[0]:.2f}, along {rf[1]:.2f}, "
            f"cross {rf[2]:.2f}, 3D {rf[3]:.2f}"
        )
        cells = []
        for hours in range(3, 25, 3):
            k = min(int(hours * 3600 / SUBSAMPLE_S), n_arc - 1)
            cells.append(f"{hours}h {alongf[k]:+.0f}")
        print("  signed along-track profile (m): " + "  ".join(cells))

    # --- Verify 4 (optional): scale collapse of the box run ------------------
    # One propagation at the analytically predicted scale (no re-fit): scaling
    # the box Cd*A onto the fitted product should collapse Run 5 to ~ Run 3 if
    # the box adds no non-absorbable structure for this ram-dominated body.
    s_fit = diag["cda_fit"] / diag["cda_box_w"]

    def _scaled_box_cd(radius_m: float, density_kgm3: float, theta_rad: float) -> float:
        # The shipped box_face_default grid carries noise-level *negative* leeward
        # entries (~ -2e-6 near theta=pi) that the table lookup path tolerates but
        # the from_callable validation rejects (Cd must be >= 0) -- clamp at zero;
        # the effect is ~1e-6 m^2 of Cd*A, far below everything measured here.
        return max(0.0, s_fit * box_table(radius_m, density_kgm3, theta_rad))

    t_wall = _time.perf_counter()
    pos5s = _propagate_itrf(
        state0,
        arc_span_s,
        drag=True,
        spacecraft=box_spacecraft(
            BoxFaceCd.from_callable(_scaled_box_cd, name=f"box_face_default_x{s_fit:.4f}")
        ),
        attitude=ipt,
    )
    t5s = _time.perf_counter() - t_wall
    d5s = pos5s[:n_arc] - eph.positions_m[:n_arc]
    along5s = _rms(_along_track(d5s, eph, n_arc))
    print(f"[verify 4]  box Cd*A scaled onto the fitted product (x{s_fit:.3f})")
    print(
        f"  scaled-box along RMS = {along5s:.2f} m vs Run 3 fitted {r3[1]:.2f} m "
        f"({t5s:.0f} s wall)"
    )
    print(
        "  collapse to ~Run 3 = the box adds only absorbable scale for "
        "ram-dominated GRACE (the Checkpoint B geometry evidence)."
    )

    # --- Verify 5 (optional): length-corrected box sensitivity ---------------
    # The +0.33 m one-off check: geometry-insensitivity proves the Run 5
    # residual is density-limited, not dimension-limited.
    t_wall = _time.perf_counter()
    pos5l = _propagate_itrf(
        state0,
        arc_span_s,
        drag=True,
        spacecraft=box_spacecraft(box_table, y_length_m=BOX_Y_M + LENGTH_CORRECTION_M),
        attitude=ipt,
    )
    t5l = _time.perf_counter() - t_wall
    d5l = pos5l[:n_arc] - eph.positions_m[:n_arc]
    along5l = _rms(_along_track(d5l, eph, n_arc))
    print(
        f"[verify 5]  +{LENGTH_CORRECTION_M} m length-corrected box "
        f"(y = {BOX_Y_M + LENGTH_CORRECTION_M:.3f} m)"
    )
    print(
        f"  along RMS = {along5l:.2f} m vs Run 5 baseline {r5[1]:.2f} m "
        f"(delta {along5l - r5[1]:+.2f} m; density confound |Run5 - Run3| = "
        f"{r5[1] - r3[1]:.2f} m) ({t5l:.0f} s wall)"
    )

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
    print(
        f"  chunk 2b, on the common A_ram = {A_RAM_M2:.3f} m^2: sphere table Cd "
        f"{diag['cd_sphere_aram']:.2f} / box table Cd {diag['cd_box_aram']:.2f} / "
        f"fitted Cd {diag['cd_fit_aram']:.2f}; DSMC band "
        f"{DSMC_CD_BAND[0]}-{DSMC_CD_BAND[1]}"
    )
    print(
        f"  chunk 2b geometry evidence: no-fit along RMS sphere {r4[1]:.1f} m / "
        f"box {r5[1]:.1f} m vs fitted {r3[1]:.1f} m; scale-collapsed box "
        f"{along5s:.1f} m (~ Run 3 => the box adds only absorbable scale); "
        f"+{LENGTH_CORRECTION_M} m length check moves it {along5l - r5[1]:+.1f} m "
        f"(density-limited, not dimension-limited)."
    )


if __name__ == "__main__":
    main()
