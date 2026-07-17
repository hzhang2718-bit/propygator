"""Real-world pinned regression: the TLE fitter on measured GNV1B truth.

The study Chunk 4 pin (docs/build-plan-real-world-validation.md; evidence in
``experiments/real-world-validation/gracefo/results_fit_vs_catalog.txt``): the
batch-least-squares fit must converge on a real, non-propygator-generated
trajectory — the pinned GRACE-FO GNV1B day — with post-fit RMS in the SGP4
representation-noise class. Every other fitter test fits propygator-generated
references; this is the one anchored to a measured orbit.

Fixture: the shared solar-active GNV1B day (145 PV samples at 600 s,
``tests/propagation/real_world_gnv1b.py``). The committed Chunk 3 evidence fit
the same day at 60 s cadence (300 measurements) and converged in 16
iterations at 626.9 m RMS; the coarser cadence here is the same arc and the
same expected RMS class.

Tolerance policy (build-plan Chunk 4, binding): measured x generous margin —
the pin proves "the fitter still converges on reality", not the exact RMS.
"""

from __future__ import annotations

import numpy as np
import pytest

from propygator import Epoch, Frame, TimeScale, Trajectory, fit_tle_detailed
from tests.propagation.real_world_gnv1b import (
    STEP_S,
    T0_ISO,
    TRUTH_POS_M,
    TRUTH_VEL_MS,
)

pytestmark = pytest.mark.usefixtures("orekit")

NORAD_ID = 43476
FIT_SPAN_S = 86400.0
# Measured 626.9 m (60 s cadence, results_fit_vs_catalog.txt) — the ~600 m
# SGP4 representation floor for this orbit, x~2.4 margin.
POST_FIT_RMS_BOUND_M = 1500.0
# §1.2: the fitted TLE's epoch is the reference start (TLE-format day-fraction
# quantization allows sub-10-ms slack).
EPOCH_TOLERANCE_S = 0.05


def test_fitter_converges_on_real_gnv1b_truth():
    t0 = Epoch.from_iso(T0_ISO, TimeScale.TAI)
    epochs = [t0.shifted_by(k * STEP_S) for k in range(len(TRUTH_POS_M))]
    reference = Trajectory.from_arrays(
        epochs,
        np.asarray(TRUTH_POS_M),
        np.asarray(TRUTH_VEL_MS),
        Frame.ITRF,
    )

    fit = fit_tle_detailed(
        reference,
        fitting_span=FIT_SPAN_S,
        norad_id=NORAD_ID,
        name="GRACE-FO 1",
        progress=False,
    )

    # Convergence on measured truth (non-convergence raises TLEFitError).
    assert fit.iterations >= 1
    assert fit.rms_m < POST_FIT_RMS_BOUND_M
    # The whole day fed the fit (<= 300-measurement subsampling keeps all 145).
    assert len(fit.residuals_m) == len(TRUTH_POS_M)
    # Identity + epoch policy held on the real-data path.
    assert fit.tle.norad_id == NORAD_ID
    assert abs(fit.tle.epoch.seconds_since(t0)) < EPOCH_TOLERANCE_S
