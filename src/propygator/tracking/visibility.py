"""Visibility physics for Feature 1.5: eclipse, phase angle, apparent magnitude.

The only new *physics* Feature 1.5 adds (features.md §1.5 "Lighting model" /
"Brightness"; architecture §7). Three layers, split by JVM contact:

- **Pure NumPy, no JVM:** the conical-umbra sunlit test (:func:`_is_sunlit`), the
  Sun–satellite–observer phase angle (:func:`_phase_angle_rad`), and the
  diffuse-sphere phase function (:func:`_diffuse_sphere_phase_function`). All take
  positions already expressed in one common inertial frame.
- **JVM-touching helper:** :func:`_sun_positions_eme2000` — geocentric Sun
  positions for a list of epochs (the per-pass batch ``find_passes`` feeds the
  pure layer with).
- **JVM-touching public kernel:** :func:`compute_magnitude` — the photometric
  formula for one state/station pair. Reachable as
  ``propygator.tracking.visibility.compute_magnitude``; deliberately not a
  top-level export (the ``look_angles_track`` precedent, features.md §1.5).

**Shadow convention.** The umbra test is conical — Earth's disk must *fully*
cover the Sun's disk; penumbra counts as lit (a grazing satellite is still
visibly bright) — consistent in spirit with the §1.1 SRP conical shadow. The
occulting Earth is a **sphere at the WGS84 equatorial radius** (the widest disk
the ellipsoid presents, so the simplification leans "dark" and never paints an
eclipsed satellite lit); the oblateness refinement shifts shadow crossings by
seconds, far below the −6° twilight gate that dominates 1.5's visibility call.
Atmospheric refraction is out of scope (features.md §1.5).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np

from ..core.frames import Frame
from ..core.observation import _station_topocentric_frame
from ..core.states import _vector3d_to_array

if TYPE_CHECKING:
    from ..core.observation import GroundStation
    from ..core.states import State
    from ..core.time import Epoch

# Spherical-Earth conical-shadow constants. Plain floats (not Orekit lookups) so
# the umbra test stays pure NumPy with no JVM; they are physical definitions
# matching Orekit's Constants.WGS84_EARTH_EQUATORIAL_RADIUS / Constants.SUN_RADIUS,
# not tunables.
_EARTH_RADIUS_M = 6_378_137.0
_SUN_RADIUS_M = 695_500_000.0

# 1000 km in meters — the reference range of the standard-magnitude convention
# (architecture §3; core/catalogs.py provenance block).
_REFERENCE_RANGE_M = 1_000_000.0


def _as_rows(positions_m: np.ndarray) -> np.ndarray:
    """Coerce ``(3,)`` or ``(N, 3)`` input to a float64 ``(N, 3)`` array."""
    rows = np.atleast_2d(np.asarray(positions_m, dtype=np.float64))
    if rows.ndim != 2 or rows.shape[1] != 3:
        raise ValueError(f"expected shape (3,) or (N, 3), got {rows.shape}")
    return rows


def _is_sunlit(sat_positions_m: np.ndarray, sun_positions_m: np.ndarray) -> np.ndarray:
    """Conical-umbra test: is the satellite outside Earth's full shadow?

    ``sat_positions_m`` / ``sun_positions_m`` are geocentric positions in one
    common inertial frame, shape ``(N, 3)`` (a single ``(3,)`` row is accepted),
    equal length. Returns a ``(N,)`` bool array — ``True`` = sunlit, where
    **penumbra counts as lit**: the satellite is dark only when Earth's apparent
    disk fully covers the Sun's, i.e. when the Sun–Earth angular separation seen
    from the satellite is below ``asin(R_earth/r) − asin(R_sun/d_sun)`` (the
    module-docstring shadow convention). Assumes ``|sat| > R_earth`` (above the
    surface — ``find_passes`` never queries below it). Pure NumPy, no JVM.
    """
    sat = _as_rows(sat_positions_m)
    sun = _as_rows(sun_positions_m)
    if sat.shape[0] != sun.shape[0]:
        raise ValueError(
            f"satellite and Sun position arrays must have equal length, "
            f"got {sat.shape[0]} and {sun.shape[0]}"
        )
    r_sat = np.linalg.norm(sat, axis=1)
    to_sun = sun - sat
    d_sun = np.linalg.norm(to_sun, axis=1)
    alpha_earth = np.arcsin(np.clip(_EARTH_RADIUS_M / r_sat, -1.0, 1.0))
    alpha_sun = np.arcsin(np.clip(_SUN_RADIUS_M / d_sun, -1.0, 1.0))
    # Angular separation between the Earth-center and Sun directions, seen from
    # the satellite (the eclipse-detector geometry Orekit's g-function uses).
    cos_sep = np.einsum("ij,ij->i", -sat, to_sun) / (r_sat * d_sun)
    separation = np.arccos(np.clip(cos_sep, -1.0, 1.0))
    lit: np.ndarray = separation >= alpha_earth - alpha_sun
    return lit


def _phase_angle_rad(
    sat_positions_m: np.ndarray,
    sun_positions_m: np.ndarray,
    station_positions_m: np.ndarray,
) -> np.ndarray:
    """Sun–satellite–observer phase angle, radians, shape ``(N,)``.

    The angle *at the satellite* between the direction to the Sun and the
    direction to the observer: ``0`` = full phase (Sun behind the observer, the
    lit face squarely toward them), ``π`` = new phase (satellite between observer
    and Sun, dark face toward them). All positions in one common inertial frame,
    equal length (single ``(3,)`` rows accepted). Pure NumPy, no JVM.
    """
    sat = _as_rows(sat_positions_m)
    to_sun = _as_rows(sun_positions_m) - sat
    to_station = _as_rows(station_positions_m) - sat
    cos_phi = np.einsum("ij,ij->i", to_sun, to_station) / (
        np.linalg.norm(to_sun, axis=1) * np.linalg.norm(to_station, axis=1)
    )
    phase: np.ndarray = np.arccos(np.clip(cos_phi, -1.0, 1.0))
    return phase


def _diffuse_sphere_phase_function(phase_angle_rad: np.ndarray) -> np.ndarray:
    """Diffuse-sphere (Lambertian) phase function ``F(φ) = ((π−φ)cosφ + sinφ)/π``.

    The fraction of a fully-lit diffuse sphere's flux seen at phase angle ``φ`` —
    the standard satellite-photometry phase law (the convention behind the
    Heavens-Above / quicksat standard magnitudes; architecture §3). ``F(0) = 1``
    (full phase), ``F(π/2) = 1/π`` (the 50%-illumination reference of the
    standard-magnitude convention), ``F(π) = 0`` (new phase). Vectorized; pure
    NumPy, no JVM.
    """
    phi = np.asarray(phase_angle_rad, dtype=np.float64)
    result: np.ndarray = ((np.pi - phi) * np.cos(phi) + np.sin(phi)) / np.pi
    return result


def _magnitudes(
    standard_magnitude: float,
    range_m: np.ndarray,
    phase_angle_rad: np.ndarray,
) -> np.ndarray:
    """Vectorized photometric formula, shape ``(N,)`` — the single implementation
    shared by :func:`compute_magnitude` (one sample) and ``find_passes``'s
    per-pass sweep, so the two cannot drift::

        mag = std + 5 log10(range / 1000 km) - 2.5 log10(F(phi) / F(90 deg))

    with ``F`` the diffuse-sphere phase function and ``F(90 deg) = 1/pi`` the
    50%-illumination reference of the standard-magnitude convention. Exact new
    phase (``F(phi) = 0``) yields ``+inf`` (the log divide is deliberately let
    through); ``phi`` from :func:`_phase_angle_rad` is clipped to ``[0, pi]`` so
    ``F`` is never negative. Pure NumPy, no JVM.
    """
    flux_ratio = _diffuse_sphere_phase_function(phase_angle_rad)
    with np.errstate(divide="ignore"):
        result: np.ndarray = (
            standard_magnitude
            + 5.0 * np.log10(np.asarray(range_m, dtype=np.float64) / _REFERENCE_RANGE_M)
            - 2.5 * np.log10(flux_ratio * np.pi)  # / F(90 deg), i.e. * pi
        )
    return result


def _sun_positions_eme2000(epochs: Sequence[Epoch]) -> np.ndarray:
    """Geocentric Sun positions (EME2000, meters) at ``epochs``, shape ``(N, 3)``.

    The batch the per-pass lighting evaluation feeds :func:`_is_sunlit` /
    :func:`_phase_angle_rad` with (features.md §1.5 "Search algorithm" step 3) —
    a thin loop over the DE-ephemeris Sun accessor (``core/bodies``), fine at
    per-pass scale. **JVM-touching, not safe-before-init.**
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    from ..core.bodies import _sun

    sun = _sun()
    eme_frame = Frame.EME2000.to_orekit()
    out = np.empty((len(epochs), 3), dtype=np.float64)
    for i, epoch in enumerate(epochs):
        pv = sun.getPVCoordinates(epoch.to_orekit(), eme_frame)
        out[i] = _vector3d_to_array(pv.getPosition())
    return out


