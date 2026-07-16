"""LAGEOS-2 vs. ILRS precise orbit — the Chunk 0 conservative-force diagnostic.

Evidence for ``docs/build-plan-real-world-validation.md`` Chunk 0 (Checkpoint A
is called on these numbers): parse the ILRS SP3 truth week, propagate the t0
truth state 7 days with the conservative force set, and decompose the residuals
in RIC at 1 / 3 / 7 days — after a t0 sanity diff that isolates frame/time
conversion from all dynamics.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data); the script is
cwd-independent:

    cd experiments/real-world-validation/lageos
    conda run -n propygator python run_lageos.py > results.txt

Stdout is ASCII-only (captured under cp1252); progress goes to stderr.
``--parse-only`` stops before the JVM-touching steps (parser checks only).
"""

from __future__ import annotations

import math
import sys
import time as _time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import ric_components, rms as _rms  # noqa: E402  (shared analysis kit)
from sp3 import lagrange_velocities, parse_sp3  # noqa: E402

from propygator import (  # noqa: E402
    Epoch,
    ForceModelConfig,
    Frame,
    IntegratorConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    State,
    propagate_numerical,
)

DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "lageos"

# LAGEOS-2 physical parameters (re-confirmed 2026-07-12; citations in README.md):
# mass and diameter from the ILRS mission page; Cr is the plan-pinned 1.13
# (literature range ~1.10-1.13 -- the Checkpoint-A tier-2 sweep knob if needed).
LAGEOS2_MASS_KG = 405.38
LAGEOS2_RADIUS_M = 0.30
LAGEOS2_AREA_M2 = math.pi * LAGEOS2_RADIUS_M**2
LAGEOS2_CR = 1.13


