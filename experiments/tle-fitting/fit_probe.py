"""
TLE-fitting feasibility probe -- build-plan-feature-1.2.md Chunk 0 evidence
(binding contract: features.md section 1.2 -> "Validated domain & de-risking").

Runs the ENTIRE fit recipe against the shipped stack before any src/ code
exists: Orekit TLEPropagatorBuilder + BatchLSEstimator (Levenberg-Marquardt)
over ~300 evenly subsampled PV measurements, with a BatchLSObserver
@JImplements proxy printing per-iteration lines (this IS the de-risk of the
one new JPype proxy -- reflection shows the interface has a single abstract
method and NO default methods, so the default-method trap does not apply,
but only the real call path proves it).

  >>> RUN IN THE propygator CONDA ENV (starts the JVM, needs orekit-data). <<<

      conda run -n propygator python experiments/tle-fitting/fit_probe.py > experiments/tle-fitting/results.txt

Scenarios (build-plan "Decisions to confirm" defaults):
  (i)   SGP4 self-fit -- a fixed ISS TLE (the test-suite fixture),
        propagate_tle over 2 d @ 60 s; known-exact answer, must recover the
        source TLE nearly exactly (tens-of-meters RMS, elements close).
  (ii)  Numerical fit -- the same orbit's first state through
        propagate_numerical leo_default + IntegratorConfig.high_precision(),
        2 d @ 600 s; records the honest km-level RMS the docs will quote.
  (iii) Molniya/SDP4 self-fit -- the Vallado 08195 case (deep-space branch,
        e ~ 0.69); an early read on deep-space fragility.

Per scenario the probe fits with BOTH seeds (TLE.from_state_unfitted and
Orekit's FixedPointTleGenerationAlgorithm refinement of it) x BSTAR driver
on/off, then a positionScale / convergence-threshold sensitivity sweep on the
self-fit leg. Each fit reports: converged?, iterations, evaluations, final
observed-vs-estimated position RMS (m), a propagate-back residual over the
full reference grid (m), and (self-fit legs) fitted-vs-source element deltas.

Also recorded (Checkpoint A item 3 input): whether per-measurement residuals
fall out of the estimator essentially free -- they do; the observer receives
an EstimationsProvider (per-measurement observed/estimated values) plus the
LS Evaluation (getRMS/getResiduals/getCost), and this probe's physical RMS is
computed from exactly that, every iteration.

Reference-only: not shipped, not in CI, outside testpaths. ASCII-only stdout
(cp1252 redirect). Wall time: a few minutes (the 2-day high-precision
numerical reference dominates).
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

import numpy as np

import propygator as pgr
from propygator import (
    TLE,
    ForceModelConfig,
    IntegratorConfig,
    SpacecraftConfig,
    propagate_numerical,
    propagate_tle,
)
from propygator.core.frames import Frame

# ---------------------------------------------------------------------------
# Fixtures: the test-suite ISS TLE (tests/core/test_tle.py) and the Vallado
# AIAA 2006-6753 case 08195 (Molniya 1-36, SDP4 deep-space branch -- the same
# lines pinned in tests/tle/test_sgp4_agreement.py).
# ---------------------------------------------------------------------------
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

MOLNIYA_LINE1 = "1 08195U 75081A   06176.33215444  .00000099  00000-0  11873-3 0   813"
MOLNIYA_LINE2 = "2 08195  64.1586 279.0717 6877146 264.7651  20.2257  2.00491383225656"

# ---------------------------------------------------------------------------
# Probe constants (the internal knobs Chunk 2 will inherit pre-tuned; the
# baseline values below are swept at the end).
# ---------------------------------------------------------------------------
DURATION_S = 2 * 86400.0  # the contract's default fitting_span
SELF_FIT_STEP_S = 60.0  # reference grid, scenarios (i)/(iii)
NUMERICAL_STEP_S = 600.0  # reference grid, scenario (ii) (~289 samples)
N_MEAS = 300  # even-subsample cap (contract: ~300, tunable)
SIGMA_POS_M = 1.0  # PV measurement sigmas (uniform weights --
SIGMA_VEL_MS = 1.0e-3  # a perfect reference has no noise model)
BASE_WEIGHT = 1.0
POSITION_SCALE_M = 1.0  # baseline; swept {1, 10, 100, 1000}
CONV_THRESHOLD = 1.0e-3  # baseline; swept {1e-2, 1e-3, 1e-4}
MAX_ITERATIONS = 100  # the contract default; bounds iterations
MAX_EVALUATIONS = 100  # ... and evaluations alike

_OBSERVER_CLASS = None
_BUILDER_DESCRIBED = False


def _observer_class():
    """Build (once) the @JImplements BatchLSObserver proxy class.

    JVM must already be started. BatchLSObserver has exactly one abstract
    method and no defaults (verified by reflection), so the proxy implements
    just evaluationPerformed.
    """
    global _OBSERVER_CLASS
    if _OBSERVER_CLASS is not None:
        return _OBSERVER_CLASS
    import jpype

    @jpype.JImplements("org.orekit.estimation.leastsquares.BatchLSObserver")
    class ProbeObserver:
        """Per-iteration hook: physical position RMS + normalized LS RMS."""

        def __init__(self, verbose):
            self.verbose = verbose
            # (iterations_count, evaluations_count, pos_rms_m, normalized_rms)
            self.history = []

        @jpype.JOverride
        def evaluationPerformed(
            self,
            iterations_count,
            evaluations_count,
            orbits,
            estimated_orbital_parameters,
            estimated_propagator_parameters,
            estimated_measurements_parameters,
            evaluations_provider,
            ls_evaluation,
        ):
            # Physical position RMS from the per-measurement residuals the
            # provider hands us for free (the FitResult-revisit finding).
            n = int(evaluations_provider.getNumber())
            sq_sum = 0.0
            for i in range(n):
                est = evaluations_provider.getEstimatedMeasurement(i)
                obs = est.getObservedValue()
                thr = est.getEstimatedValue()
                for k in range(3):
                    d = float(obs[k]) - float(thr[k])
                    sq_sum += d * d
            pos_rms = math.sqrt(sq_sum / n)
            norm_rms = float(ls_evaluation.getRMS())
            self.history.append(
                (int(iterations_count), int(evaluations_count), pos_rms, norm_rms)
            )
            if self.verbose:
                print(
                    f"    iter {int(iterations_count):3d} | "
                    f"eval {int(evaluations_count):3d} | "
                    f"pos rms {pos_rms:14.6g} m | "
                    f"normalized rms {norm_rms:.6e}"
                )

    _OBSERVER_CLASS = ProbeObserver
    return ProbeObserver


def _describe_builder(builder):
    """Print the builder's frame + parameter-driver defaults once (evidence)."""
    global _BUILDER_DESCRIBED
    if _BUILDER_DESCRIBED:
        return
    _BUILDER_DESCRIBED = True
    print(f"  [builder] propagation frame: {builder.getFrame().getName()}")
    print("  [builder] orbital parameter drivers (defaults):")
    for d in builder.getOrbitalParametersDrivers().getDrivers():
        print(f"      {d.getName()} selected={d.isSelected()}")
    print("  [builder] propagation parameter drivers (defaults):")
    for d in builder.getPropagationParametersDrivers().getDrivers():
        print(f"      {d.getName()} selected={d.isSelected()}")


