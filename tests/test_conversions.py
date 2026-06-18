"""Orekit-crossing conversion tests (Feature 1.1, build-plan chunk 1+).

The first JVM-touching tests outside ``test_stack_compat``: they exercise the
data-model conversions that resolve propygator types to Orekit objects
(``Frame.to_orekit``, the ``core.bodies`` accessors, ``State.to_orekit``). Unlike
the pure-Python ``tests/core/*`` suite (which asserts the JVM stays *down*), every
test here starts the JVM once via the session-scoped ``orekit`` fixture.

Later Chunk-1.1 chunks (state<->Keplerian, frame conversions, geodetic) append to
this module under the same fixture.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from propygator import (
    Epoch,
    Frame,
    KeplerianElements,
    Orientation,
    State,
    TimeScale,
    Trajectory,
)
from propygator.core.bodies import _earth, _moon, _sun
from propygator.core.frames import geodetic_track, to_geodetic

# Every test in this module needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")


def _epoch() -> Epoch:
    return Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC)


# --- Frame.to_orekit() ------------------------------------------------------


def test_frame_to_orekit_resolves_each_member():
    """Each Frame resolves to the matching FramesFactory frame (by name)."""
    from org.orekit.frames import FramesFactory
    from org.orekit.utils import IERSConventions

    assert Frame.EME2000.to_orekit().getName() == FramesFactory.getEME2000().getName()
    assert Frame.TEME.to_orekit().getName() == FramesFactory.getTEME().getName()
    assert (
        Frame.ITRF.to_orekit().getName()
        == FramesFactory.getITRF(IERSConventions.IERS_2010, True).getName()
    )


def test_frame_to_orekit_members_are_distinct():
    names = {f.to_orekit().getName() for f in Frame}
    assert len(names) == 3  # EME2000, ITRF, TEME all distinct


def test_j2000_alias_resolves_like_eme2000():
    # Frame.J2000 is the same enum member as EME2000, so it resolves identically.
    assert Frame.J2000.to_orekit().getName() == Frame.EME2000.to_orekit().getName()


# --- core.bodies accessors --------------------------------------------------


def test_earth_is_wgs84_ellipsoid_in_itrf():
    from org.orekit.utils import Constants

    earth = _earth()
    assert earth.getEquatorialRadius() == pytest.approx(
        Constants.WGS84_EARTH_EQUATORIAL_RADIUS
    )
    assert earth.getFlattening() == pytest.approx(Constants.WGS84_EARTH_FLATTENING)
    # Body shape is expressed in the Earth-fixed ITRF frame.
    assert earth.getBodyFrame().getName() == Frame.ITRF.to_orekit().getName()


def test_sun_and_moon_construct():
    assert _sun().getName() == "Sun"
    assert _moon().getName() == "Moon"


# --- State.to_orekit() ------------------------------------------------------


@pytest.mark.parametrize("frame", list(Frame))
def test_state_to_orekit_round_trips_pv(frame):
    """position/velocity round-trip through the SpacecraftState to machine precision."""
    pos = np.array([7000e3, 1234.5, -42.0], dtype=np.float64)
    vel = np.array([-1.0, 7.5e3, 0.25], dtype=np.float64)
    state = State(_epoch(), pos, vel, frame)

    ss = state.to_orekit()
    p = ss.getPosition()
    v = ss.getVelocity()
    pos_back = np.array([p.getX(), p.getY(), p.getZ()])
    vel_back = np.array([v.getX(), v.getY(), v.getZ()])

    np.testing.assert_array_equal(pos_back, pos)
    np.testing.assert_array_equal(vel_back, vel)


def test_state_to_orekit_carries_frame_and_no_orbit():
    state = State(
        _epoch(),
        np.array([7000e3, 0.0, 0.0], dtype=np.float64),
        np.array([0.0, 7.5e3, 0.0], dtype=np.float64),
        Frame.EME2000,
    )
    ss = state.to_orekit()
    # Built from AbsolutePVCoordinates: frame-agnostic, no mu/orbit attached.
    assert ss.getFrame().getName() == Frame.EME2000.to_orekit().getName()
    assert ss.isOrbitDefined() is False


def test_state_to_orekit_epoch_matches():
    epoch = _epoch()
    state = State(
        epoch,
        np.array([7000e3, 0.0, 0.0], dtype=np.float64),
        np.array([0.0, 7.5e3, 0.0], dtype=np.float64),
        Frame.EME2000,
    )
    ss = state.to_orekit()
    # The SpacecraftState date equals the Epoch's AbsoluteDate (sub-ns envelope).
    assert abs(ss.getDate().durationFrom(epoch.to_orekit())) < 1e-9


# --- shared fixtures for the conversion math --------------------------------


def _leo_state(frame: Frame = Frame.EME2000) -> State:
    """A bound, mildly elliptical, inclined LEO state — well away from the
    near-circular / near-equatorial singularities (architecture §6)."""
    pos = np.array([7000e3, 0.0, 0.0], dtype=np.float64)
    vel = np.array([0.0, 6.0e3, 4.5e3], dtype=np.float64)
    return State(_epoch(), pos, vel, frame)


# Vallado, *Fundamentals of Astrodynamics and Applications*, Example 2-6
# (RV -> COE). Position/velocity in km, km/s; expected classical elements below.
_VALLADO_R = np.array([6524.834e3, 6862.875e3, 6448.296e3], dtype=np.float64)
_VALLADO_V = np.array([4.901327e3, 5.533756e3, -1.976341e3], dtype=np.float64)


# --- State.to_frame() -------------------------------------------------------


def test_to_frame_same_frame_returns_fresh_equal_copy():
    state = _leo_state(Frame.EME2000)
    out = state.to_frame(Frame.EME2000)
    assert out == state
    assert out is not state
    # Fresh, read-only arrays — no aliasing of the source state's memory.
    assert out.position is not state.position
    assert not out.position.flags.writeable
    assert not out.velocity.flags.writeable


def test_to_frame_round_trip_is_identity():
    state = _leo_state(Frame.EME2000)
    back = state.to_frame(Frame.ITRF).to_frame(Frame.EME2000)
    np.testing.assert_allclose(back.position, state.position, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(back.velocity, state.velocity, rtol=0.0, atol=1e-9)
    assert back.frame is Frame.EME2000
    assert back.epoch == state.epoch


def test_to_frame_rotates_position_but_preserves_radius():
    # EME2000 and ITRF differ by the Earth-rotation transform, so the position
    # components must change, while the geocentric radius is rotation-invariant.
    state = _leo_state(Frame.EME2000)
    itrf = state.to_frame(Frame.ITRF)
    assert itrf.frame is Frame.ITRF
    assert not np.allclose(itrf.position, state.position)
    assert float(np.linalg.norm(itrf.position)) == pytest.approx(
        float(np.linalg.norm(state.position)), rel=1e-9
    )


# --- State <-> KeplerianElements --------------------------------------------


def test_state_keplerian_round_trip():
    state = _leo_state(Frame.EME2000)
    back = state.to_keplerian().to_state(state.epoch, state.frame)
    np.testing.assert_allclose(back.position, state.position, rtol=1e-9, atol=1e-6)
    np.testing.assert_allclose(back.velocity, state.velocity, rtol=1e-9, atol=1e-9)
    assert back.frame is state.frame
    assert back.epoch == state.epoch


def test_from_state_matches_to_keplerian():
    state = _leo_state(Frame.EME2000)
    assert KeplerianElements.from_state(state) == state.to_keplerian()


def test_to_keplerian_matches_vallado_example_2_6():
    state = State(_epoch(), _VALLADO_R, _VALLADO_V, Frame.EME2000)
    k = state.to_keplerian()
    assert k.semi_major_axis_m == pytest.approx(36127.343e3, rel=1e-4)
    assert k.eccentricity == pytest.approx(0.832853, abs=1e-5)
    assert math.degrees(k.inclination_rad) == pytest.approx(87.870, abs=1e-2)
    assert math.degrees(k.raan_rad) % 360.0 == pytest.approx(227.898, abs=1e-2)
    assert math.degrees(k.arg_perigee_rad) % 360.0 == pytest.approx(53.38, abs=1e-2)
    assert math.degrees(k.true_anomaly_rad) % 360.0 == pytest.approx(92.335, abs=1e-2)


def test_to_keplerian_rejects_non_inertial_frame():
    # ITRF is rotating (not pseudo-inertial); classical elements are undefined
    # there, so to_keplerian raises a clean ValueError rather than leaking a raw
    # Orekit exception (mirrors to_geodetic's strict-frame guard).
    itrf_state = _leo_state(Frame.EME2000).to_frame(Frame.ITRF)
    with pytest.raises(ValueError, match="pseudo-inertial"):
        itrf_state.to_keplerian()


def test_to_keplerian_allows_teme():
    # TEME is pseudo-inertial, so it is accepted (TLE-derived elements live there).
    k = State(_epoch(), _VALLADO_R, _VALLADO_V, Frame.TEME).to_keplerian()
    assert k.semi_major_axis_m > 0.0


def test_to_state_rejects_non_inertial_frame():
    k = KeplerianElements(7.0e6, 0.01, 0.9, 0.2, 0.3, 0.5)
    with pytest.raises(ValueError, match="pseudo-inertial"):
        k.to_state(_epoch(), Frame.ITRF)


# --- mean / eccentric anomaly -----------------------------------------------


def _orekit_keplerian_orbit(k: KeplerianElements):
    """Build the matching Orekit KeplerianOrbit for cross-checking anomalies.

    Note Orekit's constructor takes the perigee argument *before* the RAAN."""
    from org.orekit.orbits import KeplerianOrbit, PositionAngleType
    from org.orekit.utils import Constants

    return KeplerianOrbit(
        k.semi_major_axis_m,
        k.eccentricity,
        k.inclination_rad,
        k.arg_perigee_rad,
        k.raan_rad,
        k.true_anomaly_rad,
        PositionAngleType.TRUE,
        Frame.EME2000.to_orekit(),
        _epoch().to_orekit(),
        Constants.WGS84_EARTH_MU,
    )


