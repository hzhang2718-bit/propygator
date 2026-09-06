"""Part 2 drag propagations, one GRACE-FO window per invocation (Chunks 4-13).

Evidence for ``docs/history/build-plan-extended-validation-updated.md`` Part 2,
the contract's "Part A: additional drag-significant propagations, GRACE-FO".
Five configurations, five propagations, one 7-day arc from the window's t0:

1. drag off -- the residual growth IS the drag signal the model has to remove
2. drag on, ``Cd = 2.3`` -- the naive constant
3. drag on, in-arc scalar Cd fit over the FULL 7-day along-track RMS -- the best
   a scalar Cd can do over the window, and the reference the other four are read
   against
4. sphere table, ``VariableCd.sphere_default()`` on ``A_ref``
5. box table, ``BoxFaceCd.default()``, flown ``InPlaneTracking(ecef)``

    conda run -n propygator python run_drag_window.py low_2019_12
    conda run -n propygator python run_drag_window.py low_2019_12 --parse-only

**THE DAY 1, DAY 3 AND DAY 7 NUMBERS ARE READ OFF THOSE FIVE TRAJECTORIES,
NEVER RE-PROPAGATED** -- the easiest way to accidentally triple the study's
cost. Radial / along / cross / 3D RMS is recorded for every individual day,
days 1-7, under the per-day rule stated in full in ``drag_common``.

**THIS PART HAS NO BENCHMARK AND NONE IS ADDED HERE.** Nothing below is scored
HIT/MISS and no verdict is flagged; what warrants a bug search is an
*inversion*, a table run losing badly where drag is strong.

All runs are on GRACE-FO C, the leading twin (contract, "all the runs will be
conducted on GRACE-FO C"). ``--smoke`` runs a deliberately short, two-configuration
arc that is **not evidence** and says so in its own banner; it exists to prove
the driver end to end without paying for a real window.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data). Stdout is ASCII-only
(captured under cp1252); the fit reports on stderr.
"""

from __future__ import annotations

