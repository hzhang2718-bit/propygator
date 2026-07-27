"""Probe 1: the TLE-fitting strategy matrix on a day-7 anchor.

Part of the **TLE fit strategy** experiment (2026-07-19, promoted from the
post-v0.8.0 strategy-session scratchpad probes; see README.md): what should a
user *do* with the v0.8.0 ``FitResult`` diagnostics? This probe measures, per
window (quiet_2019 / active_2023), using the 10 GNV1B truth days on disk (the
shipped ``run_fit_vs_catalog.py --sweep`` used 6):

  1. fitted-B* arcs at 1/2/3/4/6 d           (does quiet fitted B* converge to
                                              the catalog long-arc value? no)
  2. held-catalog-B* arcs at 1/2/3/6 d       (does quiet's monotonic span gain
                                              continue past 3 d? no -- F8)
  3. held-zero-B* arcs at 1/3/6 d            (the no-prior baseline)
  4. held-physical-B* at 3 d                 (B* from 0.5*rho0*Cd*A/m -- ruled
                                              out, catastrophically)
  5. the two-stage self-calibrated transplant (fit B* on a long arc, hold it
     (2d->1d, 6d->1d, 6d->3d)                 via initial_guess+fit_bstar=False,
                                              refit elements on a fresh arc)

Every fit records the v0.8.0 diagnostics: sigma0, raw + sigma0-scaled
sigma(B*), and the linear/quadratic coefficients of the in-arc along-track RIC
residual -- the candidate catalog-free discriminators behind the playbook's
r-gate (``docs/tle-fitting-playbook.md``).

Design mirrors ``run_fit_vs_catalog.py --sweep``: end-anchored fit arcs, all
ending at the day-7 start; common forecast window = days 7-10 (4 days).

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data + the study's GNV1B
data); cwd-independent. Stdout is ASCII-only (captured under cp1252):

    cd experiments/tle-fit-strategy
    conda run -n propygator python probe1_strategy_matrix.py quiet_2019  >  results_probe1_strategy_matrix.txt
    conda run -n propygator python probe1_strategy_matrix.py active_2023 >> results_probe1_strategy_matrix.txt
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
    A_RAM_M2,
    DATA_ROOT,
    GRACEFO_CD_NOMINAL,
    GRACEFO_MASS_KG,
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

# Same catalog TLEs as run_fit_vs_catalog.py (Space-Track gp_history pulls,
# epochs ~6 h before each window's day-1 start). Here they are 6+ days stale
# vs the day-7 anchor: their B* value is the "long-arc catalog calibration"
# for held-cat rows; the forecast context row is honest-labeled as stale.
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
ANCHOR_DAY = 7  # all fit arcs end at the day-7 start; forecast = days 7-10

# Physical B* from the SGP4 convention B* = rho0/2 * Cd*A/m,
# rho0 = 0.15696615 kg/(m^2 * Earth radius) (Vallado).
RHO0_KG_M2_RE = 0.15696615
BSTAR_PHYS = 0.5 * RHO0_KG_M2_RE * GRACEFO_CD_NOMINAL * A_RAM_M2 / GRACEFO_MASS_KG


def _parse_bstar(line1: str) -> float:
    field = line1[53:61]
    sign = -1.0 if field[0] == "-" else 1.0
    return sign * (int(field[1:6]) / 1.0e5) * 10.0 ** int(field[6:8])


def _mean_motion(line2: str) -> float:
    return float(line2[52:63])


def main() -> None:
    window = sys.argv[1] if len(sys.argv) > 1 else "quiet_2019"
    t_wall = time.time()

    files = find_window_files(DATA_ROOT / window, GRACEFO_SAT_ID)
    if len(files) < LOAD_DAYS:
        raise SystemExit(f"need {LOAD_DAYS} days under {window}, found {len(files)}")
    eph = parse_gnv1b(
        files[:LOAD_DAYS], sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S
    )
    n = len(eph.epochs)
    n_per_day = int(86400.0 / SUBSAMPLE_S)
    k_end = (ANCHOR_DAY - 1) * n_per_day  # the day-7 start
    t_end = eph.epochs[k_end]
    span_fc = eph.epochs[-1].seconds_since(t_end)
    truth_fc = eph.positions_m[k_end:]
    n_fc_days = (n - k_end) // n_per_day

    catalog = TLE.from_strings(*CATALOG_TLES[window], name=SAT_NAME)
    cat_bstar = _parse_bstar(catalog.line1)

    print(f"Probe 1: strategy matrix -- {window}")
    print("=" * 78)
    print(f"  loaded {n} truth epochs ({n / n_per_day:.1f} d); anchor = day-{ANCHOR_DAY} "
          f"start {t_end.to_iso()} {t_end.scale.value}")
    print(f"  forecast window: days {ANCHOR_DAY}-{ANCHOR_DAY - 1 + n_fc_days} "
          f"({n_fc_days} days); catalog B* = {cat_bstar:.3e} "
          f"(epoch {t_end.seconds_since(catalog.epoch) / 86400.0:.2f} d before anchor)")
    print(f"  physical B* (0.5*rho0*Cd*A/m, Cd {GRACEFO_CD_NOMINAL}, "
          f"A {A_RAM_M2:.3f} m^2, m {GRACEFO_MASS_KG:.0f} kg) = {BSTAR_PHYS:.3e}")

    def forecast_rms(tle: TLE) -> list[float]:
        traj = propagate_tle(tle, span_fc, output_step=SUBSAMPLE_S, start=t_end)
        pos = traj.to_frame(Frame.ITRF).positions
        d = np.linalg.norm(pos[: len(truth_fc)] - truth_fc, axis=1)
        return [_rms(d[j * n_per_day : (j + 1) * n_per_day]) for j in range(n_fc_days)]

    def ref_for_span(span_d: int) -> Trajectory:
        k0 = k_end - span_d * n_per_day
        return Trajectory.from_arrays(
            list(eph.epochs[k0 : k_end + 1]),
            eph.positions_m[k0 : k_end + 1],
            eph.velocities_ms[k0 : k_end + 1],
            Frame.ITRF,
        )

    def run_fit(label: str, span_d: int, guess: TLE | None, fit_bstar: bool):
        fit = fit_tle_detailed(
            ref_for_span(span_d),
            fitting_span=span_d * 86400.0,
            initial_guess=guess,
            fit_bstar=fit_bstar,
            norad_id=NORAD_ID,
            name=SAT_NAME,
            progress=False,
        )
        bstar = _parse_bstar(fit.tle.line1)
        nn = _mean_motion(fit.tle.line2)
        per_day = forecast_rms(fit.tle)
        # Diagnostics: sigma(B*) raw + sigma0-scaled; along-track poly coeffs.
        names = fit.parameter_names
        sig_raw = sig_scaled = ratio = None
        if fit.covariance is not None and "BSTAR" in names:
            i = names.index("BSTAR")
            sig_raw = float(fit.sigmas[i])
            sig_scaled = fit.sigma0 * sig_raw
            ratio = sig_scaled / abs(bstar) if bstar != 0.0 else float("inf")
        t_days = np.array(
            [e.seconds_since(fit.measurement_epochs[0]) for e in fit.measurement_epochs]
        ) / 86400.0
        c2, c1, _c0 = np.polyfit(t_days, fit.residuals_ric_m[:, 1], 2)
        rows.append(
            dict(label=label, span=span_d, rms=fit.rms_m, fc=per_day, bstar=bstar,
                 n=nn, sigma0=fit.sigma0, sig_raw=sig_raw, sig_scaled=sig_scaled,
                 ratio=ratio, c1=float(c1), c2=float(c2), iters=fit.iterations)
        )
        print(f"  [{time.time() - t_wall:6.0f} s] {label:<22} {span_d} d done "
              f"({fit.iterations} iters)", file=sys.stderr)
        return fit

    rows: list[dict] = []
    fitted_by_span: dict[int, TLE] = {}

    # 1. fitted B*
    for span in (1, 2, 3, 4, 6):
        fit = run_fit("fitted", span, None, True)
        fitted_by_span[span] = fit.tle
    # 2. held at catalog B*
    for span in (1, 2, 3, 6):
        run_fit("held-cat", span, catalog, False)
    # 3. held at B* = 0
    for span in (1, 3, 6):
        run_fit("held-zero", span, None, False)
    # 4. held at physical B* (guess TLE = unfitted template carrying B*_phys;
    #    the fixed-point seed re-derives elements, only B* is donated)
    k0_3d = k_end - 3 * n_per_day
    s0 = State(
        eph.epochs[k0_3d], eph.positions_m[k0_3d], eph.velocities_ms[k0_3d], Frame.ITRF
    ).to_frame(Frame.TEME)
    phys_guess = TLE.from_state_unfitted(s0, norad_id=NORAD_ID, bstar=BSTAR_PHYS)
    run_fit("held-phys", 3, phys_guess, False)
    # 5. two-stage self-calibrated transplant (catalog-free): stage-1 fitted
    #    B* donated via initial_guess, elements refit on the fresh arc.
    run_fit("selfcal 2d->1d", 1, fitted_by_span[2], False)
    run_fit("selfcal 6d->1d", 1, fitted_by_span[6], False)
    run_fit("selfcal 6d->3d", 3, fitted_by_span[6], False)

    # --- table A: forecasts ---------------------------------------------------
    print()
    print("[A] forecast table (end-anchored arcs; common days 7-10 window; RMS m)")
    hdr = (f"  {'config':<17}{'span':>5}{'in-arc':>8}"
           + "".join(f"{f'+{j + 1} d':>9}" for j in range(n_fc_days))
           + f"{'B*':>11}{'n (rev/d)':>14}")
    print(hdr)
    for r in rows:
        print(f"  {r['label']:<17}{r['span']:>4}d{r['rms']:>8.1f}"
              + "".join(f"{v:>9.1f}" for v in r["fc"])
              + f"{r['bstar']:>11.3e}{r['n']:>14.8f}")
    per_day = forecast_rms(catalog)
    print(f"  {'catalog (stale)':<17}{'-':>5}{'-':>8}"
          + "".join(f"{v:>9.1f}" for v in per_day)
          + f"{cat_bstar:>11.3e}{_mean_motion(catalog.line2):>14.8f}")
    print(f"  (catalog row context only: its epoch is "
          f"{t_end.seconds_since(catalog.epoch) / 86400.0:.1f} d stale at the anchor)")

    # --- table B: the v0.8.0 diagnostics per fit --------------------------------
    print()
    print("[B] diagnostics (sigma(B*) raw + sigma0-scaled; along-track poly, m)")
    print(f"  {'config':<17}{'span':>5}{'sigma0':>10}{'sigB*raw':>11}"
          f"{'sigB*scl':>11}{'scl/|B*|':>10}{'c1 m/d':>9}{'c2 m/d^2':>10}")
    for r in rows:
        s_raw = f"{r['sig_raw']:.3e}" if r["sig_raw"] is not None else "-"
        s_scl = f"{r['sig_scaled']:.3e}" if r["sig_scaled"] is not None else "-"
        s_rat = f"{r['ratio']:.3f}" if r["ratio"] is not None else "-"
        print(f"  {r['label']:<17}{r['span']:>4}d{r['sigma0']:>10.1f}{s_raw:>11}"
              f"{s_scl:>11}{s_rat:>10}{r['c1']:>9.1f}{r['c2']:>10.1f}")
    print()
    print(f"  wall time {time.time() - t_wall:.0f} s")


if __name__ == "__main__":
    main()