def test_anomalies_match_orekit_elliptic():
    k = KeplerianElements(7.0e6, 0.2, 0.9, 0.5, 0.4, 1.1)
    orbit = _orekit_keplerian_orbit(k)
    assert k.mean_anomaly() == pytest.approx(orbit.getMeanAnomaly(), abs=1e-12)
    assert k.eccentric_anomaly() == pytest.approx(
        orbit.getEccentricAnomaly(), abs=1e-12
    )


def test_anomalies_match_orekit_hyperbolic():
    # e > 1 requires a < 0; true anomaly inside the asymptote limit acos(-1/e).
    k = KeplerianElements(-7.0e6, 1.5, 0.5, 0.3, 0.2, 0.4)
    orbit = _orekit_keplerian_orbit(k)
    assert k.mean_anomaly() == pytest.approx(orbit.getMeanAnomaly(), abs=1e-12)
    assert k.eccentric_anomaly() == pytest.approx(
        orbit.getEccentricAnomaly(), abs=1e-12
    )


def test_anomalies_circular_orbit_equal_true_anomaly():
    # e = 0: M = E = nu exactly.
    k = KeplerianElements(7.0e6, 0.0, 0.5, 0.0, 0.0, 0.7)
    assert k.mean_anomaly() == pytest.approx(0.7, abs=1e-12)
    assert k.eccentric_anomaly() == pytest.approx(0.7, abs=1e-12)


