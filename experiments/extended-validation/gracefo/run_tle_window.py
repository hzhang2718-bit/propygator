"""Part 3 TLE fitting tests, one GRACE-FO window per invocation (Chunks 14-18).

Evidence for ``docs/build-plan-extended-validation-updated.md`` Part 3, the
contract's "The design -- TLE fitting tests". Thirteen scored configurations,
all forecasting the same ``[T, T + 7 d]`` from the same arc end ``T = t0 + 6 d``:

    naive_2d  arm_transplant  arm_zero  arm_fresh  catalog
    state_sphere  state_box  fade_tau_{0.5,0.75,1,1.5,2,3}

    conda run -n propygator python run_tle_window.py low_2019_12
    conda run -n propygator python run_tle_window.py low_2019_12 --parse-only

**FOURTEEN RUNS, THIRTEEN SCORED.** The 3 d staging fit ``fit3`` exists only to
supply the gate's ``s`` and is not a scored row; ``naive_2d`` doubles as the
staging fit ``fit2``, so it is fitted once and reported once. The ``catalog``
row fits nothing.

**THE GATE IS EVALUATED HERE BUT NOT ACTED ON.** All three arms run in every
window regardless of what the gate selects, so this driver never has to know
which arm won; the gate -> arm mapping is applied by ``summarize_tle.py``, a
JVM-free text pass that can be re-scored in seconds. Thresholds are frozen at
r < 0.05 and s < 0.1 and are never re-fitted (contract).

**GRACE-FO C ONLY.** D is read here for exactly one purpose: the catalogue
cross-tag discriminator, one day of truth. A burn on D does not matter to it --
the discriminator is a ~200 km tag offset against a km-class burn.

Five switches produce no evidence and are never committed as a results file:
``--parse-only`` (JVM-free parse, checks and arc geometry), ``--emit-fixture``
(the Chunk 23 gate pin's literals, JVM-free), ``--smoke`` (a short
five-configuration run that says so in its own banner), ``--verify-harness``
(the build plan's ``tau = None`` no-op check on the private fade harness, which
nothing else in the study exercises), and ``--verify-gate`` (the thresholds
against the playbook and one arm per corner case; needs neither data nor JVM,
so the window argument is ignored).

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data). Stdout is ASCII-only
(captured under cp1252); fit progress goes to stderr.
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

from catalog_tles import (  # noqa: E402
    CROSS_TAG_MIN_RATIO,
    cross_tag_check,
    entry_for,
    format_cross_tag,
    staleness_days,
)
from drag_common import (  # noqa: E402
    GRID_CONTINUITY_TOL_S,
    check_cssi_observed,
    display_path,
    pkg_version,
)
from gnv1b import parse_gnv1b  # noqa: E402

# ARC/LOAD/READ CONSTANTS COME FROM tle_fit_common ONLY -- gracefo_ext_common
# carries Part 2's ARC_DAYS = 7.0 / LOAD_DAYS = 8 under the same names, and an
# import of those here would silently fit Part 3 over Part 2's arc.
from gracefo_ext_common import (  # noqa: E402
    DRY_MASS_KG,
    NORAD_IDS,
    SUBSAMPLE_S,
    window_mass_kg,
)
from mas1b import parse_mas1b  # noqa: E402
from thr1b import format_screen, screen_thr1b  # noqa: E402
from tle_fit_common import (  # noqa: E402
    CONFIGS,
    CONFIGS_BY_ID,
    FORECAST_DAYS,
    K_T,
    LOAD_DAYS,
    R_THRESHOLD,
    READ_DAYS,
    S_THRESHOLD,
    SAMPLES_PER_DAY,
    SAT,
    SAT_NAME,
    STAGING_SPAN_2_D,
    STAGING_SPAN_3_D,
    arc_trajectory,
    bstar_sigma,
    compute_rs,
    forecast_ric_rms,
    measurement_indices,
    parse_bstar,
    run_weighted_fit,
    select_arm,
    state_reference,
)
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

from propygator import (  # noqa: E402
    Epoch,
    Frame,
    TimeScale,
    fit_tle_detailed,
    propagate_tle,
)

# --smoke: NOT EVIDENCE. Real T, one forecast day. Eight loaded days is enough
# for every arc: the 6 d fade arc reaches index 0 and the 1 d forecast ends at
# index 10080 of 11520.
#
# FIVE CONFIGURATIONS, NOT THE BUILD PLAN'S THREE. The plan names naive_2d,
# arm_zero and one tau -- a public free-B* fit, a public held-B* fit and the
# private age-weighted harness. The two state rows are added because they are
# the only remaining code path a window run can break on (numerical reference,
# the InPlaneTracking-ecef attitude, the propagate-then-fit route, the guard
# check), they cost ~35 s between them, and discovering a defect there in
# Chunk 15 would cost a full 5-10 minute window instead. The catalogue row is
# the one path smoke does not cover -- it was swept over all ten windows in
# Chunk 14 (10/10 PASS, see catalog_tles.py) and is re-checked in every real run.
SMOKE_LOAD_DAYS = 8
SMOKE_FORECAST_DAYS = 1.0
SMOKE_CONFIGS = ("naive_2d", "arm_zero", "fade_tau_1", "state_sphere", "state_box")

# In-arc RMS class check. The v0.7.2 study measured the SGP4 representation
# floor at ~500-700 m on a GNV1B day (docs sec 1.2 "the documented lossiness");
# anything past this is flagged, never silently accepted.
IN_ARC_RMS_FLAG_M = 2000.0

# --verify-harness bounds, pre-registered: the build plan's own "< 1 m in-arc
# RMS with the same B*". Measured bit-exact on window 1 (2026-08-22), so the
# bound is loose by design -- a drift alarm, not a tolerance to tune toward.
HARNESS_RMS_TOL_M = 1.0
HARNESS_SPANS_D = (2.0, 6.0)  # the shortest scored arc and the fade arc

# Arc-end / arc-span tolerance. Both deltas are exactly 0.0 on the truth grid
# and on both state references (measured, window 1), so this is a drift alarm
# rather than a tolerance to fit toward.
ARC_ALIGN_TOL_S = 1e-9

# THE FADE ROWS GET A LARGER BUDGET THAN THE SHIPPED DEFAULT, and only they do.
# `max_iterations` bounds evaluations as well as iterations (fitter.py, one
# value into setMaxIterations AND setMaxEvaluations), and short tau is expensive
# because uniform 300-sample subsampling leaves it an effective N of ~25 of 300 --
# the sampling-skew axis the build plan scopes out.
#
# RAISED 200 -> 800 (2026-08-23) AFTER 200 KILLED WINDOW 3. The 200 was
# calibrated on window 1 alone and does not generalise: a one-time uncommitted
# sweep of tau = 0.5 over all ten windows put the worst case at 471 evaluations,
# with seven of the ten past 200, so 800 is ~1.7x the worst case seen. Those
# sweep figures are PROVISIONAL -- every window's real demand lands in its own
# TFADE row, and Chunk 18 re-derives the range from the committed files. A cap
# above the demand cannot change a fitted answer (LM stops on convergence), so
# raising it moves no number in a window that was already converging; windows 1
# and 2 were never cap-bound and only their printed cap line changes.
#
# The unweighted rows keep the shipped 100 deliberately: they exist to represent
# what a user gets at defaults, and they top out at 20 evaluations across all
# ten windows and every band, a ~5x margin.
FADE_MAX_ITERATIONS = 800


def verify_harness(eph) -> int:
    """The build plan's ``tau = None`` no-op check. Returns the failure count.

    THE GUARD ON THIS STUDY'S ONE UNSUPPORTED DEPENDENCY. ``tle_fit_common``
    reaches into ``propygator.tle.fitter`` privates to make age weighting
    testable with no API change; the risk that carries is silent drift, where
    the private path stops matching the public one -- a different seed, a
    different measurement set, a different sigma -- and every fading-memory row
    in Part 3 then measures the harness rather than the weighting.

    Run the harness with ``tau_days=None`` (uniform sigmas, i.e. no weighting at
    all) over the same arc the public verb gets. They must agree. A disagreement
    is a build defect, not a result.

    Lives on the driver rather than in a probe script because nothing else in
    the study exercises it -- no driver runs it and no evidence file records it
    -- so without a home here it is a check that happens once and can never be
    repeated.
    """
    print("[verify-harness]  tau = None must reproduce the public fit_tle_detailed")
    print(
        f"  bounds (pre-registered, build plan Chunk 14): in-arc RMS within "
        f"{HARNESS_RMS_TOL_M:.1f} m, B* equal to 6 significant figures"
    )
    failures = 0
    for span in HARNESS_SPANS_D:
        arc = arc_trajectory(eph, span)
        public = fit_tle_detailed(
            arc,
            fitting_span=span * 86400.0,
            norad_id=NORAD_IDS[SAT],
            name=SAT_NAME,
            progress=False,
        )
        private = run_weighted_fit(arc, None, f"noop_{span:g}d")
        b_pub, b_prv = parse_bstar(public.tle.line1), private.bstar
        d_rms = abs(public.rms_m - private.rms_m)
        b_match = f"{b_pub:.6e}" == f"{b_prv:.6e}"
        ok = d_rms < HARNESS_RMS_TOL_M and b_match
        failures += 0 if ok else 1
        print(
            f"  arc [T - {span:g} d, T] ({len(arc)} samples, "
            f"{len(measurement_indices(len(arc)))} measurements)"
        )
        print(
            f"    public  fit_tle_detailed  : rms {public.rms_m:10.4f} m, "
            f"B* {b_pub:.6e}, {public.iterations} iters"
        )
        print(
            f"    private harness (tau=None): rms {private.rms_m:10.4f} m, "
            f"B* {b_prv:.6e}, {private.iterations} iters"
        )
        print(
            f"    delta rms {d_rms:.3e} m, B* equal {b_match} -> "
            f"{'PASS' if ok else 'FAIL'}"
        )
    if failures:
        print(
            f"  VERDICT: {failures} of {len(HARNESS_SPANS_D)} arcs FAILED -- the "
            f"private path has drifted from the public one; do not read a fade row"
        )
    else:
        print(
            f"  VERDICT: PASS on all {len(HARNESS_SPANS_D)} arcs -- the harness "
            f"differs from the shipped fitter only in its measurement sigmas, "
            f"which is the one thing it is supposed to change"
        )
    return failures


def verify_gate() -> int:
    """The build plan's gate check: thresholds, and an arm per corner case.

    JVM-free and data-free -- pure arithmetic over :func:`compute_rs` and
    :func:`select_arm`. Lives here beside ``--verify-harness`` because Chunk
    14's other Verify bullets each have a code home and this one otherwise has
    none: nothing else in the study re-checks the mapping, and
    ``summarize_tle.py`` only ever exercises the corners the ten landed windows
    happen to hit.

    The thresholds are checked against ``docs/tle-fitting-playbook.md`` itself,
    not merely against their own literals -- they are pre-registered predictions
    carried verbatim from that document, so the document is the authority.
    """
    print("[verify-gate]  frozen thresholds and the gate -> arm mapping")
    failures = 0

    playbook = _HERE.parents[2] / "docs" / "tle-fitting-playbook.md"
    text = playbook.read_text(encoding="utf-8")
    for label, const, literal in (
        ("R_THRESHOLD", R_THRESHOLD, "r < 0.05?"),
        ("S_THRESHOLD", S_THRESHOLD, "s < 0.1?"),
    ):
        found = literal in text
        ok = found and f"{const:g}" in literal
        failures += 0 if ok else 1
        print(
            f"  {label} = {const:g} vs playbook {literal!r}: "
            f"{'PASS' if ok else 'FAIL'}"
        )
    if not text:
        failures += 1

    inf, nan = float("inf"), float("nan")
    cases = (
        (0.01, 0.01, "arm_transplant", "observable and stationary"),
        (0.10, 0.01, "arm_zero", "r fails; s is not consulted"),
        (0.10, 0.50, "arm_zero", "both fail"),
        (0.01, 0.50, "arm_fresh", "observable but nonstationary (storm)"),
        (R_THRESHOLD, 0.01, "arm_zero", "r exactly at the bar -- strict <"),
        (0.01, S_THRESHOLD, "arm_fresh", "s exactly at the bar -- strict <"),
        (inf, inf, "arm_zero", "degenerate, pre-registered"),
        (nan, nan, "arm_zero", "NaN fails every comparison"),
    )
    for r, s, expect, why in cases:
        got = select_arm(r, s)
        ok = got == expect
        failures += 0 if ok else 1
        print(
            f"  r={r:<8g} s={s:<8g} -> {got:<15} expect {expect:<15} "
            f"{'PASS' if ok else 'FAIL'}  ({why})"
        )

    # The two degeneracies compute_rs is pre-registered to return as inf, which
    # must then route to arm_zero -- the arm for "B* unobservable".
    for label, args, expect_r in (
        ("covariance absent", (1.0, None, 1e-4, 1e-4), inf),
        ("B*(fit2) exactly zero", (1.0, 1e-6, 0.0, 1e-4), inf),
    ):
        r, s = compute_rs(*args)
        got = select_arm(r, s)
        ok = r == expect_r and got == "arm_zero"
        failures += 0 if ok else 1
        print(
            f"  compute_rs({label:<22}) -> r={r:<8g} arm={got:<15} "
            f"{'PASS' if ok else 'FAIL'}"
        )

    n = 2 + len(cases) + 2
    if failures:
        print(f"  VERDICT: {failures} of {n} checks FAILED -- the gate no longer "
              f"carries the playbook's prediction, so Part 3 would score a "
              f"different rule than the one it claims to test")
    else:
        print(f"  VERDICT: PASS on all {n} checks -- thresholds match the "
              f"playbook and every corner routes as documented")
    return failures


def _load_truth(window_dir: Path, sat: str, load_days: int, *, first_day: int = 0):
    """Parse GNV1B for one satellite over a slice of the window's daily files."""
    files = find_product_files(window_dir, "GNV1B", sat, days=WINDOW_DAYS)
    return parse_gnv1b(
        files[first_day : first_day + load_days], sat_id=sat, subsample_s=SUBSAMPLE_S
    )


