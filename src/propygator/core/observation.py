"""Observation-domain value types + the topocentric look-angle kernel.

The value types ``GroundStation`` / ``GeodeticPosition`` / ``Pass`` / ``AzElRange``
live in ``core/`` (not ``io/`` or ``tracking/``) so the ``io`` leaf and the
``tracking`` layer can both import them without breaking the inward dependency
rule (architecture §7). **Constructing any of the four value types is pure-Python
and never touches the JVM** (the "safe before init" surface, architecture §10).

``GroundStation`` and ``GeodeticPosition`` are boundary types (user-constructed
and user-facing respectively), so they validate their latitude/longitude/
finiteness on construction. ``Pass`` is produced internally by ``find_passes``
(Feature 1.5) and is kept as a plain value type. ``AzElRange`` is the topocentric
counterpart of ``GeodeticPosition`` — the output of :func:`look_angles`.

This module also hosts the **topocentric look-angle kernel** (Feature 1.4):
:func:`look_angles` / :func:`look_angles_track` / :func:`sun_look_angles` /
:func:`moon_look_angles` / :func:`observer_snapshot`. Unlike the value types, these
*calls* cross into Orekit — they build an Orekit ``TopocentricFrame`` on the WGS84
ellipsoid (:func:`core.bodies._earth`) and start the JVM lazily (the ``to_geodetic``
precedent, architecture §6/§10). They lazy-import jpype inside the body, so
importing this module is still JVM-free; the ``tests/core/*`` "no JVM started"
suite must therefore exercise only the value types, never the look-angle calls.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from .frames import Frame
from .time import Epoch, _abs_date

if TYPE_CHECKING:
    # Type-only; the org.* namespaces are runtime JPype stubs with no importable
    # module at type-check time (mypy: ignore_missing_imports). State/Trajectory
    # are imported here (not at runtime) to avoid a core-internal import cycle.
    import org.hipparchus.geometry.euclidean.threed  # noqa: F401
    import org.orekit.bodies  # noqa: F401
    import org.orekit.frames  # noqa: F401
    import org.orekit.time  # noqa: F401

    from .states import State, Trajectory  # noqa: F401


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
class AzElRange:
    """A topocentric look angle: where a target sits in a station's local sky.

    The observer-relative counterpart of :class:`GeodeticPosition` and the output
    of :func:`look_angles`. Like ``GeodeticPosition`` it carries **no** ``Frame``
    (the look angle is intrinsically observer-relative), so by the explicit-frame
    rule (architecture §6/§10) the producing call may convert its input internally.

    - ``azimuth_deg``: compass bearing, ``0`` = North, increasing **clockwise**
      toward East (so East ``= 90``, South ``= 180``, West ``= 270``); in ``[0, 360)``.
    - ``elevation_deg``: angle above the local horizon, ``0`` = horizon,
      ``+90`` = zenith, **negative** = below the horizon; in ``[-90, 90]``.
    - ``range_m``: straight-line (slant) station → target distance, meters.

    Pure-Python and safe before JVM init. ``__post_init__`` validates that all
    three fields are finite and that ``range_m`` is non-negative (a slant distance
    cannot be negative). The az/el documented ranges are *semantic* — they are not
    hard-bounded, because the values come from Orekit already normalized to those
    ranges and a strict bound would risk a spurious failure at the float-rounding
    edges this type hits most (zenith ``el = 90``, due-north ``az = 0``/``360``);
    finiteness is the property downstream consumers actually depend on.
    """

    azimuth_deg: float
    elevation_deg: float
    range_m: float

    def __post_init__(self) -> None:
        if not (
            math.isfinite(self.azimuth_deg)
            and math.isfinite(self.elevation_deg)
            and math.isfinite(self.range_m)
        ):
            raise ValueError(
                "azimuth_deg, elevation_deg and range_m must be finite, got "
                f"{self.azimuth_deg!r}, {self.elevation_deg!r}, {self.range_m!r}"
            )
        if self.range_m < 0.0:
            raise ValueError(f"range_m must be non-negative, got {self.range_m!r}")


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


# ---------------------------------------------------------------------------
# Topocentric look-angle kernel (Feature 1.4) — JVM-touching
# ---------------------------------------------------------------------------
#
# One shared kernel: build the station's Orekit ``TopocentricFrame`` once
# (``_station_topocentric_frame``), then project any target's position into it
# (``_raw_azel``). ``look_angles`` is the single-shot primitive; the batched
# ``look_angles_track`` builds the station frame once and walks a trajectory
# (the ``geodetic_track`` analogue). Chunk 4 reuses the same two privates for the
# Sun/Moon projections + ``observer_snapshot``. All of it is reused verbatim by
# Feature 1.5.


def _station_topocentric_frame(
    station: GroundStation,
) -> "org.orekit.frames.TopocentricFrame":
    """Build the Orekit ``TopocentricFrame`` for ``station`` (JVM-crossing).

    A topocentric frame on the canonical WGS84 ellipsoid (:func:`core.bodies._earth`)
    at the station's geodetic point. Depends only on the ``station`` (not on any
    target or epoch), so callers build it **once** and reuse it across samples /
    bodies — the shared kernel behind every look-angle shape. Starts the JVM lazily.
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.bodies import GeodeticPoint
    from org.orekit.frames import TopocentricFrame

    from .bodies import _earth

    point = GeodeticPoint(
        math.radians(station.latitude_deg),
        math.radians(station.longitude_deg),
        float(station.altitude_m),
    )
    return TopocentricFrame(_earth(), point, station.name)