def test_anomalies_zero_at_perigee():
    k = KeplerianElements(7.0e6, 0.2, 0.5, 0.0, 0.0, 0.0)
    assert k.mean_anomaly() == pytest.approx(0.0, abs=1e-12)
    assert k.eccentric_anomaly() == pytest.approx(0.0, abs=1e-12)


# --- Trajectory fixtures (a real two-body trajectory) -----------------------

_TRAJ_STEP = 60.0  # seconds between samples
_TRAJ_N = 8  # sample count


def _keplerian_propagator():
    """Orekit analytic two-body propagator for a fixed inclined LEO orbit (EME2000).

    Mildly eccentric/inclined so positions genuinely vary with time and stay away
    from the near-circular / near-equatorial singularities (architecture §6)."""
    from org.orekit.orbits import KeplerianOrbit, PositionAngleType
    from org.orekit.propagation.analytical import KeplerianPropagator
    from org.orekit.utils import Constants

    orbit = KeplerianOrbit(
        7.0e6,
        0.01,
        0.9,
        0.2,
        0.3,
        0.5,
        PositionAngleType.TRUE,
        Frame.EME2000.to_orekit(),
        _epoch().to_orekit(),
        Constants.WGS84_EARTH_MU,
    )
    return KeplerianPropagator(orbit)


