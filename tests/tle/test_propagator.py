"""``propagate_tle`` tests (Feature 1.3, build-plan chunk 3).

Covers the headline SGP4/SDP4 verb: the propygator-side pre-flight (argument
``ValueError``s and the shared output-sample cap), the sample-count contract shared
with ``propagate_numerical`` (identical grid for the same ``duration`` /
``output_step``), the native TEME output frame, the SGP4 metadata block, and the
warn-once stale-TLE
notice. Every test starts the JVM once via the session-scoped ``orekit`` fixture, so
``conftest``'s ordering hook schedules this module after the pure-Python
``tests/core/*`` "no JVM started" guards (architecture §11).

Chunk 4 adds the **decay error path** here (a TLE propagated past decay raising
:class:`TLEPropagationError`) and the SGP4/SDP4 implementation-agreement against the
published Vallado vectors in ``test_sgp4_agreement.py``; the ISS end-to-end output run
is Chunk 5 (``test_outputs.py``).
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from propygator import (
    TLE,
    Epoch,
    Frame,
    KeplerianElements,
    PropagationError,
    TimeScale,
    TLEPropagationError,
    propagate_tle,
)
from propygator.propagation import ForceModelConfig, propagate_numerical

# Every test here needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used in tests/core/test_tle.py — epoch
# 2026-06-20T09:57:02 UTC, NORAD 25544, a near-Earth (SGP4) orbit.
ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


def _iss_tle(name: str | None = None) -> TLE:
    return TLE.from_strings(ISS_LINE1, ISS_LINE2, name=name)


def _offsets(traj) -> list[float]:
    """Per-sample seconds offset of ``traj`` from its own first sample."""
    start = traj[0].epoch
    return [traj[i].epoch.seconds_since(start) for i in range(len(traj))]


# --- argument validation (propygator-side, before any Orekit call) ----------


@pytest.mark.parametrize(
    "duration, output_step",
    [
        (0.0, 60.0),  # duration not positive
        (-100.0, 60.0),  # backward / zero span unsupported
        (600.0, 0.0),  # output_step not positive
        (600.0, -60.0),  # negative output_step
        (60.0, 120.0),  # output_step > duration
    ],
)
def test_duration_output_step_validation(duration, output_step):
    with pytest.raises(ValueError):
        propagate_tle(_iss_tle(), duration, output_step=output_step)


def test_excessive_sample_count_raises():
    """A tiny output_step over a long duration trips the shared cap (core/sampling)."""
    with pytest.raises(ValueError, match="output samples"):
        propagate_tle(_iss_tle(), 1.0e9, output_step=1.0e-3)


# --- sample-count contract (shared with propagate_numerical) ----------------


def test_sample_count_and_first_sample_at_start():
    """floor(d/step + tol) + 1 samples, the first exactly at the resolved start."""
    tle = _iss_tle()
    traj = propagate_tle(tle, 600.0, output_step=60.0)
    assert len(traj) == 11
    # Default start is the TLE epoch; the first sample sits exactly there.
    assert traj[0].epoch == tle.epoch
    assert traj[-1].epoch == tle.epoch.shifted_by(600.0)


def test_non_divisible_duration_drops_partial_step():
    traj = propagate_tle(_iss_tle(), 665.0, output_step=60.0)
    # floor(665/60 + tol) + 1 = 12, last at +660 s (strictly inside the span).
    assert len(traj) == 12
    assert _offsets(traj)[-1] == pytest.approx(660.0)


def test_grid_identical_to_propagate_numerical():
    """The two propagators produce an identically-gridded trajectory (same offsets).

    This is the guard against the dependency-rule promotion of the sampling helper
    (core/sampling) drifting between the two call sites (features.md §1.3).
    """
    duration, output_step = 3600.0, 90.0
    tle_traj = propagate_tle(_iss_tle(), duration, output_step=output_step)

    elements = KeplerianElements(
        semi_major_axis_m=6878e3,
        eccentricity=0.001,
        inclination_rad=np.radians(51.6),
        raan_rad=0.0,
        arg_perigee_rad=0.0,
        true_anomaly_rad=0.0,
    )
    initial = elements.to_state(
        Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC), Frame.EME2000
    )
    num_traj = propagate_numerical(
        initial,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
    )

    assert len(tle_traj) == len(num_traj)
    assert _offsets(tle_traj) == pytest.approx(_offsets(num_traj))


# --- output frame -----------------------------------------------------------


def test_output_frame_is_teme():
    """SGP4's native frame; no silent conversion (architecture §10)."""
    traj = propagate_tle(_iss_tle(), 600.0, output_step=60.0)
    assert traj.frame is Frame.TEME