def _raw_azel(
    topo: "org.orekit.frames.TopocentricFrame",
    point: "org.hipparchus.geometry.euclidean.threed.Vector3D",
    frame: "org.orekit.frames.Frame",
    date: "org.orekit.time.AbsoluteDate",
) -> tuple[float, float, float]:
    """Project ``point`` (expressed in ``frame`` at ``date``) into ``topo``.

    Returns ``(azimuth_deg, elevation_deg, range_m)``. Body-agnostic — the target
    is just a Hipparchus ``Vector3D`` position, so the same helper serves the
    satellite (Chunk 3) and the Sun/Moon (Chunk 4). The ``TopocentricFrame``
    methods transform ``point`` from ``frame`` into the Earth body frame at ``date``
    internally, so the caller need not pre-convert (an inertial ECI input is fine —
    the Earth-rotation transform is applied here). The caller must have started the
    JVM. Returned in user-facing units (degrees, meters); :func:`look_angles` wraps
    these into an :class:`AzElRange`, the batched path fills arrays directly.

    One ``getTrackingCoordinates`` call (not separate ``getAzimuth``/``getElevation``/
    ``getRange``) so the ``frame``→Earth-body transform is computed once per sample
    rather than three times — the per-sample crossing matters in ``look_angles_track``.
    """
    tc = topo.getTrackingCoordinates(point, frame, date)
    return (
        math.degrees(tc.getAzimuth()),
        math.degrees(tc.getElevation()),
        float(tc.getRange()),
    )