def _truth_state(epoch: Epoch) -> State:
    """Two-body truth state at ``epoch`` (EME2000), via the analytic propagator."""
    ss = _keplerian_propagator().propagate(epoch.to_orekit())
    p = ss.getPosition()
    v = ss.getVelocity()
    return State(
        epoch,
        np.array([p.getX(), p.getY(), p.getZ()], dtype=np.float64),
        np.array([v.getX(), v.getY(), v.getZ()], dtype=np.float64),
        Frame.EME2000,
    )


def _leo_trajectory() -> Trajectory:
    base = _epoch()
    states = [_truth_state(base.shifted_by(_TRAJ_STEP * i)) for i in range(_TRAJ_N)]
    return Trajectory.from_states(states)


# --- Trajectory.to_frame() --------------------------------------------------


def test_trajectory_to_frame_same_frame_fresh_copy():
    traj = _leo_trajectory()
    out = traj.to_frame(Frame.EME2000)
    assert out is not traj
    assert out.frame is Frame.EME2000
    # Fresh, read-only position/velocity arrays — no aliasing of the source.
    assert out.positions is not traj.positions
    assert out.velocities is not traj.velocities
    assert not out.positions.flags.writeable
    assert not out.velocities.flags.writeable
    np.testing.assert_array_equal(out.positions, traj.positions)
    np.testing.assert_array_equal(out.velocities, traj.velocities)
    # Metadata is shallow-copied, not shared.
    assert out.metadata is not traj.metadata
    assert out.metadata == traj.metadata


def test_trajectory_to_frame_round_trip_is_identity():
    traj = _leo_trajectory()
    back = traj.to_frame(Frame.ITRF).to_frame(Frame.EME2000)
    np.testing.assert_allclose(back.positions, traj.positions, rtol=0.0, atol=1e-6)
    np.testing.assert_allclose(back.velocities, traj.velocities, rtol=0.0, atol=1e-9)
    assert back.frame is Frame.EME2000
    assert len(back) == len(traj)
    # Epoch arrays are frame-independent and carry over unchanged.
    np.testing.assert_array_equal(back._epochs_int, traj._epochs_int)
    np.testing.assert_array_equal(back._epochs_frac, traj._epochs_frac)


def test_trajectory_to_frame_rotates_each_sample_preserving_radius():
    traj = _leo_trajectory()
    itrf = traj.to_frame(Frame.ITRF)
    assert itrf.frame is Frame.ITRF
    assert not itrf.positions.flags.writeable
    # Earth rotation moves every sample's position components...
    assert not np.allclose(itrf.positions, traj.positions)
    # ...but the per-sample geocentric radius is rotation-invariant.
    r_eme = np.linalg.norm(traj.positions, axis=1)
    r_itrf = np.linalg.norm(itrf.positions, axis=1)
    np.testing.assert_allclose(r_itrf, r_eme, rtol=1e-9)


# --- Trajectory.at() --------------------------------------------------------


def test_trajectory_at_exact_at_sample_nodes():
    traj = _leo_trajectory()
    for i in (0, 3, len(traj) - 1):
        s = traj.at(traj[i].epoch)
        np.testing.assert_allclose(s.position, traj[i].position, rtol=0.0, atol=1e-6)
        np.testing.assert_allclose(s.velocity, traj[i].velocity, rtol=0.0, atol=1e-9)
        assert s.frame is traj.frame


def test_trajectory_at_hermite_between_samples():
    traj = _leo_trajectory()
    k = 3
    mid = _epoch().shifted_by(_TRAJ_STEP * k + _TRAJ_STEP / 2)
    s = traj.at(mid)
    truth = _truth_state(mid)
    hermite_err = float(np.linalg.norm(s.position - truth.position))

    # Cubic Hermite on (p, v) with the USE_PV filter (see _ephemeris): sub-meter at
    # this 60 s LEO cadence. It must comfortably beat naive linear interpolation
    # between the bracketing nodes (the point of Hermite), and the absolute bound is
    # tight enough to catch a regression to the constructor-default USE_PVA filter,
    # whose fabricated zero-acceleration nodes balloon this error to ~900 m.
    linear = 0.5 * (traj[k].position + traj[k + 1].position)
    linear_err = float(np.linalg.norm(linear - truth.position))
    assert hermite_err < linear_err
    assert hermite_err < 50.0
    assert s.frame is Frame.EME2000
    assert s.epoch == mid


