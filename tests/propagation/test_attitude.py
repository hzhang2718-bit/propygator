"""Pure-Python tests for the ``AttitudeConfig`` family (build-plan chunk 6).

Construction, validation, and the ``attitude`` metadata serializer are all on the
"safe before init" surface (architecture §10) — these tests must not start the
JVM. The provider lowering (``_to_provider``, JVM-crossing) is exercised separately
in ``test_attitude_providers.py`` under the ``orekit`` fixture.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from propygator import Frame
from propygator.propagation import (
    AttitudeConfig,
    CustomAttitude,
    Inertial,
    InPlaneTracking,
    LofAligned,
    LofOffset,
    NadirPointing,
    SunPointing,
)
from propygator.propagation.attitude import _serialize_attitude


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- construction defaults --------------------------------------------------


def test_lof_aligned_has_no_params():
    LofAligned()  # constructs


def test_lof_offset_defaults():
    a = LofOffset()
    assert (a.roll_deg, a.pitch_deg, a.yaw_deg) == (0.0, 0.0, 0.0)


def test_inertial_defaults():
    a = Inertial()
    assert a.reference_frame is Frame.EME2000
    assert (a.roll_deg, a.pitch_deg, a.yaw_deg) == (0.0, 0.0, 0.0)


def test_sun_pointing_defaults():
    a = SunPointing()
    assert a.pointing_axis == (0.0, 0.0, 1.0)
    assert a.phasing_axis == (1.0, 0.0, 0.0)
    assert a.phasing_reference == "orbit_normal"


def test_nadir_pointing_defaults():
    assert NadirPointing().velocity_reference == "inertial"


def test_in_plane_tracking_has_no_params():
    InPlaneTracking()  # constructs


def test_custom_attitude_requires_law():
    def law(state):  # noqa: ARG001
        return None

    assert CustomAttitude(law).law is law


def test_frozen():
    a = LofOffset()
    with pytest.raises(FrozenInstanceError):
        a.roll_deg = 5.0  # type: ignore[misc]


# --- validation -------------------------------------------------------------


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -float("inf")])
def test_lof_offset_rejects_non_finite_angle(bad):
    with pytest.raises(ValueError):
        LofOffset(roll_deg=bad)
    with pytest.raises(ValueError):
        LofOffset(pitch_deg=bad)
    with pytest.raises(ValueError):
        LofOffset(yaw_deg=bad)


def test_inertial_accepts_eme2000_and_j2000():
    assert Inertial(reference_frame=Frame.EME2000).reference_frame is Frame.EME2000
    # J2000 is the same enum member as EME2000 (alias), so it is accepted too.
    assert Inertial(reference_frame=Frame.J2000).reference_frame is Frame.EME2000


@pytest.mark.parametrize("frame", [Frame.ITRF, Frame.TEME])
def test_inertial_rejects_non_inertial_frame(frame):
    with pytest.raises(ValueError):
        Inertial(reference_frame=frame)


def test_inertial_rejects_non_finite_angle():
    with pytest.raises(ValueError):
        Inertial(pitch_deg=float("nan"))


def test_sun_pointing_rejects_bad_phasing_reference():
    with pytest.raises(ValueError):
        SunPointing(phasing_reference="nadir")


@pytest.mark.parametrize(
    "point, phase",
    [
        ((0.0, 0.0, 1.0), (0.0, 0.0, 1.0)),  # parallel
        ((0.0, 0.0, 1.0), (0.0, 0.0, -1.0)),  # antiparallel
        ((1.0, 2.0, 3.0), (2.0, 4.0, 6.0)),  # parallel, non-unit
    ],
)
def test_sun_pointing_rejects_parallel_axes(point, phase):
    with pytest.raises(ValueError):
        SunPointing(pointing_axis=point, phasing_axis=phase)


def test_sun_pointing_normalizes_axes_silently():
    a = SunPointing(pointing_axis=(0.0, 0.0, 2.0), phasing_axis=(3.0, 0.0, 0.0))
    assert a.pointing_axis == (0.0, 0.0, 1.0)
    assert a.phasing_axis == (1.0, 0.0, 0.0)


@pytest.mark.parametrize("axis", [(0.0, 0.0, 0.0), (1.0, 0.0), (1.0, 0.0, 0.0, 0.0)])
def test_sun_pointing_rejects_bad_pointing_axis(axis):
    with pytest.raises(ValueError):
        SunPointing(pointing_axis=axis)


def test_nadir_pointing_accepts_ecef():
    # 'ecef' constructs here (pure-Python); it lowers to a working custom
    # TargetProvider in test_attitude_providers.py (addendum §2).
    assert NadirPointing(velocity_reference="ecef").velocity_reference == "ecef"


def test_nadir_pointing_rejects_bad_velocity_reference():
    with pytest.raises(ValueError):
        NadirPointing(velocity_reference="lvlh")


def test_custom_attitude_rejects_non_callable():
    with pytest.raises(ValueError):
        CustomAttitude(law=42)  # type: ignore[arg-type]


# --- metadata strings (byte-exact, features.md §1.1) ------------------------


def _named_law(state):  # noqa: ARG001
    return None


@pytest.mark.parametrize(
    "config, expected",
    [
        (LofAligned(), "lof_aligned:TNW"),
        (LofOffset(roll_deg=90.0), "lof_offset:TNW;roll=90.0,pitch=0.0,yaw=0.0"),
        (Inertial(), "inertial:EME2000;roll=0.0,pitch=0.0,yaw=0.0"),
        (SunPointing(), "sun_pointing:point=(0,0,1),phase=(1,0,0):orbit_normal"),
        (NadirPointing(), "nadir_pointing:vel=inertial"),
        (NadirPointing(velocity_reference="ecef"), "nadir_pointing:vel=ecef"),
        (InPlaneTracking(), "in_plane_tracking"),
        (CustomAttitude(_named_law), "custom:_named_law"),
    ],
)
def test_metadata_strings(config, expected):
    assert _serialize_attitude(config) == expected
    assert config._metadata_string() == expected


def test_lof_offset_metadata_coerces_int_angles_to_float():
    # An int angle still serializes with the trailing .0 (matches features.md).
    assert (
        LofOffset(roll_deg=90)._metadata_string()
        == "lof_offset:TNW;roll=90.0,pitch=0.0,yaw=0.0"
    )


def test_sun_pointing_metadata_uses_normalized_axes():
    a = SunPointing(pointing_axis=(0.0, 0.0, 5.0), phasing_axis=(2.0, 0.0, 0.0))
    assert (
        a._metadata_string() == "sun_pointing:point=(0,0,1),phase=(1,0,0):orbit_normal"
    )


def test_metadata_is_deterministic():
    a = SunPointing(phasing_reference="velocity")
    assert a._metadata_string() == a._metadata_string()


def test_custom_attitude_lambda_metadata():
    assert CustomAttitude(lambda s: None)._metadata_string() == "custom:<lambda>"


# --- union alias ------------------------------------------------------------


@pytest.mark.parametrize(
    "config",
    [
        LofAligned(),
        LofOffset(),
        Inertial(),
        SunPointing(),
        NadirPointing(),
        InPlaneTracking(),
        CustomAttitude(_named_law),
    ],
)
def test_every_mode_is_an_attitude_config(config):
    assert isinstance(config, AttitudeConfig)


def test_unrelated_type_is_not_an_attitude_config():
    assert not isinstance(object(), AttitudeConfig)
    assert not isinstance(math.pi, AttitudeConfig)
