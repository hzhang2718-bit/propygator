"""Probe 2: epoch-at-arc-end + age-weighted (fading-memory) measurements.

Part of the **TLE fit strategy** experiment (2026-07-19; see README.md). Two
mechanisms outside the public 1.2 surface, driven through the fitter
internals — the one probe in this experiment that deliberately imports
``propygator.tle.fitter`` privates (documented, unsupported usage; the point
is to measure whether either mechanism *deserves* a contract amendment):

  A. **Epoch at the arc end.** The shipped contract pins the fitted TLE epoch
     to the reference START, so an end-anchored 3 d fit forecasts from a 3 d
     stale epoch while catalog TLEs epoch near their arc ends. Here the seed
     is built at the arc's LAST sample (measurements all lie before the
     epoch). Measured outcome: a mathematical NO-OP (< 2 m forecast deltas —
     the same converged trajectory, reparameterized), which *validates* the
     shipped epoch-at-start rule. Kept as the negative-result record.
  B. **Age-weighted measurements.** sigma(age) = base * exp(age_days / tau):
     a fading-memory fit — long-arc B* observability and fresh elements in
     ONE fit (the single-fit rival of the two-stage transplant; the follow-up
     question lives in ``tle-fit-strategy-findings.md``, same folder).

Same day-7 anchor / days 7-10 forecast as probe 1, so rows compare directly
across probes.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data + the study's GNV1B
data); cwd-independent. Stdout is ASCII-only (captured under cp1252):

    cd experiments/tle-fit-strategy
    conda run -n propygator python probe2_epoch_and_weights.py quiet_2019  >  results_probe2_epoch_weights.txt
    conda run -n propygator python probe2_epoch_and_weights.py active_2023 >> results_probe2_epoch_weights.txt
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

_EXP = Path(__file__).resolve().parents[1] / "real-world-validation"
sys.path.insert(0, str(_EXP / "gracefo"))
sys.path.insert(0, str(_EXP))

from common import rms as _rms  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402
from gracefo_common import (  # noqa: E402
    DATA_ROOT,
    GRACEFO_SAT_ID,
    NORAD_ID,
    SAT_NAME,
    SUBSAMPLE_S,
)

from propygator import (  # noqa: E402
    TLE,
    Frame,
    State,
    Trajectory,
    fit_tle_detailed,
    propagate_tle,
)
from propygator.core.progress import _ProgressReporter  # noqa: E402
from propygator.tle.fitter import (  # noqa: E402
    _MEASUREMENT_CAP,
    _SIGMA_POSITION_M,
    _SIGMA_VELOCITY_MS,
    _run_estimation,
)

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

LOAD_DAYS = 10
ANCHOR_DAY = 7


def _parse_bstar(line1: str) -> float:
    field = line1[53:61]
    sign = -1.0 if field[0] == "-" else 1.0
    return sign * (int(field[1:6]) / 1.0e5) * 10.0 ** int(field[6:8])


def main() -> None:
    window = sys.argv[1] if len(sys.argv) > 1 else "quiet_2019"
    t_wall = time.time()

    files = find_window_files(DATA_ROOT / window, GRACEFO_SAT_ID)
    eph = parse_gnv1b(
        files[:LOAD_DAYS], sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S
    )
    n = len(eph.epochs)
    n_per_day = int(86400.0 / SUBSAMPLE_S)
    k_end = (ANCHOR_DAY - 1) * n_per_day
    t_end = eph.epochs[k_end]
    span_fc = eph.epochs[-1].seconds_since(t_end)
    truth_fc = eph.positions_m[k_end:]
    n_fc_days = (n - k_end) // n_per_day

    catalog = TLE.from_strings(*CATALOG_TLES[window], name=SAT_NAME)

    print(f"Probe 2: epoch-at-end + age weights -- {window}")
    print("=" * 78)
    print(f"  anchor = day-{ANCHOR_DAY} start {t_end.to_iso()} {t_end.scale.value}; "
          f"forecast days {ANCHOR_DAY}-{ANCHOR_DAY - 1 + n_fc_days}")

    def forecast_rms(tle: TLE) -> list[float]:
        traj = propagate_tle(tle, span_fc, output_step=SUBSAMPLE_S, start=t_end)
        pos = traj.to_frame(Frame.ITRF).positions
        d = np.linalg.norm(pos[: len(truth_fc)] - truth_fc, axis=1)
        return [_rms(d[j * n_per_day : (j + 1) * n_per_day]) for j in range(n_fc_days)]

    def ref_teme_for_span(span_d: int) -> Trajectory:
        k0 = k_end - span_d * n_per_day
        traj = Trajectory.from_arrays(
            list(eph.epochs[k0 : k_end + 1]),
            eph.positions_m[k0 : k_end + 1],
            eph.velocities_ms[k0 : k_end + 1],
            Frame.ITRF,
        )
        return traj.to_frame(Frame.TEME)

    # --- internals: seed at an arbitrary sample + custom-sigma measurements ----
    def build_seed_at(state_teme: State, template: TLE) -> TLE:
        from org.orekit.orbits import CartesianOrbit
        from org.orekit.propagation import SpacecraftState
        from org.orekit.propagation.analytical.tle import TLEConstants
        from org.orekit.propagation.analytical.tle.generation import (
            FixedPointTleGenerationAlgorithm,
        )

        orbit = CartesianOrbit(
            state_teme._orekit_pv(),
            Frame.TEME.to_orekit(),
            state_teme.epoch.to_orekit(),
            float(TLEConstants.MU),
        )
        refined = FixedPointTleGenerationAlgorithm().generate(
            SpacecraftState(orbit), template.to_orekit()
        )
        return TLE.from_strings(str(refined.getLine1()), str(refined.getLine2()))

    def build_measurements(ref_teme: Trajectory, tau_days: float | None):
        from org.orekit.estimation.measurements import PV, ObservableSatellite

        m = len(ref_teme)
        indices = np.unique(
            np.round(np.linspace(0, m - 1, min(_MEASUREMENT_CAP, m))).astype(int)
        )
        satellite = ObservableSatellite(0)
        end_epoch = ref_teme.end_epoch
        measurements = []
        for i in indices:
            sample = ref_teme[int(i)]
            pv = sample._orekit_pv()
            if tau_days is None:
                inflate = 1.0
            else:
                age_d = end_epoch.seconds_since(sample.epoch) / 86400.0
                inflate = float(np.exp(age_d / tau_days))
            measurements.append(
                PV(
                    sample.epoch.to_orekit(),
                    pv.getPosition(),
                    pv.getVelocity(),
                    _SIGMA_POSITION_M * inflate,
                    _SIGMA_VELOCITY_MS * inflate,
                    1.0,
                    satellite,
                )
            )
        return measurements

    def run_internal(
        label: str,
        span_d: int,
        template: TLE,
        fit_bstar: bool,
        *,
        seed_at_end: bool,
        tau_days: float | None = None,
    ) -> TLE:
        ref = ref_teme_for_span(span_d)
        seed_state = ref[len(ref) - 1] if seed_at_end else ref[0]
        seed = build_seed_at(seed_state, template)
        measurements = build_measurements(ref, tau_days)
        reporter = _ProgressReporter(f"probe2:{label}", False)
        try:
            (fitted_j, iters, _evals, rms_m, _res, _vres, _ric, cov, names, sigma0
             ) = _run_estimation(seed, measurements, 100, fit_bstar, reporter, False)
        finally:
            reporter.close()
        tle = TLE.from_strings(str(fitted_j.getLine1()), str(fitted_j.getLine2()))
        per_day = forecast_rms(tle)
        bstar = _parse_bstar(tle.line1)
        sig_txt = "-"
        if cov is not None and "BSTAR" in names:
            i = names.index("BSTAR")
            sig_txt = f"{sigma0 * float(np.sqrt(cov[i, i])):.2e}"
        stale_d = t_end.seconds_since(tle.epoch) / 86400.0
        rows.append((label, span_d, rms_m, per_day, bstar, stale_d, sig_txt))
        print(f"  [{time.time() - t_wall:6.0f} s] {label:<28} done ({iters} iters)",
              file=sys.stderr)
        return tle

    rows: list[tuple] = []

    # Templates for seed B*: unfitted TLE at the arc-end truth sample.
    def template_with_bstar(bstar: float) -> TLE:
        s_end = State(
            eph.epochs[k_end], eph.positions_m[k_end], eph.velocities_ms[k_end],
            Frame.ITRF,
        ).to_frame(Frame.TEME)
        return TLE.from_state_unfitted(s_end, norad_id=NORAD_ID, bstar=bstar)

    if window == "quiet_2019":
        # Quiet: does end-epoch rescue/boost the long-arc configs?
        run_internal("held-cat 3d endEpoch", 3, catalog, False, seed_at_end=True)
        run_internal("held-cat 6d endEpoch", 6, catalog, False, seed_at_end=True)
        run_internal("fitted 6d endEpoch", 6, template_with_bstar(0.0), True,
                     seed_at_end=True)
        run_internal("fitted 6d endEp w tau1.5", 6, template_with_bstar(0.0), True,
                     seed_at_end=True, tau_days=1.5)
        run_internal("held-cat 6d endEp w tau2", 6, catalog, False,
                     seed_at_end=True, tau_days=2.0)
    else:
        # Active: end-epoch versions of the winners + the single-fit rival.
        run_internal("fitted 2d endEpoch", 2, template_with_bstar(0.0), True,
                     seed_at_end=True)
        run_internal("held-cat 1d endEpoch", 1, catalog, False, seed_at_end=True)
        # two-stage: stage 1 public (fitted 2d, normal epoch), stage 2 internal
        stage1 = fit_tle_detailed(
            Trajectory.from_arrays(
                list(eph.epochs[k_end - 2 * n_per_day : k_end + 1]),
                eph.positions_m[k_end - 2 * n_per_day : k_end + 1],
                eph.velocities_ms[k_end - 2 * n_per_day : k_end + 1],
                Frame.ITRF,
            ),
            fitting_span=2 * 86400.0,
            norad_id=NORAD_ID, name=SAT_NAME, progress=False,
        )
        print(f"  stage-1 fitted 2d B* = {_parse_bstar(stage1.tle.line1):.3e}",
              file=sys.stderr)
        run_internal("selfcal 2d->1d endEpoch", 1, stage1.tle, False,
                     seed_at_end=True)
        run_internal("fitted 3d endEp w tau0.75", 3, template_with_bstar(0.0), True,
                     seed_at_end=True, tau_days=0.75)
        run_internal("fitted 3d endEp w tau1.0", 3, template_with_bstar(0.0), True,
                     seed_at_end=True, tau_days=1.0)

    print()
    print("[forecast] (same anchor/window as probe 1 -- rows comparable across probes)")
    print(f"  {'config':<28}{'span':>5}{'in-arc':>8}"
          + "".join(f"{f'+{j + 1} d':>9}" for j in range(n_fc_days))
          + f"{'B*':>11}{'epoch stale':>12}{'sigB*scl':>10}")
    for label, span_d, rms_m, per_day, bstar, stale_d, sig_txt in rows:
        print(f"  {label:<28}{span_d:>4}d{rms_m:>8.1f}"
              + "".join(f"{v:>9.1f}" for v in per_day)
              + f"{bstar:>11.3e}{stale_d:>10.2f} d{sig_txt:>10}")
    per_day = forecast_rms(catalog)
    print(f"  {'catalog (stale)':<28}{'-':>5}{'-':>8}"
          + "".join(f"{v:>9.1f}" for v in per_day))
    print()
    print(f"  wall time {time.time() - t_wall:.0f} s")


if __name__ == "__main__":
    main()