@dataclass
class FitOutcome:
    label: str
    converged: bool
    error: str | None
    iterations: int
    evaluations: int
    elapsed_s: float
    fitted: TLE | None
    final_pos_rms_m: float | None  # observed-vs-estimated, last iteration
    back_rms_m: float | None  # propagate-back over the full reference grid
    back_max_m: float | None
    seed_bstar: float | None = None
    fitted_bstar: float | None = None


def run_fit(
    ref_teme,
    seed,
    label,
    *,
    fit_bstar,
    duration_s,
    step_s,
    position_scale=POSITION_SCALE_M,
    conv_threshold=CONV_THRESHOLD,
    n_meas=N_MEAS,
    verbose=True,
):
    """One batch-LS fit of `seed` against the TEME reference trajectory."""
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.hipparchus.optim.nonlinear.vector.leastsquares import (
        LevenbergMarquardtOptimizer,
    )
    from org.orekit.estimation.leastsquares import BatchLSEstimator
    from org.orekit.estimation.measurements import ObservableSatellite, PV
    from org.orekit.orbits import PositionAngleType
    from org.orekit.propagation.analytical.tle.generation import (
        FixedPointTleGenerationAlgorithm,
    )
    from org.orekit.propagation.conversion import TLEPropagatorBuilder

    assert ref_teme.frame is Frame.TEME  # PV measurements live in the SGP4 frame

    builder = TLEPropagatorBuilder(
        seed.to_orekit(),
        PositionAngleType.MEAN,
        float(position_scale),
        FixedPointTleGenerationAlgorithm(),
    )
    _describe_builder(builder)

    seed_bstar = float(seed.to_orekit().getBStar())
    for d in builder.getPropagationParametersDrivers().getDrivers():
        if str(d.getName()) == "BSTAR":
            d.setSelected(bool(fit_bstar))

    estimator = BatchLSEstimator(LevenbergMarquardtOptimizer(), builder)
    estimator.setParametersConvergenceThreshold(float(conv_threshold))
    estimator.setMaxIterations(MAX_ITERATIONS)
    estimator.setMaxEvaluations(MAX_EVALUATIONS)
    observer = _observer_class()(verbose)
    estimator.setObserver(observer)

    sat = ObservableSatellite(0)
    idx = np.unique(np.round(np.linspace(0, len(ref_teme) - 1, n_meas)).astype(int))
    for i in idx:
        s = ref_teme[int(i)]
        estimator.addMeasurement(
            PV(
                s.epoch.to_orekit(),
                Vector3D(*[float(x) for x in s.position]),
                Vector3D(*[float(x) for x in s.velocity]),
                SIGMA_POS_M,
                SIGMA_VEL_MS,
                BASE_WEIGHT,
                sat,
            )
        )

    if verbose:
        print(
            f"  {label}: {len(idx)} PV measurements | "
            f"positionScale {position_scale:g} m | "
            f"convergence threshold {conv_threshold:g}"
        )

    t0 = time.perf_counter()
    try:
        propagators = estimator.estimate()
    except Exception as exc:  # noqa: BLE001 -- Java exceptions surface here
        elapsed = time.perf_counter() - t0
        msg = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
        outcome = FitOutcome(
            label=label,
            converged=False,
            error=msg,
            iterations=int(estimator.getIterationsCount()),
            evaluations=int(estimator.getEvaluationsCount()),
            elapsed_s=elapsed,
            fitted=None,
            final_pos_rms_m=observer.history[-1][2] if observer.history else None,
            back_rms_m=None,
            back_max_m=None,
            seed_bstar=seed_bstar,
        )
        print(
            f"  {label}: NOT CONVERGED after "
            f"{outcome.iterations} iterations / {outcome.evaluations} evaluations "
            f"({elapsed:.1f} s)"
        )
        print(f"    error: {msg}")
        return outcome
    elapsed = time.perf_counter() - t0

    fitted_j = propagators[0].getTLE()
    fitted = TLE.from_strings(str(fitted_j.getLine1()), str(fitted_j.getLine2()))
    back_rms, back_max = propagate_back_residual(fitted, ref_teme, duration_s, step_s)
    outcome = FitOutcome(
        label=label,
        converged=True,
        error=None,
        iterations=int(estimator.getIterationsCount()),
        evaluations=int(estimator.getEvaluationsCount()),
        elapsed_s=elapsed,
        fitted=fitted,
        final_pos_rms_m=observer.history[-1][2] if observer.history else None,
        back_rms_m=back_rms,
        back_max_m=back_max,
        seed_bstar=seed_bstar,
        fitted_bstar=float(fitted_j.getBStar()),
    )
    print(
        f"  {label}: converged in {outcome.iterations} iterations / "
        f"{outcome.evaluations} evaluations ({elapsed:.1f} s)"
    )
    print(
        f"    final obs-vs-est pos rms {outcome.final_pos_rms_m:.6g} m | "
        f"propagate-back rms {back_rms:.6g} m | max {back_max:.6g} m"
    )
    print(
        f"    B* seed {seed_bstar:.6e} -> fitted {outcome.fitted_bstar:.6e}"
        f" (held: {outcome.fitted_bstar == seed_bstar})"
    )
    print(f"    fitted L1: {fitted.line1}")
    print(f"    fitted L2: {fitted.line2}")
    return outcome