def emit_fixture(eph, window_name: str) -> None:
    """Print the Chunk 23 gate-pin literals: the `fit2` arc, and exit. JVM-free.

    THE ARC IS EMITTED AT THE ESTIMATOR'S OWN MEASUREMENT INDICES. A fit over
    the full 60 s arc subsamples to ``_MEASUREMENT_CAP`` = 300 evenly spaced
    samples; emitting truth at exactly those indices means the pinned test
    builds a 300-sample Trajectory that re-subsamples 300 -> 300 and therefore
    fits the IDENTICAL measurement set off the IDENTICAL seed sample. The pin
    then reproduces this window's ``r`` closely rather than approximately, so a
    drift in the covariance path is visible rather than absorbed by a loose
    bound.

    The expected r / s / arm are NOT emitted here -- they need the JVM and two
    fits. They are hand-transcribed into the test from the committed ``[gate]``
    block, the repo's normal convention for transcribed numbers.
    """

    def row(a) -> str:
        return repr(tuple(float(v) for v in a))

    k0 = K_T - int(round(STAGING_SPAN_2_D * 86400.0 / SUBSAMPLE_S))
    if len(eph.epochs) <= K_T:
        raise SystemExit(
            f"fixture needs truth through index {K_T}, only "
            f"{len(eph.epochs)} samples loaded"
        )
    arc_epochs = eph.epochs[k0 : K_T + 1]
    dts = np.array(
        [
            arc_epochs[i + 1].seconds_since(arc_epochs[i])
            for i in range(len(arc_epochs) - 1)
        ]
    )
    max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
    if max_dt_error > GRID_CONTINUITY_TOL_S:
        raise SystemExit(
            f"fit2 arc has an interior hole -- max |dt - {SUBSAMPLE_S:.0f} s| = "
            f"{max_dt_error:.3e} s. The emitted sample offsets would be a lie and "
            f"the pin would bake it in permanently."
        )
    t0 = arc_epochs[0]
    if Epoch.from_iso(t0.to_iso(), t0.scale) != t0:
        raise SystemExit("arc-start round trip not exact -- the emitted ISO is lossy")

    # `idx` indexes the ARC, so truth reads are offset by k0. The epochs above
    # are already arc-relative; the position/velocity arrays are not.
    idx = measurement_indices(len(arc_epochs))
    print("# --- pinned fixture generated by run_tle_window.py --emit-fixture ---")
    print(
        f"# source: {window_name} GNV1B, {eph.sat_name}, the Part 3 `fit2` arc "
        f"[T - {STAGING_SPAN_2_D:g} d, T], see "
        f"experiments/extended-validation/README.md"
    )
    print(
        f"# emitted at the estimator's own measurement indices, so a fit over "
        f"these {len(idx)} samples sees the identical measurement set"
    )
    print(f'ARC_START_ISO = "{t0.to_iso()}"  # {t0.scale.value}, ITRF')
    print(f"FITTING_SPAN_S = {STAGING_SPAN_2_D * 86400.0!r}")
    print(f"NORAD_ID = {NORAD_IDS[SAT]}")
    print("# seconds after ARC_START_ISO, one per sample below")
    print("OFFSETS_S = (")
    for i in idx:
        print(f"    {arc_epochs[int(i)].seconds_since(t0)!r},")
    print(")")
    print("TRUTH_POS_M = (")
    for i in idx:
        print(f"    {row(eph.positions_m[k0 + int(i)])},")
    print(")")
    print("TRUTH_VEL_MS = (")
    for i in idx:
        print(f"    {row(eph.velocities_ms[k0 + int(i)])},")
    print(")")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("window", metavar="WINDOW", help="one of the frozen ten")
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="parse, checks, T and the THR1B verdict only, JVM-free",
    )
    parser.add_argument(
        "--emit-fixture",
        action="store_true",
        help="print the Chunk 23 gate-pin literals and exit (JVM-free)",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="NOT EVIDENCE: a short five-configuration run that proves the driver",
    )
    parser.add_argument(
        "--verify-harness",
        action="store_true",
        help="the tau = None no-op check on the private fade harness, then exit",
    )
    parser.add_argument(
        "--verify-gate",
        action="store_true",
        help="the gate's thresholds and corner cases, then exit (needs no data)",
    )
    args = parser.parse_args()

    if args.verify_gate:
        print("=" * 78)
        print("Part 3 gate check -- window-independent (NOT EVIDENCE)")
        print("=" * 78)
        sys.exit(1 if verify_gate() else 0)

    window = resolve(args.window)
    data_root = args.data_root.resolve()
    window_dir = data_root / window.name
    load_days = SMOKE_LOAD_DAYS if (args.smoke or args.verify_harness) else LOAD_DAYS
    fc_days = SMOKE_FORECAST_DAYS if args.smoke else FORECAST_DAYS
    read_days = tuple(d for d in READ_DAYS if d <= fc_days)
    run_ids = SMOKE_CONFIGS if args.smoke else tuple(c.id for c in CONFIGS)
    t_start = _time.perf_counter()

    check_window_files(window, window_dir)
    eph = _load_truth(window_dir, SAT, load_days)

    if args.emit_fixture:
        emit_fixture(eph, window.name)
        return

    if args.verify_harness:
        print("=" * 78)
        print(f"Part 3 harness check -- window {window.name} (NOT EVIDENCE)")
        print("=" * 78)
        sys.exit(1 if verify_harness(eph) else 0)

    print("=" * 78)
    print(
        f"Extended validation -- Part 3 TLE fitting: window {window.index:02d} "
        f"{window.name} ({window.band})"
    )
    print("=" * 78)
    if args.smoke:
        print("*** SMOKE RUN -- NOT EVIDENCE ***")
        print(
            f"    {fc_days:.0f}-day forecast, {load_days} days loaded, "
            f"configurations {', '.join(run_ids)} only. This output proves the "
            f"driver runs end to end; it is not a Part 3 result and must never "
            f"be committed as one."
        )
    print(
        f"[versions] propygator {pkg_version('propygator')}, "
        f"orekit_jpype {pkg_version('orekit_jpype')}, numpy {np.__version__}"
    )
    print(f"[data root] {display_path(data_root)}")
    print(
        f"[window] {window.name}, band {window.band}, t0 {window.t0}, "
        f"{WINDOW_DAYS} days landed, {load_days} loaded"
    )
    if window.note:
        print(f"  note: {window.note}")

    # --- space weather -------------------------------------------------------
    cssi_file = cssi_path()
    idx_sw = window_indices(window, read_cssi(cssi_file))
    print("[space weather]  window aggregates, re-read from CSSI at runtime")
    print(f"  source: {cssi_display_name()}  (UPDATED {cssi_updated(cssi_file)})")
    print(
        f"  F10.7 {idx_sw['f107']:.1f} (range {idx_sw['f107_lo']:.0f}-"
        f"{idx_sw['f107_hi']:.0f}), Ctr81 {idx_sw['ctr81']:.1f}, "
        f"Ap max {idx_sw['ap_max']:.0f}, ap3 max {idx_sw['ap3_max']:.0f}, "
        f"Kp max {idx_sw['kp_max']:.1f}"
    )
    check_cssi_observed(idx_sw, window.name)

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

    # --- mass ----------------------------------------------------------------
    mas_files = find_product_files(window_dir, "MAS1B", SAT, days=WINDOW_DAYS)
    mas = parse_mas1b(mas_files, sat_id=SAT)
    mass_kg = window_mass_kg(mas.gas_mean_kg)
    print("[mass]  MAS1B tank gas, both tanks (L1 Handbook sec 4.2.17)")
    print(
        f"  {SAT}: gas mean {mas.gas_mean_kg:.4f} kg over {mas.n_records} records "
        f"(range {mas.gas_min_kg:.4f}..{mas.gas_max_kg:.4f}) -> dry "
        f"{DRY_MASS_KG:.3f} + gas = {mass_kg:.3f} kg"
    )
    print(
        "  mass enters Part 3 only through the two state rows' reference "
        "propagations; every fit below is to TRUTH and carries no mass"
    )
    if mas.empty_files:
        bound = mas.mean_shift_bound_kg
        print(
            f"     {len(mas.empty_files)} day(s) declare num_records: 0 "
            f"({', '.join(mas.empty_files)}) -- telemetry outage; the mass is a "
            f"reading and is never interpolated across it"
        )
        print(
            f"     the missing days can move the mean by at most {bound:.4f} kg "
            f"({100.0 * bound / mass_kg:.4f}% of total mass)"
        )

    # --- tier-1 THR1B --------------------------------------------------------
    print("[screen tier-1 THR1B]  exact gate, no threshold, storm-proof")
    thr_files = find_product_files(window_dir, "THR1B", SAT, days=WINDOW_DAYS)
    screen = screen_thr1b(thr_files, sat_id=SAT)
    for line in format_screen(screen):
        print(line)
    if not screen.clean:
        raise SystemExit(
            f"{window.name}: THR1B reports a burn on {SAT}, which every arc and "
            f"forecast in this window would sit on top of."
        )

    # --- parser checks -------------------------------------------------------
    print("[parser checks]")
    exact = all(Epoch.from_iso(e.to_iso(), e.scale) == e for e in eph.epochs)
    dts = np.array(
        [eph.epochs[i + 1].seconds_since(eph.epochs[i]) for i in range(n - 1)]
    )
    max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
    print(f"  from_iso(to_iso()) == epoch for all {n}: {exact}")
    print(f"  grid uniformity: max |dt - {SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s")
    if not exact:
        raise SystemExit("epoch round trip not exact -- fix the parser first")
    if max_dt_error > GRID_CONTINUITY_TOL_S:
        raise SystemExit(
            f"truth grid has an interior hole -- max |dt - {SUBSAMPLE_S:.0f} s| = "
            f"{max_dt_error:.3e} s. Every residual here aligns by array index, so "
            f"every sample after the hole would be compared against truth one step "
            f"later (~456 km of along-track) with nothing raising."
        )

    # --- the arc geometry ----------------------------------------------------
    n_fc = int(fc_days * 86400.0 / SUBSAMPLE_S)
    if K_T + n_fc >= n:
        raise SystemExit(
            f"forecast needs truth through index {K_T + n_fc} but only {n} "
            f"samples loaded -- load {LOAD_DAYS} days"
        )
    t_arc_end = eph.epochs[K_T]
    t_utc = t_arc_end.in_scale(TimeScale.UTC)
    print("[arc geometry]  every scored arc ENDS at T; they differ only in reach")
    print(
        f"  T = truth index {K_T} = {t_arc_end.to_iso()} "
        f"{t_arc_end.scale.value} | UTC {t_utc.to_iso()}"
    )
    print(
        f"  T sits 18 s before the UTC day boundary -- GNV1B days start at GPS "
        f"midnight -- and index {K_T} is the truth sample NEAREST that boundary "
        f"(18 s before, vs 42 s after for {K_T + 1}); nothing is interpolated"
    )
    print(
        f"  forecast [T, T + {fc_days:.0f} d] on the {SUBSAMPLE_S:.0f} s grid, "
        f"read per-day at day(s) {', '.join(map(str, read_days))} -- day N is "
        f"[N-1 d, N d] PAST T alone, never accumulated"
    )
    truth_fc = eph.positions_m[K_T : K_T + n_fc + 1]

    if args.parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        print(f"  wall time: {_time.perf_counter() - t_start:.0f} s")
        return

    def _arc_record(ref) -> tuple[float, float]:
        """The two numbers the arc-end block checks: end-vs-T, and own span.

        Taken from the reference a fit ACTUALLY received, so the block cannot
        restate the constant the arc was built from.
        """
        return (
            ref.end_epoch.seconds_since(t_arc_end),
            ref.end_epoch.seconds_since(ref.start_epoch),
        )

    # --- the two staging fits ------------------------------------------------
    print("[staging]  fit2 (2 d, B* free) IS the scored naive_2d row; fit3 is not scored")
    t_fit = _time.perf_counter()
    arc2 = arc_trajectory(eph, STAGING_SPAN_2_D)
    fit2 = fit_tle_detailed(
        arc2,
        fitting_span=STAGING_SPAN_2_D * 86400.0,
        norad_id=NORAD_IDS[SAT],
        name=SAT_NAME,
        progress=False,
    )
    fit3 = fit_tle_detailed(
        arc_trajectory(eph, STAGING_SPAN_3_D),
        fitting_span=STAGING_SPAN_3_D * 86400.0,
        norad_id=NORAD_IDS[SAT],
        name=SAT_NAME,
        progress=False,
    )
    bstar2, bstar3 = parse_bstar(fit2.tle.line1), parse_bstar(fit3.tle.line1)
    sigma_b = bstar_sigma(fit2)
    r, s = compute_rs(fit2.sigma0, sigma_b, bstar2, bstar3)
    arm = select_arm(r, s)
    print(f"  fit2: {fit2.iterations} iters, in-arc RMS {fit2.rms_m:.1f} m")
    print(f"  fit3: {fit3.iterations} iters, in-arc RMS {fit3.rms_m:.1f} m "
          f"({_time.perf_counter() - t_fit:.0f} s wall)")

    print("[gate]  the playbook's r/s trust gate, thresholds FROZEN and never re-fitted")
    print(f"  sigma0(fit2)      = {fit2.sigma0:.6g}")
    print(
        "  sigma(BSTAR) raw  = "
        + ("n/a (covariance absent)" if sigma_b is None else f"{sigma_b:.6e}")
    )
    print(f"  B*(fit2)          = {bstar2:.6e}")
    print(f"  B*(fit3)          = {bstar3:.6e}")
    print(
        f"  r = sigma0*sigma(B*)/|B*| = {r:.6g}  (bar r < {R_THRESHOLD}) -> "
        f"{'PASS' if r < R_THRESHOLD else 'FAIL'}"
    )
    print(
        f"  s = |B*3 - B*2|/|B*2|     = {s:.6g}  (bar s < {S_THRESHOLD}) -> "
        f"{'PASS' if s < S_THRESHOLD else 'FAIL'}"
    )
    print(f"  mapping selects: {arm}")
    print(
        "  all three arms run regardless -- the mapping is applied by "
        "summarize_tle.py, so a re-score needs no re-fit"
    )

    # --- the scored rows -----------------------------------------------------
    print(f"[runs]  {len(run_ids)} scored configurations")
    results: dict[str, dict] = {}
    state_drift: dict[str, tuple[float, float]] = {}
    fitted_arcs: dict[str, tuple[float, float]] = {}

    for cfg_id in run_ids:
        cfg = CONFIGS_BY_ID[cfg_id]
        t_row = _time.perf_counter()
        if cfg_id == "naive_2d":
            tle, in_arc, iters = fit2.tle, fit2.rms_m, fit2.iterations
            fitted_arcs[cfg_id] = _arc_record(arc2)
        elif cfg.kind == "catalog":
            entry = entry_for(window.name)
            tle, in_arc, iters = entry.tle, float("nan"), 0
        elif cfg.kind == "state":
            ref, ref_pos = state_reference(eph, cfg.geometry, mass_kg, cfg.arc_days)
            fitted_arcs[cfg_id] = _arc_record(ref)
            k0 = K_T - int(round(cfg.arc_days * 86400.0 / SUBSAMPLE_S))
            m = min(len(ref_pos), K_T + 1 - k0)
            drift = np.linalg.norm(ref_pos[:m] - eph.positions_m[k0 : k0 + m], axis=1)
            state_drift[cfg_id] = (
                float(np.sqrt(np.mean(drift**2))),
                float(drift[-1]),
            )
            fit = fit_tle_detailed(
                ref,
                fitting_span=cfg.arc_days * 86400.0,
                norad_id=NORAD_IDS[SAT],
                name=SAT_NAME,
                progress=False,
            )
            tle, in_arc, iters = fit.tle, fit.rms_m, fit.iterations
        elif cfg.tau_days is not None:
            arc = arc_trajectory(eph, cfg.arc_days)
            fitted_arcs[cfg_id] = _arc_record(arc)
            wf = run_weighted_fit(
                arc, cfg.tau_days, cfg_id, max_iterations=FADE_MAX_ITERATIONS
            )
            tle, in_arc, iters = wf.tle, wf.rms_m, wf.iterations
            results.setdefault(cfg_id, {})["weighted"] = wf
        else:
            # The arc comes from cfg.arc_days, never a hardcoded span: a literal
            # here would fit one arc while reporting another, and _clip_leading
            # keeps every sample of a too-short reference without raising.
            arc = arc_trajectory(eph, cfg.arc_days)
            fitted_arcs[cfg_id] = _arc_record(arc)
            guess = fit2.tle if cfg.bstar == "held_fit2" else None
            fit = fit_tle_detailed(
                arc,
                fitting_span=cfg.arc_days * 86400.0,
                initial_guess=guess,
                fit_bstar=(cfg.bstar == "free"),
                norad_id=NORAD_IDS[SAT],
                name=SAT_NAME,
                progress=False,
            )
            tle, in_arc, iters = fit.tle, fit.rms_m, fit.iterations

        traj = propagate_tle(tle, fc_days * 86400.0, output_step=SUBSAMPLE_S, start=t_arc_end)
        pos = traj.to_frame(Frame.ITRF).positions
        m = min(len(pos), len(truth_fc))
        diff = pos[:m] - truth_fc[:m]
        row = results.setdefault(cfg_id, {})
        row.update(
            tle=tle,
            in_arc_rms_m=in_arc,
            iterations=iters,
            bstar=parse_bstar(tle.line1),
            per_day={d: forecast_ric_rms(diff, eph, d) for d in read_days},
        )
        print(f"    {cfg.label:<32} {_time.perf_counter() - t_row:6.0f} s wall")

    # --- arc-end alignment, the structural check of the whole part ------------
    # MEASURED ON THE REFERENCE EACH FIT ACTUALLY RECEIVED, not on a rebuild of
    # the constant it came from -- a rebuild can only restate its own factory.
    # TWO CONDITIONS, because ending at T is not sufficient on its own:
    # fit_tle_detailed clips a reference to its LEADING fitting_span, so a row
    # can end at T and still have fitted a shorter arc than it reports (a
    # too-short reference keeps every sample and never raises).
    print("[arc-end alignment]  every scored arc ends at T and spans what it reports")
    worst_end = worst_span = 0.0
    for cfg_id in run_ids:
        cfg = CONFIGS_BY_ID[cfg_id]
        if cfg_id not in fitted_arcs:
            print(f"  {cfg_id:<16} no arc (the row fits nothing)")
            continue
        d_end, span_s = fitted_arcs[cfg_id]
        d_span = span_s - cfg.arc_days * 86400.0
        worst_end = max(worst_end, abs(d_end))
        worst_span = max(worst_span, abs(d_span))
        print(
            f"  {cfg_id:<16} [T - {cfg.arc_days:g} d, T]: end delta "
            f"{d_end:+.1e} s, fitted span {span_s:.1f} s (delta {d_span:+.1e} s)"
        )
    print(
        f"  worst |end delta| = {worst_end:.1e} s, "
        f"worst |span delta| = {worst_span:.1e} s (tol {ARC_ALIGN_TOL_S:.0e} s)"
    )
    if worst_end > ARC_ALIGN_TOL_S:
        raise SystemExit(
            "arc-end alignment FAILED -- the arcs do not share an end, so every "
            "row below forecasts from a different epoch and the part would "
            "measure arc-end epoch rather than method"
        )
    if worst_span > ARC_ALIGN_TOL_S:
        raise SystemExit(
            "arc-span mismatch FAILED -- a row fitted an arc of a different "
            "length than the fitting_span it reports, so its label and its "
            "result describe different configurations"
        )

    # --- the catalogue row's provenance and cross-tag ------------------------
    res = None
    if "catalog" in run_ids:
        entry = entry_for(window.name)
        print("[catalog]  Space-Track gp_history, latest epoch at or before T")
        # D is read for exactly one day -- the cross-tag discriminator.
        #
        # THE D-SIDE CHECKS BELOW ARE NOT SYMMETRY WITH C'S: they are load
        # bearing. cross_tag_check diffs by array index and scores
        # rms_d / rms_c, so ANY D misalignment inflates rms_d, inflates the
        # ratio, and makes the check PASS more easily -- it fails OPEN, on the
        # one discriminator standing between the catalog row and a set that
        # actually describes D. C's own hole check (above) quotes the cost: one
        # 60 s step is ~456 km of along-track. D is otherwise never QC'd here,
        # and its QC drops are independent of C's, so C being clean says
        # nothing about D.
        n_day1 = int(86400.0 / SUBSAMPLE_S) + 1
        eph_d = _load_truth(window_dir, "D", 2, first_day=int(K_T // SAMPLES_PER_DAY))
        if len(eph_d.positions_m) < n_day1:
            raise SystemExit(
                f"D truth is {len(eph_d.positions_m)} samples, short of the "
                f"{n_day1} the cross-tag reads -- cross_tag_check takes the "
                f"min() of the two lengths, so this would silently score the "
                f"tag test over less than the day it claims"
            )
        d_offset = eph_d.epochs[0].seconds_since(t_arc_end)
        if abs(d_offset) > GRID_CONTINUITY_TOL_S:
            raise SystemExit(
                f"D truth starts {d_offset:+.3f} s from T -- the twins' daily "
                f"files are not index-aligned in this window, so the cross-tag "
                f"would compare D against C's grid shifted by "
                f"{d_offset / SUBSAMPLE_S:+.2f} steps and PASS on the offset"
            )
        d_dts = np.array(
            [
                eph_d.epochs[i + 1].seconds_since(eph_d.epochs[i])
                for i in range(n_day1 - 1)
            ]
        )
        d_max_dt_error = float(np.max(np.abs(d_dts - SUBSAMPLE_S)))
        if d_max_dt_error > GRID_CONTINUITY_TOL_S:
            raise SystemExit(
                f"D truth has an interior hole over the cross-tag day -- max "
                f"|dt - {SUBSAMPLE_S:.0f} s| = {d_max_dt_error:.3e} s. Every "
                f"sample past it would be compared one step late, inflating "
                f"the D residual and passing the tag test on the gap."
            )
        print(
            f"  D truth checks: start delta {d_offset:+.1e} s, max "
            f"|dt - {SUBSAMPLE_S:.0f} s| = {d_max_dt_error:.3e} s over "
            f"{n_day1} samples"
        )
        res = cross_tag_check(
            entry, t_arc_end, truth_fc[:n_day1], eph_d.positions_m[:n_day1]
        )
        for line in format_cross_tag(entry, t_arc_end, res):
            print(line)
        if not res.passed:
            raise SystemExit(
                f"{window.name}: catalogue cross-tag FAILED (ratio {res.ratio:.2f}x "
                f"against a {CROSS_TAG_MIN_RATIO:.0f}x bar) -- the pulled set does "
                f"not track C. Do not read the catalog row."
            )
        if staleness_days(entry, t_arc_end) > 0.25:
            print(
                "  NOTE: staleness here is the outlier of the pull -- a weak "
                "catalog row in this window is a staleness result before it is a "
                "method result"
            )

    # --- the state rows' reference drift -------------------------------------
    if state_drift:
        print("[state]  numerical reference vs truth over the fitted arc")
        print(
            "  the a-priori tables cannot meet sec 1.2's single-digit-% "
            "calibration bar, so degradation roughly this size is EXPECTED -- "
            "recorded as an expectation, never a bar"
        )
        for cfg_id, (rms_m, end_m) in state_drift.items():
            print(
                f"  {CONFIGS_BY_ID[cfg_id].label:<28} drift RMS {rms_m:9.1f} m, "
                f"end {end_m:9.1f} m"
            )

    # --- the fade harness's own diagnostics ----------------------------------
    # The build plan's "the weighted fits' own diagnostics are printed but never
    # feed the gate". Printed here so Chunk 18's [bench-3] can SHOW the weighted
    # fits' conditioning rather than assert it.
    faded = [c for c in run_ids if "weighted" in results[c]]
    if faded:
        print(
            f"[fade]  the age-weighted fits' own conditioning -- these rows "
            f"alone run at max_iterations {FADE_MAX_ITERATIONS}, not the "
            f"shipped 100 (it caps evaluations too; this window's own demand is "
            f"the evals column below)"
        )
        print(
            "  WEIGHTED QUANTITIES -- never compared against r < "
            f"{R_THRESHOLD} / s < {S_THRESHOLD}: age weighting turns sigma0 and "
            "the covariance into weighted quantities and the playbook's "
            "thresholds do not carry over (the conservative default)"
        )
        print(f"  {'id':<16}{'iters':>7}{'evals':>7}{'sigma0':>14}{'sigma(B*)':>14}")
        for cfg_id in faded:
            wf = results[cfg_id]["weighted"]
            sig_b = "n/a" if wf.sigma_bstar is None else f"{wf.sigma_bstar:.6e}"
            print(
                f"  {cfg_id:<16}{wf.iterations:>7}{wf.evaluations:>7}"
                f"{wf.sigma0:>14.6g}{sig_b:>14}"
            )

    # --- the rows ------------------------------------------------------------
    print(
        "[rows]  forecast RMS vs truth, per-day 3D (m). Day N = [N-1 d, N d] "
        "PAST T alone."
    )
    print(
        f"  {'id':<16}{'in-arc':>10}{'B*':>12}"
        + "".join(f"{f'day {d}':>12}" for d in read_days)
    )
    for cfg_id in run_ids:
        row = results[cfg_id]
        in_arc = row["in_arc_rms_m"]
        in_arc_txt = "-" if np.isnan(in_arc) else f"{in_arc:.1f}"
        cells = "".join(f"{row['per_day'][d][3]:>12.1f}" for d in read_days)
        print(f"  {cfg_id:<16}{in_arc_txt:>10}{row['bstar']:>12.3e}{cells}")

    flagged = [
        cfg_id
        for cfg_id in run_ids
        if not np.isnan(results[cfg_id]["in_arc_rms_m"])
        and results[cfg_id]["in_arc_rms_m"] > IN_ARC_RMS_FLAG_M
    ]
    print(
        f"  in-arc RMS class: the SGP4 representation floor is ~500-700 m on a "
        f"GNV1B arc; rows past {IN_ARC_RMS_FLAG_M:.0f} m: "
        + (", ".join(flagged) if flagged else "none")
    )

    # --- the RIC breakdown ---------------------------------------------------
    print("[breakdown]  radial / along / cross / 3D RMS (m), per configuration per day")
    print(
        f"  {'id':<16}{'day':>5}{'radial':>12}{'along':>14}{'cross':>12}{'3D':>14}"
    )
    for cfg_id in run_ids:
        for j, d in enumerate(read_days):
            rr = results[cfg_id]["per_day"][d]
            name = cfg_id if j == 0 else ""
            print(
                f"  {name:<16}{d:>5}{rr[0]:>12.2f}{rr[1]:>14.2f}"
                f"{rr[2]:>12.2f}{rr[3]:>14.2f}"
            )

    # --- machine-readable rows ----------------------------------------------
    if not args.smoke:
        print("[machine]  fixed-token rows for summarize_tle.py -- do not reformat")
        print(
            f"  TGATE {window.name} {window.band} {r:.6e} {s:.6e} "
            f"{fit2.sigma0:.6e} {-1.0 if sigma_b is None else sigma_b:.6e} "
            f"{bstar2:.6e} {bstar3:.6e} {arm}"
        )
        for cfg_id in run_ids:
            row = results[cfg_id]
            in_arc = row["in_arc_rms_m"]
            for d in read_days:
                rr = row["per_day"][d]
                print(
                    f"  TROW {window.name} {window.band} {cfg_id} {d} "
                    f"{rr[0]:.4f} {rr[1]:.4f} {rr[2]:.4f} {rr[3]:.4f} "
                    f"{-1.0 if np.isnan(in_arc) else in_arc:.4f} {row['bstar']:.6e}"
                )
        if res is not None:
            entry = entry_for(window.name)
            print(
                f"  TCAT {window.name} {staleness_days(entry, t_arc_end):.6f} "
                f"{res.rms_c_m:.4f} {res.rms_d_m:.4f} {res.ratio:.4f} {res.verdict}"
            )
        for cfg_id, (rms_m, end_m) in state_drift.items():
            print(f"  TSTATE {window.name} {cfg_id} {rms_m:.4f} {end_m:.4f}")
        for cfg_id in faded:
            wf = results[cfg_id]["weighted"]
            print(
                f"  TFADE {window.name} {cfg_id} {wf.iterations} {wf.evaluations} "
                f"{wf.sigma0:.6e} "
                f"{-1.0 if wf.sigma_bstar is None else wf.sigma_bstar:.6e}"
            )
    print(f"  wall time: {_time.perf_counter() - t_start:.0f} s")


if __name__ == "__main__":
    main()