def main() -> None:
    parse_only = "--parse-only" in sys.argv

    print("LAGEOS-2 vs ILRS precise orbit -- Chunk 0 conservative-force diagnostic")
    print("=" * 74)

    files = sorted(DATA_DIR.glob("*.sp3*"))
    if not files:
        raise SystemExit(
            f"no SP3 file under {DATA_DIR} -- download the ILRS week first "
            "(see README.md; raw truth files are never committed)"
        )
    sp3_path = files[0]
    eph = parse_sp3(sp3_path)
    n = len(eph.epochs)
    span_s = eph.epochs[-1].seconds_since(eph.epochs[0])

    print("[data]")
    print(f"  file: {sp3_path.name}")
    print(f"  SP3 version: {eph.version}, V-records: {eph.velocities_ms is not None}")
    print(f"  satellite: {eph.sat_id}")
    print(f"  time system: {eph.time_system}")
    print(f"  coordinate system: {eph.coordinate_system} (ITRF-realization class)")
    print(
        f"  epochs: {n} (header claims {eph.n_epochs_header}), "
        f"interval {eph.epoch_interval_s:.1f} s"
    )
    print(
        f"  span: {eph.epochs[0].to_iso()} -> {eph.epochs[-1].to_iso()} "
        f"{eph.epochs[0].scale.value} ({span_s / 86400.0:.3f} days)"
    )

    # --- parser checks: bit-clean epoch round trip + grid uniformity ---------
    print("[parser checks]")
    exact = all(Epoch.from_iso(e.to_iso(), e.scale) == e for e in eph.epochs)
    for i in (0, n // 2, n - 1):
        y, mo, d, h, mi, s = eph.epoch_fields[i]
        print(
            f"  epoch[{i}]: file fields {y:4d}-{mo:02d}-{d:02d} "
            f"{h:02d}:{mi:02d}:{s:011.8f} {eph.time_system} -> "
            f"Epoch {eph.epochs[i].to_iso()} ({eph.epochs[i].scale.value})"
        )
    print(f"  from_iso(to_iso()) == epoch for all {n} epochs: {exact}")
    dts = np.array(
        [eph.epochs[i + 1].seconds_since(eph.epochs[i]) for i in range(n - 1)]
    )
    print(
        f"  grid uniformity: max |dt - {eph.epoch_interval_s:.1f} s| = "
        f"{np.max(np.abs(dts - eph.epoch_interval_s)):.3e} s "
        f"over {n - 1} intervals"
    )
    x0_km = eph.positions_m[0, 0] / 1000.0
    print(
        f"  position text round trip: first X re-formats to "
        f"'{x0_km:14.6f}' km (file: '   4648.005426')"
    )
    if not exact:
        raise SystemExit("epoch round trip not exact -- fix the parser first")

    # --- velocity routes: V-records vs Lagrange differentiation --------------
    if eph.velocities_ms is None:
        raise SystemExit("expected V-records in the ILRS product")
    vel_lag = lagrange_velocities(eph.positions_m, eph.epoch_interval_s)
    dv = np.linalg.norm(vel_lag - eph.velocities_ms, axis=1)
    print("[velocity routes]  V-records vs 7-point Lagrange differentiation")
    print(f"  all {n} epochs:  rms {_rms(dv):.3e} m/s, max {np.max(dv):.3e} m/s")
    print(
        f"  interior (excl. 3 edge samples/end): rms {_rms(dv[3:-3]):.3e} m/s, "
        f"max {np.max(dv[3:-3]):.3e} m/s"
    )
    print(f"  at t0 (initial state uses the V-record): |dv| = {dv[0]:.3e} m/s")

    if parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        return

    # --- t0 sanity: frame/time conversion isolated from all dynamics ---------
    t0 = eph.epochs[0]
    state0_itrf = State(t0, eph.positions_m[0], eph.velocities_ms[0], Frame.ITRF)
    state0 = state0_itrf.to_frame(Frame.EME2000)
    back = state0.to_frame(Frame.ITRF)
    print("[t0 sanity]")
    print(
        f"  ITRF -> EME2000 -> ITRF round trip at t0: "
        f"|dr| = {np.linalg.norm(back.position - state0_itrf.position):.3e} m, "
        f"|dv| = {np.linalg.norm(back.velocity - state0_itrf.velocity):.3e} m/s"
    )

    # --- propagate the 7-day arc ---------------------------------------------
    force_models = ForceModelConfig(
        drag=False, solid_tides=True, ocean_tides=True, relativity=True
    )
    spacecraft = SpacecraftConfig(
        mass_kg=LAGEOS2_MASS_KG,
        geometry=SpacecraftGeometry.sphere(
            area_m2=LAGEOS2_AREA_M2, reflectivity_coefficient=LAGEOS2_CR
        ),
    )
    print("[propagation]")
    print(f"  initial EME2000 state: r = {state0.position.tolist()} m")
    print(f"                         v = {state0.velocity.tolist()} m/s")
    print(
        f"  spacecraft: sphere A = {LAGEOS2_AREA_M2:.4f} m2, Cr = {LAGEOS2_CR}, "
        f"mass = {LAGEOS2_MASS_KG} kg"
    )
    print(
        "  force model: EIGEN-6S 70x70, Sun+Moon third body, cannonball SRP, "
        "solid tides, ocean tides, relativity; drag OFF"
    )
    print("  integrator: IntegratorConfig.high_precision()")
    t_wall = _time.perf_counter()
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=eph.epoch_interval_s,
        force_models=force_models,
        spacecraft=spacecraft,
        integrator=IntegratorConfig.high_precision(),
    )
    t_wall = _time.perf_counter() - t_wall
    print(f"  wall time: {t_wall:.1f} s; samples: {len(traj)} (truth: {n})")
    print(f"  metadata force_models: {traj.metadata.get('force_models')}")
    print(f"  metadata spacecraft: {traj.metadata.get('spacecraft')}")

    # Output grid vs truth grid: propagate_numerical samples at
    # t0 + k*output_step, which is exactly the truth grid (uniform, starts at
    # t0) -- verify, then diff sample arrays directly. (Trajectory.at() on the
    # truth epochs would reproduce these same samples: Hermite interpolation is
    # exact at its nodes. Fall back to it only if the grids ever misalign.)
    if len(traj) != n:
        raise SystemExit(f"sample count mismatch: {len(traj)} vs {n}")
    align = max(
        abs(traj[i].epoch.seconds_since(eph.epochs[i])) for i in (0, n // 2, n - 1)
    )
    print(
        f"  epoch alignment vs truth grid: max |dt| = {align:.3e} s "
        "(exact-grid diff path)"
    )
    if align > 1e-6:
        raise SystemExit("output grid misaligned with truth grid -- use .at()")

    traj_itrf = traj.to_frame(Frame.ITRF)
    d = traj_itrf.positions - eph.positions_m
    d_norm = np.linalg.norm(d, axis=1)
    dv0 = np.linalg.norm(traj_itrf.velocities[0] - eph.velocities_ms[0])
    print(
        f"  first propagated sample (t0) vs truth: |dr| = {d_norm[0]:.3e} m, "
        f"|dv| = {dv0:.3e} m/s   << 1 m required before anything else is "
        "interpretable"
    )

    print("[early growth]  |dr| propagated - truth")
    for label, offset_s in [
        ("t0 + 2 min", 120),
        ("t0 + 10 min", 600),
        ("t0 + 1 h", 3600),
        ("t0 + 6 h", 21600),
        ("t0 + 24 h", 86400),
    ]:
        k = int(offset_s / eph.epoch_interval_s)
        print(f"  {label:<11}: {d_norm[k]:12.3f} m")

    # --- RIC residual table ---------------------------------------------------
    ric = ric_components(d, eph.positions_m, eph.velocities_ms, earth_fixed=True)
    t_rel = np.arange(n) * eph.epoch_interval_s
    print("[residuals]  propagated - truth, ITRF positions, RIC (meters)")
    print(
        f"  {'horizon':<9}{'n':>6}{'radial rms':>12}{'max':>10}"
        f"{'along rms':>12}{'max':>10}{'cross rms':>12}{'max':>10}"
        f"{'3D rms':>12}{'max':>10}"
    )
    day1_rms = day1_max = 0.0
    for days in (1, 3, 7):
        m = t_rel <= days * 86400.0 + 1e-6
        row = [f"  {days} d".ljust(9), f"{int(np.sum(m)):>6}"]
        for c in range(3):
            row.append(f"{_rms(ric[m, c]):>12.3f}")
            row.append(f"{np.max(np.abs(ric[m, c])):>10.3f}")
        row.append(f"{_rms(d_norm[m]):>12.3f}")
        row.append(f"{np.max(d_norm[m]):>10.3f}")
        print("".join(row))
        if days == 1:
            day1_rms, day1_max = _rms(d_norm[m]), float(np.max(d_norm[m]))

    print("[checkpoint A]")
    print(
        f"  day-1 3D residual: rms {day1_rms:.3f} m, max {day1_max:.3f} m; "
        f"|dr| at t0+24h = {d_norm[int(86400 / eph.epoch_interval_s)]:.3f} m"
    )
    print(
        "  tiers: <=20 m/day GO | ~20-500 m/day INVESTIGATE inputs "
        "(Cr/mass/area, second AC's SP3) | >500 m/day INVESTIGATE wiring"
    )


if __name__ == "__main__":
    main()
