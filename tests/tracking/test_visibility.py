"""Tests for the Feature 1.5 visibility kernel (`tracking/visibility.py`, Chunk 2).

Two halves, split by JVM contact (the module's own layering):

- **Pure NumPy** — umbra geometry with synthetic vectors (behind Earth → dark,
  sun-side → lit, penumbra-grazing → lit), phase-angle geometry, the phase
  function's pinned values, and ``compute_magnitude``'s pre-flight ``ValueError``
  paths (validated *before* any JVM work, so these stay JVM-free).
- **JVM cross-checks** (``orekit`` fixture, scheduled last by the conftest hook) —
  ``_is_sunlit`` against Orekit's ``EclipseDetector`` umbra g-function over a real
  LEO arc through Earth's shadow (an independent implementation of the same
  conical geometry), and ``compute_magnitude`` against hand-computed pins at
  constructed geometries (the reference conditions land exactly on the standard
  magnitude; doubling the range adds 5·log10(2); full phase brightens by
  2.5·log10(π) — features.md §1.5 "Brightness").
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from propygator import TLE, Epoch, Frame, GroundStation, State, TimeScale, propagate_tle
from propygator.tracking.visibility import (
    _EARTH_RADIUS_M,
    _SUN_RADIUS_M,
    _diffuse_sphere_phase_function,
    _is_sunlit,
    _phase_angle_rad,
    _sun_positions_eme2000,
    compute_magnitude,
)

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3/1.4 tests.
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

STATION = GroundStation("Durham", 35.99, -78.90, altitude_m=130.0)
EPOCH = Epoch.from_iso("2026-06-23T00:00:00", scale=TimeScale.UTC)

AU_M = 1.496e11  # synthetic Sun distance for the pure-geometry tests
LEO_R_M = 7_000_000.0  # synthetic satellite geocentric radius


# --- umbra geometry (pure NumPy, no JVM) -------------------------------------


def test_behind_earth_is_dark():
    # Sun far along +X; satellite dead behind Earth on -X: deep umbra.
    sat = np.array([-LEO_R_M, 0.0, 0.0])
    sun = np.array([AU_M, 0.0, 0.0])
    assert not _is_sunlit(sat, sun)[0]


def test_sun_side_is_lit():
    sat = np.array([LEO_R_M, 0.0, 0.0])
    sun = np.array([AU_M, 0.0, 0.0])
    assert _is_sunlit(sat, sun)[0]


def test_terminator_side_is_lit():
    # Over the terminator (90 deg from the Sun line): Earth's disk (~65.7 deg
    # apparent radius at r = 7000 km) is nowhere near the Sun direction.
    sat = np.array([0.0, LEO_R_M, 0.0])
    sun = np.array([AU_M, 0.0, 0.0])
    assert _is_sunlit(sat, sun)[0]


def _anti_sun_satellite(offset_angle_rad: float) -> np.ndarray:
    """A satellite behind Earth, its anti-Sun axis offset by ``offset_angle_rad``.

    With the Sun far along +X, a satellite at ``r(-cos g, sin g, 0)`` sees a
    Sun–Earth angular separation of ~``g`` (the 1 AU Sun distance makes the
    to-Sun direction +X to ~r/AU ≈ 5e-5 rad).
    """
    return LEO_R_M * np.array(
        [-math.cos(offset_angle_rad), math.sin(offset_angle_rad), 0.0]
    )


def test_penumbra_grazing_is_lit():
    # Separation between the umbra and penumbra cone edges: dark only below
    # alpha_earth - alpha_sun, so alpha_earth - alpha_sun/2 is penumbra -> lit.
    alpha_earth = math.asin(_EARTH_RADIUS_M / LEO_R_M)
    alpha_sun = math.asin(_SUN_RADIUS_M / AU_M)
    sun = np.array([AU_M, 0.0, 0.0])
    sat = _anti_sun_satellite(alpha_earth - 0.5 * alpha_sun)
    assert _is_sunlit(sat, sun)[0]


def test_just_inside_umbra_is_dark():
    alpha_earth = math.asin(_EARTH_RADIUS_M / LEO_R_M)
    alpha_sun = math.asin(_SUN_RADIUS_M / AU_M)
    sun = np.array([AU_M, 0.0, 0.0])
    sat = _anti_sun_satellite(alpha_earth - 2.0 * alpha_sun)
    assert not _is_sunlit(sat, sun)[0]


def test_is_sunlit_vectorized_shapes():
    sats = np.array([[-LEO_R_M, 0.0, 0.0], [LEO_R_M, 0.0, 0.0]])
    suns = np.array([[AU_M, 0.0, 0.0], [AU_M, 0.0, 0.0]])
    lit = _is_sunlit(sats, suns)
    assert lit.shape == (2,)
    assert lit.dtype == np.bool_
    assert list(lit) == [False, True]


def test_is_sunlit_length_mismatch_raises():
    with pytest.raises(ValueError, match="equal length"):
        _is_sunlit(np.zeros((2, 3)), np.zeros((3, 3)))


def test_bad_shape_raises():
    with pytest.raises(ValueError, match="shape"):
        _is_sunlit(np.zeros((2, 2)), np.zeros((2, 2)))


# --- phase angle + phase function (pure NumPy, no JVM) ------------------------


def test_phase_angle_right_angle():
    sat = np.array([LEO_R_M, 0.0, 0.0])
    sun = sat + np.array([AU_M, 0.0, 0.0])  # to-Sun along +X
    station = sat + np.array([0.0, 500_000.0, 0.0])  # to-station along +Y
    phi = _phase_angle_rad(sat, sun, station)
    assert phi[0] == pytest.approx(math.pi / 2)


def test_phase_angle_full_and_new_phase():
    sat = np.array([LEO_R_M, 0.0, 0.0])
    sun = sat + np.array([AU_M, 0.0, 0.0])
    behind_observer = sat + np.array([500_000.0, 0.0, 0.0])  # same side as Sun
    between = sat - np.array([500_000.0, 0.0, 0.0])  # Sun behind the satellite
    assert _phase_angle_rad(sat, sun, behind_observer)[0] == pytest.approx(0.0)
    assert _phase_angle_rad(sat, sun, between)[0] == pytest.approx(math.pi)


def test_phase_function_pinned_values():
    # F(0) = 1 (full), F(pi/2) = 1/pi (the 50%-illumination reference), F(pi) = 0.
    phi = np.array([0.0, math.pi / 2, math.pi])
    f = _diffuse_sphere_phase_function(phi)
    assert f[0] == pytest.approx(1.0)
    assert f[1] == pytest.approx(1.0 / math.pi)
    assert f[2] == pytest.approx(0.0, abs=1e-15)


# --- compute_magnitude pre-flight (validated before any JVM work) -------------


def test_compute_magnitude_rejects_non_eme2000_frame():
    state = State(EPOCH, np.array([LEO_R_M, 0.0, 0.0]), np.zeros(3), Frame.TEME)
    with pytest.raises(ValueError, match="EME2000"):
        compute_magnitude(state, STATION, 2.0)


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_compute_magnitude_rejects_non_finite_standard_magnitude(bad):
    state = State(EPOCH, np.array([LEO_R_M, 0.0, 0.0]), np.zeros(3), Frame.EME2000)
    with pytest.raises(ValueError, match="finite"):
        compute_magnitude(state, STATION, bad)


# --- JVM cross-checks ---------------------------------------------------------


@pytest.mark.usefixtures("orekit")
class TestAgainstOrekit:
    def test_is_sunlit_agrees_with_orekit_eclipse_detector(self):
        """Our conical-umbra test vs Orekit's EclipseDetector umbra g-function.

        Same geometry (spherical Earth at the WGS84 equatorial radius, Orekit's
        Sun radius), independent implementation: over a multi-orbit ISS arc the
        two must agree everywhere except possibly the exact crossing samples.
        """
        from org.orekit.bodies import OneAxisEllipsoid
        from org.orekit.propagation.events import EclipseDetector

        from propygator.core.bodies import _sun

        traj = propagate_tle(
            TLE.from_strings(ISS_LINE1, ISS_LINE2), 3 * 5580.0, output_step=60.0
        )
        eme = traj.to_frame(Frame.EME2000)
        states = [eme[i] for i in range(len(eme))]
        sun_positions = _sun_positions_eme2000([s.epoch for s in states])

        ours = _is_sunlit(eme.positions, sun_positions)

        sphere = OneAxisEllipsoid(_EARTH_RADIUS_M, 0.0, Frame.ITRF.to_orekit())
        detector = EclipseDetector(_sun(), _SUN_RADIUS_M, sphere).withUmbra()
        orekit_lit = np.array(
            [detector.g(s.to_orekit()) >= 0.0 for s in states], dtype=bool
        )

        transitions = int(np.sum(orekit_lit[1:] != orekit_lit[:-1]))
        assert transitions >= 2, "arc never crossed Earth's shadow — bad fixture"
        mismatches = int(np.sum(ours != orekit_lit))
        # Only samples landing essentially on a cone crossing may disagree.
        assert mismatches <= transitions

    def test_arc_is_dark_roughly_a_third_of_the_orbit(self):
        """Sanity on the eclipse fraction: LEO shadow arcs run ~25-40% of a rev."""
        traj = propagate_tle(
            TLE.from_strings(ISS_LINE1, ISS_LINE2), 3 * 5580.0, output_step=60.0
        )
        eme = traj.to_frame(Frame.EME2000)
        states = [eme[i] for i in range(len(eme))]
        sun_positions = _sun_positions_eme2000([s.epoch for s in states])
        lit = _is_sunlit(eme.positions, sun_positions)
        dark_fraction = 1.0 - float(np.mean(lit))
        assert 0.05 <= dark_fraction <= 0.5


@pytest.mark.usefixtures("orekit")
class TestComputeMagnitude:
    """Hand-computed pins at constructed geometries (features.md §1.5 Brightness).

    The station's EME2000 position is derived here independently of the
    production route (ellipsoid point + ITRF→EME2000 transform, the 1.4 test
    pattern), then satellites are placed relative to it so range and phase angle
    are known by construction. The to-Sun direction is 1 AU away, so a satellite
    1000–2000 km from the station perturbs the phase angle by ~1e-5 rad —
    negligible against the 1e-3 mag tolerances.
    """

    STD_MAG = 2.0

    def _station_eme2000(self, epoch: Epoch) -> np.ndarray:
        from org.hipparchus.geometry.euclidean.threed import Vector3D
        from org.orekit.bodies import GeodeticPoint

        from propygator.core.bodies import _earth

        point = _earth().transform(
            GeodeticPoint(
                math.radians(STATION.latitude_deg),
                math.radians(STATION.longitude_deg),
                float(STATION.altitude_m),
            )
        )
        transform = Frame.ITRF.to_orekit().getTransformTo(
            Frame.EME2000.to_orekit(), epoch.to_orekit()
        )
        moved = transform.transformPosition(
            Vector3D(point.getX(), point.getY(), point.getZ())
        )
        return np.array([moved.getX(), moved.getY(), moved.getZ()])

    def _geometry(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Station position, unit to-Sun direction, and a unit vector ⊥ to it."""
        station_pos = self._station_eme2000(EPOCH)
        sun_pos = _sun_positions_eme2000([EPOCH])[0]
        u_sun = sun_pos - station_pos
        u_sun /= np.linalg.norm(u_sun)
        u_perp = np.cross(u_sun, np.array([0.0, 0.0, 1.0]))
        u_perp /= np.linalg.norm(u_perp)
        return station_pos, u_sun, u_perp

    def _magnitude_at(self, position: np.ndarray) -> float:
        state = State(EPOCH, position, np.zeros(3), Frame.EME2000)
        return compute_magnitude(state, STATION, self.STD_MAG)

    def test_reference_conditions_return_the_standard_magnitude(self):
        # 1000 km range, phase angle 90 deg -> exactly the standard magnitude.
        station_pos, _, u_perp = self._geometry()
        mag = self._magnitude_at(station_pos + 1_000_000.0 * u_perp)
        assert mag == pytest.approx(self.STD_MAG, abs=2e-3)

    def test_doubling_the_range_adds_5log2(self):
        station_pos, _, u_perp = self._geometry()
        mag_1000 = self._magnitude_at(station_pos + 1_000_000.0 * u_perp)
        mag_2000 = self._magnitude_at(station_pos + 2_000_000.0 * u_perp)
        assert mag_2000 - mag_1000 == pytest.approx(5.0 * math.log10(2.0), abs=2e-3)

    def test_full_phase_brightens_by_the_qsmag_offset(self):
        # Satellite on the anti-Sun side of the station: the Sun sits behind the
        # observer (phase ~ 0), brightening by 2.5*log10(pi) over the reference.
        station_pos, u_sun, _ = self._geometry()
        mag = self._magnitude_at(station_pos - 1_000_000.0 * u_sun)
        expected = self.STD_MAG - 2.5 * math.log10(math.pi)
        assert mag == pytest.approx(expected, abs=2e-3)
