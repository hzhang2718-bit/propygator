"""GRACE-FO 2 stand-up, the twin noise floor, and Checkpoint A -- Chunk 0.

Evidence for ``docs/build-plan-extended-validation.md`` Chunk 0. Activates the
formation twin (GRACE-FO 2 = GRACE D, NORAD 43477) on truth already on disk,
measures the noise floor the fitted-Cd method has never had, and resolves
**Checkpoint A**. Zero downloads.

Run once per inherited window (quiet 2019 / active 2023 / Gannon storm 2024),
over BOTH satellites:

- **parse report** -- per-satellite qualflg drop rates, raw record counts, seam
  gaps, and the MAS1B tank-gas mass that sets the window's assumed spacecraft
  mass;
- **formation check** -- separation and which twin leads, measured from the two
  ephemerides rather than taken from literature. The L1 Handbook (sec 3.2.3)
  puts the roll axis anti-flight for the LEADING satellite and in-flight for
  the trailing one, so this fixes which end of the body meets the wind on each;
- **parser checks** -- epoch round-trip, grid uniformity, altitude;
- **t0 sanity** -- ITRF -> EME2000 -> ITRF round trip, isolated from dynamics;
- **maneuver screen** -- the v0.7.2 deg-5 departure test over the 3-day load.
  Not in the plan's literal Chunk 0 list; included because an unscreened burn
  on D alone would masquerade as a twin deviation and be misread as a wiring
  bug, which is exactly what this gate hunts;
- **Run 1 / Run 2** -- drag off, drag on at the nominal Cd;
- **Run 3** -- the scalar-Cd golden-section fit, per satellite;
- **A1** -- T(C,w)/T(D,w) for both shipped tables, plus the table-free
  Cd_fit(D)/Cd_fit(C), against the Checkpoint A criterion.

A1 CARRIES A MANDATORY THREE-TERM LABEL (contract sec 2.3 M1): the measured
deviation is "noise floor + fore/aft asymmetry + any true A/m difference
between the twins", never "noise floor" and never the two-term form. Both twins
are given the SAME assumed area and mass so that constant cancels from kappa;
the measured C-vs-D mass difference is reported separately as the bound on the
third term.

With no window argument it runs EVERY window in one process and closes with the
cross-window ``[A1 summary]`` block -- which is the point: A1's spread is the
chunk's deliverable, so it is computed here rather than transcribed into a
README afterwards. A single window may be named for debugging; it just cannot
produce the summary.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data). The script is
cwd-independent; a RELATIVE ``--data-root`` is resolved against the cwd, so the
example below assumes this directory (which is what ``run_all.py`` uses)::

    conda run -n propygator python run_twin_checkout.py \\
        --data-root=../../real-world-validation/data/gracefo

Stdout is ASCII-only (captured under cp1252); progress is silenced except the
fit, which reports on stderr. ``--parse-only`` stops before the JVM-touching
steps.
"""

from __future__ import annotations

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

# Frozen v0.7.2 modules -- imported, never edited (contract sec 9).
from common import OMEGA_EARTH, ric_components, rms as _rms  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402

from gracefo_ext_common import (  # noqa: E402
    A_REF_BRACKET_M2,
    A_REF_M2,
    BOX_GEOMETRY_SYSTEMATIC,
    BOX_X_M,
    BOX_Y_M,
    BOX_Z_M,
    CD_FIT_HI_DEFAULT,
    CD_FIT_HI_STORM,
    CD_FIT_TOL,
    CD_NOMINAL,
    CR,
    DATA_ROOT,
    DRY_MASS_KG,
    LAUNCH_MASS_KG,
    NORAD_IDS,
    SAT_IDS,
    SUBSAMPLE_S,
    box_cda,
    box_table,
    fit_cd_scalar,
    force_config,
    sphere_spacecraft,
    sphere_table,
    window_mass_kg,
)
from mas1b import parse_mas1b  # noqa: E402

from propygator import (  # noqa: E402
    Frame,
    IntegratorConfig,
    SpacecraftConfig,
    State,
    propagate_numerical,
)

LOAD_DAYS = 3  # consecutive days loaded (screen span); the runs use a 1-day arc
ARC_DAYS = 1.0