def test_trajectory_at_out_of_bounds_raises():
    traj = _leo_trajectory()
    base = _epoch()
    with pytest.raises(ValueError, match="outside the trajectory span"):
        traj.at(base.shifted_by(-1.0))
    with pytest.raises(ValueError, match="outside the trajectory span"):
        traj.at(base.shifted_by(_TRAJ_STEP * _TRAJ_N + 1.0))


def test_trajectory_at_caches_ephemeris():
    traj = _leo_trajectory()
    assert getattr(traj, "_ephemeris_cache", None) is None
    traj.at(traj[2].epoch)
    cached = traj._ephemeris_cache
    assert cached is not None
    traj.at(traj[5].epoch)
    # Second query reuses the cached Ephemeris rather than rebuilding it.
    assert traj._ephemeris_cache is cached


def test_geodetic_track_caches():
    traj = _leo_trajectory()
    assert getattr(traj, "_geodetic_cache", None) is None
    itrf, lat, lon, alt = geodetic_track(traj)
    cached = traj._geodetic_cache
    assert cached is not None
    # Second call reuses the cached ITRF conversion + projection rather than redoing it.
    itrf2, lat2, lon2, alt2 = geodetic_track(traj)
    assert traj._geodetic_cache is cached
    assert itrf2 is itrf and lat2 is lat and lon2 is lon and alt2 is alt
    # The shared cached lat/lon/alt arrays are read-only.
    assert not (lat.flags.writeable or lon.flags.writeable or alt.flags.writeable)


def test_trajectory_at_needs_two_samples():
    single = Trajectory.from_states([_truth_state(_epoch())])
    with pytest.raises(ValueError, match="at least 2 samples"):
        single.at(_epoch())


def test_trajectory_at_on_itrf_trajectory_does_not_leak_orekit_error():
    """at() on a non-inertial (ITRF) trajectory interpolates via EME2000.

    Orekit's ``SpacecraftStateInterpolator`` rejects a non-pseudo-inertial output
    frame, so a previous implementation crashed with a raw
    ``OrekitIllegalArgumentException`` on the documented ``to_frame(ITRF).at(...)``
    path. The fix interpolates in EME2000 and transforms the sampled state back to
    ITRF, which must equal converting the EME2000 interpolant directly.
    """
    eme = _leo_trajectory()
    itrf = eme.to_frame(Frame.ITRF)
    mid = _epoch().shifted_by(_TRAJ_STEP * 3 + _TRAJ_STEP / 2)

    s = itrf.at(mid)  # must not raise
    assert s.frame is Frame.ITRF
    assert s.epoch == mid

    expected = eme.at(mid).to_frame(Frame.ITRF)
    np.testing.assert_allclose(s.position, expected.position, rtol=0.0, atol=1e-4)
    np.testing.assert_allclose(s.velocity, expected.velocity, rtol=0.0, atol=1e-7)


# --- frames.to_geodetic() ---------------------------------------------------


def test_to_geodetic_round_trips_known_point():
    from org.orekit.bodies import GeodeticPoint

    lat_deg, lon_deg, alt_m = 28.5, -80.6, 500e3  # near KSC, 500 km up
    earth = _earth()
    xyz = earth.transform(
        GeodeticPoint(math.radians(lat_deg), math.radians(lon_deg), alt_m)
    )
    pos = np.array([xyz.getX(), xyz.getY(), xyz.getZ()], dtype=np.float64)
    # Velocity is irrelevant to a geodetic projection; any finite value works.
    state = State(_epoch(), pos, np.ones(3, dtype=np.float64), Frame.ITRF)

    geo = to_geodetic(state)
    assert geo.latitude_deg == pytest.approx(lat_deg, abs=1e-6)
    assert geo.longitude_deg == pytest.approx(lon_deg, abs=1e-6)
    assert geo.altitude_m == pytest.approx(alt_m, abs=1e-3)


