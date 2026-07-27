"""Real-world pinned regression: the TLE fitter on measured GNV1B truth.

The study Chunk 4 pin (docs/history/build-plan-real-world-validation.md; evidence in
``experiments/real-world-validation/gracefo/results_fit_vs_catalog.txt``): the
batch-least-squares fit must converge on a real, non-propygator-generated
trajectory — the pinned GRACE-FO GNV1B day — with post-fit RMS in the SGP4
representation-noise class. Every other fitter test fits propygator-generated
references; this is the one anchored to a measured orbit.

The Chunk 6 additions (2026-07-18, the ``FitResult`` covariance / ``sigma0``
amendment) pin the B*-observability reads on the same fixture, weak arc
(~1 revolution) vs drag-observable full day — the probe-measured
relationships, not the build plan's a-priori guesses (the plan's
"sigma(B*) ≫ estimate" read was falsified: the fitted B* inflates in step
with its sigma on weak arcs, so only comparative reads discriminate).

The Chunk 7 additions (2026-07-19, the residual-diagnostics amendment) pin
the RIC structure on the full measured day: along-track dominates the signed
decomposition (measured RIC RMS 116.5 / 594.4 / 162.1 m). The short arc is
deliberately *not* structure-pinned — measured there, the dominance inverts
(cross-track leads at 52 m vs 13 m along), a fit-absorption artifact of the
~1-rev arc, not a stable relationship.

Fixture: the shared solar-active GNV1B day (145 PV samples at 600 s,
``tests/propagation/real_world_gnv1b.py``). The committed Chunk 3 evidence fit
the same day at 60 s cadence (300 measurements) and converged in 16
iterations at 626.9 m RMS; the coarser cadence here is the same arc and the
same expected RMS class.

Tolerance policy (build-plan Chunk 4, binding): measured x generous margin —
relationships over absolutes; the pins prove "the wiring didn't regress",
not the exact numbers.
"""

from __future__ import annotations

import numpy as np
import pytest

from propygator import (
    TLE,
    Epoch,
    FitResult,
    Frame,
    TimeScale,
    Trajectory,
    fit_tle_detailed,
)
from tests.propagation.real_world_gnv1b import (
    STEP_S,
    T0_ISO,
    TRUTH_POS_M,
    TRUTH_VEL_MS,
)

pytestmark = pytest.mark.usefixtures("orekit")

NORAD_ID = 43476
FIT_SPAN_S = 86400.0
# ~1 revolution (GRACE-FO period ~94.6 min): the weak-drag arc of the Chunk 6
# probe. 1.7 h puts the *realized* arc (600 s cadence clips the last sample
# to 6000 s) just past one revolution — no sub-revolution warning, B* still
# essentially unobservable.
WEAK_SPAN_S = 1.7 * 3600.0
# Measured 626.9 m (60 s cadence, results_fit_vs_catalog.txt) — the ~600 m
# SGP4 representation floor for this orbit, x~2.4 margin.
POST_FIT_RMS_BOUND_M = 1500.0
# §1.2: the fitted TLE's epoch is the reference start (TLE-format day-fraction
# quantization allows sub-10-ms slack).
EPOCH_TOLERANCE_S = 0.05
# The window-matched Space-Track catalog B* for the active_2023 day
# (results_fit_vs_catalog.txt; the quiet-window catalog sits at 9.85e-6 —
# B* itself is regime-dependent). The "physically plausible B* scale" of the
# amendment's comparative sigma(B*) read.
CATALOG_BSTAR = 1.617e-4


@pytest.fixture(scope="module")
def gnv1b_reference(orekit: None) -> Trajectory:
    t0 = Epoch.from_iso(T0_ISO, TimeScale.TAI)
    epochs = [t0.shifted_by(k * STEP_S) for k in range(len(TRUTH_POS_M))]
    return Trajectory.from_arrays(
        epochs,
        np.asarray(TRUTH_POS_M),
        np.asarray(TRUTH_VEL_MS),
        Frame.ITRF,
    )