def test_returns_nonzero_states():
    """Sanity: a real ISS propagation yields finite, LEO-scale positions/velocities."""
    traj = propagate_tle(_iss_tle(), 600.0, output_step=60.0)
    r = np.linalg.norm(traj.positions, axis=1)
    v = np.linalg.norm(traj.velocities, axis=1)
    assert np.all(np.isfinite(traj.positions)) and np.all(np.isfinite(traj.velocities))
    # ~6.7e6 m geocentric radius, ~7.6 km/s speed for a 400 km orbit.
    assert np.all((6.5e6 < r) & (r < 7.0e6))
    assert np.all((7.0e3 < v) & (v < 8.0e3))


# --- metadata ---------------------------------------------------------------


def test_metadata_block():
    tle = _iss_tle()
    traj = propagate_tle(tle, 600.0, output_step=60.0)
    md = traj.metadata
    assert md["propagator"] == "sgp4"
    assert md["tle_line1"] == ISS_LINE1
    assert md["tle_line2"] == ISS_LINE2
    assert md["norad_id"] == 25544
    assert isinstance(md["norad_id"], int)
    assert md["output_step_s"] == 60.0
    assert md["propygator_version"] and md["orekit_version"]
    assert md["created_at"]
    # Epoch keys are the UTC instant with no zone suffix (to_iso emits none).
    assert md["tle_epoch"] == tle.epoch.in_scale(TimeScale.UTC).to_iso()
    assert md["tle_epoch"].startswith("2026-06-20T")
    assert md["start"] == tle.epoch.in_scale(TimeScale.UTC).to_iso()
    # No force/integrator/termination keys on an SGP4 run.
    for absent in ("force_models", "integrator", "terminated", "termination_reason"):
        assert absent not in md


def test_start_metadata_forced_to_utc_for_non_utc_start():
    """A TT-scaled start is recorded as the same instant presented in UTC."""
    tle = _iss_tle()
    start_tt = tle.epoch.in_scale(TimeScale.TT)
    traj = propagate_tle(tle, 600.0, output_step=60.0, start=start_tt)
    assert traj.metadata["start"] == start_tt.in_scale(TimeScale.UTC).to_iso()


def test_name_falls_back_to_tle_name():
    traj = propagate_tle(_iss_tle(name=ISS_NAME), 600.0, output_step=60.0)
    assert traj.metadata["name"] == ISS_NAME


def test_explicit_name_wins_over_tle_name():
    traj = propagate_tle(
        _iss_tle(name=ISS_NAME), 600.0, output_step=60.0, name="custom"
    )
    assert traj.metadata["name"] == "custom"


def test_name_absent_when_unnamed_tle_and_no_arg():
    traj = propagate_tle(_iss_tle(name=None), 600.0, output_step=60.0)
    assert "name" not in traj.metadata


# --- stale-TLE warn-once ----------------------------------------------------


def test_stale_tle_warns_past_30_days_forward():
    tle = _iss_tle()
    with pytest.warns(UserWarning, match="from the TLE epoch"):
        # 40 days forward from epoch; large output_step keeps the run cheap.
        propagate_tle(tle, 40.0 * 86400.0, output_step=86400.0)


def test_stale_tle_warns_past_30_days_backward():
    """`start` may precede the epoch; the backward end trips the threshold too."""
    tle = _iss_tle()
    start = tle.epoch.shifted_by(-40.0 * 86400.0)
    with pytest.warns(UserWarning, match="from the TLE epoch"):
        propagate_tle(tle, 3600.0, output_step=600.0, start=start)


