"""Pure-Python tests for ``KeplerianElements`` (build-plan chunk 5).

Field validation is part of the "safe before init" surface (architecture §10) —
these tests must not start the JVM. The conversion / anomaly methods are
Orekit-crossing (Feature 1.1, build-plan chunk 2) and are exercised under the
``orekit`` fixture in tests/test_conversions.py.
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


def test_rejects_parabolic_eccentricity():
    # e == 1 (parabolic) has no finite semi-major axis; rejected regardless of a.
    with pytest.raises(ValueError):
        _ke(eccentricity=1.0)
    with pytest.raises(ValueError):
        _ke(semi_major_axis_m=-7.0e6, eccentricity=1.0)


def test_rejects_hyperbolic_positive_semi_major_axis():
    # e > 1 with a > 0 is physically inconsistent (hyperbola needs a < 0).
    with pytest.raises(ValueError):
        _ke(semi_major_axis_m=7.0e6, eccentricity=1.5)


def test_rejects_hyperbolic_true_anomaly_past_asymptote():
    # For e > 1 the true anomaly must satisfy |ν| < acos(-1/e); beyond the
    # asymptote the orbit has no real point and ν→M/E would silently return NaN.
    limit = math.acos(-1.0 / 1.5)  # ~2.30 rad
    with pytest.raises(ValueError, match="acos"):
        _ke(semi_major_axis_m=-7.0e6, eccentricity=1.5, true_anomaly_rad=limit + 0.1)


def test_allows_hyperbolic_true_anomaly_inside_asymptote():
    limit = math.acos(-1.0 / 1.5)
    k = _ke(semi_major_axis_m=-7.0e6, eccentricity=1.5, true_anomaly_rad=limit - 0.1)
    assert k.eccentricity == 1.5


def test_allows_large_elliptic_true_anomaly():
    # Elliptic ν is unbounded (mod 2π); the asymptote guard must not touch e < 1.
    k = _ke(true_anomaly_rad=3.0)
    assert k.true_anomaly_rad == 3.0


@pytest.mark.parametrize("i", [-0.1, math.pi + 0.1, math.nan, math.inf])
def test_rejects_bad_inclination(i):
    with pytest.raises(ValueError):
        _ke(inclination_rad=i)


@pytest.mark.parametrize("field", ["raan_rad", "arg_perigee_rad", "true_anomaly_rad"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_nonfinite_angles(field, bad):
    with pytest.raises(ValueError):
        _ke(**{field: bad})


# mean_anomaly / eccentric_anomaly / to_state / from_state are Orekit-crossing
# (Feature 1.1, build-plan chunk 2); they start the JVM, so they are exercised
# under the ``orekit`` fixture in tests/test_conversions.py.