import argparse
import sys
import time as _time
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
_FROZEN = _STUDY.parent / "real-world-validation"
for _p in (str(_HERE), str(_STUDY), str(_FROZEN), str(_FROZEN / "gracefo")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

# Frozen v0.7.2 modules -- imported, never edited. find_window_files is
# deliberately NOT imported: it does not glob .gz, which is what this study's
# tree holds; windows.py carries this study's own finder.
from drag_common import (  # noqa: E402
    GRID_CONTINUITY_TOL_S,
    T0_ROUNDTRIP_TOL_M,
    arc_conditions,
    check_cssi_observed,
    display_path,
    make_recording_objective,
    pkg_version,
    print_conditions,
    print_day_table,
    print_fit_block,
    print_machine_rows,
    print_read_block,
    propagate_itrf,
    ric_rms,
    run_configs,
)
from gnv1b import parse_gnv1b  # noqa: E402
from gracefo_ext_common import (  # noqa: E402
    A_REF_M2,
    A_SIDE_X_M2,
    A_SIDE_Z_M2,
    ARC_DAYS,
    BOX_X_M,
    BOX_Y_M,
    BOX_Z_M,
    CD_FIT_HI_DEFAULT,
    CD_FIT_HI_STORM,
    CD_FIT_TOL,
    CD_NOMINAL,
    DRY_MASS_KG,
    LOAD_DAYS,
    NORAD_IDS,
    READ_DAYS,
    SUBSAMPLE_S,
    TABLE_5_SIDE_TOTAL_M2,
    box_spacecraft,
    box_table,
    fit_cd_scalar,
    sphere_spacecraft,
    sphere_table,
    window_mass_kg,
)
from mas1b import parse_mas1b  # noqa: E402
from thr1b import format_screen, screen_thr1b  # noqa: E402
from windows import (  # noqa: E402
    DATA_ROOT,
    WINDOW_DAYS,
    check_window_files,
    cssi_display_name,
    cssi_path,
    cssi_updated,
    find_product_files,
    read_cssi,
    resolve,
    window_indices,
)

from propygator import Epoch, Frame, InPlaneTracking, State  # noqa: E402

SAT = "C"  # the contract runs every Part 2 window on the leading twin

# The five configurations, in contract order. The id is the machine-readable
# token the summary keys off; the label is what the human tables print.
CONFIG_LABELS = {
    "drag_off": "1: drag off",
    "cd_2p3": "2: drag on (Cd=2.3)",
    "cd_fit": "3: drag on (Cd fit)",
    "sphere": "4: sphere table",
    "box": "5: box table (IPT)",
}

# --smoke: NOT EVIDENCE. A 1-day arc over 2 loaded days, drag-off and Cd = 2.3
# only. One day rather than the build plan's half day, because a half-day arc
# cannot produce a single per-day row and would therefore verify strictly less:
# day 1 is what exercises day_bounds, the RIC read, the day table and the
# machine rows -- i.e. the output shape this run exists to prove.
SMOKE_ARC_DAYS = 1.0
SMOKE_LOAD_DAYS = 2
SMOKE_CONFIGS = ("drag_off", "cd_2p3")


def _load_truth(window_dir: Path, load_days: int):
    """Parse GNV1B for C over the first ``load_days`` days of the window."""
    files = find_product_files(window_dir, "GNV1B", SAT, days=WINDOW_DAYS)
    return parse_gnv1b(files[:load_days], sat_id=SAT, subsample_s=SUBSAMPLE_S)


def _print_convention(arc_days: float) -> None:
    """The A/m header, with both geometry identities asserted and printed.

    ``arc_days`` is the arc this run will actually fit over, not ``ARC_DAYS``,
    so a smoke arc cannot claim the contract's 7-day objective.
    """
    ram = BOX_X_M * BOX_Z_M
    sides = 2.0 * BOX_Y_M * (BOX_X_M + BOX_Z_M)
    print("[convention]  the 2026-08-13 contract geometry -- the repo's THIRD A_ref")
    print(
        f"  A_ref = {A_REF_M2:.7f} m^2; box x {BOX_X_M} (height) x y {BOX_Y_M} "
        f"(length) x z {BOX_Z_M} (width) m, +Y held on the wind by "
        f"InPlaneTracking(ecef)"
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
        f"  Cd fit: tol {CD_FIT_TOL}, objective = the FULL {arc_days:.0f}-day "
        f"along-track RMS"
    )
    print(
        "  every fitted Cd prints B = Cd*A/m beside it -- the only "
        "convention-free number, and the one that travels between studies"
    )
    if not (
        abs(ram / A_REF_M2 - 1.0) < 1e-6
        and abs(sides / TABLE_5_SIDE_TOTAL_M2 - 1.0) < 1e-6
    ):
        raise SystemExit(
            "geometry identities do not hold -- the box dimensions and A_ref "
            "have drifted apart; fix before reading any number below"
        )


def emit_fixture(eph, window_name: str) -> None:
    """Print the Deliverable 4 pinned-test literals: t0 PV + 600 s day-1 truth PV.

    Every 10th sample of the 60 s truth grid over day 1 (145 samples, offsets
    k*600 s), matching the frozen study's fixture shape so the Chunk 23 tests
    can be written the same way. ``repr`` floats round-trip exactly. JVM-free.

    THE DAY-1 GRID IS RE-VALIDATED HERE rather than inherited from the
    ``[parser checks]`` block below. That block runs later and prints, so this
    path cannot reach it without corrupting the literals it emits -- yet
    ``STEP_S = 600.0`` and the positional ``range(0, 1441, 10)`` are true only
    on a hole-free 60 s grid. One QC-dropped record on a grid point would shift
    every later sample by 60 s, and this fixture is the one artifact that
    outlives the study as a permanent test pin.
    """

    def row(a) -> str:
        return repr(tuple(float(v) for v in a))

    t0 = eph.epochs[0]
    if len(eph.epochs) <= 1440:
        raise SystemExit(
            f"fixture needs 1441 day-1 samples, only {len(eph.epochs)} loaded"
        )
    dts = np.array(
        [eph.epochs[i + 1].seconds_since(eph.epochs[i]) for i in range(1440)]
    )
    max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
    if max_dt_error > GRID_CONTINUITY_TOL_S:
        raise SystemExit(
            f"day-1 truth grid has an interior hole -- max |dt - "
            f"{SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s. The emitted STEP_S = "
            f"600.0 would be a lie and the pin would bake it in permanently."
        )
    if Epoch.from_iso(t0.to_iso(), t0.scale) != t0:
        raise SystemExit("t0 round trip not exact -- the emitted T0_ISO is lossy")
    print("# --- pinned fixture generated by run_drag_window.py --emit-fixture ---")
    print(
        f"# source: {window_name} GNV1B, {eph.sat_name}, see "
        f"experiments/extended-validation/README.md"
    )
    print(f'T0_ISO = "{t0.to_iso()}"  # {t0.scale.value}, ITRF')
    print("STEP_S = 600.0  # truth sample spacing below (day 1)")
    print("TRUTH_POS_M = (")
    for i in range(0, 1441, 10):
        print(f"    {row(eph.positions_m[i])},")
    print(")")
    print("TRUTH_VEL_MS = (")
    for i in range(0, 1441, 10):
        print(f"    {row(eph.velocities_ms[i])},")
    print(")")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("window", metavar="WINDOW", help="one of the frozen ten")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="parse, checks and the THR1B verdict only, JVM-free",
    )
    parser.add_argument(
        "--emit-fixture",
        action="store_true",
        help="print the Deliverable 4 pinned-test literals and exit (JVM-free)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="NOT EVIDENCE: a short two-configuration arc that proves the driver",
    )
    args = parser.parse_args()

    window = resolve(args.window)
    data_root = args.data_root.resolve()
    window_dir = data_root / window.name
    load_days = SMOKE_LOAD_DAYS if args.smoke else LOAD_DAYS
    arc_days = SMOKE_ARC_DAYS if args.smoke else ARC_DAYS
    read_days = tuple(range(1, int(arc_days) + 1))  # the arc THIS run propagates
    horizons = tuple(d for d in READ_DAYS if d in read_days)
    t_start = _time.perf_counter()

    check_window_files(window, window_dir)
    eph = _load_truth(window_dir, load_days)

    if args.emit_fixture:
        emit_fixture(eph, window.name)
        return

    print("=" * 78)
    print(
        f"Extended validation -- Part 2 drag: window {window.index:02d} "
        f"{window.name} ({window.band})"
    )
    print("=" * 78)
    if args.smoke:
        print("*** SMOKE ARC -- NOT EVIDENCE ***")
        print(
            f"    {arc_days:.1f}-day arc, {load_days} days loaded, configurations "
            f"{', '.join(SMOKE_CONFIGS)} only, no Cd fit. This output proves the "
            f"driver runs end to end; it is not a Part 2 result and must never be "
            f"committed as one."
        )
    print(
        f"[versions] propygator {pkg_version('propygator')}, "
        f"orekit_jpype {pkg_version('orekit_jpype')}, numpy {np.__version__}"
    )
    print(f"[data root] {display_path(data_root)}")
    print(
        f"[window] {window.name}, band {window.band}, t0 {window.t0}, "
        f"{WINDOW_DAYS} days landed, {load_days} loaded, {arc_days:.0f}-day arc"
    )
    if window.note:
        print(f"  note: {window.note}")
    _print_convention(arc_days)

    # --- space weather: the window aggregates, re-read rather than trusted ----
    cssi_file = cssi_path()
    idx = window_indices(window, read_cssi(cssi_file))
    print("[space weather]  window aggregates, re-read from CSSI at runtime")
    print(f"  source: {cssi_display_name()}  (UPDATED {cssi_updated(cssi_file)})")
    print(
        f"  F10.7 {idx['f107']:.1f} (range {idx['f107_lo']:.0f}-{idx['f107_hi']:.0f}), "
        f"Ctr81 {idx['ctr81']:.1f}, Ap max {idx['ap_max']:.0f}, "
        f"ap3 max {idx['ap3_max']:.0f}, Kp max {idx['kp_max']:.1f}"
    )
    check_cssi_observed(idx, window.name)

    # --- parse report --------------------------------------------------------
    n = len(eph.epochs)
    print("[parse]")
    print(
        f"  {SAT} = {eph.sat_name} (NORAD {NORAD_IDS[SAT]}), platform "
        f"{eph.platform!r} v{eph.product_version}, {len(eph.source_files)} daily files"
    )
    print(
        f"  1 Hz records {eph.n_raw_records} (QC-dropped {eph.n_dropped_qc}); "
        f"subsampled to {SUBSAMPLE_S:.0f} s -> {n} epochs"
    )
    print(f"  seam gaps > 1.5 s: {eph._n_gaps} (max gap {eph._max_gap_s:.1f} s)")
    print(
        f"  span: {eph.epochs[0].to_iso()} -> {eph.epochs[-1].to_iso()} "
        f"{eph.epochs[0].scale.value}"
    )

    # --- mass: the whole window, so it ties out with the screen and Part 3 ---
    mas_files = find_product_files(window_dir, "MAS1B", SAT, days=WINDOW_DAYS)
    mas = parse_mas1b(mas_files, sat_id=SAT)
    mass_kg = window_mass_kg(mas.gas_mean_kg)
    print("[mass]  MAS1B tank gas, both tanks (L1 Handbook sec 4.2.17)")
    print(
        f"  read over the full {WINDOW_DAYS}-day window, not the {load_days} "
        f"loaded, so this is the same mass the screen and Part 3 print"
    )
    print(
        f"  {SAT}: gas mean {mas.gas_mean_kg:.4f} kg over {mas.n_records} records "
        f"(range {mas.gas_min_kg:.4f}..{mas.gas_max_kg:.4f}) -> dry "
        f"{DRY_MASS_KG:.3f} + gas = {mass_kg:.3f} kg"
    )
    if mas.empty_files:
        bound = mas.mean_shift_bound_kg
        print(
            f"     {len(mas.empty_files)} day(s) declare num_records: 0 "
            f"({', '.join(mas.empty_files)}) -- telemetry outage, not a truncated "
            f"file; the mass is a reading and is never interpolated across it"
        )
        print(
            f"     the missing days can move the mean by at most {bound:.4f} kg "
            f"({100.0 * bound / mass_kg:.4f}% of total mass), against a CD_FIT_TOL "
            f"resolution of ~0.05-0.1% in Cd"
        )

    # --- tier-1 THR1B, re-printed so this file is verifiable standalone ------
    print("[screen tier-1 THR1B]  exact gate, no threshold, storm-proof")
    print(
        f"  re-computed here over all {WINDOW_DAYS} days -- free, and it keeps "
        f"this results file readable without results_screen.txt beside it"
    )
    thr_files = find_product_files(window_dir, "THR1B", SAT, days=WINDOW_DAYS)
    screen = screen_thr1b(thr_files, sat_id=SAT)
    for line in format_screen(screen):
        print(line)
    if not screen.clean:
        raise SystemExit(
            f"{window.name}: THR1B reports a burn on {SAT}, which every Part 2 "
            f"run in this window would sit on top of. The window is retired or "
            f"slid per the build plan's failure rule before any number is read."
        )

    # --- parser checks -------------------------------------------------------
    print("[parser checks]")
    exact = all(Epoch.from_iso(e.to_iso(), e.scale) == e for e in eph.epochs)
    dts = np.array(
        [eph.epochs[i + 1].seconds_since(eph.epochs[i]) for i in range(n - 1)]
    )
    max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
    r0 = float(np.linalg.norm(eph.positions_m[0]))
    print(f"  from_iso(to_iso()) == epoch for all {n}: {exact}")
    print(f"  grid uniformity: max |dt - {SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s")
    print(f"  |r0| = {r0 / 1e3:.1f} km (altitude ~ {r0 / 1e3 - 6378.1:.0f} km)")
    if not exact:
        raise SystemExit("epoch round trip not exact -- fix the parser first")
    if max_dt_error > GRID_CONTINUITY_TOL_S:
        raise SystemExit(
            f"truth grid has an interior hole -- max |dt - {SUBSAMPLE_S:.0f} s| = "
            f"{max_dt_error:.3e} s. Every diff here aligns by array index, so every "
            f"sample after the hole would be compared against truth one step later "
            f"(~456 km of along-track), railing the fit and inflating every RMS "
            f"with nothing raising."
        )

    n_arc = int(arc_days * 86400 / SUBSAMPLE_S) + 1
    if n_arc > n:
        raise SystemExit(f"arc needs {n_arc} truth samples but only {n} loaded")

    if args.parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        print(f"  wall time: {_time.perf_counter() - t_start:.0f} s")
        return

    # --- t0 sanity -----------------------------------------------------------
    print("[t0 sanity]  ITRF -> EME2000 -> ITRF, isolated from dynamics")
    state0 = State(
        eph.epochs[0], eph.positions_m[0], eph.velocities_ms[0], Frame.ITRF
    ).to_frame(Frame.EME2000)
    back = state0.to_frame(Frame.ITRF)
    dr = float(np.linalg.norm(back.position - eph.positions_m[0]))
    dv = float(np.linalg.norm(back.velocity - eph.velocities_ms[0]))
    print(f"  |dr| = {dr:.3e} m, |dv| = {dv:.3e} m/s (bound {T0_ROUNDTRIP_TOL_M:.0e} m)")
    if dr > T0_ROUNDTRIP_TOL_M:
        raise SystemExit(f"t0 round trip {dr:.3e} m exceeds {T0_ROUNDTRIP_TOL_M:.0e} m")

    # --- what the shipped tables predict over this arc -----------------------
    print("[tables]  shipped a-priori tables at this window's conditions")
    cond = arc_conditions(
        eph,
        n_arc,
        a_ref_m2=A_REF_M2,
        a_ram_m2=BOX_X_M * BOX_Z_M,
        a_side_x_m2=A_SIDE_X_M2,
        a_side_z_m2=A_SIDE_Z_M2,
    )
    print_conditions(cond, a_ref_m2=A_REF_M2)

    # --- the in-arc scalar Cd fit -------------------------------------------
    ipt = InPlaneTracking(velocity_reference="ecef")
    cd_hi = CD_FIT_HI_STORM if window.is_storm else CD_FIT_HI_DEFAULT
    best_cd = None
    if not args.smoke:
        print(
            f"[Cd fit]  golden section on the FULL {arc_days:.0f}-day along-track "
            f"RMS (stderr trace)"
        )
        scan: list[tuple[float, float]] = []

        def _inner(cd: float) -> float:
            pos = propagate_itrf(
                state0, arc_days * 86400.0, sphere_spacecraft(cd, mass_kg=mass_kg)
            )
            diff = pos[:n_arc] - eph.positions_m[:n_arc]
            val = ric_rms(diff, eph, 0, n_arc - 1)[1]
            print(
                f"    [{SAT}] Cd = {cd:9.5f}  ->  along RMS = {val:13.6f} m",
                file=sys.stderr,
            )
            return val

        t_fit = _time.perf_counter()
        best_cd, n_evals, bracket = fit_cd_scalar(
            make_recording_objective(_inner, scan), cd_hi
        )
        print_fit_block(
            scan,
            best_cd,
            n_evals,
            bracket,
            cd_hi=cd_hi,
            n_coarse=7,
            a_ref_m2=A_REF_M2,
            mass_kg=mass_kg,
            tol=CD_FIT_TOL,
            wall_s=_time.perf_counter() - t_fit,
        )

    # --- the five propagations ----------------------------------------------
    # Built by FILTERING the full five on SMOKE_CONFIGS rather than by appending
    # under a second `if not args.smoke`, so the NOT-EVIDENCE banner above names
    # exactly the configurations that run. Deferred through lambdas because
    # `cd_fit` has no Cd until the fit above has run.
    builders = {
        "drag_off": lambda: (sphere_spacecraft(CD_NOMINAL, mass_kg=mass_kg), False, None),
        "cd_2p3": lambda: (sphere_spacecraft(CD_NOMINAL, mass_kg=mass_kg), True, None),
        "cd_fit": lambda: (sphere_spacecraft(best_cd, mass_kg=mass_kg), True, None),
        "sphere": lambda: (sphere_spacecraft(sphere_table(), mass_kg=mass_kg), True, None),
        "box": lambda: (box_spacecraft(box_table(), mass_kg=mass_kg), True, ipt),
    }
    run_ids = SMOKE_CONFIGS if args.smoke else tuple(CONFIG_LABELS)
    specs = [(i, CONFIG_LABELS[i], *builders[i]()) for i in run_ids]
    print(
        f"[runs]  {len(specs)} propagations, {arc_days:.0f}-day arc from t0, "
        f"output {SUBSAMPLE_S:.0f} s, high_precision"
    )
    diffs, _walls = run_configs(state0, eph, specs, arc_days=arc_days, n_arc=n_arc)

    # --- the per-day table ---------------------------------------------------
    print(
        f"[per-day]  propagated - truth, ITRF RIC RMS (m). Day N = [N-1 d, N d] "
        f"ALONE, never accumulated from t0."
    )
    per_day = print_day_table(diffs, CONFIG_LABELS, eph, read_days)

    # --- the read ------------------------------------------------------------
    print_read_block(
        per_day,
        CONFIG_LABELS,
        horizons,
        show_removed=not args.smoke,
        quote_v072=True,  # the v0.7.2 table is GRACE-FO's, not Swarm's
    )

    # --- machine-readable rows ----------------------------------------------
    if not args.smoke:
        print_machine_rows("gracefo", window.name, window.band, SAT, per_day)
        b_fit = best_cd * A_REF_M2 / mass_kg
        print(
            f"  MFIT gracefo {window.name} {SAT} {best_cd:.5f} {b_fit:.6e} "
            f"{mass_kg:.3f} {cd_hi:.1f}"
        )
    print(f"  wall time: {_time.perf_counter() - t_start:.0f} s")


if __name__ == "__main__":
    main()