def propagate_back_residual(fitted, ref_teme, duration_s, step_s):
    """Position residual of the fitted TLE against the FULL reference grid (m)."""
    back = propagate_tle(
        fitted, duration_s, output_step=step_s, start=ref_teme[0].epoch
    )
    assert len(back) == len(ref_teme)
    norms = np.linalg.norm(back.positions - ref_teme.positions, axis=1)
    return float(np.sqrt(np.mean(norms**2))), float(norms.max())


def _wrap_deg(x):
    """Wrap an angle delta to [-180, 180) degrees."""
    return (x + 180.0) % 360.0 - 180.0


def element_delta_report(source, fitted):
    """Fitted-vs-source TLE element deltas (self-fit legs; epochs coincide)."""
    s = source.to_orekit()
    f = fitted.to_orekit()
    rev_day = 86400.0 / (2.0 * math.pi)
    print("    element deltas (fitted - source):")
    rows = [
        ("mean motion (rev/day)", s.getMeanMotion() * rev_day, f.getMeanMotion() * rev_day, False),
        ("eccentricity", s.getE(), f.getE(), False),
        ("inclination (deg)", math.degrees(s.getI()), math.degrees(f.getI()), True),
        ("RAAN (deg)", math.degrees(s.getRaan()), math.degrees(f.getRaan()), True),
        ("arg perigee (deg)", math.degrees(s.getPerigeeArgument()), math.degrees(f.getPerigeeArgument()), True),
        ("mean anomaly (deg)", math.degrees(s.getMeanAnomaly()), math.degrees(f.getMeanAnomaly()), True),
        ("B* (1/Re)", s.getBStar(), f.getBStar(), False),
    ]
    for name, sv, fv, is_angle in rows:
        delta = _wrap_deg(fv - sv) if is_angle else fv - sv
        print(
            f"      {name:22s} source {float(sv):18.9f} | "
            f"fitted {float(fv):18.9f} | delta {float(delta):+.3e}"
        )