def compute_magnitude(
    state: State, station: GroundStation, standard_magnitude: float
) -> float:
    """Apparent visual magnitude of ``state`` as seen from ``station``.

    Applies the standard satellite-photometry formula (features.md §1.5
    "Brightness"; the convention of architecture §3's standard-magnitude table)::

        mag = standard_magnitude
              + 5 * log10(range / 1000 km)
              - 2.5 * log10(F(phi) / F(90 deg))

    where ``F`` is the diffuse-sphere phase function
    ``F(phi) = ((pi - phi) * cos(phi) + sin(phi)) / pi`` and ``phi`` the
    Sun–satellite–observer phase angle — so at exactly 1000 km range and 50%
    illumination (``phi = 90 deg``) the result *is* ``standard_magnitude``.
    The Sun position is fetched internally at ``state.epoch`` (DE ephemeris via
    ``core/bodies``); the station position is the topocentric-kernel origin
    expressed in EME2000 at the same instant.

    **Purely photometric.** No eclipse check — an umbra-eclipsed satellite still
    gets a (meaningless) number; the caller gates lighting (``find_passes`` uses
    :func:`_is_sunlit`). Returns ``+inf`` at exact new phase (``F(phi) = 0``, an
    exact-zero unreachable through real fetched geometry).

    Per the architecture §10 explicit-frame rule (the ``to_geodetic`` pattern),
    the frame-carrying input must already be in **EME2000** — any other frame
    raises ``ValueError`` (convert with ``state.to_frame(Frame.EME2000)``).
    A non-finite ``standard_magnitude`` raises ``ValueError``. Both checks run
    before any JVM work; the call itself is **JVM-touching, not
    safe-before-init**.
    """
    if state.frame is not Frame.EME2000:
        raise ValueError(
            f"compute_magnitude requires an EME2000 state (architecture §10), "
            f"got {state.frame.name}; convert with state.to_frame(Frame.EME2000)."
        )
    if not math.isfinite(standard_magnitude):
        raise ValueError(
            f"standard_magnitude must be finite, got {standard_magnitude!r}"
        )

    from .._orekit_init import _ensure_started

    _ensure_started()

    sun_position = _sun_positions_eme2000([state.epoch])[0]
    topo = _station_topocentric_frame(station)
    station_position = _vector3d_to_array(
        topo.getPVCoordinates(
            state.epoch.to_orekit(), Frame.EME2000.to_orekit()
        ).getPosition()
    )

    slant_range_m = np.array([np.linalg.norm(state.position - station_position)])
    phi = _phase_angle_rad(state.position, sun_position, station_position)
    return float(_magnitudes(standard_magnitude, slant_range_m, phi)[0])
