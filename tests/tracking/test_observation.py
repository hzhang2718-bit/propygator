"""JVM cross-checks for the topocentric look-angle kernel (Feature 1.4, chunk 3).

The pure-Python ``AzElRange`` construction/validation lives in
``tests/core/test_observation.py`` (the no-JVM suite). Here we exercise the
JVM-touching ``look_angles`` / ``look_angles_track`` calls with **self-sourced
geometric cross-checks** (the locked decision): no external reference numbers, just
independent topocentric geometry derived from the geodetic normal —

- a target at the station's local **zenith** ⇒ elevation ≈ 90°,
- a target displaced along local **East** ⇒ azimuth ≈ 90°, elevation ≈ 0°,
- a target displaced along local **North** ⇒ azimuth ≈ 0°, elevation ≈ 0°
  (verifying the "0 = North, clockwise toward East" convention),
- ``range_m`` ≈ the independently-computed Euclidean station→target distance,
- ``look_angles_track`` equals per-sample ``look_angles`` over a short trajectory,
- ``look_angles`` auto-converts its input (a TEME state and the same state in ITRF
  give the same look angle).

Every test starts the JVM once via the session-scoped ``orekit`` fixture, so
``conftest``'s ordering hook schedules this module after the pure-Python
``tests/core/*`` "no JVM started" guards (architecture §11).
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from propygator import (
    TLE,
    AzElRange,
    Epoch,
    Frame,
    GroundStation,
    State,
    TimeScale,
    look_angles,
    moon_look_angles,
    propagate_tle,
    sun_look_angles,
)
from propygator.core.observation import look_angles_track, observer_snapshot

pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3/1.4 tests.
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

# A mid-latitude station (Durham, NC) for the cross-checks.
STATION = GroundStation("Durham", 35.99, -78.90, altitude_m=130.0)
EPOCH = Epoch.from_iso("2026-06-23T00:00:00", scale=TimeScale.UTC)
OFFSET_M = 500_000.0  # how far to place the synthetic targets from the station


def _v3(point) -> np.ndarray:
    """Pull an Orekit/Hipparchus ``Vector3D`` into a ``(3,)`` float64 array."""
    return np.array([point.getX(), point.getY(), point.getZ()], dtype=np.float64)


def _station_ecef_and_enu() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return the station's ITRF position and local up/east/north unit vectors.

    ``up`` is the geodetic normal ``(cosφcosλ, cosφsinλ, sinφ)`` — derived by hand,
    independent of Orekit's azimuth/elevation code — and ``east``/``north`` complete
    the local ENU triad. ``east`` and ``north`` are orthogonal to ``up``, so a target
    displaced along either lies in the station's local horizontal plane (elevation 0).
    The station ECEF position itself comes from the canonical ellipsoid (it is an
    input to the look angle, not the convention under test).
    """
    from org.orekit.bodies import GeodeticPoint

    from propygator.core.bodies import _earth

    phi = math.radians(STATION.latitude_deg)
    lam = math.radians(STATION.longitude_deg)
    station_ecef = _v3(
        _earth().transform(GeodeticPoint(phi, lam, float(STATION.altitude_m)))
    )
    up = np.array(
        [math.cos(phi) * math.cos(lam), math.cos(phi) * math.sin(lam), math.sin(phi)]
    )
    east = np.array([-math.sin(lam), math.cos(lam), 0.0])
    north = np.array(
        [
            -math.sin(phi) * math.cos(lam),
            -math.sin(phi) * math.sin(lam),
            math.cos(phi),
        ]
    )
    return station_ecef, up, east, north


def _itrf_target(ecef_position: np.ndarray) -> State:
    """A static ITRF :class:`State` at ``ecef_position`` (velocity unused here)."""
    return State(EPOCH, ecef_position, np.zeros(3), Frame.ITRF)