def _state_azel(topo: "org.orekit.frames.TopocentricFrame", state: State) -> AzElRange:
    """Project a satellite ``state`` into an already-built station frame.

    Shared by :func:`look_angles` and :func:`observer_snapshot`, so the satellite
    look angle is computed one way. Uses ``state.epoch`` for the projection's
    Earth-rotation transform — mandatory for an inertial-frame (TEME / EME2000)
    state, whose position is fixed in inertial space at exactly that instant. The
    caller built ``topo`` and started the JVM.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    point = Vector3D(
        float(state.position[0]),
        float(state.position[1]),
        float(state.position[2]),
    )
    az, el, rng = _raw_azel(
        topo, point, state.frame.to_orekit(), state.epoch.to_orekit()
    )
    return AzElRange(az, el, rng)


def _body_azel(
    topo: "org.orekit.frames.TopocentricFrame",
    body: "org.orekit.bodies.CelestialBody",
    epoch: Epoch,
) -> AzElRange:
    """Project a celestial ``body`` (Sun / Moon) at ``epoch`` into a station frame.

    Resolves the body's position in EME2000 and projects it through the shared
    :func:`_raw_azel` (which applies the EME2000 → Earth-body transform at ``epoch``
    internally). Shared by :func:`sun_look_angles` / :func:`moon_look_angles` /
    :func:`observer_snapshot`. The caller built ``topo`` and started the JVM.
    """
    frame = Frame.EME2000.to_orekit()
    date = epoch.to_orekit()
    position = body.getPosition(date, frame)
    az, el, rng = _raw_azel(topo, position, frame, date)
    return AzElRange(az, el, rng)


def look_angles(station: GroundStation, state: State) -> AzElRange:
    """Return the azimuth/elevation/range of ``state`` seen from ``station``.

    The topocentric analogue of :func:`~propygator.core.frames.to_geodetic`: it
    projects the satellite ``state`` into the station's local sky. ``AzElRange``
    carries no ``Frame``, so by the explicit-frame rule (architecture §6/§10) the
    input is converted internally — ``state`` may be in any frame (TEME, EME2000,
    ITRF); callers need not pre-convert. Builds the station ``TopocentricFrame``
    and starts the JVM on first call.

    For a whole :class:`Trajectory`, prefer :func:`look_angles_track`, which builds
    the station frame once instead of once per sample.
    """
    return _state_azel(_station_topocentric_frame(station), state)


def look_angles_track(
    station: GroundStation, trajectory: Trajectory
) -> "tuple[np.ndarray, np.ndarray, np.ndarray]":
    """Project a whole trajectory into ``station``'s sky (the batched analogue).

    Returns parallel ``float64`` arrays ``(azimuth_deg, elevation_deg, range_m)``,
    one entry per sample — the look-angle counterpart of
    :func:`~propygator.core.frames.geodetic_track`. The station ``TopocentricFrame``
    and the trajectory's Orekit frame are resolved **once**, then every sample is
    projected, so the JPype boundary is crossed per sample only for the cheap
    az/el/range reads (not a frame rebuild). Starts the JVM on first call.

    Unlike ``geodetic_track`` this is **not** memoized on the trajectory: the result
    is station-keyed, so the freshly-allocated, caller-owned arrays are returned for
    the caller (e.g. the live dashboard engine) to hold for the buffer's lifetime.
    Consumed by ``_draw_sky_track`` and the dashboard sky panel; per-sample
    :func:`look_angles` stays the ergonomic single-shot primitive.
    """
    topo = _station_topocentric_frame(station)
    orekit_frame = trajectory.frame.to_orekit()

    from org.hipparchus.geometry.euclidean.threed import Vector3D

    n = len(trajectory)
    azimuth_deg = np.empty(n, dtype=np.float64)
    elevation_deg = np.empty(n, dtype=np.float64)
    range_m = np.empty(n, dtype=np.float64)
    positions = trajectory.positions
    for i in range(n):
        point = Vector3D(
            float(positions[i, 0]),
            float(positions[i, 1]),
            float(positions[i, 2]),
        )
        # Build the AbsoluteDate straight from the two-part TAI count (the
        # Trajectory.to_frame / io.exports per-sample idiom) rather than materializing a
        # throwaway Epoch per sample; topo and orekit_frame are hoisted above.
        date = _abs_date(
            int(trajectory._epochs_int[i]), float(trajectory._epochs_frac[i])
        )
        az, el, rng = _raw_azel(topo, point, orekit_frame, date)
        azimuth_deg[i] = az
        elevation_deg[i] = el
        range_m[i] = rng
    return azimuth_deg, elevation_deg, range_m


def sun_look_angles(station: GroundStation, epoch: Epoch) -> AzElRange:
    """Return the Sun's azimuth/elevation/range seen from ``station`` at ``epoch``.

    The same topocentric kernel as :func:`look_angles`, projecting the Sun
    (:func:`core.bodies._sun`) instead of a satellite. The observer's Sun elevation
    is the live dashboard's sky tint and Feature 1.5's "observer in darkness" gate,
    so this is reused well beyond 1.4. Builds the station frame and starts the JVM on
    first call. (``range_m`` is the ~1 AU station→Sun distance, carried for
    :class:`AzElRange` shape parity; az/el are the useful fields.)
    """
    from .bodies import _sun

    return _body_azel(_station_topocentric_frame(station), _sun(), epoch)


def moon_look_angles(station: GroundStation, epoch: Epoch) -> AzElRange:
    """Return the Moon's azimuth/elevation/range seen from ``station`` at ``epoch``.

    The Moon counterpart of :func:`sun_look_angles` (projecting
    :func:`core.bodies._moon`); used for the dashboard's Moon marker. Builds the
    station frame and starts the JVM on first call.
    """
    from .bodies import _moon

    return _body_azel(_station_topocentric_frame(station), _moon(), epoch)


def observer_snapshot(
    station: GroundStation, epoch: Epoch, state: State
) -> tuple[AzElRange, AzElRange, AzElRange]:
    """Project the satellite + Sun + Moon from a single station-frame build.

    Returns ``(satellite, sun, moon)`` :class:`AzElRange`s — the live dashboard's
    per-frame batch. Building the station ``TopocentricFrame`` is the expensive
    boundary crossing, so calling :func:`look_angles` + :func:`sun_look_angles` +
    :func:`moon_look_angles` separately would rebuild the identical frame three
    times; this builds it once and projects all three through it.

    ``epoch`` is the observation time for the **Sun/Moon**; the **satellite** is
    projected at ``state.epoch`` — the only time its position is defined, and (for an
    inertial-frame state) the instant its Earth-rotation transform must use. In normal
    use these coincide: the live caller passes ``epoch = now`` and
    ``state = buffer.at(now)``. They differ only in a degraded stall, where the
    satellite is correctly frozen at its last realized epoch while the Sun/Moon track
    real ``now`` — a sub-degree, physically-consistent divergence. Pass
    ``epoch == state.epoch`` for a strict single-instant snapshot. Starts the JVM on
    first call.
    """
    from .bodies import _moon, _sun

    topo = _station_topocentric_frame(station)
    return (
        _state_azel(topo, state),
        _body_azel(topo, _sun(), epoch),
        _body_azel(topo, _moon(), epoch),
    )
