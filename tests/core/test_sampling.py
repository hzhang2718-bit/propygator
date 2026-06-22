"""Pure-Python tests for the shared output-sample grid (Feature 1.3 Chunk 1).

The sampling contract promoted out of ``propagation.numerical`` into
``core.sampling``: the sample-count formula, the pre-flight validation, the cap, and
the on-grid offset list. None of these may start the JVM — they exercise the "safe
before init" surface (architecture §10).
"""

from __future__ import annotations

import math

import pytest

from propygator.core.sampling import (
    _MAX_OUTPUT_SAMPLES,
    _output_offsets,
    _sample_count,
    _validate_sampling,
)

# --- JVM guard -------------------------------------------------------------


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- _sample_count ---------------------------------------------------------


@pytest.mark.parametrize(
    "duration, output_step, expected",
    [
        (600.0, 60.0, 11),  # 10 steps -> 11 samples (endpoints inclusive)
        (650.0, 60.0, 11),  # non-divisible: floor(10.83) + 1
        (86400.0, 60.0, 1441),  # one day at 60 s
        (120.0, 120.0, 2),  # output_step == duration -> 2 samples (n >= 2)
    ],
)
def test_sample_count_formula(duration, output_step, expected):
    assert _sample_count(duration, output_step) == expected


def test_sample_count_divisible_is_deterministic():
    """Exact-multiple cases include the endpoint despite float round-off.

    ``0.3 / 0.1`` is ``2.9999999999999996`` in IEEE-754; without the tolerance the
    floor drops to 2 and the count is a wrong 3. The ``_SAMPLE_COUNT_TOL`` slack
    restores the deterministic 4 (offsets 0.0, 0.1, 0.2, 0.3).
    """
    assert _sample_count(0.3, 0.1) == 4


# --- _validate_sampling: success -------------------------------------------


def test_validate_sampling_returns_sample_count():
    assert _validate_sampling(600.0, 60.0) == _sample_count(600.0, 60.0) == 11


# --- _validate_sampling: pre-flight ValueErrors ----------------------------


@pytest.mark.parametrize("duration", [0.0, -100.0, math.inf, math.nan])
def test_validate_sampling_bad_duration_raises(duration):
    with pytest.raises(ValueError, match="duration must be finite"):
        _validate_sampling(duration, 60.0)


@pytest.mark.parametrize("output_step", [0.0, -60.0, math.inf, math.nan])
def test_validate_sampling_bad_output_step_raises(output_step):
    with pytest.raises(ValueError, match="output_step must be finite"):
        _validate_sampling(600.0, output_step)


def test_validate_sampling_output_step_exceeds_duration_raises():
    with pytest.raises(ValueError, match="output_step must be <= duration"):
        _validate_sampling(60.0, 120.0)


def test_validate_sampling_excessive_count_raises():
    """A tiny output_step over a long duration trips the cap before allocation."""
    with pytest.raises(ValueError, match="output samples"):
        _validate_sampling(1.0e9, 1.0e-3)  # ~1e12 samples


def test_validate_sampling_at_cap_boundary():
    """Exactly the cap is allowed; one sample over it raises."""
    # n = floor(duration/step) + 1; pick duration so n == _MAX_OUTPUT_SAMPLES.
    step = 1.0
    duration = float(_MAX_OUTPUT_SAMPLES - 1)  # -> exactly _MAX_OUTPUT_SAMPLES samples
    assert _validate_sampling(duration, step) == _MAX_OUTPUT_SAMPLES
    with pytest.raises(ValueError, match="output samples"):
        _validate_sampling(duration + step, step)


# --- _output_offsets -------------------------------------------------------


def test_output_offsets_shape_and_values():
    offsets = _output_offsets(5, 60.0)
    assert offsets == [0.0, 60.0, 120.0, 180.0, 240.0]
    assert len(offsets) == 5
    assert offsets[0] == 0.0


def test_output_offsets_matches_k_times_step():
    n, step = 1441, 60.0
    offsets = _output_offsets(n, step)
    assert len(offsets) == n
    assert offsets == [k * step for k in range(n)]