def make_seeds(ref_teme, norad_id):
    """The two candidate seeds at the reference start epoch.

    Seed A: TLE.from_state_unfitted (the contract default -- osculating values
    in mean slots). Seed B: Orekit's FixedPointTleGenerationAlgorithm applied
    to the same first sample with seed A as template (fixed-point-refined mean
    elements). Seed B needs an orbit-defined SpacecraftState, so the probe
    wraps the first sample as a CartesianOrbit in TEME with TLEConstants.MU
    (the TLE world's WGS-72 mu, in SI).
    """
    first = ref_teme[0]
    seed_a = TLE.from_state_unfitted(first, norad_id=norad_id)

    seed_b = None
    seed_b_error = None
    try:
        from org.hipparchus.geometry.euclidean.threed import Vector3D
        from org.orekit.orbits import CartesianOrbit
        from org.orekit.propagation import SpacecraftState
        from org.orekit.propagation.analytical.tle import TLEConstants
        from org.orekit.propagation.analytical.tle.generation import (
            FixedPointTleGenerationAlgorithm,
        )
        from org.orekit.utils import PVCoordinates

        orbit = CartesianOrbit(
            PVCoordinates(
                Vector3D(*[float(x) for x in first.position]),
                Vector3D(*[float(x) for x in first.velocity]),
            ),
            Frame.TEME.to_orekit(),
            first.epoch.to_orekit(),
            float(TLEConstants.MU),
        )
        fp = FixedPointTleGenerationAlgorithm().generate(
            SpacecraftState(orbit), seed_a.to_orekit()
        )
        seed_b = TLE.from_strings(str(fp.getLine1()), str(fp.getLine2()))
    except Exception as exc:  # noqa: BLE001
        seed_b_error = str(exc).strip().splitlines()[0] if str(exc).strip() else repr(exc)
    return seed_a, seed_b, seed_b_error


