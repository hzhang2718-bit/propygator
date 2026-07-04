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

from propygator import Epoch, Frame, KeplerianElements, Orientation, State, TimeScale
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


def _orbit_at_true_anomaly(epoch: Epoch, *, true_anomaly_deg: float):
    """A 500 km / 51.6 deg circular EME2000 ``CartesianOrbit`` at a true anomaly.

    With ``raan = arg_perigee = 0``, true anomaly 0 is the equatorial ascending node
    (where the Earth-rotation yaw peaks) and 90 deg is the max-latitude apex (where it
    vanishes) — the two addendum §2.4 yaw anchors.
    """
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.utils import Constants

    elements = KeplerianElements(
        semi_major_axis_m=6878.0e3,
        eccentricity=0.0,
        inclination_rad=math.radians(51.6),
        raan_rad=0.0,
        arg_perigee_rad=0.0,
        true_anomaly_rad=math.radians(true_anomaly_deg),
    )
    state = elements.to_state(epoch, Frame.EME2000)
    return CartesianOrbit(
        state.to_orekit().getPVCoordinates(),
        Frame.EME2000.to_orekit(),
        epoch.to_orekit(),
        Constants.WGS84_EARTH_MU,
    )


def _body_axis_in_inertial(provider, orbit, epoch, axis):  # noqa: ANN001, ANN202
    """The inertial-frame direction of a body ``axis`` under ``provider`` at ``orbit``.

    Orekit's ``Attitude`` rotation is reference(inertial)->body, so a body axis is
    recovered in inertial components with ``applyInverseTo`` (the same convention the
    ``CustomAttitude`` body->inertial tests pin).
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    rotation = provider.getAttitude(
        orbit, epoch.to_orekit(), Frame.EME2000.to_orekit()
    ).getRotation()
    return rotation.applyInverseTo(Vector3D(*axis))


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
    InPlaneTracking(velocity_reference="ecef"),
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


# --- 'ecef' lowers to a working provider (addendum chunk 1) -----------------


def test_nadir_pointing_ecef_lowers_to_provider():
    # The ECEF velocity-reference deferral is closed (addendum §2.3): lowering now
    # yields a working provider that produces a non-null attitude. The yaw-vs-inertial
    # and convention assertions are the chunk-2 verification tests.
    provider = _to_provider(NadirPointing(velocity_reference="ecef"))
    assert provider is not None
    epoch = _epoch()
    att = provider.getAttitude(
        _orbit(epoch), epoch.to_orekit(), Frame.EME2000.to_orekit()
    )
    assert att is not None
    assert att.getRotation() is not None


def test_nadir_ecef_yaws_off_inertial_by_earth_rotation():
    """ecef vs inertial ``NadirPointing`` differ by a pure nadir-axis yaw — the
    ``ω⊕ × r`` Earth-rotation term (addendum §2.4).

    The yaw peaks near the equator (~3.08 deg for a 500 km / 51.6 deg orbit, the
    hand-checked anchor) and vanishes at the max-latitude turning point, while body
    -Z stays exactly on nadir for both modes — so the two share the primary target
    (nadir) and differ only in the secondary (velocity) direction. This pins that the
    custom ECEF target provider yaws by exactly the Earth-rotation term, nothing more.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    epoch = _epoch()
    ecef = _to_provider(NadirPointing(velocity_reference="ecef"))
    inertial = _to_provider(NadirPointing(velocity_reference="inertial"))

    def yaw_deg(true_anomaly_deg: float) -> float:
        orbit = _orbit_at_true_anomaly(epoch, true_anomaly_deg=true_anomaly_deg)
        py_ecef = _body_axis_in_inertial(ecef, orbit, epoch, (0.0, 1.0, 0.0))
        py_inertial = _body_axis_in_inertial(inertial, orbit, epoch, (0.0, 1.0, 0.0))
        mz_ecef = _body_axis_in_inertial(ecef, orbit, epoch, (0.0, 0.0, -1.0))
        mz_inertial = _body_axis_in_inertial(inertial, orbit, epoch, (0.0, 0.0, -1.0))
        # Both hold -Z on nadir: the only difference is yaw about the nadir axis.
        assert math.degrees(Vector3D.angle(mz_ecef, mz_inertial)) < 1e-6
        return math.degrees(Vector3D.angle(py_ecef, py_inertial))

    # Equatorial ascending node: yaw peaks at the hand-checked ~3.08 deg.
    assert yaw_deg(0.0) == pytest.approx(3.08, abs=0.05)
    # Max-latitude apex: the Earth-rotation yaw vanishes.
    assert yaw_deg(90.0) < 0.1


# --- InPlaneTracking 'ecef': the primary-slot swap (general-upgrades-1.md) --

_OMEGA_EARTH = 7.292115e-5  # rad/s, for the independent hardcoded-wind anchor