# window -> first loaded day (a tarball-name date filter; None = all files).
WINDOWS: dict[str, str | None] = {
    "quiet_2019": None,  # F10.7 ~ 70, daily Ap ~ 2 (deep solar minimum)
    "active_2023": None,  # F10.7 ~ 190, daily Ap ~ 4 (solar max, storm-free)
    "storm_2024": "2024-05-11",  # Gannon peak arc; the 05-10 onset arc is an
    # inherited daily-Ap smearing artifact and deliberately NOT an anchor
}

# --- v0.7.2 continuity reference (FROZEN -- quoted, never recomputed) ---------
# From experiments/real-world-validation/gracefo/results.txt, on that study's
# convention: A_ref = 1.027 m^2, m = 600.0 kg, box height 0.780 m. These are
# printed for continuity only. They are NEVER divided into a number produced
# here (docs/build-plan-extended-validation.md:484, :531 -- "never recomputed").
V072 = {
    # window: (fitted Cd on A=1.0, sphere CdA m^2, box CdA m^2)  [results.txt]
    "quiet_2019": (2.034, 2.996, 4.542),  # results.txt:31, :40, :41
    "active_2023": (3.405, 2.776, 4.173),  # results.txt:112, :121, :122
    "storm_2024": (4.080, 2.580, 3.983),  # results.txt:194, :203, :204
}
V072_MASS_KG = 600.0
V072_AREA_M2 = 1.0  # the driver's fit reference; A_ram = 1.027 was the restate

# Checkpoint A: |T(C,w)/T(D,w) - 1| must be within this of 1 in EVERY window.
CHECKPOINT_A_TOL = 0.10


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _display_path(path: Path) -> str:
    """Repo-relative, forward-slashed -- so the evidence is machine-independent.

    An absolute path in a committed results file reds ``run_all.py --verify`` on
    any other machine (and leaks a home directory). Falls back to the absolute
    form if --data-root points outside the repo, which is legal.
    """
    try:
        return path.relative_to(_REPO).as_posix()
    except ValueError:
        return str(path)


def _propagate_itrf(
    state0: State,
    span_s: float,
    drag: bool,
    spacecraft: SpacecraftConfig,
) -> np.ndarray:
    """Propagate ``span_s`` and return ITRF positions on the t0 + k*60 s grid."""
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=SUBSAMPLE_S,
        force_models=force_config(drag),
        spacecraft=spacecraft,
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    return traj.to_frame(Frame.ITRF).positions


def _along_track(diff: np.ndarray, eph, n: int) -> np.ndarray:
    """Signed along-track residual component over the first ``n`` samples."""
    return ric_components(
        diff[:n], eph.positions_m[:n], eph.velocities_ms[:n], earth_fixed=True
    )[:, 1]