def run_scenario(title, ref_teme, norad_id, duration_s, step_s, compare_source=None):
    """Fit matrix for one scenario: {seed A, seed B} x {BSTAR on, off}."""
    print()
    print("=" * 78)
    print(title)
    print("=" * 78)
    print(
        f"  reference: {len(ref_teme)} samples | {duration_s / 86400.0:g} d "
        f"@ {step_s:g} s | frame {ref_teme.frame.name}"
    )

    seed_a, seed_b, seed_b_error = make_seeds(ref_teme, norad_id)
    print(f"  seed A (from_state_unfitted) L1: {seed_a.line1}")
    print(f"  seed A (from_state_unfitted) L2: {seed_a.line2}")
    if seed_b is not None:
        print(f"  seed B (fixed-point)         L1: {seed_b.line1}")
        print(f"  seed B (fixed-point)         L2: {seed_b.line2}")
    else:
        print(f"  seed B (fixed-point) FAILED to generate: {seed_b_error}")

    outcomes = []
    for seed_name, seed in (("seed A/unfitted", seed_a), ("seed B/fixed-point", seed_b)):
        if seed is None:
            continue
        for fit_bstar in (True, False):
            label = f"{seed_name} | bstar {'on ' if fit_bstar else 'off'}"
            print(f"  --- {label} ---")
            outcome = run_fit(
                ref_teme,
                seed,
                label,
                fit_bstar=fit_bstar,
                duration_s=duration_s,
                step_s=step_s,
            )
            if outcome.converged and compare_source is not None:
                element_delta_report(compare_source, outcome.fitted)
            outcomes.append(outcome)
    return outcomes


def run_sweep(ref_teme, norad_id, duration_s, step_s):
    """positionScale / convergence-threshold sensitivity (self-fit, seed A, B* on)."""
    print()
    print("=" * 78)
    print("SWEEP: positionScale / convergence threshold sensitivity")
    print("(scenario (i) reference, seed A, BSTAR on; quiet observer)")
    print("=" * 78)
    seed_a, _, _ = make_seeds(ref_teme, norad_id)
    outcomes = []
    print(f"  positionScale sweep at threshold {CONV_THRESHOLD:g}:")
    for ps in (1.0, 10.0, 100.0, 1000.0):
        o = run_fit(
            ref_teme,
            seed_a,
            f"positionScale {ps:7g} m",
            fit_bstar=True,
            duration_s=duration_s,
            step_s=step_s,
            position_scale=ps,
            verbose=False,
        )
        outcomes.append(o)
    print(f"  convergence-threshold sweep at positionScale {POSITION_SCALE_M:g} m:")
    for ct in (1.0e-2, 1.0e-3, 1.0e-4):
        o = run_fit(
            ref_teme,
            seed_a,
            f"threshold {ct:8g}",
            fit_bstar=True,
            duration_s=duration_s,
            step_s=step_s,
            conv_threshold=ct,
            verbose=False,
        )
        outcomes.append(o)
    return outcomes


def print_summary(all_outcomes):
    print()
    print("=" * 78)
    print("SUMMARY (all fits)")
    print("=" * 78)
    header = (
        f"  {'label':44s} {'conv':4s} {'iter':>4s} {'eval':>4s} "
        f"{'back rms (m)':>14s} {'back max (m)':>14s} {'time':>6s}"
    )
    print(header)
    for section, outcomes in all_outcomes:
        print(f"  -- {section}")
        for o in outcomes:
            back_rms = f"{o.back_rms_m:.6g}" if o.back_rms_m is not None else "-"
            back_max = f"{o.back_max_m:.6g}" if o.back_max_m is not None else "-"
            print(
                f"  {o.label:44s} {'yes' if o.converged else 'NO ':4s} "
                f"{o.iterations:4d} {o.evaluations:4d} "
                f"{back_rms:>14s} {back_max:>14s} {o.elapsed_s:5.1f}s"
            )


