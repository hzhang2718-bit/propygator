"""Table noise -- GRACE-FO C/D over the three inherited windows (Chunk 2).

Evidence for ``docs/history/build-plan-extended-validation-updated.md`` Chunk 2,
the contract's "The design - table noise". GRACE-FO C and D are essentially the
same body flying through the same atmosphere, so a quantity measured on one and
divided by the same quantity on the other should come out near 1.0. Four such
ratios are computed per window; a large departure is a bug signal, not a
finding.

    conda run -n propygator python run_table_noise.py
    conda run -n propygator python run_table_noise.py quiet_2019 --parse-only

THE RUNS, per window, per satellite. A 1-day arc from the window's t0: the
scalar-Cd fit against the along-track residual, then three propagations --
fitted Cd, sphere table, box table flown ``InPlaneTracking(ecef)``. No drag-off
run: the drag signal per window is Part 2's job, not this part's.

THE FOUR METRICS are the contract's, on 3D RMS alone (maintainer decision 2,
2026-08-14 -- radial / along / cross go in the breakdown, not the ratio table):
``Cd_fit``, ``RMS_Cd_fit``, ``RMS_sphere`` and ``RMS_box``, each as C/D. The
bars, why a non-zero deviation is expected physics rather than noise, and the
A/m convention are all printed into the results file itself -- that is the
authoritative statement of them, because it travels with the numbers.

FROZEN TRUTH, READ IN PLACE. The three windows belong to the v0.7.2 study, which
is frozen: its tarballs are read through ``--data-root`` and nothing there is
extracted, compressed, moved or deleted. Its ``find_window_files`` looks for
tarballs first, which is why this driver must not be pointed at an extracted
tree.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data). Stdout is ASCII-only
(captured under cp1252); the fit reports on stderr. ``--parse-only`` stops
before the JVM-touching steps.
"""

from __future__ import annotations

import argparse
import sys
import time as _time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
_REPO = _STUDY.parents[1]  # experiments/extended-validation -> repo root
_FROZEN = _STUDY.parent / "real-world-validation"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_FROZEN))
sys.path.insert(0, str(_FROZEN / "gracefo"))

# Frozen v0.7.2 modules -- imported, never edited (contract, "The earlier
# experiment is frozen"). find_window_files IS used here, unlike in run_screen:
# the frozen tree holds tarballs, which is exactly what it looks for.
from common import OMEGA_EARTH, ric_components  # noqa: E402
from common import rms as _rms  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402
from gracefo_ext_common import (  # noqa: E402
    A_RAM_M2,
    A_REF_M2,
    A_SIDES_TOTAL_M2,
    BOOM_PROJ_M2,
    BOX_X_M,
    BOX_Y_M,
    BOX_Z_M,
    CD_FIT_HI_DEFAULT,
    CD_FIT_HI_STORM,
    CD_FIT_TOL,
    CD_NOMINAL,
    DRY_MASS_KG,
    FRONT_PANEL_M2,
    FROZEN_DATA_ROOT,
    NORAD_IDS,
    SAT_IDS,
    SUBSAMPLE_S,
    TABLE_5_SIDE_TOTAL_M2,
    box_cda,
    box_spacecraft,
    box_table,
    fit_cd_scalar,
    force_config,
    sphere_spacecraft,
    sphere_table,
    window_mass_kg,
)
from mas1b import parse_mas1b  # noqa: E402
from thr1b import format_screen, screen_thr1b  # noqa: E402

from propygator import (  # noqa: E402
    Epoch,
    Frame,
    InPlaneTracking,
    IntegratorConfig,
    SpacecraftConfig,
    State,
    propagate_numerical,
)

LOAD_DAYS = 3  # both screens span the loaded days; the runs use a 1-day arc
ARC_DAYS = 1.0

# The three inherited v0.7.2 windows -> first loaded day (a file-name date
# filter; None = start at the window's first file). t0s unchanged from that
# study and from the retired Chunk 0 build.
WINDOWS: dict[str, str | None] = {
    "quiet_2019": None,  # t0 2019-11-14; F10.7 ~ 70, daily Ap ~ 2
    "active_2023": None,  # t0 2023-12-20; F10.7 ~ 190, daily Ap ~ 4
    "storm_2024": "2024-05-11",  # Gannon peak arc; the on-disk 05-10 onset day
    # is skipped, matching the frozen study
}

# The contract's qualification bars ("The design - table noise", Qualifications).
CD_RATIO_TOL = 0.10  # a failure warrants a bug search
RMS_RATIO_TOL = 0.20  # a departure past this demands attention

