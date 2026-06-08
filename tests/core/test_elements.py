"""Pure-Python tests for ``KeplerianElements`` (build-plan chunk 5).

Field validation is part of the "safe before init" surface (architecture §10) —
these tests must not start the JVM. The conversion / anomaly methods are deferred
to Feature 1 and assert ``NotImplementedError``.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from propygator import KeplerianElements


def _ke(**overrides) -> KeplerianElements:
    base = dict(
        semi_major_axis_m=7.0e6,
        eccentricity=0.001,
        inclination_rad=0.9,
        raan_rad=0.5,
        arg_perigee_rad=0.4,
        true_anomaly_rad=0.3,
    )
    base.update(overrides)
    return KeplerianElements(**base)


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


def test_valid_construction():
    k = _ke()
    assert k.semi_major_axis_m == 7.0e6
    assert k.eccentricity == 0.001
    assert k.true_anomaly_rad == 0.3


def test_is_frozen():
    k = _ke()
    with pytest.raises(FrozenInstanceError):
        k.eccentricity = 0.5


@pytest.mark.parametrize("a", [0.0, math.nan, math.inf, -math.inf])
def test_rejects_bad_semi_major_axis(a):
    with pytest.raises(ValueError):
        _ke(semi_major_axis_m=a)


@pytest.mark.parametrize("e", [-0.1, math.nan, math.inf])
def test_rejects_bad_eccentricity(e):
    with pytest.raises(ValueError):
        _ke(eccentricity=e)


def test_rejects_elliptical_negative_semi_major_axis():
    # e < 1 with a < 0 is physically inconsistent.
    with pytest.raises(ValueError):
        _ke(semi_major_axis_m=-7.0e6, eccentricity=0.1)


def test_allows_hyperbolic_negative_semi_major_axis():
    # e > 1 legitimately carries a < 0.
    k = _ke(semi_major_axis_m=-7.0e6, eccentricity=1.5)
    assert k.semi_major_axis_m == -7.0e6


@pytest.mark.parametrize("i", [-0.1, math.pi + 0.1, math.nan, math.inf])
def test_rejects_bad_inclination(i):
    with pytest.raises(ValueError):
        _ke(inclination_rad=i)


@pytest.mark.parametrize("field", ["raan_rad", "arg_perigee_rad", "true_anomaly_rad"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_nonfinite_angles(field, bad):
    with pytest.raises(ValueError):
        _ke(**{field: bad})


def test_deferred_methods_raise():
    k = _ke()
    with pytest.raises(NotImplementedError):
        k.mean_anomaly()
    with pytest.raises(NotImplementedError):
        k.eccentric_anomaly()
    with pytest.raises(NotImplementedError):
        k.to_state(None, None)
    with pytest.raises(NotImplementedError):
        KeplerianElements.from_state(None)