@pytest.mark.parametrize("frame", [Frame.EME2000, Frame.TEME])
def test_to_geodetic_rejects_non_itrf(frame):
    state = State(
        _epoch(),
        np.array([7000e3, 0.0, 0.0], dtype=np.float64),
        np.array([0.0, 7.5e3, 0.0], dtype=np.float64),
        frame,
    )
    with pytest.raises(ValueError, match="ITRF"):
        to_geodetic(state)


# --- Orientation.to_orekit() ------------------------------------------------


def test_orientation_to_orekit_round_trips_quaternion():
    o = Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 3)
    rot = o.to_orekit()
    q = o.as_quaternion()
    qback = np.array([rot.getQ0(), rot.getQ1(), rot.getQ2(), rot.getQ3()])
    # q and -q denote the same rotation; accept either stored sign.
    assert np.allclose(qback, q, atol=1e-12) or np.allclose(qback, -q, atol=1e-12)


def test_orientation_to_orekit_identity_leaves_vector_unchanged():
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    rot = Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0).to_orekit()
    out = rot.applyTo(Vector3D(1.0, 2.0, 3.0))
    assert out.getX() == pytest.approx(1.0)
    assert out.getY() == pytest.approx(2.0)
    assert out.getZ() == pytest.approx(3.0)


def test_orientation_to_orekit_rotation_direction_is_pinned():
    # Characterization test locking the *vector-action* convention so a future
    # change to to_orekit (a quaternion-sign flip, a pre-conjugation, a switch to a
    # different Rotation constructor) cannot silently invert the rotation.
    #
    # from_axis_angle stores the standard ACTIVE +90 deg about +Z quaternion
    # (cos45, 0, 0, sin45); classically that active rotation sends body +X -> +Y.
    # But Hipparchus builds its Rotation from the quaternion in the FRAME_TRANSFORM
    # (passive) sense, so applyTo is the INVERSE of that active rotation, while
    # applyInverseTo reproduces it:
    #     applyTo(+X)        = -Y   (Hipparchus default / frame-transform)
    #     applyInverseTo(+X) = +Y   (the active body rotation the quaternion denotes)
    # The body->inertial *semantic* check against an Orekit AttitudeProvider lands
    # with the attitude-config chunk (features.md 1.1); this test only pins the
    # mechanical action so that work — and any consumer of to_orekit — starts from a
    # known baseline rather than guessing which of applyTo/applyInverseTo is active.
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    rot = Orientation.from_axis_angle((0.0, 0.0, 1.0), math.pi / 2).to_orekit()
    x = Vector3D(1.0, 0.0, 0.0)

    fwd = rot.applyTo(x)
    assert (fwd.getX(), fwd.getY(), fwd.getZ()) == pytest.approx(
        (0.0, -1.0, 0.0), abs=1e-12
    )

    inv = rot.applyInverseTo(x)
    assert (inv.getX(), inv.getY(), inv.getZ()) == pytest.approx(
        (0.0, 1.0, 0.0), abs=1e-12
    )


# --- _epoch_from_orekit (inverse of Epoch.to_orekit / _abs_date) ------------


@pytest.mark.parametrize(
    "iso",
    [
        "2024-01-01T00:00:00",
        "2026-06-12T13:45:07.250",
        "1999-12-31T23:59:59.999",  # before J2000 (negative count)
    ],
)
def test_epoch_from_orekit_round_trips(iso):
    from propygator.core.time import _epoch_from_orekit

    epoch = Epoch.from_iso(iso, scale=TimeScale.UTC)
    back = _epoch_from_orekit(epoch.to_orekit(), TimeScale.UTC)
    # durationFrom returns a double, so the two-part count round-trips to ~us, not
    # to the bit; compare the instants, not the raw fields.
    original = epoch._int_seconds + epoch._frac_seconds
    recovered = back._int_seconds + back._frac_seconds
    assert recovered == pytest.approx(original, abs=1e-6)
    assert back.scale is TimeScale.UTC


def test_epoch_from_orekit_default_scale_is_utc():
    from propygator.core.time import _epoch_from_orekit

    epoch = Epoch.from_iso("2024-03-01T06:00:00", scale=TimeScale.UTC)
    assert _epoch_from_orekit(epoch.to_orekit()).scale is TimeScale.UTC
