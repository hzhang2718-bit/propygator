"""GRACE-FO: propygator's TLE fitter vs. the operational catalog -- Chunk 3.

Evidence for ``docs/history/build-plan-real-world-validation.md`` Chunk 3, the question
that motivated the study: *is a propygator-fitted TLE as good as an operational
catalog TLE at predicting a real orbit?* Per window (quiet_2019 / active_2023),
one driver with four modes, each writing its own committed results file. The
full method, election history, and result readings live in README.md ("Fitter
vs. catalog" and its subsections); the build-plan Chunk 3 as-run notes record
what was elected when.

- **primary** (no flag): fit one day of GNV1B truth via the 1.2 Trajectory
  path, then fitted TLE vs the same-epoch Space-Track catalog TLE over the fit
  day + 3 forward days, plus element-level sanity. Parity, not victory, is the
  claim. ``--fit-bstar=off`` re-runs it with B* held at the seed's 0.0 (the
  weak-drag regime diagnostic).
- **--sweep**: the fitting-span sweep -- 1/2/3-day fit arcs end-anchored at the
  day-4 start, forecast over the common days 4-6 window; B* fitted vs held at
  the catalog's long-arc value. Loads 6 truth days.
- **--state-path**: the 1.2 State-reference-path composition check (the fitter
  propagates its own internal reference) against the live-recomputed
  trajectory-path twin, at the nominal / Run-3-fitted Cd, plus the
  a-priori-table rows (sphere table through the native State path AND the
  external propagate-then-fit route -- the measured equivalence -- and the box
  table via the external route, whose IPT-ecef attitude the State path cannot
  express). Loads 6 truth days.

The catalog TLEs are pasted below from the Space-Track **gp_history** class
(the maintainer's pull, per the build plan's data-access rule -- ``fetch_tle``
is CelesTrak-current-epoch only); the nearest-epoch entry from a +/-1-day query
around the fit-day start was selected. Full provenance in README.md.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data); cwd-independent:

    cd experiments/real-world-validation/gracefo
    conda run -n propygator python run_fit_vs_catalog.py quiet_2019  >  results_fit_vs_catalog.txt
    conda run -n propygator python run_fit_vs_catalog.py active_2023 >> results_fit_vs_catalog.txt
    conda run -n propygator python run_fit_vs_catalog.py quiet_2019 --fit-bstar=off  >> results_fit_vs_catalog.txt
    conda run -n propygator python run_fit_vs_catalog.py active_2023 --fit-bstar=off >> results_fit_vs_catalog.txt
    conda run -n propygator python run_fit_vs_catalog.py quiet_2019 --sweep  >  results_fit_span_sweep.txt
    conda run -n propygator python run_fit_vs_catalog.py active_2023 --sweep >> results_fit_span_sweep.txt
    conda run -n propygator python run_fit_vs_catalog.py quiet_2019 --state-path  >  results_fit_state_path.txt
    conda run -n propygator python run_fit_vs_catalog.py active_2023 --state-path >> results_fit_state_path.txt

(or ``python ../run_all.py --only fit`` to regenerate all three files).
Stdout is ASCII-only (captured under cp1252); the fit's ``iter N | rms``
progress goes to stderr. ``--parse-only`` stops before the JVM-touching steps
(truth parse + catalog-TLE validation only).
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_HERE.parent))
# Shared study analysis kit (the Chunk 0 RIC helper + rms; build plan "Reuse")
# and the GRACE-FO leg configuration -- the same constants/factories the Chunk
# 2/2b reference-vs-reality rates were measured with, plus the RUN3_FITTED_CD
# measured anchors (imported, not duplicated, so the Chunk 2/2b drift rates and
# table findings apply verbatim).
from common import ric_components, rms as _rms  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402
from gracefo_common import (  # noqa: E402
    A_RAM_M2,
    DATA_ROOT,
    GRACEFO_CD_NOMINAL,
    GRACEFO_SAT_ID,
    NORAD_ID,
    RUN3_FITTED_CD,
    SAT_NAME,
    SUBSAMPLE_S,
    box_spacecraft,
    force_config,
    sphere_spacecraft,
)

from propygator import (  # noqa: E402
    TLE,
    BoxFaceCd,
    Frame,
    InPlaneTracking,
    IntegratorConfig,
    State,
    Trajectory,
    VariableCd,
    fit_tle_detailed,
    propagate_numerical,
    propagate_tle,
)

FIT_SPAN_S = 86400.0  # the 1-day fit arc (build plan Chunk 3)
FORWARD_DAYS = 3  # prediction days past the fit span
LOAD_DAYS = 4  # fit day + FORWARD_DAYS of truth

# --sweep mode (the 2026-07-14 fitting-span extension)
SWEEP_SPANS_D = (1, 2, 3)  # end-anchored fit-arc lengths
SWEEP_LOAD_DAYS = 6  # max span (3 d) + the common 3-day forecast window

# --state-path mode (the 2026-07-14 State-path extension + the 2026-07-15
# a-priori-table rows)
STATE_FIT_SPAN_S = 2 * 86400.0  # the shipped features.md 1.2 default

# Historical catalog TLEs for NORAD 43476, Space-Track gp_history class,
# retrieved by the maintainer 2026-07-14 (build plan: fetch_tle cannot reach
# historical epochs). Selection rule: the epoch nearest each window's fit-day
# start from a +/-1-day EPOCH-range query; both winners happen to precede the
# fit day (quiet: epoch 19317.74687279, ~6.1 h before t0; active: epoch
# 23353.82590425, ~4.2 h before t0), so neither has "seen" fit-day data.
# The full query outputs are recorded in README.md.
CATALOG_TLES: dict[str, tuple[str, str]] = {
    "quiet_2019": (
        "1 43476U 18047A   19317.74687279 +.00000271 +00000-0 +98502-5 0  9994",
        "2 43476 088.9970 166.9377 0018420 022.3999 337.8049 15.23932987082211",
    ),
    "active_2023": (
        "1 43476U 18047A   23353.82590425  .00004407  00000-0  16167-3 0  9994",
        "2 43476  88.9824 323.8854 0015957  51.6909 308.5772 15.27615336310325",
    ),
}


def _parse_bstar(line1: str) -> float:
    """B* from line-1 columns 54-61 (sign + 5-digit mantissa + signed exponent)."""
    field = line1[53:61]
    sign = -1.0 if field[0] == "-" else 1.0
    mantissa = int(field[1:6]) / 1.0e5
    return sign * mantissa * 10.0 ** int(field[6:8])


def _elements(tle: TLE) -> dict[str, float]:
    """The line-2 mean elements + B*, by the fixed TLE columns (pure Python)."""
    l2 = tle.line2
    return {
        "inclination_deg": float(l2[8:16]),
        "raan_deg": float(l2[17:25]),
        "eccentricity": float("0." + l2[26:33].strip()),
        "arg_perigee_deg": float(l2[34:42]),
        "mean_anomaly_deg": float(l2[43:51]),
        "mean_motion_revday": float(l2[52:63]),
        "bstar": _parse_bstar(tle.line1),
    }


def _tle_diff_itrf(tle: TLE, eph, span_s: float) -> np.ndarray:
    """Propagate ``tle`` on the truth grid; return propagated - truth ITRF diff."""
    traj = propagate_tle(
        tle, span_s, output_step=SUBSAMPLE_S, start=eph.epochs[0]
    )
    pos = traj.to_frame(Frame.ITRF).positions
    n = min(len(pos), len(eph.positions_m))
    return pos[:n] - eph.positions_m[:n]


def _run_sweep(eph, catalog: TLE) -> None:
    """The fitting-span sweep (maintainer-elected 2026-07-14 extension).

    End-anchored design: every fit arc ends at the day-4 start and the forecast
    window is the common days 4-6 -- the operational question ("given truth up
    to T, how much history should the fit consume to predict T..T+3d?") with
    the forecast window and its density realization held fixed across spans.
    The 1.2 epoch-at-reference-start rule places a longer span's TLE epoch
    farther from the window; that is a real consequence of the design under
    evaluation, deliberately included. Two configs per span: B* fitted, and B*
    held at the catalog's long-arc value (initial_guess=catalog +
    fit_bstar=False). The catalog row is context, **not** a parity benchmark
    here -- its epoch predates the forecast window by ~3.2 days (parity was
    the primary experiment's claim, on a same-epoch footing).
    """
    n = len(eph.epochs)
    n_per_day = int(86400.0 / SUBSAMPLE_S)
    k_end = (SWEEP_LOAD_DAYS - FORWARD_DAYS) * n_per_day  # the day-4 start
    t_end = eph.epochs[k_end]
    span_fc = eph.epochs[-1].seconds_since(t_end)
    truth_fc = eph.positions_m[k_end:]
    n_fc_days = (n - k_end) // n_per_day

    def forecast_rms(tle: TLE) -> list[float]:
        traj = propagate_tle(tle, span_fc, output_step=SUBSAMPLE_S, start=t_end)
        pos = traj.to_frame(Frame.ITRF).positions
        d = np.linalg.norm(pos[: len(truth_fc)] - truth_fc, axis=1)
        return [
            _rms(d[j * n_per_day : (j + 1) * n_per_day]) for j in range(n_fc_days)
        ]

    print("[sweep]  end-anchored fit arcs; common forecast window = days 4-6")
    print(
        f"  all fit arcs end at {t_end.to_iso()} {t_end.scale.value} "
        f"(the day-4 start); forecast = the next {n_fc_days} days"
    )
    print(
        "  'B* held cat' = initial_guess=catalog + fit_bstar=False (elements "
        "fitted, B* pinned to the catalog's long-arc value)"
    )
    print(
        f"  {'config':<13}{'span':>6}{'in-arc rms':>12}{'+1 d 3D':>10}"
        f"{'+2 d 3D':>10}{'+3 d 3D':>10}{'B*':>12}{'n (rev/d)':>14}"
    )
    for hold_cat in (False, True):
        for span_d in SWEEP_SPANS_D:
            k0 = k_end - span_d * n_per_day
            ref = Trajectory.from_arrays(
                list(eph.epochs[k0 : k_end + 1]),
                eph.positions_m[k0 : k_end + 1],
                eph.velocities_ms[k0 : k_end + 1],
                Frame.ITRF,
            )
            fit = fit_tle_detailed(
                ref,
                fitting_span=span_d * 86400.0,
                initial_guess=catalog if hold_cat else None,
                fit_bstar=not hold_cat,
                norad_id=NORAD_ID,
                name=SAT_NAME,
            )
            el = _elements(fit.tle)
            per_day = forecast_rms(fit.tle)
            label = "B* held cat" if hold_cat else "B* fitted"
            print(
                f"  {label:<13}{span_d:>4} d{fit.rms_m:>12.1f}"
                f"{per_day[0]:>10.1f}{per_day[1]:>10.1f}{per_day[2]:>10.1f}"
                f"{el['bstar']:>12.3e}{el['mean_motion_revday']:>14.8f}"
            )
    stale_d = t_end.seconds_since(catalog.epoch) / 86400.0
    per_day = forecast_rms(catalog)
    el = _elements(catalog)
    print(
        f"  {'catalog (*)':<13}{'-':>6}{'-':>12}"
        f"{per_day[0]:>10.1f}{per_day[1]:>10.1f}{per_day[2]:>10.1f}"
        f"{el['bstar']:>12.3e}{el['mean_motion_revday']:>14.8f}"
    )
    print(
        f"  (*) context, not a parity benchmark: the catalog epoch sits "
        f"{stale_d:.2f} d before this forecast window (in-arc rms = RMS over the "
        f"fit measurements at convergence, meters)"
    )


def _run_state_path(eph, window: str) -> None:
    """The State-path check (maintainer-elected 2026-07-14 extension).

    The 1.2 State reference path fit against reality for the first time: the
    fitter's reference is its own internal propagate_numerical run, so the
    TLE-vs-reality error composes (SGP4 lossiness) + (reference-vs-reality
    drift). Twin design vs the sweep's 2-day trajectory-path row: the same fit
    window (days 2-3, ending at the day-4 start), the same common days 4-6
    forecast, B* fitted throughout -- only the reference source differs. The
    trajectory-path twin is recomputed live so the block is self-contained.
    Each State config also propagates its own reference on the truth grid and
    prints the drift vs truth over the fit window -- the composition evidence
    (the fitter's internal grid is ~300 samples of the same dynamics).

    The a-priori-table rows (2026-07-15 extension) add the no-truth user's
    calibration source -- Chunk 2b's Run 4/5 configs through the fitter. The
    sphere table runs through both the native State path and the external
    propagate-then-fit-Trajectory route (their delta = the construction-time
    equivalence, measured); the box table, whose IPT-ecef attitude the 1.2
    State path cannot express, rides that verified equivalence via the
    external route only. External references live on the 60 s truth grid and
    double as their own drift twins.
    """
    n_per_day = int(86400.0 / SUBSAMPLE_S)
    k0 = n_per_day  # day-2 start: the state epoch
    k_end = k0 + int(STATE_FIT_SPAN_S / 86400.0) * n_per_day  # day-4 start
    t0 = eph.epochs[k0]
    t_end = eph.epochs[k_end]
    span_fc = eph.epochs[-1].seconds_since(t_end)
    truth_fit = eph.positions_m[k0 : k_end + 1]
    truth_fc = eph.positions_m[k_end:]
    n_fc_days = len(truth_fc) // n_per_day

    def tle_vs_truth(tle: TLE) -> tuple[float, list[float]]:
        """Fit-window RMS + per-forecast-day RMS of |TLE - truth| (ITRF, m)."""
        traj = propagate_tle(
            tle, STATE_FIT_SPAN_S, output_step=SUBSAMPLE_S, start=t0
        )
        pos = traj.to_frame(Frame.ITRF).positions
        d_fit = np.linalg.norm(pos[: len(truth_fit)] - truth_fit, axis=1)
        traj = propagate_tle(tle, span_fc, output_step=SUBSAMPLE_S, start=t_end)
        pos = traj.to_frame(Frame.ITRF).positions
        d_fc = np.linalg.norm(pos[: len(truth_fc)] - truth_fc, axis=1)
        return _rms(d_fit), [
            _rms(d_fc[j * n_per_day : (j + 1) * n_per_day])
            for j in range(n_fc_days)
        ]

    print("[state path]  1.2 State reference path vs reality (composition check)")
    print(
        f"  state = the day-2-start truth sample, {t0.to_iso()} "
        f"{t0.scale.value} (ITRF -> EME2000); fitting_span = 2 d (the shipped "
        f"default; fit window ends at the day-4 start)"
    )
    print(
        f"  forecast = the common days 4-6 window (the sweep's); B* fitted "
        f"throughout; force set = run_gracefo Run 2/3 (table rows: the Chunk 2b "
        f"Run 4/5 spacecraft)"
    )

    rows = []

    # Twin baseline: the trajectory path on the same window (truth reference).
    ref = Trajectory.from_arrays(
        list(eph.epochs[k0 : k_end + 1]),
        eph.positions_m[k0 : k_end + 1],
        eph.velocities_ms[k0 : k_end + 1],
        Frame.ITRF,
    )
    fit = fit_tle_detailed(
        ref, fitting_span=STATE_FIT_SPAN_S, norad_id=NORAD_ID, name=SAT_NAME
    )
    fit_win, per_day = tle_vs_truth(fit.tle)
    rows.append(("Trajectory path (truth ref)", fit.rms_m, fit_win, per_day, fit.tle))

    # State path: the fitter propagates its own reference internally; we run
    # the identical propagation on the truth grid first, for the drift number.
    state0 = State(
        eph.epochs[k0], eph.positions_m[k0], eph.velocities_ms[k0], Frame.ITRF
    ).to_frame(Frame.EME2000)
    def _external_reference(spacecraft, attitude):
        """The documented State-path equivalent: propagate the reference on
        the 60 s truth grid (EME2000 in), so the same trajectory feeds the
        Trajectory-path fit AND supplies the drift twin directly."""
        traj = propagate_numerical(
            state0,
            STATE_FIT_SPAN_S,
            output_step=SUBSAMPLE_S,
            force_models=force_config(drag=True),
            spacecraft=spacecraft,
            attitude=attitude,
            integrator=IntegratorConfig.high_precision(),
            progress=False,
        )
        pos_ref = traj.to_frame(Frame.ITRF).positions
        d_ref = np.linalg.norm(pos_ref[: len(truth_fit)] - truth_fit, axis=1)
        return traj, _rms(d_ref), float(d_ref[-1])

    for cd, tag in (
        (GRACEFO_CD_NOMINAL, "nominal"),
        (RUN3_FITTED_CD[window], "Run-3 fit"),
    ):
        _, drift_rms, drift_end = _external_reference(sphere_spacecraft(cd), None)
        print(
            f"  reference drift vs truth over the fit window (Cd {cd:.3f}): "
            f"RMS {drift_rms:.1f} m, end {drift_end:.1f} m"
        )
        fit = fit_tle_detailed(
            state0,
            fitting_span=STATE_FIT_SPAN_S,
            force_models=force_config(drag=True),
            spacecraft=sphere_spacecraft(cd),
            norad_id=NORAD_ID,
            name=SAT_NAME,
        )
        fit_win, per_day = tle_vs_truth(fit.tle)
        rows.append(
            (f"State path, Cd {cd:.3f} ({tag})", fit.rms_m, fit_win, per_day, fit.tle)
        )

    # --- a-priori-table rows (2026-07-15 extension): the calibration source a
    # truth-less pre-flight user actually has, Chunk 2b's Run 4/5 configs
    # through the fitter. Sphere first through the NATIVE State path (legal:
    # a sphere is attitude-independent, so the pinned-LofAligned internal
    # reference is the same dynamics), then through the external route -- the
    # pair's delta measures the "State path == propagate-then-fit" equivalence
    # on real data. The box row needs IPT-ecef, which the 1.2 State path
    # cannot express, so it rides the just-verified equivalence.
    sphere_cfg = sphere_spacecraft(VariableCd.sphere_default(), area_m2=A_RAM_M2)

    fit = fit_tle_detailed(
        state0,
        fitting_span=STATE_FIT_SPAN_S,
        force_models=force_config(drag=True),
        spacecraft=sphere_cfg,
        norad_id=NORAD_ID,
        name=SAT_NAME,
    )
    fit_win, per_day = tle_vs_truth(fit.tle)
    rows.append(("State path, sphere table", fit.rms_m, fit_win, per_day, fit.tle))

    traj_ref, drift_rms, drift_end = _external_reference(sphere_cfg, None)
    print(
        f"  reference drift vs truth over the fit window (sphere table): "
        f"RMS {drift_rms:.1f} m, end {drift_end:.1f} m (rows 4+5 -- same dynamics)"
    )
    fit = fit_tle_detailed(
        traj_ref, fitting_span=STATE_FIT_SPAN_S, norad_id=NORAD_ID, name=SAT_NAME
    )
    fit_win, per_day = tle_vs_truth(fit.tle)
    rows.append(("External ref, sphere table", fit.rms_m, fit_win, per_day, fit.tle))

    traj_ref, drift_rms, drift_end = _external_reference(
        box_spacecraft(BoxFaceCd.default()),
        InPlaneTracking(velocity_reference="ecef"),
    )
    print(
        f"  reference drift vs truth over the fit window (box table, IPT-ecef): "
        f"RMS {drift_rms:.1f} m, end {drift_end:.1f} m"
    )
    fit = fit_tle_detailed(
        traj_ref, fitting_span=STATE_FIT_SPAN_S, norad_id=NORAD_ID, name=SAT_NAME
    )
    fit_win, per_day = tle_vs_truth(fit.tle)
    rows.append(
        ("External ref, box table (IPT)", fit.rms_m, fit_win, per_day, fit.tle)
    )

    print(
        f"  {'config':<34}{'in-arc rms':>11}{'fit-win 3D':>11}"
        f"{'+1 d 3D':>10}{'+2 d 3D':>10}{'+3 d 3D':>10}{'B*':>12}"
    )
    for label, rms_m, fit_win, per_day, tle in rows:
        bstar = _parse_bstar(tle.line1)
        print(
            f"  {label:<34}{rms_m:>11.1f}{fit_win:>11.1f}"
            f"{per_day[0]:>10.1f}{per_day[1]:>10.1f}{per_day[2]:>10.1f}"
            f"{bstar:>12.3e}"
        )
    _, n_rms, n_win, n_days, n_tle = rows[3]
    _, e_rms, e_win, e_days, e_tle = rows[4]
    print(
        "  [equivalence]  native State path vs external route, sphere table "
        "(rows 4 vs 5) -- absolute deltas:"
    )
    print(
        f"    in-arc rms {abs(n_rms - e_rms):.1f} m | fit-win 3D "
        f"{abs(n_win - e_win):.1f} m | +1/+2/+3 d 3D "
        f"{abs(n_days[0] - e_days[0]):.1f} / {abs(n_days[1] - e_days[1]):.1f} / "
        f"{abs(n_days[2] - e_days[2]):.1f} m | B* "
        f"{abs(_parse_bstar(n_tle.line1) - _parse_bstar(e_tle.line1)):.2e}"
    )
    print(
        "    (same dynamics through both delivery paths -- differences are "
        "measurement placement only, expected << the ~600 m SGP4 floor; the "
        "construction-time equivalence measured on real data, licensing the "
        "box row, whose attitude the State path cannot express)"
    )
    print(
        "  (in-arc rms = vs the fit's OWN reference -- truth for row 1, the "
        "internal numerical propagation for the State rows, the external 60 s "
        "reference for the 'External ref' rows; fit-win 3D = the TLE vs truth "
        "over the 2-day fit window; forecast days vs truth)"
    )
    print(
        "  reading: State-path cost vs the trajectory twin = the reference "
        "drift expressed through the fit -- expected ~nil where drift << the "
        "~600 m SGP4 noise, material where the reference Cd is uncalibrated. "
        "The table rows are the no-truth pre-flight case: the shipped a-priori "
        "tables as the calibration source, the box flown at Chunk 2b's Run-5 "
        "wind-aligned attitude via the external route."
    )


def main() -> None:
    parse_only = "--parse-only" in sys.argv
    fit_bstar = "--fit-bstar=off" not in sys.argv
    sweep = "--sweep" in sys.argv
    state_path = "--state-path" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    window = args[0] if args else "quiet_2019"
    if window not in CATALOG_TLES:
        raise SystemExit(
            f"unknown window {window!r}; choose one of {tuple(CATALOG_TLES)}"
        )
    load_days = SWEEP_LOAD_DAYS if (sweep or state_path) else LOAD_DAYS

    print("GRACE-FO 1: fitted TLE vs Space-Track catalog TLE -- Chunk 3")
    print("=" * 74)
    if sweep:
        tag = " (fitting-span sweep)"
    elif state_path:
        tag = " (state-path check)"
    else:
        tag = "" if fit_bstar else " (fit_bstar=off)"
    print(f"[window] {window}{tag}")

    # --- truth: fit arc(s) + the forward prediction days ----------------------
    window_dir = DATA_ROOT / window
    files = find_window_files(window_dir, GRACEFO_SAT_ID)
    if len(files) < load_days:
        raise SystemExit(
            f"need {load_days} GNV1B days under {window_dir}, found {len(files)}"
        )
    eph = parse_gnv1b(files[:load_days], sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S)
    n = len(eph.epochs)
    span_s = eph.epochs[-1].seconds_since(eph.epochs[0])
    n_fit = int(FIT_SPAN_S / SUBSAMPLE_S) + 1  # inclusive of the 24 h endpoint
    n_per_day = int(86400.0 / SUBSAMPLE_S)

    print("[data]")
    print(f"  satellite: {eph.sat_id} = {eph.sat_name} (NORAD {NORAD_ID})")
    print(f"  source files ({len(eph.source_files)}): {', '.join(eph.source_files)}")
    print(
        f"  1 Hz records read: {eph.n_raw_records} (QC-dropped {eph.n_dropped_qc}); "
        f"subsampled to {SUBSAMPLE_S:.0f} s -> {n} epochs"
    )
    print(
        f"  span: {eph.epochs[0].to_iso()} -> {eph.epochs[-1].to_iso()} "
        f"{eph.epochs[0].scale.value} ({span_s / 86400.0:.3f} days loaded)"
    )
    if sweep:
        print(
            f"  fit arcs: {'/'.join(str(d) for d in SWEEP_SPANS_D)} d, all ending "
            f"at the day-4 start; common forecast window: days 4-6"
        )
    elif state_path:
        print(
            "  fit window: days 2-3 (2 d, ending at the day-4 start); common "
            "forecast window: days 4-6"
        )
    else:
        print(
            f"  fit arc: first {n_fit} samples ({FIT_SPAN_S / 3600.0:.0f} h); "
            f"prediction: {FORWARD_DAYS} further days"
        )
    if n < load_days * n_per_day:
        raise SystemExit(f"expected ~{load_days * n_per_day} truth samples, got {n}")

    # --- catalog TLE (pure-Python validation: structure + checksums) ----------
    catalog = TLE.from_strings(*CATALOG_TLES[window], name=SAT_NAME)
    dt_h = eph.epochs[0].seconds_since(catalog.epoch) / 3600.0
    print("[catalog TLE]  Space-Track gp_history, nearest epoch to the fit start")
    print(f"  {catalog.line1}")
    print(f"  {catalog.line2}")
    print(
        f"  epoch {catalog.epoch.to_iso()} UTC "
        f"({dt_h:+.2f} h from truth t0 -- negative = after)"
    )

    if parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        return

    if sweep:
        _run_sweep(eph, catalog)
        return
    if state_path:
        _run_state_path(eph, window)
        return

    # --- the fit: one day of real GNV1B truth ---------------------------------
    # ITRF in; the 1.2 Trajectory path converts to TEME internally and clips to
    # the leading fitting_span. force_models/spacecraft deliberately absent --
    # they are State-path-only (warn-and-ignore) for a Trajectory reference.
    reference = Trajectory.from_arrays(
        list(eph.epochs[:n_fit]),
        eph.positions_m[:n_fit],
        eph.velocities_ms[:n_fit],
        Frame.ITRF,
    )
    print(
        "[fit]  fit_tle_detailed on the fit-day trajectory (progress on stderr)"
        + ("" if fit_bstar else "; fit_bstar=False, B* held at the seed's 0.0")
    )
    fit = fit_tle_detailed(
        reference,
        fitting_span=FIT_SPAN_S,
        norad_id=NORAD_ID,
        name=SAT_NAME,
        fit_bstar=fit_bstar,
    )
    print(f"  {fit.tle.line1}")
    print(f"  {fit.tle.line2}")
    print(
        f"  converged: {fit.iterations} iterations, {fit.evaluations} evaluations; "
        f"post-fit rms {fit.rms_m:.1f} m over {len(fit.residuals_m)} measurements"
    )
    print(
        f"  residuals (m): min {fit.residuals_m.min():.1f}, "
        f"median {np.median(fit.residuals_m):.1f}, max {fit.residuals_m.max():.1f}"
    )
    # Residual profile across the fit day (6 h bins on the measurement epochs) --
    # structure here is the SGP4 representation error over the arc.
    offsets = np.array(
        [e.seconds_since(fit.measurement_epochs[0]) for e in fit.measurement_epochs]
    )
    cells = []
    for h0 in range(0, 24, 6):
        m = (offsets >= h0 * 3600.0) & (offsets < (h0 + 6) * 3600.0)
        rms_bin = float(np.sqrt(np.mean(fit.residuals_m[m] ** 2))) if m.any() else 0.0
        cells.append(f"{h0:02d}-{h0 + 6:02d}h {rms_bin:6.1f}")
    print("  residual RMS by fit-day quarter (m): " + "  ".join(cells))
    gate = "PASS" if fit.rms_m < 1000.0 else "FAIL"
    print(f"  gate: post-fit rms sub-km-class -> {gate}")

    # --- prediction: fit day + 3 forward days, fitted vs catalog --------------
    # Both TLEs evaluated on the exact truth grid (start = truth t0; the fitted
    # TLE's epoch IS the reference start, the catalog's sits ~5 h earlier).
    print(f"[prediction]  fit day + {FORWARD_DAYS} forward days, ITRF diff vs truth")
    d_fit = _tle_diff_itrf(fit.tle, eph, span_s)
    d_cat = _tle_diff_itrf(catalog, eph, span_s)
    nn = len(d_fit)
    ric_fit = ric_components(
        d_fit, eph.positions_m[:nn], eph.velocities_ms[:nn], earth_fixed=True
    )
    ric_cat = ric_components(
        d_cat, eph.positions_m[:nn], eph.velocities_ms[:nn], earth_fixed=True
    )

    print(
        f"  {'day':<14}{'fitted 3D':>11}{'along':>10}"
        f"{'catalog 3D':>13}{'along':>10}{'3D ratio':>10}"
    )
    ratios = []
    for d in range(LOAD_DAYS):
        sl = slice(d * n_per_day, min((d + 1) * n_per_day, nn))
        rms3_f = _rms(np.linalg.norm(d_fit[sl], axis=1))
        rms3_c = _rms(np.linalg.norm(d_cat[sl], axis=1))
        along_f = _rms(ric_fit[sl, 1])
        along_c = _rms(ric_cat[sl, 1])
        ratio = rms3_f / rms3_c if rms3_c > 0 else float("nan")
        label = "1 (fit day)" if d == 0 else f"{d + 1} (+{d})"
        print(
            f"  {label:<14}{rms3_f:>11.1f}{along_f:>10.1f}"
            f"{rms3_c:>13.1f}{along_c:>10.1f}{ratio:>10.2f}"
        )
        if d > 0:
            ratios.append(ratio)
    print("  (RMS meters per UTC-day slice of the grid; along = RIC along-track)")

    # Signed along-track at each day boundary: the growth *sense* (a TLE's
    # dominant error mode is along-track timing, so sign flips are informative).
    cells_f = []
    cells_c = []
    for d in range(1, LOAD_DAYS + 1):
        k = min(d * n_per_day - 1, nn - 1)
        cells_f.append(f"{d}d {ric_fit[k, 1]:+9.0f}")
        cells_c.append(f"{d}d {ric_cat[k, 1]:+9.0f}")
    print("  signed along-track at day ends (m), fitted : " + "  ".join(cells_f))
    print("  signed along-track at day ends (m), catalog: " + "  ".join(cells_c))

    # --- element-level sanity --------------------------------------------------
    el_f = _elements(fit.tle)
    el_c = _elements(catalog)
    print("[elements]  fitted vs catalog mean elements")
    print(
        f"  epochs differ by {dt_h:.2f} h -> i/RAAN/e/n compare directly; "
        f"argp + M are epoch-dependent (fast angles), read with that offset"
    )
    print(f"  {'element':<22}{'fitted':>14}{'catalog':>14}{'delta':>12}")
    for key, fmt in (
        ("inclination_deg", "10.4f"),
        ("raan_deg", "10.4f"),
        ("eccentricity", "10.7f"),
        ("arg_perigee_deg", "10.4f"),
        ("mean_anomaly_deg", "10.4f"),
        ("mean_motion_revday", "12.8f"),
        ("bstar", "10.3e"),
    ):
        f_val, c_val = el_f[key], el_c[key]
        print(
            f"  {key:<22}{f_val:>14{fmt[fmt.index('.'):]}}"
            f"{c_val:>14{fmt[fmt.index('.'):]}}{f_val - c_val:>12.2e}"
        )
    print(
        "  B* differs by design: the fitted B* is a fit residual absorbing "
        "SGP4/density model error over THIS arc, not a physical ballistic "
        "coefficient (features.md 1.2 documented behavior)."
    )

    # --- headline ---------------------------------------------------------------
    worst = max(ratios)
    best = min(ratios)
    print("[chunk 3 verdict inputs]")
    print(
        f"  fit converged on real (non-propygator) data: {fit.iterations} iters, "
        f"post-fit rms {fit.rms_m:.1f} m ({gate})"
    )
    print(
        f"  forward-prediction 3D RMS ratio fitted/catalog over the "
        f"{FORWARD_DAYS} forward days: {best:.2f} .. {worst:.2f} "
        f"(parity band = same order, ~0.1 .. 10)"
    )


if __name__ == "__main__":
    main()