def _arc_density(eph, n_arc: int, step: int = 10) -> tuple[np.ndarray, np.ndarray]:
    """NRLMSISE-00 density + geocentric radius on every ``step``-th arc sample.

    The same CSSI-driven model the drag force consumes, queried on the truth
    positions (a diagnostic input, not a propagation).
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


def _space_weather(mid_iso: str) -> str:
    """One-line F10.7 / Ap / Kp context from CssiSpaceWeatherData."""
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

    from propygator import Epoch, TimeScale

    cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
    date = Epoch.from_iso(mid_iso, TimeScale.UTC).to_orekit()
    return (
        f"F10.7 = {float(cssi.getInstantFlux(date)):.1f} "
        f"(81-day avg {float(cssi.getMeanFlux(date)):.1f}) sfu, "
        f"daily Ap = {float(cssi.getAp(date)[0]):.1f}, "
        f"daily Kp = {float(cssi.get24HoursKp(date)):.2f}"
    )


def _fit_cd(
    state0: State,
    span_s: float,
    eph,
    n_arc: int,
    mass_kg: float,
    sat_id: str,
    cd_hi: float,
) -> tuple[float, int, float]:
    """Run the shared scalar-Cd fit against this window's along-track residual.

    Returns ``(best_cd, n_evaluations, bracket_width)``. The optimizer itself
    lives in ``gracefo_ext_common.fit_cd_scalar`` so Chunks 2 and 3 inherit one
    fitter -- and, more importantly, ONE tolerance (see CD_FIT_TOL there: the
    tolerance sets the fit's resolution, and at the v0.7.2 value it is the same
    size as the twin deviation A1 exists to measure).

    The stderr trace is printed wide on purpose: at CD_FIT_TOL the last few
    steps move Cd by ~1e-3 and the RMS by ~1e-4 m, and a 3-decimal trace would
    show them as identical rows.
    """

    def objective(cd: float) -> float:
        pos = _propagate_itrf(
            state0, span_s, True, sphere_spacecraft(cd, mass_kg=mass_kg)
        )
        along = _along_track(pos - eph.positions_m[: len(pos)], eph, n_arc)
        val = _rms(along)
        print(
            f"    [{sat_id}] Cd = {cd:9.5f}  ->  along RMS = {val:13.6f} m",
            file=sys.stderr,
        )
        return val

    return fit_cd_scalar(objective, cd_hi)


def _load(window_dir: Path, start_date: str | None, sat_id: str):
    """Parse GNV1B + MAS1B for one satellite over the loaded days."""
    files = find_window_files(window_dir, sat_id)
    if start_date is not None:
        files = [f for f in files if f.name >= f"gracefo_1B_{start_date}"]
    if not files:
        raise SystemExit(
            f"no GNV1B files under {window_dir}"
            + (f" on/after {start_date}" if start_date else "")
            + " -- point --data-root at a tree that has the window"
        )
    load = files[:LOAD_DAYS]
    eph = parse_gnv1b(load, sat_id=sat_id, subsample_s=SUBSAMPLE_S)
    mas = parse_mas1b(load, sat_id=sat_id)
    return eph, mas


def run_window(
    window: str, data_root: Path, parse_only: bool
) -> dict[str, float | bool] | None:
    """One window, both satellites. Returns the row the A1 summary consumes."""
    start_date = WINDOWS[window]
    is_storm = window.startswith("storm")

    print("GRACE-FO twin checkout -- Chunk 0: the noise floor and Checkpoint A")
    print("=" * 74)
    print(f"[window] {window}" + (f" (first loaded day {start_date})" if start_date else ""))
    print("[versions]")
    print(
        f"  propygator {_pkg_version('propygator')}, "
        f"orekit_jpype {_pkg_version('orekit_jpype')}, "
        f"numpy {_pkg_version('numpy')}"
    )
    print(f"  data root: {_display_path(data_root)}")
    print("[convention]  this study's A/m, NOT the v0.7.2 study's")
    print(
        f"  A_ref = {A_REF_M2:.7f} m^2 (L1 Handbook Table 5 Front panel); "
        f"bracket {A_REF_BRACKET_M2[0]:.4f}-{A_REF_BRACKET_M2[1]:.4f} m^2, "
        f"point value at the LOWER bound"
    )
    print(
        f"  box {BOX_X_M} x {BOX_Y_M} x {BOX_Z_M} m; box CdA under-predicts by "
        f"~{BOX_GEOMETRY_SYSTEMATIC * 100:.1f}% (flattened slant faces + omitted "
        f"boom), window-independent so it cancels from every ratio"
    )
    print(
        f"  dry mass {DRY_MASS_KG:.3f} kg = launch {LAUNCH_MASS_KG['C']:.3f} kg "
        f"(Handbook Table 4 FM1) - propellant 31.3 kg (JPL press kit); "
        f"window mass = dry + MAS1B tank gas"
    )

    window_dir = data_root / window

    # --- parse both satellites ------------------------------------------------
    eph = {}
    mas = {}
    for sat in SAT_IDS:
        eph[sat], mas[sat] = _load(window_dir, start_date, sat)

    print("[data]")
    for sat in SAT_IDS:
        e = eph[sat]
        print(f"  {sat} = {e.sat_name} (NORAD {NORAD_IDS[sat]})")
        print(
            f"    platform {e.platform!r} v{e.product_version}; files "
            f"({len(e.source_files)}): {', '.join(e.source_files)}"
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
    drop_c, drop_d = eph["C"].n_dropped_qc, eph["D"].n_dropped_qc
    print(
        f"  QC drop comparison: C {drop_c}, D {drop_d} "
        f"-- {'comparable' if abs(drop_c - drop_d) <= max(10, 0.01 * eph['C'].n_raw_records) else 'ASYMMETRIC -- a finding, read before proceeding'}"
    )

    # --- mass -----------------------------------------------------------------
    print("[mass]  MAS1B tank gas, both tanks (L1 Handbook sec 4.2.17)")
    for sat in SAT_IDS:
        m = mas[sat]
        print(
            f"  {sat}: gas mean {m.gas_mean_kg:.4f} kg over {m.n_records} records "
            f"(first {m.gas_first_kg:.4f}, last {m.gas_last_kg:.4f}) "
            f"-> total {window_mass_kg(m.gas_mean_kg):.3f} kg"
        )
    mass_c = window_mass_kg(mas["C"].gas_mean_kg)
    mass_d = window_mass_kg(mas["D"].gas_mean_kg)
    # ONE assumed mass for both twins -- contract sec 2.3 M1 (see module docstring).
    mass_window = 0.5 * (mass_c + mass_d)
    print(
        f"  assumed window mass (shared by both twins): {mass_window:.3f} kg; "
        f"v0.7.2 assumed {V072_MASS_KG:.1f} kg "
        f"(delta {100.0 * (mass_window / V072_MASS_KG - 1.0):+.2f}%)"
    )
    print(
        f"  measured C/D mass ratio {mass_c / mass_d:.6f} "
        f"({100.0 * abs(mass_c / mass_d - 1.0):.3f}%) -- this is the BOUND on the "
        f"third term of A1's label, not a correction applied to the fits"
    )

    # --- formation ------------------------------------------------------------
    n_common = min(len(eph["C"].epochs), len(eph["D"].epochs))
    dt_align = np.array(
        [
            eph["D"].epochs[i].seconds_since(eph["C"].epochs[i])
            for i in range(n_common)
        ]
    )
    rc = eph["C"].positions_m[:n_common]
    vc = eph["C"].velocities_ms[:n_common]
    v_in = vc + np.cross(OMEGA_EARTH, rc)
    i_hat = v_in / np.linalg.norm(v_in, axis=1, keepdims=True)
    sep_vec = eph["D"].positions_m[:n_common] - rc
    sep = np.linalg.norm(sep_vec, axis=1)
    along_sep = np.einsum("ij,ij->i", sep_vec, i_hat)
    leader = "D" if along_sep.mean() > 0 else "C"
    sign_const = bool(np.all(np.sign(along_sep) == np.sign(along_sep[0])))
    print("[formation]")
    print(
        f"  C/D epoch grids aligned: max |dt| = {np.max(np.abs(dt_align)):.3e} s "
        f"over {n_common} samples"
    )
    print(
        f"  separation |r_D - r_C|: mean {sep.mean() / 1e3:.1f} km "
        f"(min {sep.min() / 1e3:.1f}, max {sep.max() / 1e3:.1f})"
    )
    print(
        f"  signed along-track (D - C): {along_sep.mean() / 1e3:+.1f} km "
        f"-> {leader} LEADS; sign constant over the load: {sign_const}"
    )
    print(
        f"  L1 Handbook sec 3.2.3: roll axis anti-flight for the leader, in-flight "
        f"for the trailer -> {leader} meets the wind with its rear face, "
        f"{'D' if leader == 'C' else 'C'} with its front (KBR horn) face."
    )
    print(
        "  Front and Rear panels are both 0.9551567 m^2 (Table 5), so A_ram is "
        "IDENTICAL between the twins -- the 180 deg relative yaw is about the "
        "nadir-aligned axis and does not change frontal area."
    )

    # --- parser checks --------------------------------------------------------
    from propygator import Epoch

    print("[parser checks]")
    for sat in SAT_IDS:
        e = eph[sat]
        n = len(e.epochs)
        exact = all(Epoch.from_iso(ep.to_iso(), ep.scale) == ep for ep in e.epochs)
        dts = np.array(
            [e.epochs[i + 1].seconds_since(e.epochs[i]) for i in range(n - 1)]
        )
        r0 = float(np.linalg.norm(e.positions_m[0]))
        print(
            f"  {sat}: from_iso(to_iso()) == epoch for all {n}: {exact}; "
            f"max |dt - {SUBSAMPLE_S:.0f} s| = {np.max(np.abs(dts - SUBSAMPLE_S)):.3e} s"
        )
        print(
            f"     |r0| = {r0 / 1e3:.1f} km (altitude ~ {r0 / 1e3 - 6378.1:.0f} km)"
        )
        if not exact:
            raise SystemExit(f"{sat}: epoch round trip not exact -- fix before reading on")

    if parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        return None

    n_arc = int(ARC_DAYS * 86400 / SUBSAMPLE_S) + 1
    arc_span_s = ARC_DAYS * 86400.0

    # --- per-satellite dynamics ----------------------------------------------
    results: dict[str, dict[str, float]] = {}
    for sat in SAT_IDS:
        e = eph[sat]
        n = len(e.epochs)
        if n_arc > n:
            raise SystemExit(f"{sat}: arc needs {n_arc} samples but only {n} loaded")
        span_load_s = e.epochs[-1].seconds_since(e.epochs[0])

        print(f"[{sat}] ---------------------------------------------------------")
        state0 = State(
            e.epochs[0], e.positions_m[0], e.velocities_ms[0], Frame.ITRF
        ).to_frame(Frame.EME2000)
        back = state0.to_frame(Frame.ITRF)
        print(
            f"  t0 ITRF -> EME2000 -> ITRF: |dr| = "
            f"{np.linalg.norm(back.position - e.positions_m[0]):.3e} m, "
            f"|dv| = {np.linalg.norm(back.velocity - e.velocities_ms[0]):.3e} m/s"
        )

        if sat == "C":
            print("  space weather (CssiSpaceWeatherData), per loaded day:")
            per_day = int(86400 / SUBSAMPLE_S)
            for day in range(LOAD_DAYS):
                k = min(day * per_day + per_day // 2, n - 1)
                iso = e.epochs[k].to_iso()
                print(f"    {iso[:10]} ~ {_space_weather(iso)}")

        # maneuver screen
        t_wall = _time.perf_counter()
        pos_screen = _propagate_itrf(
            state0, span_load_s, True, sphere_spacecraft(CD_NOMINAL, mass_kg=mass_window)
        )
        t_screen = _time.perf_counter() - t_wall
        ns = min(len(pos_screen), n)
        along_screen = _along_track(pos_screen - e.positions_m[:ns], e, ns)
        t_rel = np.arange(ns) * SUBSAMPLE_S
        coef = np.polyfit(t_rel, along_screen, 5)
        max_dev = float(np.max(np.abs(along_screen - np.polyval(coef, t_rel))))
        signal = float(np.max(np.abs(along_screen)))
        clean = max_dev < 0.10 * max(signal, 1.0)
        print(
            f"  maneuver screen ({LOAD_DAYS} d, {t_screen:.0f} s wall): signal "
            f"{signal:.1f} m, deg-5 departure {max_dev:.1f} m -> "
            f"{'CLEAN' if clean else 'REVIEW -- kink'}"
        )
        if is_storm:
            print(
                "    storm window: a real onset is itself a slope kink, so the "
                "departure documents the storm, not a burn."
            )

        # Runs 1-2
        t_wall = _time.perf_counter()
        pos1 = _propagate_itrf(
            state0, arc_span_s, False, sphere_spacecraft(CD_NOMINAL, mass_kg=mass_window)
        )
        pos2 = _propagate_itrf(
            state0, arc_span_s, True, sphere_spacecraft(CD_NOMINAL, mass_kg=mass_window)
        )
        t_runs = _time.perf_counter() - t_wall
        d1 = pos1[:n_arc] - e.positions_m[:n_arc]
        d2 = pos2[:n_arc] - e.positions_m[:n_arc]
        print(
            f"  first propagated sample (t0) vs truth: |dr| = "
            f"{np.linalg.norm(d1[0]):.3e} m ({t_runs:.0f} s wall, 2 arcs)"
        )

        # Run 3
        print("  Cd fit (golden-section; progress on stderr)")
        cd_hi = CD_FIT_HI_STORM if is_storm else CD_FIT_HI_DEFAULT
        t_wall = _time.perf_counter()
        best_cd, evals, bracket = _fit_cd(
            state0, arc_span_s, e, n_arc, mass_window, sat, cd_hi
        )
        t_fit = _time.perf_counter() - t_wall
        pos3 = _propagate_itrf(
            state0, arc_span_s, True, sphere_spacecraft(best_cd, mass_kg=mass_window)
        )
        d3 = pos3[:n_arc] - e.positions_m[:n_arc]
        print(
            f"  fitted Cd = {best_cd:.5f} on A_ref = {A_REF_M2:.4f} m^2 in "
            f"{evals} evals ({t_fit:.0f} s wall); tol {CD_FIT_TOL}, bracket "
            f"width {bracket:.5f} [fit-quality diagnostic only, never an error "
            f"bar; the bracket sets the fit's RESOLUTION -- see CD_FIT_TOL]"
        )
        if best_cd >= cd_hi - 0.05:
            print(
                f"  NOTE: fit railed at the {cd_hi} scan edge -- read as "
                f"'fitted Cd > {cd_hi}' (a density-bias bound, not a converged fit)"
            )

        def ric_rms(diff: np.ndarray) -> tuple[float, float, float, float]:
            ric = ric_components(
                diff, e.positions_m[:n_arc], e.velocities_ms[:n_arc], earth_fixed=True
            )
            return (
                _rms(ric[:, 0]),
                _rms(ric[:, 1]),
                _rms(ric[:, 2]),
                _rms(np.linalg.norm(diff, axis=1)),
            )

        r1, r2, r3 = ric_rms(d1), ric_rms(d2), ric_rms(d3)
        print("  residuals, 1-day arc, ITRF RIC RMS (m):")
        print(f"    {'run':<22}{'radial':>10}{'along':>12}{'cross':>10}{'3D':>12}")
        for label, rr in (
            ("1: drag off", r1),
            (f"2: drag on (Cd={CD_NOMINAL})", r2),
            ("3: drag on (Cd fit)", r3),
        ):
            print(f"    {label:<22}{rr[0]:>10.2f}{rr[1]:>12.2f}{rr[2]:>10.2f}{rr[3]:>12.2f}")
        ratio = r2[1] / r1[1] if r1[1] > 0 else float("nan")
        print(
            f"    drag-off {r1[1]:.1f} m -> drag-on {r2[1]:.1f} m (ratio {ratio:.2f}) "
            f"-> Cd-fit {r3[1]:.1f} m"
        )

        # shipped-table lookups at arc-mean conditions (no propagation)
        rad, rho = _arc_density(e, n_arc)
        r_mean, rho_mean = float(np.mean(rad)), float(np.mean(rho))
        cd_sphere = float(
            np.mean([sphere_table()(float(a), float(b)) for a, b in zip(rad, rho)])
        )
        bt = box_table()
        cd_ram = float(np.mean([bt(float(a), float(b), 0.0) for a, b in zip(rad, rho)]))
        cd_side = float(
            np.mean([bt(float(a), float(b), np.pi / 2) for a, b in zip(rad, rho)])
        )
        cd_lee = float(np.mean([bt(float(a), float(b), np.pi) for a, b in zip(rad, rho)]))
        cda_sphere = cd_sphere * A_REF_M2
        cda_box = box_cda(cd_ram, cd_side, cd_lee)
        cda_fit = best_cd * A_REF_M2
        b_fit = cda_fit / mass_window

        print(
            f"  arc-mean conditions: r {r_mean / 1e3:.1f} km, rho {rho_mean:.3e} kg/m^3"
        )
        print(
            f"  shipped tables at those conditions: sphere Cd {cd_sphere:.3f}; "
            f"box per-face ram {cd_ram:.3f} / side {cd_side:.3f} / leeward {cd_lee:.3f}"
        )
        print(
            f"  CdA (m^2): sphere {cda_sphere:.4f}, box {cda_box:.4f}, "
            f"fitted {cda_fit:.4f}; B_fit = {b_fit:.4e} m^2/kg"
        )
        t_sphere = cda_sphere / cda_fit
        t_box = cda_box / cda_fit
        a_scale = A_REF_BRACKET_M2[1] / A_REF_BRACKET_M2[0]
        print(f"  T = Cd_table/Cd_fitted: sphere {t_sphere:.4f}, box {t_box:.4f}")
        print(
            f"    A/m bracket on T_sphere (A_ref {A_REF_BRACKET_M2[0]:.4f} .. "
            f"{A_REF_BRACKET_M2[1]:.4f} m^2): {t_sphere:.4f} .. "
            f"{t_sphere * a_scale:.4f}  (T scales exactly as A_ref, contract 2.2)"
        )
        print(
            f"    T_box carries no A_ref bracket -- A_ref cancels there "
            f"(Cd_table is itself Sigma Cd*A / A_ref). Its level uncertainty is "
            f"the box geometry systematic, ~{BOX_GEOMETRY_SYSTEMATIC * 100:.1f}%."
        )
        print(
            "    Mass rides a separate ~0.17% level ambiguity (the two sources' "
            "launch masses differ by ~1 kg); it cancels from every ratio."
        )

        results[sat] = {
            "best_cd": best_cd,
            "bracket": bracket,
            "cda_fit": cda_fit,
            "b_fit": b_fit,
            "t_sphere": t_sphere,
            "t_box": t_box,
            "along_fit": r3[1],
            "along_off": r1[1],
            "along_on": r2[1],
            "t0_diff": float(np.linalg.norm(d1[0])),
        }

    # --- A1 and Checkpoint A --------------------------------------------------
    a1_sphere = results["C"]["t_sphere"] / results["D"]["t_sphere"]
    a1_box = results["C"]["t_box"] / results["D"]["t_box"]
    a1_free = results["D"]["best_cd"] / results["C"]["best_cd"]

    print("[A1]  the twin noise floor -- the first error bar this method has had")
    print(
        f"  T(C)/T(D): sphere table {a1_sphere:.4f} "
        f"({100.0 * (a1_sphere - 1.0):+.2f}%), box table {a1_box:.4f} "
        f"({100.0 * (a1_box - 1.0):+.2f}%)"
    )
    print(
        f"  table-free Cd_fit(D)/Cd_fit(C) = {a1_free:.4f} "
        f"({100.0 * (a1_free - 1.0):+.2f}%)"
    )
    print(
        "  MANDATORY LABEL: this deviation is 'noise floor + fore/aft asymmetry + "
        "any true A/m difference between the twins' -- NOT 'noise floor', and not "
        "the two-term form (contract sec 2.3 M1)."
    )
    print(
        f"    term 3 bounded by the measured C/D mass ratio: "
        f"{100.0 * abs(mass_c / mass_d - 1.0):.3f}% (area ratio ~1 by "
        f"build-identical construction; launch masses differ by 5 g)"
    )

    print("[v0.7.2 continuity]  FROZEN -- quoted, never recomputed")
    cd072, cda_sph072, cda_box072 = V072[window]
    b072 = cd072 * V072_AREA_M2 / V072_MASS_KG
    print(
        f"  v0.7.2 (A_ref = 1.027 m^2, m = 600.0 kg): fitted Cd {cd072:.3f} on "
        f"A = {V072_AREA_M2} m^2, T_sphere {cda_sph072 / (cd072 * V072_AREA_M2):.4f}, "
        f"T_box {cda_box072 / (cd072 * V072_AREA_M2):.4f}"
    )
    print(
        f"  ballistic coefficient B: v0.7.2 {b072:.4e} vs this study's C "
        f"{results['C']['b_fit']:.4e} m^2/kg "
        f"({100.0 * (results['C']['b_fit'] / b072 - 1.0):+.2f}%)"
    )
    print(
        "    B is convention-free, so this difference is the SRP coupling only "
        "(the same area feeds drag and SRP) -- a wiring cross-check, not a "
        "restatement. A few tenths of a percent is expected."
    )

    print("[Checkpoint A]  GO / INVESTIGATE -- the maintainer's call")
    checks = [
        (
            "D parses clean, QC drop rate comparable to C",
            abs(drop_c - drop_d) <= max(10, 0.01 * eph["C"].n_raw_records),
            f"C {drop_c} / D {drop_d}",
        ),
        (
            "t0 frame/time diff at float-noise level (<= 5e-9 m)",
            max(results["C"]["t0_diff"], results["D"]["t0_diff"]) <= 5e-9,
            f"C {results['C']['t0_diff']:.2e} / D {results['D']['t0_diff']:.2e} m",
        ),
        (
            "drag-on materially below drag-off",
            all(results[s]["along_on"] < 0.5 * results[s]["along_off"] for s in SAT_IDS),
            f"C {results['C']['along_on']:.1f}/{results['C']['along_off']:.1f}, "
            f"D {results['D']['along_on']:.1f}/{results['D']['along_off']:.1f} m",
        ),
        (
            f"T(C)/T(D) within {CHECKPOINT_A_TOL * 100:.0f}% of 1 (sphere)",
            abs(a1_sphere - 1.0) <= CHECKPOINT_A_TOL,
            f"{a1_sphere:.4f}",
        ),
        (
            f"T(C)/T(D) within {CHECKPOINT_A_TOL * 100:.0f}% of 1 (box)",
            abs(a1_box - 1.0) <= CHECKPOINT_A_TOL,
            f"{a1_box:.4f}",
        ),
    ]
    for label, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'MISS'}] {label}  ({detail})")
    print(
        f"  window verdict: {'all criteria met' if all(c[1] for c in checks) else 'AT LEAST ONE MISS -- read before calling the checkpoint'}"
    )
    if is_storm:
        print(
            "  storm caveat: the scalar-Cd fit does not collapse the storm residual "
            "(v0.7.2 measured 119 m on GRACE-FO 1), so this window is the least "
            "well-conditioned of the three. A miss HERE with quiet and active tight "
            "points at fit conditioning, not at wiring."
        )
    print(
        "  Checkpoint A is resolved across ALL windows, not per window; the "
        "measured deviation itself is the deliverable (M1)."
    )

    phi = (np.sqrt(5.0) - 1.0) / 2.0
    return {
        "a1_sphere": a1_sphere,
        "a1_box": a1_box,
        "a1_free": a1_free,
        "t_sphere": results["C"]["t_sphere"],
        "rung_pct": 100.0
        * phi
        * max(results[s]["bracket"] for s in SAT_IDS)
        / min(results[s]["best_cd"] for s in SAT_IDS),
        "all_ok": all(c[1] for c in checks),
    }


def print_summary(rows: dict[str, dict[str, float | bool]]) -> None:
    """The cross-window A1 block -- computed here, never restated by hand."""
    print("[A1 summary]  across every window run -- the deliverable (M1)")
    print(
        f"  {'window':<14}{'T(C)/T(D) sph':>15}{'box':>10}{'table-free':>13}"
        f"{'fit rung':>10}{'T_sphere(C)':>14}"
    )
    for name, r in rows.items():
        print(
            f"  {name:<14}{100.0 * (r['a1_sphere'] - 1.0):>+14.2f}%"
            f"{100.0 * (r['a1_box'] - 1.0):>+9.2f}%"
            f"{100.0 * (r['a1_free'] - 1.0):>+12.2f}%"
            f"{r['rung_pct']:>9.3f}%{r['t_sphere']:>14.4f}"
        )
    dev = max(abs(r["a1_sphere"] - 1.0) for r in rows.values())
    a1_vals = [r["a1_sphere"] for r in rows.values()]
    t_vals = [r["t_sphere"] for r in rows.values()]
    spread_a1 = max(a1_vals) / min(a1_vals) - 1.0
    spread_t = max(t_vals) / min(t_vals) - 1.0
    print(
        f"  max |T(C)/T(D) - 1| = {100.0 * dev:.2f}% -- the floor every "
        f"CROSS-BODY claim is judged against (contract sec 5). Cross-window "
        f"claims (B2, B5) use Chunk 2's sub-arc floor instead, not this one."
    )
    print(
        f"  'fit rung' is the golden-section lattice spacing at that window's "
        f"tolerance ({CD_FIT_TOL}). A deviation below its own rung is not "
        f"measured, it is quantized -- read each row's first three columns "
        f"against its rung before believing them."
    )
    print("  A1, both halves, as ratios of extremes (contract sec 2.5):")
    print(
        f"    (i)  every window within {CHECKPOINT_A_TOL * 100:.0f}% of 1: "
        f"{'HIT' if dev <= CHECKPOINT_A_TOL else 'MISS'}"
    )
    print(
        f"    (ii) A1 spread < T spread: "
        f"{'HIT' if spread_a1 < spread_t else 'MISS'} "
        f"({100.0 * spread_a1:.2f}% vs {100.0 * spread_t:.2f}%)"
    )
    print(
        "  MANDATORY LABEL: this deviation is 'noise floor + fore/aft asymmetry "
        "+ any true A/m difference between the twins' -- NOT 'noise floor', and "
        "not the two-term form (contract sec 2.3 M1)."
    )
    n_ok = sum(1 for r in rows.values() if r["all_ok"])
    print(
        f"  Checkpoint A: {n_ok} of {len(rows)} windows met every criterion -- "
        f"GO / INVESTIGATE is the maintainer's call."
    )


def main() -> None:
    parse_only = "--parse-only" in sys.argv
    data_root = DATA_ROOT
    for a in sys.argv[1:]:
        if a.startswith("--data-root="):
            data_root = Path(a.split("=", 1)[1]).expanduser()
            if not data_root.is_absolute():
                data_root = (Path.cwd() / data_root).resolve()
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    # No window argument runs every window in one process, so the cross-window
    # A1 summary is COMPUTED rather than transcribed. A single window is still
    # accepted for debugging; it just cannot produce the summary.
    windows = args or list(WINDOWS)
    for w in windows:
        if w not in WINDOWS:
            raise SystemExit(f"unknown window {w!r}; choose one of {tuple(WINDOWS)}")

    rows: dict[str, dict[str, float | bool]] = {}
    for w in windows:
        row = run_window(w, data_root, parse_only)
        if row is not None:
            rows[w] = row
    if len(rows) > 1:
        print_summary(rows)
    elif rows:
        print(
            "[A1 summary]  skipped -- one window only. Run with no window "
            "argument for the cross-window summary (the committed evidence)."
        )


if __name__ == "__main__":
    main()