@pytest.fixture(scope="module")
def full_day_fit(gnv1b_reference: Trajectory) -> FitResult:
    """The drag-observable fit: the whole pinned day (the Chunk 4 pin)."""
    return fit_tle_detailed(
        gnv1b_reference,
        fitting_span=FIT_SPAN_S,
        norad_id=NORAD_ID,
        name="GRACE-FO 1",
        progress=False,
    )


@pytest.fixture(scope="module")
def short_arc_fit(gnv1b_reference: Trajectory) -> FitResult:
    """The weak-drag fit: the leading ~1 revolution of the same day."""
    return fit_tle_detailed(
        gnv1b_reference,
        fitting_span=WEAK_SPAN_S,
        norad_id=NORAD_ID,
        progress=False,
    )


def test_fitter_converges_on_real_gnv1b_truth(
    gnv1b_reference: Trajectory, full_day_fit: FitResult
) -> None:
    t0 = gnv1b_reference.start_epoch

    # Convergence on measured truth (non-convergence raises TLEFitError).
    assert full_day_fit.iterations >= 1
    assert full_day_fit.rms_m < POST_FIT_RMS_BOUND_M
    # The whole day fed the fit (<= 300-measurement subsampling keeps all 145).
    assert len(full_day_fit.residuals_m) == len(TRUTH_POS_M)
    # Identity + epoch policy held on the real-data path.
    assert full_day_fit.tle.norad_id == NORAD_ID
    assert abs(full_day_fit.tle.epoch.seconds_since(t0)) < EPOCH_TOLERANCE_S


def test_covariance_surface_on_real_data(full_day_fit: FitResult) -> None:
    # Chunk 6: the amendment fields populate on the measured-truth path — the
    # documented Cartesian parameter order, a read-only (7, 7) matrix, and
    # sigma0 far above 1 (real residuals ~600 m against the assumed 1 m
    # measurement sigma; probe measured sigma0 ~373).
    assert full_day_fit.parameter_names == (
        "Px",
        "Py",
        "Pz",
        "Vx",
        "Vy",
        "Vz",
        "BSTAR",
    )
    assert full_day_fit.covariance is not None
    assert full_day_fit.covariance.shape == (7, 7)
    assert not full_day_fit.covariance.flags.writeable
    sigmas = full_day_fit.sigmas
    assert sigmas is not None
    assert np.all(sigmas > 0.0)
    assert full_day_fit.sigma0 > 10.0


def test_raw_sigma_bstar_collapses_with_drag_information(
    short_arc_fit: FitResult, full_day_fit: FitResult
) -> None:
    # Chunk 6 probe relationship: the raw formal sigma(B*) is the
    # drag-information content of the arc — measured 7.6e-5 (~1 rev) vs
    # 6.3e-8 (full day), a ~1200x collapse. Generous x40 margin on the ratio.
    weak_sigmas = short_arc_fit.sigmas
    strong_sigmas = full_day_fit.sigmas
    assert weak_sigmas is not None and strong_sigmas is not None
    weak_sigma_bstar = weak_sigmas[short_arc_fit.parameter_names.index("BSTAR")]
    strong_sigma_bstar = strong_sigmas[full_day_fit.parameter_names.index("BSTAR")]
    assert weak_sigma_bstar > 30.0 * strong_sigma_bstar
    # sigma0 lands far above 1 on the short real arc too (measured ~37).
    assert short_arc_fit.sigma0 > 10.0