def _azimuth_error_deg(azimuth_deg: float, target_deg: float) -> float:
    """Smallest angular distance (deg) between two compass bearings (handles 0≡360)."""
    diff = (azimuth_deg - target_deg) % 360.0
    return min(diff, 360.0 - diff)


# --- single-shot look_angles: geometric cross-checks ------------------------


def test_look_angles_zenith_is_overhead():
    station_ecef, up, _, _ = _station_ecef_and_enu()
    target = _itrf_target(station_ecef + OFFSET_M * up)

    ae = look_angles(STATION, target)

    assert isinstance(ae, AzElRange)
    assert abs(ae.elevation_deg - 90.0) < 1e-3  # straight up
    assert ae.range_m == pytest.approx(OFFSET_M, rel=1e-9)


def test_look_angles_east_is_azimuth_90_on_horizon():
    station_ecef, _, east, _ = _station_ecef_and_enu()
    target = _itrf_target(station_ecef + OFFSET_M * east)

    ae = look_angles(STATION, target)

    assert _azimuth_error_deg(ae.azimuth_deg, 90.0) < 1e-3  # due East
    assert abs(ae.elevation_deg) < 1e-3  # in the local horizontal plane


def test_look_angles_north_is_azimuth_0_on_horizon():
    station_ecef, _, _, north = _station_ecef_and_enu()
    target = _itrf_target(station_ecef + OFFSET_M * north)

    ae = look_angles(STATION, target)

    assert _azimuth_error_deg(ae.azimuth_deg, 0.0) < 1e-3  # due North (0 ≡ 360)
    assert abs(ae.elevation_deg) < 1e-3


def test_look_angles_range_is_euclidean_distance():
    station_ecef, up, _, _ = _station_ecef_and_enu()
    target_ecef = station_ecef + OFFSET_M * up
    target = _itrf_target(target_ecef)

    ae = look_angles(STATION, target)

    expected = float(np.linalg.norm(target_ecef - station_ecef))
    assert ae.range_m == pytest.approx(expected, rel=1e-9)


# --- batched look_angles_track ---------------------------------------------


def _iss_trajectory():
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2)
    # A short TEME arc around the TLE epoch (SGP4 most accurate there).
    return propagate_tle(tle, 1800.0, output_step=120.0, start=tle.epoch)


def test_look_angles_track_matches_per_sample():
    traj = _iss_trajectory()

    az, el, rng = look_angles_track(STATION, traj)

    assert az.shape == el.shape == rng.shape == (len(traj),)
    assert az.dtype == el.dtype == rng.dtype == np.float64
    for i in range(len(traj)):
        single = look_angles(STATION, traj[i])
        assert az[i] == pytest.approx(single.azimuth_deg, abs=1e-9)
        assert el[i] == pytest.approx(single.elevation_deg, abs=1e-9)
        assert rng[i] == pytest.approx(single.range_m, rel=1e-12)


# --- input is converted internally (no pre-conversion needed) ---------------


