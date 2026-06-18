"""Orekit-crossing tests for attitude provider lowering (build-plan chunk 6).

Exercises ``attitude._to_provider`` — the JVM-touching half of the attitude family
that maps each :data:`AttitudeConfig` to a native Orekit ``AttitudeProvider``.
Every test starts the JVM once via the session-scoped ``orekit`` fixture; the
pure-Python construction/validation/metadata surface is tested separately in
``test_attitude.py`` (which asserts the JVM stays down).

Includes the body->inertial direction check the Chunk-3 ``Orientation.to_orekit``
characterization test deliberately deferred to this chunk (the first real consumer
of ``Orientation.to_orekit``).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from propygator import Epoch, Frame, Orientation, State, TimeScale
from propygator.propagation import (
    CustomAttitude,
    Inertial,
    InPlaneTracking,
    LofAligned,
    LofOffset,
    NadirPointing,
    SunPointing,
)
from propygator.propagation.attitude import _to_provider

# Every test in this module needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")


def _epoch() -> Epoch:
    return Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)


def _orbit(epoch: Epoch):
    """A circular-LEO ``CartesianOrbit`` in EME2000 to drive the providers.

    A ``NumericalPropagator`` hands the attitude provider an ``Orbit`` as the PV
    provider, so the provider tests pass one (not a ``State``-backed
    ``SpacecraftState``).
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.utils import Constants, PVCoordinates

    pv = PVCoordinates(Vector3D(7000.0e3, 0.0, 0.0), Vector3D(0.0, 7.5e3, 0.0))
    return CartesianOrbit(
        pv, Frame.EME2000.to_orekit(), epoch.to_orekit(), Constants.WGS84_EARTH_MU
    )


def _trivial_law(state: State) -> Orientation:  # noqa: ARG001
    return Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)


# --- every mode builds a usable provider ------------------------------------


_MODES = [
    LofAligned(),
    LofOffset(roll_deg=30.0, pitch_deg=10.0, yaw_deg=5.0),
    Inertial(),
    Inertial(roll_deg=15.0),
    SunPointing(phasing_reference="orbit_normal"),
    SunPointing(phasing_reference="velocity"),
    SunPointing(phasing_reference="inertial_z"),
    NadirPointing(),  # "inertial"
    InPlaneTracking(),
    CustomAttitude(_trivial_law),
]


@pytest.mark.parametrize("config", _MODES, ids=lambda c: type(c).__name__)
def test_mode_builds_non_null_provider(config):
    provider = _to_provider(config)
    assert provider is not None
    # The provider must produce a non-null attitude + rotation at a sample state.
    epoch = _epoch()
    att = provider.getAttitude(
        _orbit(epoch), epoch.to_orekit(), Frame.EME2000.to_orekit()
    )
    assert att is not None
    assert att.getRotation() is not None


def test_lof_aligned_matches_zero_offset_lof_offset():
    # LofAligned and LofOffset with zero angles are the same attitude.
    from org.hipparchus.geometry.euclidean.threed import Rotation

    epoch = _epoch()
    orbit = _orbit(epoch)
    date = epoch.to_orekit()
    frame = Frame.EME2000.to_orekit()
    r_aligned = _to_provider(LofAligned()).getAttitude(orbit, date, frame).getRotation()
    r_offset = _to_provider(LofOffset()).getAttitude(orbit, date, frame).getRotation()
    # Rotation.distance is static: the rotation angle between the two (radians).
    assert float(Rotation.distance(r_aligned, r_offset)) == pytest.approx(
        0.0, abs=1e-12
    )


# --- 'ecef' is a validated skeleton -----------------------------------------


def test_nadir_pointing_ecef_lowering_raises():
    # Constructs fine (see test_attitude.py) but lowering is deferred (Tier-B-style).
    with pytest.raises(NotImplementedError, match="ecef"):
        _to_provider(NadirPointing(velocity_reference="ecef"))


# --- CustomAttitude: the body->inertial direction check ---------------------


def test_custom_attitude_law_receives_propygator_state():
    captured: dict[str, object] = {}

    def law(state: State) -> Orientation:
        captured["state"] = state
        return Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)

    epoch = _epoch()
    provider = _to_provider(CustomAttitude(law))
    provider.getAttitude(_orbit(epoch), epoch.to_orekit(), Frame.EME2000.to_orekit())

    state = captured["state"]
    assert isinstance(state, State)
    assert state.frame is Frame.EME2000
    np.testing.assert_allclose(state.position, [7000.0e3, 0.0, 0.0], atol=1e-6)
    np.testing.assert_allclose(state.velocity, [0.0, 7.5e3, 0.0], atol=1e-6)


def test_custom_attitude_provider_body_to_inertial():
    # Pins the body->inertial semantics of a CustomAttitude law end-to-end (the
    # caveat in build-plan chunk 6). The law returns a body->inertial active +90 deg
    # about Z; that rotation carries body +X onto inertial +Y. Orekit's Attitude
    # rotation is reference(inertial)->body (frame-transform), so the inertial-frame
    # components of body +X are recovered with applyInverseTo.
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    ori = Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)
    epoch = _epoch()
    provider = _to_provider(CustomAttitude(lambda s: ori))
    att = provider.getAttitude(
        _orbit(epoch), epoch.to_orekit(), Frame.EME2000.to_orekit()
    )
    r = att.getRotation()

    body_x_in_inertial = r.applyInverseTo(Vector3D(1.0, 0.0, 0.0))
    assert (
        body_x_in_inertial.getX(),
        body_x_in_inertial.getY(),
        body_x_in_inertial.getZ(),
    ) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)

    # And the Attitude reference frame is the requested (propagation) frame.
    assert att.getReferenceFrame().getName() == Frame.EME2000.to_orekit().getName()


def test_inertial_offset_sign_matches_custom_attitude_convention():
    # Pins the Inertial offset sign. A +90 deg yaw offset must be the SAME physical
    # body orientation as a CustomAttitude law returning the equivalent +90 deg-about-Z
    # Orientation; both are referenced to the inertial (propagation) frame, so their
    # Attitude rotations must coincide. Guards against the offset being built with the
    # wrong RotationConvention, which inverts the sign and leaves Inertial opposite-
    # handed to LofOffset / CustomAttitude (a real bug fixed in attitude._to_provider).
    from org.hipparchus.geometry.euclidean.threed import Rotation, Vector3D

    epoch = _epoch()
    orbit = _orbit(epoch)
    date = epoch.to_orekit()
    frame = Frame.EME2000.to_orekit()

    r_inertial = (
        _to_provider(Inertial(yaw_deg=90.0))
        .getAttitude(orbit, date, frame)
        .getRotation()
    )
    ori = Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2)
    r_custom = (
        _to_provider(CustomAttitude(lambda s: ori))
        .getAttitude(orbit, date, frame)
        .getRotation()
    )
    assert float(Rotation.distance(r_inertial, r_custom)) == pytest.approx(
        0.0, abs=1e-12
    )

    # Physical sense (mirrors the CustomAttitude body->inertial test): a +90 deg yaw
    # carries body +X onto inertial +Y.
    body_x_in_inertial = r_inertial.applyInverseTo(Vector3D(1.0, 0.0, 0.0))
    assert (
        body_x_in_inertial.getX(),
        body_x_in_inertial.getY(),
        body_x_in_inertial.getZ(),
    ) == pytest.approx((0.0, 1.0, 0.0), abs=1e-12)
