"""Pure-Python tests for ``State`` construction + validation (build-plan chunk 4).

Construction and validation are part of the "safe before init" surface
(architecture §10) — these tests must not start the JVM.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from propygator import Epoch, Frame, State, TimeScale


def _epoch() -> Epoch:
    return Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)


def _vec(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=np.float64)


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


def test_valid_state():
    s = State(_epoch(), _vec(7000e3, 0.0, 0.0), _vec(0.0, 7.5e3, 0.0), Frame.EME2000)
    assert s.frame is Frame.EME2000
    assert s.position.shape == (3,)
    assert s.position.dtype == np.float64
    assert s.epoch.scale is TimeScale.UTC


def test_state_is_frozen():
    s = State(_epoch(), _vec(1.0, 2.0, 3.0), _vec(4.0, 5.0, 6.0), Frame.EME2000)
    with pytest.raises(FrozenInstanceError):
        s.frame = Frame.ITRF


@pytest.mark.parametrize(
    "shape",
    [(1, 3), (2,), (3, 1), (4,), (0,)],
)
def test_rejects_wrong_shape(shape):
    bad = np.zeros(shape, dtype=np.float64)
    with pytest.raises(ValueError):
        State(_epoch(), bad, _vec(0.0, 0.0, 0.0), Frame.EME2000)


@pytest.mark.parametrize("dtype", [np.float32, np.int64, np.int32])
def test_rejects_wrong_dtype(dtype):
    bad = np.zeros((3,), dtype=dtype)
    with pytest.raises(ValueError):
        State(_epoch(), bad, _vec(0.0, 0.0, 0.0), Frame.EME2000)


@pytest.mark.parametrize("bad_value", [np.nan, np.inf, -np.inf])
def test_rejects_nonfinite(bad_value):
    bad = _vec(0.0, bad_value, 0.0)
    with pytest.raises(ValueError):
        State(_epoch(), bad, _vec(0.0, 0.0, 0.0), Frame.EME2000)


def test_rejects_non_ndarray():
    with pytest.raises(TypeError):
        State(_epoch(), [1.0, 2.0, 3.0], _vec(0.0, 0.0, 0.0), Frame.EME2000)


def test_deferred_methods_raise():
    s = State(_epoch(), _vec(1.0, 2.0, 3.0), _vec(4.0, 5.0, 6.0), Frame.EME2000)
    with pytest.raises(NotImplementedError):
        s.to_frame(Frame.ITRF)
    with pytest.raises(NotImplementedError):
        s.to_keplerian()
    with pytest.raises(NotImplementedError):
        s.to_orekit()