def test_scaled_sigma_bstar_vs_catalog_reads_observability(
    short_arc_fit: FitResult, full_day_fit: FitResult
) -> None:
    # The amendment's comparative read, end to end: sigma0-scaled sigma(B*)
    # judged against a physically plausible B* (the window-matched catalog
    # value). Probe: ~17x the catalog on the ~1-rev arc ("this arc cannot
    # distinguish the true B* from zero" -> hold B*), ~0.15x on the full day
    # (B* usable). Note the fitted B* itself CANNOT be the yardstick — it
    # inflates in step with its sigma on weak arcs (the probe finding).
    weak_sigmas = short_arc_fit.sigmas
    strong_sigmas = full_day_fit.sigmas
    assert weak_sigmas is not None and strong_sigmas is not None
    weak_scaled = (
        weak_sigmas[short_arc_fit.parameter_names.index("BSTAR")] * short_arc_fit.sigma0
    )
    strong_scaled = (
        strong_sigmas[full_day_fit.parameter_names.index("BSTAR")] * full_day_fit.sigma0
    )
    assert weak_scaled > 3.0 * CATALOG_BSTAR  # measured ~17x: unconstrained
    assert strong_scaled < 1.5 * CATALOG_BSTAR  # measured ~0.15x: usable


def test_ric_structure_along_track_dominates(full_day_fit: FitResult) -> None:
    # Chunk 7: the residual-structure pin on the pinned measured day. SGP4's
    # representation error on a real drag-perturbed LEO day is dominated by
    # along-track structure (measured RIC RMS 116.5 / 594.4 / 162.1 m —
    # along/radial 5.1x, along/cross 3.7x); pin the dominance relationship at
    # a generous 1.5x, not the absolutes (study tolerance policy).
    ric = full_day_fit.residuals_ric_m
    assert ric.shape == (len(full_day_fit.residuals_m), 3)
    rms = np.sqrt(np.mean(ric**2, axis=0))
    assert rms[1] > 1.5 * rms[0]  # along-track dominates radial
    assert rms[1] > 1.5 * rms[2]  # along-track dominates cross-track
    # Orthonormal-projection consistency on real data: row norms reproduce
    # residuals_m (measured at machine precision; loose tolerance).
    np.testing.assert_allclose(
        np.linalg.norm(ric, axis=1), full_day_fit.residuals_m, rtol=1e-9
    )


def test_velocity_residuals_populate_on_real_data(full_day_fit: FitResult) -> None:
    # Chunk 7: the velocity residual norms on the measured day (measured
    # 0.12-1.26 m/s — the ~627 m position RMS maps to sub-m/s velocity
    # error). Non-degenerate and bounded, generous margin.
    vel = full_day_fit.velocity_residuals_ms
    assert vel.shape == (len(full_day_fit.residuals_m),)
    assert np.all(np.isfinite(vel))
    assert np.all(vel > 0.0)
    assert float(vel.max()) < 15.0  # measured max 1.26 m/s, ~12x margin


def test_held_catalog_bstar_carrier_configuration(
    gnv1b_reference: Trajectory,
) -> None:
    # The contract-sanctioned carrier route (§1.2, reaffirmed at the Chunk 6
    # election over a bstar= kwarg): a pre-computed B* rides in on
    # from_state_unfitted + fit_bstar=False. Doubles as the no-BSTAR-row pin:
    # an unestimated B* has no covariance row.
    first_teme = gnv1b_reference[0].to_frame(Frame.TEME)
    carrier = TLE.from_state_unfitted(
        first_teme, norad_id=NORAD_ID, bstar=CATALOG_BSTAR
    )
    fit = fit_tle_detailed(
        gnv1b_reference,
        fitting_span=FIT_SPAN_S,
        initial_guess=carrier,
        fit_bstar=False,
        progress=False,
    )
    # Held at the carrier's (TLE-quantized) catalog value, bit-exact.
    assert float(fit.tle.to_orekit().getBStar()) == pytest.approx(
        float(carrier.to_orekit().getBStar()), rel=1e-12
    )
    # Converged in the same representation-noise class (Chunk 3: the held-B*
    # fits land in-band).
    assert fit.rms_m < POST_FIT_RMS_BOUND_M
    # The parameter set is the six Cartesian orbital parameters only.
    assert fit.parameter_names == ("Px", "Py", "Pz", "Vx", "Vy", "Vz")
    assert fit.covariance is not None
    assert fit.covariance.shape == (6, 6)
