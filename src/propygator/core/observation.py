"""Observation-domain value types: ``GroundStation``, ``GeodeticPosition``, ``Pass``.

These live in ``core/`` (not ``io/`` or ``tracking/``) so the ``io`` leaf and
the ``tracking`` layer can both import them without breaking the inward
dependency rule (architecture §7). All three are pure-Python frozen dataclasses
— constructing them never touches the JVM.

``GroundStation`` and ``GeodeticPosition`` are boundary types (user-constructed
and user-facing respectively), so they validate their latitude/longitude/
finiteness on construction. ``Pass`` is produced internally by ``find_passes``
(Feature 1.5) and is kept as a plain value type.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .time import Epoch


def _check_lat_lon(latitude_deg: float, longitude_deg: float) -> None:
    """Validate a geodetic latitude/longitude pair (degrees)."""
    if not math.isfinite(latitude_deg) or not -90.0 <= latitude_deg <= 90.0:
        raise ValueError(
            f"latitude_deg must be finite and in [-90, 90], got {latitude_deg!r}"
        )
    if not math.isfinite(longitude_deg) or not -180.0 <= longitude_deg <= 180.0:
        raise ValueError(
            f"longitude_deg must be finite and in [-180, 180], got {longitude_deg!r}"
        )


@dataclass(frozen=True)
class GroundStation:
    """A fixed observer on the Earth's surface (WGS84 geodetic coordinates).

    ``latitude_deg`` ∈ [-90, 90], ``longitude_deg`` ∈ [-180, 180], ``altitude_m``
    is geodetic height above the WGS84 ellipsoid (defaults to sea level).
    """

    name: str
    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0

    def __post_init__(self) -> None:
        _check_lat_lon(self.latitude_deg, self.longitude_deg)
        if not math.isfinite(self.altitude_m):
            raise ValueError(f"altitude_m must be finite, got {self.altitude_m!r}")


@dataclass(frozen=True)
class GeodeticPosition:
    """A geodetic position: the output type of ``to_geodetic(state)`` (Feature 1.4).

    ``latitude_deg`` ∈ [-90, 90], ``longitude_deg`` ∈ [-180, 180], ``altitude_m``
    is geodetic altitude above the WGS84 ellipsoid.
    """

    latitude_deg: float
    longitude_deg: float
    altitude_m: float

    def __post_init__(self) -> None:
        _check_lat_lon(self.latitude_deg, self.longitude_deg)
        if not math.isfinite(self.altitude_m):
            raise ValueError(f"altitude_m must be finite, got {self.altitude_m!r}")


@dataclass(frozen=True)
class Pass:
    """A single visible pass of a satellite over a ground station.

    Produced by ``find_passes`` (Feature 1.5); a plain value type — field
    consistency (e.g. rise ≤ culmination ≤ set) is the producer's responsibility.
    ``peak_magnitude`` is ``None`` when brightness was not computed.
    """

    rise: Epoch
    culmination: Epoch
    set: Epoch
    max_elevation_deg: float
    peak_magnitude: float | None
    sunlit_at_culmination: bool