def test_no_stale_warning_within_30_days_both_ends():
    """A span straddling the epoch but within 30 days at both ends does not warn."""
    tle = _iss_tle()
    start = tle.epoch.shifted_by(-10.0 * 86400.0)  # 10 days before epoch
    with warnings.catch_warnings(record=True) as record:
        warnings.simplefilter("always")
        propagate_tle(tle, 5.0 * 86400.0, output_step=86400.0, start=start)
    assert not [w for w in record if "from the TLE epoch" in str(w.message)]


# --- decay error path -------------------------------------------------------

# Both Vallado SGP4-VER decay cases (Revisiting Spacetrack Report #3 / AIAA 2006-6753)
# must surface as TLEPropagationError, covering the two distinct ways Orekit's analytic
# model leaves its validity envelope:
#
#   * 20413 (MOLNIYA 1-83) — a 12 h-resonant, highly eccentric (e=0.786) deep-space
#     orbit whose secular terms pump the eccentricity to e=1, where Orekit *raises*
#     (TOO_LARGE_ECCENTRICITY_FOR_PROPAGATION_MODEL). The blow-up occurs at ~4.3 yr on
#     the installed build, so a 6 yr / 1-day span clears it with margin (the analytic
#     SGP4 raises at the first sampled epoch past the limit).
#   * 29141 (SL-14 DEB) — a high-drag LEO (ndot~1.0) that spirals sub-surface within a
#     day; there Orekit does *not* raise but returns a non-finite PV, which
#     propagate_tle's finiteness guard maps to the same TLEPropagationError.
_DECAY_CASES = [
    pytest.param(
        "1 20413U 83020D   05363.79166667  .00000000  00000-0  00000+0 0  7041",
        "2 20413  12.3514 187.4253 7864447 196.3027 356.5478  0.24690082  7978",
        6.0 * 365.25 * 86400.0,
        86400.0,
        id="eccentricity-raise-20413",
    ),
    pytest.param(
        "1 29141U 85108AA  06170.26783845  .99999999  00000-0  13519-0 0   718",
        "2 29141  82.4288 273.4882 0015848 277.2124  83.9133 15.93343074  6828",
        3.0 * 86400.0,
        3600.0,
        id="subsurface-nonfinite-29141",
    ),
]


@pytest.mark.parametrize("line1, line2, duration_s, output_step_s", _DECAY_CASES)
def test_decay_raises_tle_propagation_error(line1, line2, duration_s, output_step_s):
    """A TLE propagated past decay raises a clean ``TLEPropagationError``.

    SGP4 is least reliable precisely as it approaches decay, so 1.3 raises cleanly
    rather than stopping-and-reporting a partial trajectory (features.md §1.3) —
    regardless of whether Orekit signals the decay by raising (out-of-range
    eccentricity) or by returning a non-finite state (sub-surface). Either way the
    error is a ``PropagationError`` subclass (so ``except PropagationError`` catches it
    alongside the numerical propagator's failure), carries only a message string (no
    raw Java trace, architecture §3), and — unlike ``NumericalPropagationError`` —
    exposes **no** ``partial_trajectory`` attribute.
    """
    tle = TLE.from_strings(line1, line2)
    with warnings.catch_warnings():
        # The long span is far past epoch, so the (incidental) stale-TLE warning fires;
        # it is expected and orthogonal to the decay under test, so silence it.
        warnings.simplefilter("ignore")
        with pytest.raises(TLEPropagationError) as excinfo:
            propagate_tle(tle, duration_s, output_step=output_step_s)

    exc = excinfo.value
    # Subclass relationship: a broad `except PropagationError` also catches a decay.
    assert isinstance(exc, PropagationError)
    # A human-readable message, no leaked Java stack trace (architecture §3).
    assert "TLE propagation failed" in str(exc)
    assert "org.orekit" not in str(exc)
    # No stop-and-report: SGP4 never hands back a partial (features.md §1.3).
    assert not hasattr(exc, "partial_trajectory")