def test_look_angles_is_frame_agnostic():
    """A TEME state and the same physical state in ITRF give the same look angle."""
    traj = _iss_trajectory()
    teme_state = traj[len(traj) // 2]
    assert teme_state.frame is Frame.TEME

    from_teme = look_angles(STATION, teme_state)
    from_itrf = look_angles(STATION, teme_state.to_frame(Frame.ITRF))

    assert _azimuth_error_deg(from_teme.azimuth_deg, from_itrf.azimuth_deg) < 1e-6
    assert from_teme.elevation_deg == pytest.approx(from_itrf.elevation_deg, abs=1e-6)
    assert from_teme.range_m == pytest.approx(from_itrf.range_m, rel=1e-9)


# --- Sun / Moon look-angles -------------------------------------------------


def _assert_azel_close(a: AzElRange, b: AzElRange) -> None:
    """Assert two AzElRanges agree to numerical identity (same computation path)."""
    assert a.azimuth_deg == pytest.approx(b.azimuth_deg, abs=1e-9)
    assert a.elevation_deg == pytest.approx(b.elevation_deg, abs=1e-9)
    assert a.range_m == pytest.approx(b.range_m, rel=1e-12)


def test_sun_look_angles_at_solar_noon():
    """Sun elevation at near-meridian transit ≈ 90 − |lat − declination|.

    At the June solstice the Sun's declination equals the obliquity of the ecliptic,
    ε ≈ 23.44° (IAU 2006 mean obliquity at J2000 = 23.4393°; Astronomical Almanac).
    Greenwich is on the prime meridian, so ~12:00 UTC is close to local solar noon
    (within the equation of time), where the Sun is nearly due south (azimuth ≈ 180°)
    and at its daily-maximum elevation 90 − |lat − ε|. This is a first-principles
    cross-check of the Sun projection, no external az/el number required.
    """
    greenwich = GroundStation("Greenwich", 51.4779, 0.0, altitude_m=45.0)
    epoch = Epoch.from_iso("2026-06-21T12:00:00", scale=TimeScale.UTC)

    ae = sun_look_angles(greenwich, epoch)

    obliquity_deg = 23.44
    expected_el = 90.0 - abs(greenwich.latitude_deg - obliquity_deg)
    assert abs(ae.elevation_deg - expected_el) < 0.1
    # Near due south at near-transit; the residual is the equation of time / the fact
    # that 12:00 UTC is not the exact meridian crossing.
    assert _azimuth_error_deg(ae.azimuth_deg, 180.0) < 2.0


def test_sun_and_moon_coincide_at_2024_total_eclipse():
    """Sun and Moon share az/el at the 2024-04-08 total solar eclipse greatest point.

    Greatest eclipse: 2024-04-08 18:17:16 UTC at 25.30°N, 104.12°W, with the Sun at a
    published altitude of ≈ 69.9° (NASA GSFC eclipse catalog / Espenak). At greatest
    eclipse the Moon's centre sits within the Sun's angular radius (~0.25°) of the
    Sun, so projecting both must place them at (nearly) the same azimuth/elevation —
    a strong cross-check of the Moon ephemeris against the Sun, plus an absolute
    altitude anchor. (Geometric elevation here excludes refraction, negligible at
    ~70°.)
    """
    site = GroundStation("GreatestEclipse2024", 25.30, -104.12, altitude_m=1000.0)
    epoch = Epoch.from_iso("2024-04-08T18:17:16", scale=TimeScale.UTC)

    sun = sun_look_angles(site, epoch)
    moon = moon_look_angles(site, epoch)

    # Sun and Moon coincide (validates the Moon ephemeris relative to the Sun).
    assert _azimuth_error_deg(sun.azimuth_deg, moon.azimuth_deg) < 0.1
    assert abs(sun.elevation_deg - moon.elevation_deg) < 0.1
    # Absolute altitude vs. the published greatest-eclipse value.
    published_altitude_deg = 69.9
    assert abs(sun.elevation_deg - published_altitude_deg) < 0.5
    assert abs(moon.elevation_deg - published_altitude_deg) < 0.5
    # Sanity: the Sun is ~1 AU away, the Moon ~0.0026 AU.
    assert 1.4e11 < sun.range_m < 1.6e11
    assert 3.5e8 < moon.range_m < 4.1e8


# --- observer_snapshot ------------------------------------------------------


def test_observer_snapshot_matches_separate_calls():
    """The batched triple equals the three separate single-body calls.

    With ``epoch == state.epoch`` the snapshot is a strict single-instant projection,
    so each component must match its standalone call exactly (one station-frame build
    vs. three identical ones — same Orekit computation).
    """
    traj = _iss_trajectory()
    state = traj[len(traj) // 2]
    epoch = state.epoch

    sat, sun, moon = observer_snapshot(STATION, epoch, state)

    _assert_azel_close(sat, look_angles(STATION, state))
    _assert_azel_close(sun, sun_look_angles(STATION, epoch))
    _assert_azel_close(moon, moon_look_angles(STATION, epoch))
