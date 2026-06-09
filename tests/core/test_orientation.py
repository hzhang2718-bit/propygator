"""Pure-Python tests for ``Orientation`` (build-plan chunk 5).

Construction (quaternion / axis-angle / matrix) and validation are part of the
"safe before init" surface (architecture §10) — these tests must not start the
JVM. ``to_orekit`` is deferred to Feature 1.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import numpy as np
import pytest

from propygator import Orientation

_SQRT_HALF = math.sqrt(0.5)


def _rz(angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    return np.array([[c, -s, 0.0], [s, c, 0.0], [0.0, 0.0, 1.0]], dtype=np.float64)


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- construction / normalization ------------------------------------------


def test_from_quaternion_normalizes():
    o = Orientation.from_quaternion(2.0, 0.0, 0.0, 0.0)
    np.testing.assert_allclose(o.as_quaternion(), [1.0, 0.0, 0.0, 0.0])


def test_sign_canonicalized_to_positive_w():
    o = Orientation.from_quaternion(-1.0, 0.0, 0.0, 0.0)
    np.testing.assert_allclose(o.as_quaternion(), [1.0, 0.0, 0.0, 0.0])


def test_from_axis_angle_z90():
    o = Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)
    np.testing.assert_allclose(o.as_quaternion(), [_SQRT_HALF, 0.0, 0.0, _SQRT_HALF])


def test_from_axis_angle_normalizes_axis():
    o = Orientation.from_axis_angle((0.0, 0.0, 5.0), math.pi / 2)
    np.testing.assert_allclose(o.as_quaternion(), [_SQRT_HALF, 0.0, 0.0, _SQRT_HALF])


def test_from_matrix_identity():
    o = Orientation.from_matrix(np.eye(3))
    np.testing.assert_allclose(o.as_quaternion(), [1.0, 0.0, 0.0, 0.0])


def test_from_matrix_matches_axis_angle():
    o_mat = Orientation.from_matrix(_rz(math.pi / 2))
    o_aa = Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)
    np.testing.assert_allclose(o_mat.as_quaternion(), o_aa.as_quaternion(), atol=1e-12)


def test_from_matrix_roundtrip_several_angles():
    for angle in (0.3, 1.0, 2.0, 3.0):
        o_mat = Orientation.from_matrix(_rz(angle))
        o_aa = Orientation.from_axis_angle((0.0, 0.0, 1.0), angle)
        np.testing.assert_allclose(
            o_mat.as_quaternion(), o_aa.as_quaternion(), atol=1e-12
        )


# --- validation ------------------------------------------------------------


def test_rejects_zero_quaternion():
    with pytest.raises(ValueError):
        Orientation.from_quaternion(0.0, 0.0, 0.0, 0.0)


def test_rejects_nonfinite_quaternion():
    with pytest.raises(ValueError):
        Orientation.from_quaternion(math.nan, 0.0, 0.0, 0.0)


def test_rejects_zero_axis():
    with pytest.raises(ValueError):
        Orientation.from_axis_angle((0.0, 0.0, 0.0), 1.0)


def test_rejects_bad_axis_shape():
    with pytest.raises(ValueError):
        Orientation.from_axis_angle((0.0, 0.0), 1.0)


def test_rejects_nonfinite_angle():
    with pytest.raises(ValueError):
        Orientation.from_axis_angle((0.0, 0.0, 1.0), math.inf)


def test_rejects_bad_matrix_shape():
    with pytest.raises(ValueError):
        Orientation.from_matrix(np.eye(4))


def test_rejects_non_orthonormal_matrix():
    bad = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 2.0]])
    with pytest.raises(ValueError):
        Orientation.from_matrix(bad)


def test_rejects_reflection_matrix():
    # Orthonormal but det = -1 (improper rotation).
    reflection = np.diag([1.0, 1.0, -1.0])
    with pytest.raises(ValueError):
        Orientation.from_matrix(reflection)


# --- accessor / immutability ----------------------------------------------


def test_as_quaternion_returns_independent_copy():
    o = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    q = o.as_quaternion()
    q[0] = 5.0  # writable copy
    assert o.as_quaternion()[0] == 1.0  # original unchanged


def test_is_frozen():
    o = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    with pytest.raises(FrozenInstanceError):
        o._quaternion = np.zeros(4)


def test_stored_quaternion_read_only():
    o = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    with pytest.raises(ValueError):
        o._quaternion[0] = 5.0


def test_to_orekit_deferred():
    o = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    with pytest.raises(NotImplementedError):
        o.to_orekit()


# --- equality / hashing ----------------------------------------------------


def test_equality_by_value():
    a = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    b = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    assert a == b
    assert hash(a) == hash(b)
    # A genuinely different rotation is unequal; a non-Orientation is too (no error).
    assert a != Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)
    assert a != 42


def test_q_and_negq_compare_equal():
    # q and -q denote the same rotation and must canonicalize identically.
    a = Orientation.from_quaternion(0.3, 0.4, 0.5, 0.7)
    b = Orientation.from_quaternion(-0.3, -0.4, -0.5, -0.7)
    assert a == b
    assert hash(a) == hash(b)


def test_q_and_negq_equal_for_180_degree_rotation():
    # w == 0 (180-degree) case: 'w >= 0' alone is ambiguous, so the fix must still
    # canonicalize q and -q to the same array.
    a = Orientation.from_quaternion(0.0, 1.0, 0.0, 0.0)
    b = Orientation.from_quaternion(0.0, -1.0, 0.0, 0.0)
    assert a == b
    assert hash(a) == hash(b)


def test_axis_angle_180_sign_consistent():
    # Rotation by pi about +x and about -x are the same rotation; their stored
    # quaternions must agree on the dominant component sign.
    a = Orientation.from_axis_angle((1.0, 0.0, 0.0), math.pi)
    b = Orientation.from_axis_angle((-1.0, 0.0, 0.0), math.pi)
    # x-component sign must match (the bug stored +1 vs -1).
    assert a.as_quaternion()[1] == pytest.approx(b.as_quaternion()[1], abs=1e-12)


def test_hashable_in_set():
    a = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)
    b = Orientation.from_quaternion(-1.0, 0.0, 0.0, 0.0)  # same rotation as a
    assert len({a, b}) == 1