def test_in_plane_tracking_ecef_lowers_to_provider():
    # The custom ECEF TargetProvider's first *primary*-slot consumer (the nadir
    # addendum only ever exercised the secondary slot); lowering yields a working
    # provider. The axis geometry is pinned by the construction test below, and
    # the real-propagate() de-risk lives in test_numerical.py.
    provider = _to_provider(InPlaneTracking(velocity_reference="ecef"))
    assert provider is not None
    epoch = _epoch()
    att = provider.getAttitude(
        _orbit(epoch), epoch.to_orekit(), Frame.EME2000.to_orekit()
    )
    assert att is not None
    assert att.getRotation() is not None


def test_in_plane_tracking_ecef_axis_construction():
    """ecef ``InPlaneTracking`` realizes the contract's axis construction exactly
    (general-upgrades-1.md "ECEF InPlaneTracking"): body +Y lands *exactly* on the
    Earth-relative wind (the primary), +Z sits off the orbit normal by exactly the
    out-of-plane wind angle ``asin(|h_hat . v_rel_hat|)`` (the best-effort
    secondary), and the +Y split vs the ``inertial`` mode equals ``angle(v, v_rel)``
    — peaking at the equatorial node at the same hand-checked ~3.08 deg anchor as
    the nadir-ecef yaw test (it is the same ``ω⊕ × r`` term) and vanishing at the
    max-latitude apex, where the wind is along-track.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    epoch = _epoch()
    date = epoch.to_orekit()
    eme = Frame.EME2000.to_orekit()
    itrf = Frame.ITRF.to_orekit()
    ecef = _to_provider(InPlaneTracking(velocity_reference="ecef"))
    inertial = _to_provider(InPlaneTracking())

    def check(true_anomaly_deg: float) -> tuple[float, float]:
        orbit = _orbit_at_true_anomaly(epoch, true_anomaly_deg=true_anomaly_deg)
        pv = orbit.getPVCoordinates()
        # The reference wind, read off the EME2000->ITRF transform (the same
        # physics the provider implements — here exercised end-to-end through
        # AlignedAndConstrained's *primary* slot).
        to_itrf = eme.getTransformTo(itrf, date)
        v_rel = to_itrf.getRotation().applyInverseTo(
            to_itrf.transformPVCoordinates(pv).getVelocity()
        )
        # Independent anchor: the hardcoded-omega wind v - ω⊕×r about EME2000 +Z
        # agrees to the ~0.3 deg pole-offset scale (catches a wrong transform).
        r, v = pv.getPosition(), pv.getVelocity()
        v_rel_hardcoded = Vector3D(
            v.getX() + _OMEGA_EARTH * r.getY(),
            v.getY() - _OMEGA_EARTH * r.getX(),
            v.getZ(),
        )
        assert math.degrees(Vector3D.angle(v_rel, v_rel_hardcoded)) < 0.05

        h_hat = pv.getMomentum().normalize()
        y_ecef = _body_axis_in_inertial(ecef, orbit, epoch, (0.0, 1.0, 0.0))
        z_ecef = _body_axis_in_inertial(ecef, orbit, epoch, (0.0, 0.0, 1.0))
        y_inertial = _body_axis_in_inertial(inertial, orbit, epoch, (0.0, 1.0, 0.0))

        # Primary exact: +Y on the unit wind.
        assert math.degrees(Vector3D.angle(y_ecef, v_rel)) < 1e-6
        # Secondary best-effort: +Z off h_hat by exactly the out-of-plane wind
        # angle (the contract's residual formula).
        predicted_tilt = math.degrees(
            math.asin(abs(float(Vector3D.dotProduct(h_hat, v_rel.normalize()))))
        )
        actual_tilt = math.degrees(Vector3D.angle(z_ecef, h_hat))
        assert actual_tilt == pytest.approx(predicted_tilt, abs=1e-6)
        # The ecef-vs-inertial +Y split is exactly the wind offset angle.
        split = math.degrees(Vector3D.angle(y_ecef, y_inertial))
        assert split == pytest.approx(math.degrees(Vector3D.angle(v, v_rel)), abs=1e-6)
        return split, actual_tilt

    # Equatorial ascending node: wind offset and +Z tilt both peak at ~3.08 deg
    # (at the node the wind's velocity-perpendicular component is entirely
    # out-of-plane, so the two angles coincide).
    split_node, tilt_node = check(0.0)
    assert split_node == pytest.approx(3.08, abs=0.05)
    assert tilt_node == pytest.approx(3.08, abs=0.05)
    # Max-latitude apex: the wind is along-track; both vanish (+Z back on h_hat).
    split_apex, tilt_apex = check(90.0)
    assert split_apex < 0.1
    assert tilt_apex < 0.1


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