# --- VERBATIM COPIES -- DO NOT TUNE ------------------------------------------
# The tier-2 rule, the t0 bound and the grid-continuity bound are copied
# byte-for-byte from run_screen.py rather than re-derived, so the two drivers
# cannot disagree numerically about the same data. TIER2_FRACTION is a
# PRE-REGISTERED threshold carried from v0.7.2 run_gracefo.py:586: the contract
# requires it fixed before screening begins and never revisited after seeing a
# number, and re-fitting it and then reporting success is explicitly forbidden
# as circular. Both drivers print it into their results header, so a drift
# between these copies shows up as a diff between two committed evidence files.
# Change it in one place only by amending the contract. The full
# pre-registration argument is in run_screen.py's module docstring; the full
# t0-bound argument (1,152 measured epochs, median 5.6e-9 m, worst 2.99e-8 m, so
# 5e-8 m clears the worst case by 1.7x) is at run_screen.py::T0_ROUNDTRIP_TOL_M.
TIER2_FRACTION = 0.10
TIER2_POLY_DEGREE = 5
T0_ROUNDTRIP_TOL_M = 5e-8

# Truth-grid continuity bound, from run_screen.py::GRID_CONTINUITY_TOL_S. EVERY
# number this driver reports aligns propagated samples to truth BY ARRAY INDEX
# against a uniform t0 + k*SUBSAMPLE_S grid -- the Cd fit's objective, all three
# propagation RMS values and tier 2 alike. parse_gnv1b drops non-zero-qualflg
# records BEFORE subsampling, so one flagged 1 Hz record sitting on a grid point
# removes a 60 s epoch and every later sample is then differenced against truth
# one step later (~456 km of along-track). That does not raise anywhere: it
# rails the fit at the scan ceiling and inflates all four ratios' inputs while
# the run completes and prints HIT/MISS as though the numbers were sound. This
# is the check that catches it. A short TAIL is harmless and deliberately not
# checked -- every diff clips to a common length and t0 always aligns.
GRID_CONTINUITY_TOL_S = 1e-6


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _display_path(path: Path) -> str:
    """Repo-relative, forward-slashed, so the evidence is machine-independent."""
    try:
        return path.relative_to(_REPO).as_posix()
    except ValueError:
        return str(path)


def _propagate_itrf(
    state0: State,
    span_s: float,
    spacecraft: SpacecraftConfig,
    *,
    drag: bool = True,
    attitude: InPlaneTracking | None = None,
) -> np.ndarray:
    """Propagate ``span_s`` and return ITRF positions on the t0 + k*60 s grid."""
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
    # A guard trip returns a SHORT trajectory, and every caller slices the result
    # against a full-length truth array. Caught here so the failure names its
    # cause instead of surfacing as a numpy shape error deep inside a fit.
    if traj.metadata.get("terminated"):
        raise SystemExit(
            f"propagation terminated early: {traj.metadata.get('termination_reason')} "
            f"at {traj.metadata.get('termination_epoch')} -- the arc is short of "
            f"{span_s / 86400.0:.1f} d and no RMS below it would be over the "
            f"intended window"
        )
    return traj.to_frame(Frame.ITRF).positions


def _ric_rms(diff: np.ndarray, eph, n: int) -> tuple[float, float, float, float]:
    """Radial / along / cross / 3D RMS of a residual, Earth-fixed RIC."""
    ric = ric_components(
        diff[:n], eph.positions_m[:n], eph.velocities_ms[:n], earth_fixed=True
    )
    return (
        _rms(ric[:, 0]),
        _rms(ric[:, 1]),
        _rms(ric[:, 2]),
        _rms(np.linalg.norm(diff[:n], axis=1)),
    )


def _tier2(
    state0: State, span_s: float, eph, mass_kg: float
) -> tuple[float, float, bool, float, bool]:
    """The degree-5 departure test. Returns (signal, departure, clean, wall, term).

    Verbatim from run_screen.py::_tier2 -- see the DO NOT TUNE block above.
    """
    t_wall = _time.perf_counter()
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=SUBSAMPLE_S,
        force_models=force_config(True),
        spacecraft=sphere_spacecraft(CD_NOMINAL, mass_kg=mass_kg),
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    dt = _time.perf_counter() - t_wall
    # A guard trip would silently shorten the screened span, which is the one
    # way this gate could report CLEAN on a window it never fully examined.
    terminated = bool(traj.metadata.get("terminated"))
    positions = traj.to_frame(Frame.ITRF).positions

    n = min(len(positions), len(eph.epochs))
    diff = positions[:n] - eph.positions_m[:n]
    along = ric_components(
        diff, eph.positions_m[:n], eph.velocities_ms[:n], earth_fixed=True
    )[:, 1]
    t_rel = np.arange(n) * SUBSAMPLE_S
    coef = np.polyfit(t_rel, along, TIER2_POLY_DEGREE)
    departure = float(np.max(np.abs(along - np.polyval(coef, t_rel))))
    signal = float(np.max(np.abs(along)))
    clean = departure < TIER2_FRACTION * max(signal, 1.0)
    return signal, departure, clean, dt, terminated