def main():
    t_start = time.time()
    from importlib.metadata import version

    print("TLE-fitting feasibility probe (Feature 1.2, Chunk 0)")
    print(f"run date: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print(
        f"propygator {version('propygator')} | orekit_jpype "
        f"{version('orekit_jpype')} | numpy {np.__version__}"
    )
    print(
        f"constants: N_MEAS={N_MEAS} sigmaPos={SIGMA_POS_M:g} m "
        f"sigmaVel={SIGMA_VEL_MS:g} m/s weight={BASE_WEIGHT:g} "
        f"positionScale={POSITION_SCALE_M:g} m threshold={CONV_THRESHOLD:g} "
        f"maxIter={MAX_ITERATIONS} maxEval={MAX_EVALUATIONS}"
    )

    pgr.init()

    all_outcomes = []

    # --- scenario (i): SGP4 self-fit (known-exact answer) -------------------
    iss = TLE.from_strings(ISS_LINE1, ISS_LINE2, name="ISS (ZARYA)")
    ref_self = propagate_tle(iss, DURATION_S, output_step=SELF_FIT_STEP_S)
    outcomes_i = run_scenario(
        "SCENARIO (i): SGP4 self-fit -- ISS 25544, 2 d @ 60 s (TEME)",
        ref_self,
        iss.norad_id,
        DURATION_S,
        SELF_FIT_STEP_S,
        compare_source=iss,
    )
    all_outcomes.append(("scenario (i) self-fit", outcomes_i))

    # --- scenario (ii): numerical reference ---------------------------------
    print()
    print("building scenario (ii) numerical reference (leo_default + "
          "high_precision, 2 d) ...")
    state0 = ref_self[0].to_frame(Frame.EME2000)
    t0 = time.perf_counter()
    ref_num = propagate_numerical(
        state0,
        DURATION_S,
        output_step=NUMERICAL_STEP_S,
        force_models=ForceModelConfig.leo_default(),
        spacecraft=SpacecraftConfig(),
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    print(f"  numerical reference built in {time.perf_counter() - t0:.1f} s")
    ref_num_teme = ref_num.to_frame(Frame.TEME)
    outcomes_ii = run_scenario(
        "SCENARIO (ii): numerical fit -- leo_default / high_precision, "
        f"2 d @ {NUMERICAL_STEP_S:g} s",
        ref_num_teme,
        iss.norad_id,
        DURATION_S,
        NUMERICAL_STEP_S,
        compare_source=None,  # no exact answer; the RMS is the result
    )
    all_outcomes.append(("scenario (ii) numerical fit", outcomes_ii))

    # --- scenario (iii): Molniya / SDP4 self-fit ----------------------------
    molniya = TLE.from_strings(MOLNIYA_LINE1, MOLNIYA_LINE2, name="MOLNIYA 1-36")
    ref_mol = propagate_tle(molniya, DURATION_S, output_step=SELF_FIT_STEP_S)
    outcomes_iii = run_scenario(
        "SCENARIO (iii): Molniya 08195 SDP4 self-fit -- 2 d @ 60 s (TEME)",
        ref_mol,
        molniya.norad_id,
        DURATION_S,
        SELF_FIT_STEP_S,
        compare_source=molniya,
    )
    all_outcomes.append(("scenario (iii) Molniya/SDP4 self-fit", outcomes_iii))

    # --- sweep ---------------------------------------------------------------
    outcomes_sweep = run_sweep(ref_self, iss.norad_id, DURATION_S, SELF_FIT_STEP_S)
    all_outcomes.append(("sensitivity sweep (self-fit, seed A, bstar on)", outcomes_sweep))

    print_summary(all_outcomes)

    print()
    print("RESIDUAL AVAILABILITY (FitResult-revisit input, Checkpoint A item 3):")
    print("  Per-measurement residuals ARE essentially free: BatchLSObserver")
    print("  receives an EstimationsProvider (observed + estimated values per")
    print("  measurement) and the LS Evaluation (getRMS/getResiduals/getCost)")
    print("  every iteration; this probe's physical position RMS is computed")
    print("  from exactly that data. Iteration count and convergence flag come")
    print("  from the estimator (getIterationsCount / normal-vs-exceptional exit).")

    print()
    print(f"total wall time: {time.time() - t_start:.0f} s")


if __name__ == "__main__":
    main()
