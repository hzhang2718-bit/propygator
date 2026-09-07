"""Part 2 drag propagations, one Swarm window per invocation (Chunks 4-13).

Evidence for the contract's "Part B: additional drag-significant propagations,
Swarm A, B". The identical five configurations the GRACE-FO leg runs, over the
same frozen windows, on a body whose mass and geometry are **estimates** --
which is the point of the leg, not a defect in it. Both satellites run in one
invocation, because one results file per window is what the layout asks for.

    conda run -n propygator python run_drag_window.py low_2019_12
    conda run -n propygator python run_drag_window.py low_2019_12 --parse-only

WHAT IS DIFFERENT FROM THE GRACE-FO LEG. The consequences of the first, third
and fourth for reading a row are stated in full in ``swarm_common``:

- **The mass and the areas are estimates** (``swarm_common``).
- **Truth is SP3, not GNV1B**, served on GPS time and read through the locked
  GPS + 19 s = TAI route (``swarm_sp3``). The wrong time scale is the failure
  mode that leaves every magnitude, seam and grid check clean, so the t0 anchor
  is asserted against GPS midnight rather than assumed.
- **There is no THR1B analogue, so the degree-5 polynomial is the only maneuver
  screen**, and it is not a reliable one.
- **A and B are not a twin pair**: B flies roughly 70 km higher.

To pay for that screen without a sixth propagation, the ``Cd = 2.3`` run is
propagated over the **full 8-day load** rather than the 7-day arc and does
double duty. Every RMS below is still read over the 7-day arc alone.

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
for _p in (str(_HERE), str(_STUDY), str(_STUDY / "gracefo"), str(_FROZEN)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from drag_common import (  # noqa: E402
    GRID_CONTINUITY_TOL_S,
    T0_ROUNDTRIP_TOL_M,
    TIER2_FRACTION,
    TIER2_POLY_DEGREE,
    along_track,
    arc_conditions,
    check_cssi_observed,
    deg5_departure,
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
from gracefo_ext_common import ARC_DAYS, LOAD_DAYS, READ_DAYS  # noqa: E402
from swarm_common import (  # noqa: E402
    A_REF_M2,
    A_SIDE_X_M2,
    A_SIDE_Z_M2,
    BOX_X_M,
    BOX_Y_M,
    BOX_Z_M,
    CD_FIT_HI_DEFAULT,
    CD_FIT_HI_STORM,
    CD_FIT_TOL,
    CD_NOMINAL,
    DATA_ROOT,
    MASS_KG,
    SAT_IDS,
    SUBSAMPLE_S,
    box_spacecraft,
    box_table,
    check_geometry,
    fit_cd_scalar,
    sphere_spacecraft,
    sphere_table,
)
from swarm_sp3 import expected_t0, find_swarm_files, parse_swarm_sp3  # noqa: E402
from windows import (  # noqa: E402
    cssi_display_name,
    cssi_path,
    cssi_updated,
    read_cssi,
    resolve,
    window_indices,
)

from propygator import Epoch, Frame, InPlaneTracking, State  # noqa: E402

CONFIG_LABELS = {
    "drag_off": "1: drag off",
    "cd_2p3": "2: drag on (Cd=2.3)",
    "cd_fit": "3: drag on (Cd fit)",
    "sphere": "4: sphere table",
    "box": "5: box table (IPT)",
}

SMOKE_ARC_DAYS = 1.0
SMOKE_LOAD_DAYS = 2
SMOKE_CONFIGS = ("drag_off", "cd_2p3")


def run_sat(sat: str, window, data_root: Path, *, args, arc_days: float,
            load_days: int, read_days: tuple[int, ...],
            horizons: tuple[int, ...]) -> None:
    """One Swarm satellite over one window."""
    window_dir = data_root / window.name
    days = window.days[:load_days]
    files = find_swarm_files(window_dir, sat, days)
    eph = parse_swarm_sp3(files, sat_id=sat, subsample_s=SUBSAMPLE_S)
    n = len(eph.epochs)

    print("-" * 78)
    print(f"--- Swarm {sat} ---")
    print("-" * 78)
    print("[parse]")
    print(
        f"  {eph.sat_name} (SP3 id {eph.sp3_id}), SP3-{eph.version}, "
        f"{len(eph.source_files)} daily files"
    )
    print(
        f"  time system {eph.time_system} -> TAI via the locked GPS + 19 s route; "
        f"coordinate system {eph.coordinate_system} -> Frame.ITRF"
    )
    print(
        f"  {eph.n_raw_records} records on the delivered "
        f"{eph.native_interval_s:.0f} s grid; subsampled to {SUBSAMPLE_S:.0f} s "
        f"-> {n} epochs"
    )
    print(
        f"  span: {eph.epochs[0].to_iso()} -> {eph.epochs[-1].to_iso()} "
        f"{eph.epochs[0].scale.value}"
    )

    # --- parser checks, including the one that catches a wrong time scale ----
    print("[parser checks]")
    want_t0 = expected_t0(window.t0)
    dt0 = eph.epochs[0].seconds_since(want_t0)
    print(
        f"  t0 anchor: {eph.epochs[0].to_iso()} vs GPS midnight on {window.t0} "
        f"= {want_t0.to_iso()} TAI (offset {dt0:+.3f} s)"
    )
    if abs(dt0) > 1e-6:
        raise SystemExit(
            f"Swarm {sat}: t0 sits {dt0:+.3f} s off GPS midnight on {window.t0}. "
            f"Reading these files as UTC costs ~18 s, or ~137 km of pure "
            f"along-track error, with every magnitude, seam and grid check still "
            f"clean -- resolve before reading any number below."
        )
    exact = all(Epoch.from_iso(e.to_iso(), e.scale) == e for e in eph.epochs)
    dts = np.array(
        [eph.epochs[i + 1].seconds_since(eph.epochs[i]) for i in range(n - 1)]
    )
    max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
    r = np.linalg.norm(eph.positions_m, axis=1)
    v = np.linalg.norm(eph.velocities_ms, axis=1)
    print(f"  from_iso(to_iso()) == epoch for all {n}: {exact}")
    print(f"  grid uniformity: max |dt - {SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s")
    print(
        f"  |r| {r.min() / 1e3:.1f}..{r.max() / 1e3:.1f} km (altitude ~"
        f"{r.mean() / 1e3 - 6378.1:.0f} km); |v| {v.min():.1f}..{v.max():.1f} m/s "
        f"(Earth-fixed)"
    )
    if not exact:
        raise SystemExit(f"Swarm {sat}: epoch round trip not exact")
    if max_dt_error > GRID_CONTINUITY_TOL_S:
        raise SystemExit(
            f"Swarm {sat}: truth grid has an interior hole -- max |dt - "
            f"{SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s. Every diff here aligns "
            f"by array index, so every sample after the hole would be compared "
            f"against truth one step later, with nothing raising."
        )

    n_arc = int(arc_days * 86400 / SUBSAMPLE_S) + 1
    if n_arc > n:
        raise SystemExit(f"arc needs {n_arc} truth samples but only {n} loaded")
    if args.parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        return

    print("[t0 sanity]  ITRF -> EME2000 -> ITRF, isolated from dynamics")
    state0 = State(
        eph.epochs[0], eph.positions_m[0], eph.velocities_ms[0], Frame.ITRF
    ).to_frame(Frame.EME2000)
    back = state0.to_frame(Frame.ITRF)
    dr = float(np.linalg.norm(back.position - eph.positions_m[0]))
    dv = float(np.linalg.norm(back.velocity - eph.velocities_ms[0]))
    print(f"  |dr| = {dr:.3e} m, |dv| = {dv:.3e} m/s (bound {T0_ROUNDTRIP_TOL_M:.0e} m)")
    if dr > T0_ROUNDTRIP_TOL_M:
        raise SystemExit(f"Swarm {sat}: t0 round trip {dr:.3e} m exceeds bound")

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
            pos = propagate_itrf(state0, arc_days * 86400.0, sphere_spacecraft(cd))
            diff = pos[:n_arc] - eph.positions_m[:n_arc]
            val = ric_rms(diff, eph, 0, n_arc - 1)[1]
            print(
                f"    [{sat}] Cd = {cd:9.5f}  ->  along RMS = {val:13.6f} m",
                file=sys.stderr,
            )
            return val

        t_fit = _time.perf_counter()
        best_cd, n_evals, bracket = fit_cd_scalar(
            make_recording_objective(_inner, scan), cd_hi
        )
        print_fit_block(
            scan, best_cd, n_evals, bracket,
            cd_hi=cd_hi, n_coarse=7, a_ref_m2=A_REF_M2, mass_kg=MASS_KG,
            tol=CD_FIT_TOL, wall_s=_time.perf_counter() - t_fit,
        )

    # The Cd = 2.3 run is propagated over the FULL LOAD so it doubles as the
    # polynomial screen; every read below still slices to the 7-day arc.
    screen_span_s = (len(eph.epochs) - 1) * SUBSAMPLE_S
    # Filtered on SMOKE_CONFIGS, not appended to, so the NOT-EVIDENCE banner
    # names exactly what runs; lambdas because cd_fit has no Cd until the fit.
    builders = {
        "drag_off": lambda: (sphere_spacecraft(CD_NOMINAL), False, None),
        "cd_2p3": lambda: (sphere_spacecraft(CD_NOMINAL), True, None),
        "cd_fit": lambda: (sphere_spacecraft(best_cd), True, None),
        "sphere": lambda: (sphere_spacecraft(sphere_table()), True, None),
        "box": lambda: (box_spacecraft(box_table()), True, ipt),
    }
    run_ids = SMOKE_CONFIGS if args.smoke else tuple(CONFIG_LABELS)
    specs = [(i, CONFIG_LABELS[i], *builders[i]()) for i in run_ids]
    print(
        f"[runs]  {len(specs)} propagations, {arc_days:.0f}-day arc from t0, "
        f"output {SUBSAMPLE_S:.0f} s, high_precision"
    )
    print(
        f"    (the Cd = 2.3 run goes {screen_span_s / 86400.0:.2f} d so it also "
        f"feeds the screen below)"
    )
    diffs, _walls = run_configs(
        state0, eph, specs, arc_days=arc_days, n_arc=n_arc,
        span_override_s={"cd_2p3": screen_span_s},
    )

    # --- the only maneuver screen this leg has ------------------------------
    along_full = along_track(diffs["cd_2p3"], eph, 0, len(eph.epochs) - 1)
    signal, departure, clean = deg5_departure(along_full)
    print(
        f"[screen deg-{TIER2_POLY_DEGREE}]  the ONLY gate on this leg -- Swarm has "
        f"no THR1B analogue"
    )
    print(
        f"  drag-on Cd = {CD_NOMINAL} over the full "
        f"{screen_span_s / 86400.0:.2f}-day load: signal {signal:.1f} m, departure "
        f"{departure:.1f} m ({100.0 * departure / max(signal, 1.0):.1f}%) -> "
        f"{'CLEAN' if clean else 'REVIEW -- kink'} against the pre-registered "
        f"{TIER2_FRACTION:.0%} bar"
    )
    print(
        "  RECORDED AS WEAK EVIDENCE. This gate missed both known-real burns in "
        "Chunk 2 (0.8 % / 1.9 %), because it normalizes by an unfitted Cd = 2.3 "
        "along-track error of tens of kilometres. A CLEAN here does not establish "
        "a quiet window, and an undetected maneuver stays a live risk on the rows "
        "below. The bar is not re-fitted (contract)."
    )
    if window.is_storm and not clean:
        print(
            "  storm window: a real onset is itself a slope kink, so this "
            "departure may document the storm rather than a burn -- and on this "
            "leg there is no exact gate to arbitrate."
        )

    print(
        f"[per-day]  propagated - truth, ITRF RIC RMS (m). Day N = [N-1 d, N d] "
        f"ALONE, never accumulated from t0."
    )
    per_day = print_day_table(diffs, CONFIG_LABELS, eph, read_days)

    print_read_block(
        per_day,
        CONFIG_LABELS,
        horizons,
        show_removed=not args.smoke,
        quote_v072=False,  # that table is GRACE-FO's; this leg has no counterpart
    )
    if not args.smoke:
        print_machine_rows("swarm", window.name, window.band, sat, per_day)
        b_fit = best_cd * A_REF_M2 / MASS_KG
        print(
            f"  MFIT swarm {window.name} {sat} {best_cd:.5f} {b_fit:.6e} "
            f"{MASS_KG:.3f} {cd_hi:.1f}"
        )
        print(f"  MSCREEN swarm {window.name} {sat} {signal:.3f} {departure:.3f} "
              f"{'CLEAN' if clean else 'REVIEW'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("window", metavar="WINDOW", help="one of the frozen ten")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--parse-only", action="store_true",
                        help="parse and checks only, JVM-free")
    parser.add_argument("--smoke", action="store_true",
                        help="NOT EVIDENCE: a short two-configuration arc")
    args = parser.parse_args()

    window = resolve(args.window)
    data_root = args.data_root.resolve()
    load_days = SMOKE_LOAD_DAYS if args.smoke else LOAD_DAYS
    arc_days = SMOKE_ARC_DAYS if args.smoke else ARC_DAYS
    read_days = tuple(range(1, int(arc_days) + 1))  # the arc THIS run propagates
    horizons = tuple(d for d in READ_DAYS if d in read_days)
    t_start = _time.perf_counter()

    print("=" * 78)
    print(
        f"Extended validation -- Part 2 drag, SWARM leg: window "
        f"{window.index:02d} {window.name} ({window.band})"
    )
    print("=" * 78)
    if args.smoke:
        print("*** SMOKE ARC -- NOT EVIDENCE ***")
        print(
            f"    {arc_days:.1f}-day arc, {load_days} days loaded, configurations "
            f"{', '.join(SMOKE_CONFIGS)} only, no Cd fit."
        )
    print(
        f"[versions] propygator {pkg_version('propygator')}, "
        f"orekit_jpype {pkg_version('orekit_jpype')}, numpy {np.__version__}"
    )
    print(f"[data root] {display_path(data_root)}")
    print(
        f"[window] {window.name}, band {window.band}, t0 {window.t0}, "
        f"{load_days} days loaded, {arc_days:.0f}-day arc"
    )
    if window.note:
        print(f"  note: {window.note}")
    print("[convention]  EVERY NUMBER BELOW RESTS ON ESTIMATES -- that is the point")
    print(
        f"  box x {BOX_X_M} (height) x y {BOX_Y_M} (length) x z {BOX_Z_M} (width) m, "
        f"A_ref = {A_REF_M2} m^2, mass = {MASS_KG} kg -- all ESTIMATES, consistent "
        f"with ESA's mission description; sources disagree"
    )
    print(
        f"  ram face H*W = {BOX_X_M * BOX_Z_M:.4f} m^2 = A_ref; +Y held on the "
        f"wind by InPlaneTracking(ecef)"
    )
    print(
        "  mass is a fixed literal, identical for both satellites and every "
        "window -- Swarm has no MAS1B analogue here"
    )
    print(
        "  A and B are NOT a twin pair (B flies higher), so an A-vs-B difference "
        "is an altitude difference before it is a body difference"
    )
    check_geometry()

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

    for sat in SAT_IDS:
        run_sat(sat, window, data_root, args=args, arc_days=arc_days,
                load_days=load_days, read_days=read_days, horizons=horizons)
    print(f"  wall time: {_time.perf_counter() - t_start:.0f} s")


if __name__ == "__main__":
    main()