def _fit_cd(
    state0: State,
    eph,
    n_arc: int,
    mass_kg: float,
    sat_id: str,
    cd_hi: float,
) -> tuple[float, int, float]:
    """The shared scalar-Cd fit against this window's along-track residual.

    The stderr trace is printed wide on purpose: at CD_FIT_TOL the last few steps
    move Cd by ~1e-3 and the RMS by ~1e-4 m, and a 3-decimal trace would show
    them as identical rows.
    """

    def objective(cd: float) -> float:
        pos = _propagate_itrf(
            state0, ARC_DAYS * 86400.0, sphere_spacecraft(cd, mass_kg=mass_kg)
        )
        diff = pos[:n_arc] - eph.positions_m[:n_arc]
        along = ric_components(
            diff, eph.positions_m[:n_arc], eph.velocities_ms[:n_arc], earth_fixed=True
        )[:, 1]
        val = _rms(along)
        print(
            f"    [{sat_id}] Cd = {cd:9.5f}  ->  along RMS = {val:13.6f} m",
            file=sys.stderr,
        )
        return val

    return fit_cd_scalar(objective, cd_hi)


def _arc_conditions(eph, n_arc: int, step: int = 10) -> dict[str, float]:
    """Arc-mean radius and density, and what the shipped tables predict there.

    The same CSSI-driven NRLMSISE-00 the drag force consumes, queried on the
    truth positions -- a diagnostic input, not a propagation. Face-flow angles
    under InPlaneTracking(ecef) are constant by construction (ram theta=0,
    leeward theta=pi, all four sides theta=pi/2), so the arc-mean varies only
    through the tables' (radius, density) inputs along the orbit.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.models.earth.atmosphere import NRLMSISE00
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

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
    pairs = list(zip(rad, rho))
    sph, box = sphere_table(), box_table()
    cd_sphere = float(np.mean([sph(float(a), float(b)) for a, b in pairs]))
    cd_ram = float(np.mean([box(float(a), float(b), 0.0) for a, b in pairs]))
    cd_side = float(np.mean([box(float(a), float(b), np.pi / 2) for a, b in pairs]))
    cd_lee = float(np.mean([box(float(a), float(b), np.pi) for a, b in pairs]))
    return {
        "r_mean": float(np.mean(rad)),
        "rho_mean": float(np.mean(rho)),
        "cd_sphere": cd_sphere,
        "cd_ram": cd_ram,
        "cd_side": cd_side,
        "cd_lee": cd_lee,
        "cda_sphere": cd_sphere * A_REF_M2,
        "cda_box": box_cda(cd_ram, cd_side, cd_lee),
    }


def _load(window_dir: Path, start_date: str | None, sat_id: str):
    """Parse GNV1B + MAS1B for one satellite, and list the days for THR1B.

    One file list serves all three products: the frozen tree holds daily
    tarballs, and every parser here reads its own member out of them.
    """
    files = find_window_files(window_dir, sat_id)
    if start_date is not None:
        files = [f for f in files if f.name >= f"gracefo_1B_{start_date}"]
    if not files:
        raise SystemExit(
            f"no GNV1B files under {window_dir}"
            + (f" on/after {start_date}" if start_date else "")
            + " -- point --data-root at the frozen v0.7.2 tree, which holds "
            "the daily tarballs this driver reads in place"
        )
    load = files[:LOAD_DAYS]
    if len(load) < LOAD_DAYS:
        raise SystemExit(
            f"{window_dir.name}: {len(load)} day(s) available, {LOAD_DAYS} needed"
        )
    return parse_gnv1b(load, sat_id=sat_id, subsample_s=SUBSAMPLE_S), load


def _print_convention() -> None:
    """The header block, with both geometry identities asserted and printed."""
    ram = BOX_X_M * BOX_Z_M
    sides = 2.0 * BOX_Y_M * (BOX_X_M + BOX_Z_M)
    print("[convention]  the 2026-08-13 contract geometry -- the repo's THIRD A_ref")
    print(
        f"  A_ref = {A_REF_M2:.7f} m^2 = Table 5 front panel {FRONT_PANEL_M2:.7f} "
        f"+ boom {BOOM_PROJ_M2:.7f} (boom folded into the ram face)"
    )
    print(
        f"  box x {BOX_X_M} (height) x y {BOX_Y_M} (length) x z {BOX_Z_M} (width) m; "
        f"+Y held on the wind by InPlaneTracking(ecef)"
    )
    print(
        f"  identity 1, ram face H*W  = {ram:.8f} m^2 vs A_ref {A_REF_M2:.7f} "
        f"(rel {abs(ram / A_REF_M2 - 1.0):.1e})"
    )
    print(
        f"  identity 2, sides 2L(H+W) = {sides:.7f} m^2 vs Table 5 "
        f"{TABLE_5_SIDE_TOTAL_M2:.7f} (rel "
        f"{abs(sides / TABLE_5_SIDE_TOTAL_M2 - 1.0):.1e})"
    )
    print(
        f"  mass = dry {DRY_MASS_KG:.3f} kg + MAS1B tank gas, PER SATELLITE "
        f"(decision 1, 2026-08-14)"
    )
    print(
        f"  Cd fit: tol {CD_FIT_TOL}, scan ceiling {CD_FIT_HI_DEFAULT} "
        f"({CD_FIT_HI_STORM} on storm windows)"
    )
    print(
        f"  [pre-registered] tier-2: degree-{TIER2_POLY_DEGREE} fit to the "
        f"{LOAD_DAYS}-day along-track residual of a drag-on Cd = {CD_NOMINAL} "
        f"propagation, CLEAN iff max departure < {TIER2_FRACTION:.0%} of max "
        f"|along-track|. Carried verbatim from v0.7.2 run_gracefo.py:586."
    )
    # Both identities are asserted, not merely printed: a geometry constant
    # edited without re-deriving its partner would otherwise flow silently into
    # every number below.
    if not (
        abs(ram / A_REF_M2 - 1.0) < 1e-6
        and abs(sides / TABLE_5_SIDE_TOTAL_M2 - 1.0) < 1e-6
    ):
        raise SystemExit(
            "geometry identities do not hold -- the box dimensions and A_ref "
            "have drifted apart; fix before reading any number below"
        )


def _emit_fixture(eph: dict[str, object], window: str) -> None:
    """Print the Chunk 23 twin-ratio pin literals: t0 PV + 600 s day-1 truth PV, C and D.

    Mirrors ``run_drag_window.py --emit-fixture`` (every 10th sample of the 60 s
    truth grid over day 1, 145 samples, offsets k*600 s), emitted for BOTH
    satellites so the Chunk 23 pin can build a genuine twin comparison. ``repr``
    floats round-trip exactly. JVM-free -- called before any JVM-touching step.

    THE DAY-1 GRID IS RE-VALIDATED HERE PER SATELLITE, same reasoning as
    run_drag_window.py's emitter: the grid-continuity check in ``run_window``'s
    ``[parser checks]`` block runs later and prints, so this path (which returns
    before reaching it) cannot rely on it without risking corrupted literals.
    """

    def row(a) -> str:
        return repr(tuple(float(v) for v in a))

    print("# --- pinned fixture generated by run_table_noise.py --emit-fixture ---")
    print(
        f"# source: {window} GNV1B, GRACE-FO C and D, see "
        f"experiments/extended-validation/README.md"
    )
    for sat in SAT_IDS:
        e = eph[sat]
        t0 = e.epochs[0]
        if len(e.epochs) <= 1440:
            raise SystemExit(
                f"{sat}: fixture needs 1441 day-1 samples, only {len(e.epochs)} loaded"
            )
        dts = np.array(
            [e.epochs[i + 1].seconds_since(e.epochs[i]) for i in range(1440)]
        )
        max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
        if max_dt_error > GRID_CONTINUITY_TOL_S:
            raise SystemExit(
                f"{sat}: day-1 truth grid has an interior hole -- max |dt - "
                f"{SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s. The emitted STEP_S "
                f"would be a lie and the pin would bake it in permanently."
            )
        if Epoch.from_iso(t0.to_iso(), t0.scale) != t0:
            raise SystemExit(
                f"{sat}: t0 round trip not exact -- the emitted T0_ISO is lossy"
            )
        print(f'T0_ISO_{sat} = "{t0.to_iso()}"  # {t0.scale.value}, ITRF')
    print("STEP_S = 600.0  # truth sample spacing below (day 1)")
    for sat in SAT_IDS:
        e = eph[sat]
        print(f"TRUTH_POS_M_{sat} = (")
        for i in range(0, 1441, 10):
            print(f"    {row(e.positions_m[i])},")
        print(")")
        print(f"TRUTH_VEL_MS_{sat} = (")
        for i in range(0, 1441, 10):
            print(f"    {row(e.velocities_ms[i])},")
        print(")")


def run_window(
    window: str, data_root: Path, *, parse_only: bool, emit_fixture: bool = False
) -> dict[str, float] | None:
    """One window, both satellites. Returns the row the cross-window summary uses."""
    start_date = WINDOWS[window]
    is_storm = window.startswith("storm")

    window_dir = data_root / window
    eph: dict[str, object] = {}
    files: dict[str, list[Path]] = {}
    for sat in SAT_IDS:
        eph[sat], files[sat] = _load(window_dir, start_date, sat)

    if emit_fixture:
        _emit_fixture(eph, window)
        return None

    print("=" * 78)
    print(
        f"=== window {window}"
        + (f" (first loaded day {start_date})" if start_date else "")
        + f", {LOAD_DAYS} days loaded, {ARC_DAYS:.0f}-day arc ==="
    )
    print("=" * 78)
    print(
        f"[versions] propygator {_pkg_version('propygator')}, "
        f"orekit_jpype {_pkg_version('orekit_jpype')}, numpy {np.__version__}"
    )
    print(
        f"[data root] {_display_path(data_root)}  (frozen v0.7.2 tree, read in place)"
    )
    _print_convention()

    print("[parse]")
    for sat in SAT_IDS:
        e = eph[sat]
        print(
            f"  {sat} = {e.sat_name} (NORAD {NORAD_IDS[sat]}), platform "
            f"{e.platform!r} v{e.product_version}, {len(e.source_files)} daily files"
        )
        print(
            f"    1 Hz records {e.n_raw_records} (QC-dropped {e.n_dropped_qc}); "
            f"subsampled to {SUBSAMPLE_S:.0f} s -> {len(e.epochs)} epochs"
        )
        print(f"    seam gaps > 1.5 s: {e._n_gaps} (max gap {e._max_gap_s:.1f} s)")
        print(
            f"    span: {e.epochs[0].to_iso()} -> {e.epochs[-1].to_iso()} "
            f"{e.epochs[0].scale.value}"
        )

    print("[mass]  MAS1B tank gas, both tanks (L1 Handbook sec 4.2.17)")
    mass: dict[str, float] = {}
    for sat in SAT_IDS:
        m = parse_mas1b(files[sat], sat_id=sat)
        mass[sat] = window_mass_kg(m.gas_mean_kg)
        print(
            f"  {sat}: gas mean {m.gas_mean_kg:.4f} kg over {m.n_records} records "
            f"(range {m.gas_min_kg:.4f}..{m.gas_max_kg:.4f}) "
            f"-> total {mass[sat]:.3f} kg"
        )
        if m.empty_files:
            # MAS1B is periodic, so a zero-record day is an OUTAGE, not a quiet
            # day. Named, with the bound it puts on the mean, so the reader can
            # see the gap is immaterial instead of being told it is. The mass is
            # never interpolated across it -- it is a reading (contract, "MAS1B
            # outages"). Matters more here than in run_screen: the per-satellite
            # mass is the whole content of the mass ratio below, and of the
            # shared-mass form of the headline Cd ratio.
            bound = m.mean_shift_bound_kg
            print(
                f"     {len(m.empty_files)} day(s) declare num_records: 0 "
                f"({', '.join(m.empty_files)}) -- telemetry outage, not a "
                f"truncated file (header cross-checked)"
            )
            print(
                f"     the mean is over the {m.n_records} records that exist; "
                f"the missing days can move it by at most {bound:.4f} kg "
                f"({100.0 * bound / mass[sat]:.4f}% of total mass), against a "
                f"CD_FIT_TOL resolution of ~0.05-0.1% in Cd"
            )
    mass_ratio = mass["C"] / mass["D"]
    print(
        f"  C/D mass ratio {mass_ratio:.6f} ({100.0 * (mass_ratio - 1.0):+.3f}%) -- "
        f"the Cd ratio below carries this factor exactly, and dividing it out "
        f"gives the shared-mass form"
    )

    # --- formation: which twin leads, measured rather than taken from literature
    n_common = min(len(eph["C"].epochs), len(eph["D"].epochs))
    dt_align = np.array(
        [eph["D"].epochs[i].seconds_since(eph["C"].epochs[i]) for i in range(n_common)]
    )
    rc = eph["C"].positions_m[:n_common]
    v_in = eph["C"].velocities_ms[:n_common] + np.cross(OMEGA_EARTH, rc)
    i_hat = v_in / np.linalg.norm(v_in, axis=1, keepdims=True)
    sep_vec = eph["D"].positions_m[:n_common] - rc
    sep = np.linalg.norm(sep_vec, axis=1)
    along_sep = np.einsum("ij,ij->i", sep_vec, i_hat)
    leader = "D" if along_sep.mean() > 0 else "C"
    max_align_s = float(np.max(np.abs(dt_align)))
    print("[formation]")
    print(
        f"  C/D epoch grids aligned: max |dt| = {max_align_s:.3e} s "
        f"over {n_common} samples"
    )
    # Asserted, not merely printed: every one of the four contract metrics is a
    # ratio of a quantity measured on C to the same quantity on D, which assumes
    # index i is the same instant for both twins. If one satellite loses a QC
    # record the other keeps, the twins are compared 60 s apart and the ratios
    # are meaningless -- while the run completes and reports HIT/MISS normally.
    if max_align_s > GRID_CONTINUITY_TOL_S:
        raise SystemExit(
            f"C/D epoch grids are not aligned -- max |dt| = {max_align_s:.3e} s. "
            f"The twin ratios compare C and D at index i, so a step of offset "
            f"makes all four of them meaningless. Resolve the dropped record "
            f"before reading any number from this window."
        )
    print(
        f"  separation |r_D - r_C|: mean {sep.mean() / 1e3:.1f} km "
        f"(min {sep.min() / 1e3:.1f}, max {sep.max() / 1e3:.1f})"
    )
    print(
        f"  signed along-track (D - C): {along_sep.mean() / 1e3:+.1f} km -> "
        f"{leader} LEADS; sign constant over the load: "
        f"{bool(np.all(np.sign(along_sep) == np.sign(along_sep[0])))}"
    )
    print(
        f"  Handbook sec 3.2.3 puts the roll axis anti-flight for the leader, so "
        f"{leader} meets the wind with its rear face. Front and Rear panels are "
        f"both {FRONT_PANEL_M2:.7f} m^2, so A_ram is IDENTICAL between the twins "
        f"and the model cannot see the 180 deg relative yaw."
    )

    print("[parser checks]")
    for sat in SAT_IDS:
        e = eph[sat]
        n = len(e.epochs)
        exact = all(Epoch.from_iso(ep.to_iso(), ep.scale) == ep for ep in e.epochs)
        dts = np.array(
            [e.epochs[i + 1].seconds_since(e.epochs[i]) for i in range(n - 1)]
        )
        r0 = float(np.linalg.norm(e.positions_m[0]))
        max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
        print(
            f"  {sat}: from_iso(to_iso()) == epoch for all {n}: {exact}; "
            f"max |dt - {SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s"
        )
        print(f"     |r0| = {r0 / 1e3:.1f} km (altitude ~ {r0 / 1e3 - 6378.1:.0f} km)")
        if not exact:
            raise SystemExit(
                f"{sat}: epoch round trip not exact -- fix before reading on"
            )
        if max_dt_error > GRID_CONTINUITY_TOL_S:
            raise SystemExit(
                f"{sat}: truth grid has an interior hole -- max |dt - "
                f"{SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s. Every diff in this "
                f"driver aligns by array index, so every sample after the hole "
                f"would be compared against truth one step later (~456 km of "
                f"along-track), railing the Cd fit and inflating all three RMS "
                f"runs with nothing raising. Resolve the dropped record before "
                f"reading any number from this window."
            )

    print("[screen tier-1 THR1B]  exact gate, no threshold, storm-proof")
    for sat in SAT_IDS:
        screen = screen_thr1b(files[sat], sat_id=sat)
        for line in format_screen(screen):
            print(line)
        if not screen.clean:
            print(
                f"     A burn on {sat} inside a table-noise window is not a "
                f"maintainer judgement call the way a Part 2 burn on D is: this "
                f"part needs BOTH twins. Escalate before reading the ratios."
            )

    if parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        print()
        return None

    n_arc = int(ARC_DAYS * 86400 / SUBSAMPLE_S) + 1

    print("[t0 sanity]  ITRF -> EME2000 -> ITRF, isolated from dynamics")
    state0: dict[str, State] = {}
    for sat in SAT_IDS:
        e = eph[sat]
        s0 = State(
            e.epochs[0], e.positions_m[0], e.velocities_ms[0], Frame.ITRF
        ).to_frame(Frame.EME2000)
        state0[sat] = s0
        back = s0.to_frame(Frame.ITRF)
        dr = float(np.linalg.norm(back.position - e.positions_m[0]))
        dv = float(np.linalg.norm(back.velocity - e.velocities_ms[0]))
        print(
            f"  {sat}: |dr| = {dr:.3e} m, |dv| = {dv:.3e} m/s "
            f"(bound {T0_ROUNDTRIP_TOL_M:.0e} m)"
        )
        if dr > T0_ROUNDTRIP_TOL_M:
            raise SystemExit(
                f"{sat}: t0 round trip {dr:.3e} m exceeds {T0_ROUNDTRIP_TOL_M:.0e} m"
            )

    print(
        f"[screen tier-2 deg-{TIER2_POLY_DEGREE}]  drag-on Cd = {CD_NOMINAL} over "
        f"the {LOAD_DAYS}-day load, so both gates cover the same span"
    )
    for sat in SAT_IDS:
        e = eph[sat]
        span_s = e.epochs[-1].seconds_since(e.epochs[0])
        signal, departure, clean, wall, terminated = _tier2(
            state0[sat], span_s, e, mass[sat]
        )
        verdict = clean and not terminated
        call = (
            "CLEAN"
            if verdict
            else ("REVIEW -- kink" if not clean else "REVIEW -- terminated")
        )
        print(
            f"  {sat}: signal {signal:.1f} m, departure {departure:.1f} m "
            f"({100.0 * departure / max(signal, 1.0):.1f}%) -> {call}  "
            f"({wall:.0f} s wall)"
        )
        if terminated:
            print(
                f"     TERMINATED trajectory -- a guard tripped, so the screened "
                f"span is short of {span_s / 86400.0:.1f} d. Treated as NOT CLEAN "
                f"regardless of the departure."
            )
        if is_storm and not clean:
            print(
                "     storm window: a real onset is itself a slope kink, so this "
                "departure documents the storm, not a burn. Tier 1 is the gate "
                "that is trusted here."
            )

    # --- per-satellite dynamics ----------------------------------------------
    ipt = InPlaneTracking(velocity_reference="ecef")
    cd_hi = CD_FIT_HI_STORM if is_storm else CD_FIT_HI_DEFAULT
    out: dict[str, dict[str, float]] = {}
    runs: dict[str, dict[str, tuple[float, float, float, float]]] = {}
    conditions: dict[str, dict[str, float]] = {}

    for sat in SAT_IDS:
        e = eph[sat]
        if n_arc > len(e.epochs):
            raise SystemExit(
                f"{sat}: arc needs {n_arc} samples but only {len(e.epochs)} loaded"
            )
        print(f"[{sat}]  {e.sat_name}, mass {mass[sat]:.3f} kg")

        print("  Cd fit (golden-section on the 1-day along-track RMS; stderr trace)")
        t_wall = _time.perf_counter()
        best_cd, evals, bracket = _fit_cd(state0[sat], e, n_arc, mass[sat], sat, cd_hi)
        t_fit = _time.perf_counter() - t_wall
        b_fit = best_cd * A_REF_M2 / mass[sat]
        print(
            f"    fitted Cd = {best_cd:.5f} on A_ref = {A_REF_M2:.7f} m^2, "
            f"B = Cd*A/m = {b_fit:.6e} m^2/kg"
        )
        print(
            f"    {evals} evals, tol {CD_FIT_TOL}, bracket width {bracket:.5f}, "
            f"ceiling {cd_hi}"
            + (" -- RAILED" if best_cd >= cd_hi - 0.05 else "")
            + f"  ({t_fit:.0f} s wall)"
        )
        if best_cd >= cd_hi - 0.05:
            print(
                f"    RAILED at the {cd_hi} scan edge -- read as 'fitted Cd > "
                f"{cd_hi}' (a density-bias bound, not a converged fit)"
            )

        span = ARC_DAYS * 86400.0
        specs = (
            ("fitted Cd", sphere_spacecraft(best_cd, mass_kg=mass[sat]), None),
            (
                "sphere table",
                sphere_spacecraft(sphere_table(), mass_kg=mass[sat]),
                None,
            ),
            ("box table (IPT)", box_spacecraft(box_table(), mass_kg=mass[sat]), ipt),
        )
        runs[sat] = {}
        timings = []
        for label, spacecraft, attitude in specs:
            t_wall = _time.perf_counter()
            pos = _propagate_itrf(state0[sat], span, spacecraft, attitude=attitude)
            timings.append(f"{label} {_time.perf_counter() - t_wall:.0f} s wall")
            runs[sat][label] = _ric_rms(pos[:n_arc] - e.positions_m[:n_arc], e, n_arc)
        print(f"    runs (1-day arc, output {SUBSAMPLE_S:.0f} s): {', '.join(timings)}")

        conditions[sat] = _arc_conditions(e, n_arc)
        out[sat] = {"cd": best_cd, "b": b_fit, "mass": mass[sat]}

    # --- the four contract metrics -------------------------------------------
    # Named rather than read back out of `metrics` below, because the shared-mass
    # form divides THIS ratio and nothing else by the mass ratio.
    cd_ratio = out["C"]["cd"] / out["D"]["cd"]
    metrics = [
        ("Cd_fit(C)/Cd_fit(D)", cd_ratio, CD_RATIO_TOL),
        (
            "RMS_Cd_fit(C)/RMS_Cd_fit(D)",
            runs["C"]["fitted Cd"][3] / runs["D"]["fitted Cd"][3],
            RMS_RATIO_TOL,
        ),
        (
            "RMS_sphere(C)/RMS_sphere(D)",
            runs["C"]["sphere table"][3] / runs["D"]["sphere table"][3],
            RMS_RATIO_TOL,
        ),
        (
            "RMS_box(C)/RMS_box(D)",
            runs["C"]["box table (IPT)"][3] / runs["D"]["box table (IPT)"][3],
            RMS_RATIO_TOL,
        ),
    ]

    print("[ratios]  the four contract metrics, C/D, on 3D RMS")
    print(f"  {'metric':<30}{'C/D':>10}{'dev':>10}{'bar':>8}   verdict")
    for name, value, bar in metrics:
        hit = abs(value - 1.0) <= bar
        print(
            f"  {name:<30}{value:>10.5f}{100.0 * (value - 1.0):>+9.2f}%"
            f"{bar:>7.0%}   {'HIT' if hit else 'MISS'}"
        )
    cd_shared = cd_ratio / mass_ratio
    print(
        f"  shared-mass form of the Cd ratio: {cd_shared:.5f} "
        f"({100.0 * (cd_shared - 1.0):+.2f}%) -- the per-satellite ratio above "
        f"divided by the C/D mass ratio {mass_ratio:.6f}, which is the whole of "
        f"the difference between the two forms"
    )
    print(
        "  A non-zero deviation is expected physics, not only noise: the twins fly "
        "a 180 deg relative yaw that puts opposite ends of the same tapered bus "
        "into the wind, but the box's +/-Y faces are equal-area, so that yaw is "
        "invisible to InPlaneTracking and the model gives both twins IDENTICAL "
        "geometry. The asymmetry is in the truth and absent from the model."
    )

    print("[values]  numerator and denominator of each ratio")
    print(f"  {'quantity':<28}{'C':>14}{'D':>14}")
    print(f"  {'fitted Cd':<28}{out['C']['cd']:>14.5f}{out['D']['cd']:>14.5f}")
    print(f"  {'mass (kg)':<28}{out['C']['mass']:>14.3f}{out['D']['mass']:>14.3f}")
    print(f"  {'B = Cd*A/m (m^2/kg)':<28}{out['C']['b']:>14.6e}{out['D']['b']:>14.6e}")
    for label in ("fitted Cd", "sphere table", "box table (IPT)"):
        print(
            f"  {'3D RMS ' + label + ' (m)':<28}"
            f"{runs['C'][label][3]:>14.2f}{runs['D'][label][3]:>14.2f}"
        )

    print("[breakdown]  1-day arc, propagated - truth, ITRF RIC RMS (m)")
    print(f"  {'sat':<5}{'run':<18}{'radial':>10}{'along':>12}{'cross':>10}{'3D':>12}")
    for sat in SAT_IDS:
        for label in ("fitted Cd", "sphere table", "box table (IPT)"):
            rr = runs[sat][label]
            print(
                f"  {sat:<5}{label:<18}{rr[0]:>10.2f}{rr[1]:>12.2f}"
                f"{rr[2]:>10.2f}{rr[3]:>12.2f}"
            )
    for sat in SAT_IDS:
        c = conditions[sat]
        print(
            f"  {sat} arc-mean conditions: r {c['r_mean'] / 1e3:.1f} km, "
            f"rho {c['rho_mean']:.3e} kg/m^3"
        )
        print(
            f"     shipped tables there: sphere Cd {c['cd_sphere']:.3f} -> CdA "
            f"{c['cda_sphere']:.4f} m^2; box per-face ram {c['cd_ram']:.3f} / "
            f"side {c['cd_side']:.3f} / leeward {c['cd_lee']:.3f} -> face-sum CdA "
            f"{c['cda_box']:.4f} m^2"
        )
        print(
            f"     fitted CdA {out[sat]['cd'] * A_REF_M2:.4f} m^2 on A_ref "
            f"{A_REF_M2:.7f}; box faces: ram/leeward {A_RAM_M2:.4f} m^2 each, "
            f"four sides {A_SIDES_TOTAL_M2:.4f} m^2 total"
        )
    print()

    return {name: value for name, value, _ in metrics}


def print_summary(rows: dict[str, dict[str, float]]) -> None:
    """The cross-window block -- computed here, never transcribed by hand."""
    names = [
        "Cd_fit(C)/Cd_fit(D)",
        "RMS_Cd_fit(C)/RMS_Cd_fit(D)",
        "RMS_sphere(C)/RMS_sphere(D)",
        "RMS_box(C)/RMS_box(D)",
    ]
    bars = {names[0]: CD_RATIO_TOL, **{n: RMS_RATIO_TOL for n in names[1:]}}
    print("=" * 78)
    print("[summary]  the four contract metrics across every window run")
    print("=" * 78)
    header = f"  {'window':<14}"
    for name in names:
        header += f"{name.split('(')[0]:>16}"
    print(header)
    n_hit = 0
    for window, row in rows.items():
        line = f"  {window:<14}"
        for name in names:
            hit = abs(row[name] - 1.0) <= bars[name]
            n_hit += int(hit)
            line += f"{100.0 * (row[name] - 1.0):>+13.2f}% {'H' if hit else 'M'}"
        print(line)
    total = len(rows) * len(names)
    print(
        f"  bars: Cd ratio within {CD_RATIO_TOL:.0%} of 1.0 (a failure warrants a "
        f"bug search); RMS ratios within {RMS_RATIO_TOL:.0%} (a departure past it "
        f"demands attention, and a bug search if no non-bug explanation is found)"
    )
    print(f"  {n_hit}/{total} metrics HIT")
    if n_hit != total:
        print(
            "  A MISS is written down as a miss (decision 5, 2026-08-14). The "
            "disposition is the maintainer's."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "windows",
        nargs="*",
        metavar="WINDOW",
        help=f"windows to run (default: all of {', '.join(WINDOWS)})",
    )
    parser.add_argument("--data-root", type=Path, default=FROZEN_DATA_ROOT)
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="parse, checks and tier 1 only, JVM-free",
    )
    parser.add_argument(
        "--emit-fixture",
        action="store_true",
        help="print the Chunk 23 twin-ratio pin literals (C and D) and exit, "
        "JVM-free -- pass exactly one window",
    )
    args = parser.parse_args()

    selected = args.windows or list(WINDOWS)
    for name in selected:
        if name not in WINDOWS:
            raise SystemExit(
                f"unknown window {name!r}; choose from {', '.join(WINDOWS)}"
            )

    if args.emit_fixture:
        for name in selected:
            run_window(
                name, args.data_root.resolve(), parse_only=False, emit_fixture=True
            )
        return

    t0 = _time.perf_counter()
    print("Extended validation -- Chunk 2: table noise, GRACE-FO C/D")
    rows: dict[str, dict[str, float]] = {}
    for name in selected:
        row = run_window(name, args.data_root.resolve(), parse_only=args.parse_only)
        if row is not None:
            rows[name] = row
    if rows:
        print_summary(rows)
    print(f"  wall time: {_time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    main()
