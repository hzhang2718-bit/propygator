"""Spatial trajectory plots: the 2D ground track and the interactive 3D view.

``plot_ground_track`` (matplotlib, chunk 11c) projects a trajectory onto a lon/lat map:
convert to ITRF, take the geodetic sub-satellite point per sample (Chunk 3's strict
Earth-fixed-input ``to_geodetic``), and draw a blue→red time-coloured line over the
bundled coastline (features.md §1.1 "Map machinery").

``plot_3d`` (Plotly, chunk 11e) draws the trajectory in 3-D in a chosen frame,
optionally over an Earth sphere. The coastline drapes the sphere **only in the
Earth-fixed ITRF frame**, where the orbit's relationship to the continents is fixed and
correct; in an inertial frame (EME2000/TEME) the Earth rotates under the orbit, so a
coastline would invite the false reading "the orbit passes over these places" — there
``show_map_overlay`` is ignored (with a warning) and a featureless sphere is drawn.

The ground-track drawing logic lives in the ``_draw_ground_track(ax, ...)`` primitive
(same contract as the time-series primitives, chunk 11b): it draws onto a *supplied*
``Axes`` and sets the map framing, but does not create a figure or add the colorbar — it
*returns the colorbar mappable* so the wrapper (and the chunk-11d composite) decide
colorbar placement. ``plot_ground_track`` is the thin public wrapper.

``plot_sky_track`` (matplotlib polar, Feature 1.4) draws the observer's sky view: the
satellite's azimuth/elevation path as seen from a ``GroundStation``, on a polar disk
with the zenith at the centre and the horizon at the rim. It follows the same
primitive/wrapper split (``_draw_sky_track(ax, ...)``), maps the trajectory through the
batched ``look_angles_track`` (one topocentric frame), and stays **geometry-only** —
passes and brightness are Feature 1.5's concern. The live dashboard's sky panel reuses
``_draw_sky_track`` via its ``azel=`` (precomputed look angles) and ``track_style=``
seams.

Two ground-track specifics:

- **Dateline.** A continuous line would streak across the whole map each time longitude
  wraps ±180°. :func:`_dateline_segments` builds per-segment arrays and drops any
  segment that jumps more than 180°, breaking the line cleanly at the seam.
- **Framing.** Equirectangular (plate carrée) with ``aspect="equal"`` so continents
  keep their true 2:1 shape, fixed −180..180 / −90..90 limits, and a 60°/30° graticule.
"""

from __future__ import annotations

import logging
import warnings
from typing import TYPE_CHECKING, Any, cast

import numpy as np
from matplotlib.collections import LineCollection
from matplotlib.lines import Line2D

from ..core.frames import Frame, geodetic_track
from ..core.observation import look_angles_track
from .basemap import _coastline_lonlat, _render_earth_basemap
from .style import (
    FIGSIZE_3D_PX,
    FIGSIZE_GROUND_TRACK,
    FIGSIZE_SKY,
    MARKER_END,
    MARKER_START,
    PLOTLY_TIME_COLORSCALE,
    TIME_CMAP,
    TIME_COLOR_END,
    TIME_COLOR_START,
    TIMESERIES_COLOR,
    _apply_plotly_template,
    _heading_marker,
    _marker_legend_handle,
    _mpl_style,
    _require_min_samples,
)
from .timeseries import _elapsed_hours, _suptitle_from_metadata

if TYPE_CHECKING:
    import plotly.graph_objects as go
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure
    from matplotlib.projections.polar import PolarAxes

    from ..core.observation import GroundStation
    from ..core.states import Trajectory

logger = logging.getLogger(__name__)

# A longitude step larger than this (degrees) is a ±180° wrap, not real motion.
_DATELINE_JUMP_DEG = 180.0
_LON_LABEL = "Longitude (°)"
_LAT_LABEL = "Latitude (°)"
_TIME_LABEL = "Elapsed time (hours)"

# 3-D Earth sphere (plot_3d). A spherical Earth at the mean radius is plenty for a
# visual; the coastline drapes just above it to avoid z-fighting. Colour / opacity /
# mesh size are the locked cosmetic baseline — retune here (a darker or translucent
# globe, a finer mesh). The mesh is intentionally fine so the sphere reads as smooth
# rather than faceted.
_EARTH_RADIUS_KM = 6371.0
# Light, low-saturation ocean blue: a pale globe keeps the saturated blue→red
# trajectory legible (a darker blue competes with the trajectory's blue endpoint).
_EARTH_COLOR = "#b3cde0"
_EARTH_OPACITY = 1.0  # opaque: occludes the far arc (rotate the view to see it)
# Near-matte shading (high ambient, low specular) so a single-colour sphere doesn't
# show shiny facet highlights; combined with the fine mesh it looks smooth.
_EARTH_LIGHTING = {"ambient": 0.85, "diffuse": 0.5, "specular": 0.05, "roughness": 0.9}
_COASTLINE_DRAPE_FACTOR = 1.003
_SPHERE_LON_POINTS = 120
_SPHERE_LAT_POINTS = 60
_MARKER_SIZE_3D = 6

# End-of-trajectory velocity cone (plot_3d). go.Cone has no pixel size mode, so its
# size lives in *data units*; a hardcoded size would shrink to nothing on a large (GEO
# ~6x, escape-guard partial up to ~50x) scene. Size it relative to the scene instead —
# ``sizeref = _CONE_SIZE_FRACTION x (max position span)`` — so the cone holds constant
# *visual* weight on every orbit. ``_CONE_ANCHOR = "tip"`` pins the apex at the final
# sample so the cone points tip-forward along the velocity. Both are cosmetic and may be
# retuned (re-records the 3-D snapshots).
_CONE_SIZE_FRACTION = 0.05
_CONE_ANCHOR = "tip"

# Padding (fraction of the largest scene extent) added around the orbit when fixing the
# 3-D axis ranges. The ranges are set explicitly (with a matching manual aspect ratio;
# see _scene_aspect_ratio) rather than auto-ranged: under aspectmode="data" Plotly
# derives the aspect ratio from the *trace* data bounds (which the cone perturbs in z),
# not the axis ranges, so a flat scene (e.g. GEO) renders the globe squashed. The
# pad just frames the orbit and leaves a little room for the end cone.
_SCENE_PAD_FRACTION = 0.05

# Floor for a per-axis aspect-ratio component (see _scene_aspect_ratio). A perfectly
# planar axis (e.g. an equatorial orbit with show_earth=False, zero z-span) would
# otherwise get a zero-thickness — and, when the whole scene is a single point, a 0/0
# NaN — box. The floor renders such an axis as a thin slab instead. It sits far below
# the tightest *legitimate* Earth-shown ratio (~0.02 for a planar escape-boundary
# scene), so it never perturbs a real round-Earth scene.
_MIN_ASPECT_RATIO = 1e-3


def _geodetic_lonlat(traj: Trajectory) -> tuple[np.ndarray, np.ndarray]:
    """Sub-satellite geodetic (longitude, latitude) in degrees, per sample.

    Thin adapter over the shared :func:`~propygator.core.frames.geodetic_track`
    (which converts to ITRF and projects each sample), returning just (lon, lat).
    """
    _itrf, lat, lon, _alt = geodetic_track(traj)
    return lon, lat


def _dateline_segments(
    lon: np.ndarray, lat: np.ndarray, values: np.ndarray | None = None
) -> tuple[np.ndarray, np.ndarray | None]:
    """Build ``LineCollection`` segments, dropping any that wrap the ±180° dateline.

    Returns ``(segments, seg_values)`` where ``segments`` has shape ``(M, 2, 2)`` and
    ``seg_values`` (or ``None``) is the per-segment colour value — the midpoint of the
    supplied ``values`` (e.g. elapsed time), masked to match the kept segments.
    """
    points = np.column_stack([lon, lat])
    segments = np.stack([points[:-1], points[1:]], axis=1)  # (N-1, 2, 2)
    keep = np.abs(np.diff(lon)) <= _DATELINE_JUMP_DEG
    if values is None:
        return segments[keep], None
    midpoints = (values[:-1] + values[1:]) / 2.0
    return segments[keep], midpoints[keep]


#: The end-marker triangle's heading when no usable segment exists: due north, which
#: ``rotate_deg(heading - 90)`` maps to zero rotation (the un-rotated "^" points north).
_DEFAULT_HEADING_DEG = 90.0


def _track_heading_deg(
    lon: np.ndarray, lat: np.ndarray, *, at_index: int | None = None
) -> float:
    """Local heading (degrees) of the ground track, for a direction glyph.

    Returns ``degrees(atan2(Δlat, Δlon))`` of a track segment, always skipping any
    segment that **wraps the ±180° dateline or is degenerate** (coincident points):

    - **``at_index=None`` (default)** — the **last** valid segment: the end-of-track
      heading the shipped ``_draw_ground_track`` end triangle uses. A wrapping or
      zero-length final segment falls back to the previous valid one (unchanged 1.1
      behaviour).
    - **``at_index`` given** — a *sample* index (the live dashboard's current-position
      marker): the heading of the valid segment **nearest that sample**, so the live
      marker reads the satellite's direction *now* rather than at the buffer's leading
      edge. The index maps onto its forward segment (the last sample clamps to the final
      segment); if that segment is invalid the nearest valid one is taken (backward
      tie-break), reusing the identical dateline/degenerate-fallback convention.

    With no usable segment at all (a single point, an all-wrapping/all-coincident track)
    it returns due north (:data:`_DEFAULT_HEADING_DEG`), which rotates the triangle not
    at all.

    Exact on the equirectangular (plate carrée, ``aspect="equal"``) map, where one
    degree of longitude and latitude are isotropic on screen, so no projection fix.
    """
    dlon = np.diff(lon)
    dlat = np.diff(lat)
    # Reuse the dateline keep-mask (no ±180° wrap) and drop zero-length segments, which
    # have no defined bearing.
    valid = (np.abs(dlon) <= _DATELINE_JUMP_DEG) & ((dlon != 0.0) | (dlat != 0.0))
    valid_idx = np.flatnonzero(valid)
    if valid_idx.size == 0:
        return _DEFAULT_HEADING_DEG
    if at_index is None:
        chosen = int(valid_idx[-1])
    else:
        # Map the sample index onto its forward segment (last sample -> final segment),
        # then pick the valid segment nearest it; argmin's first-min gives the backward
        # tie-break that mirrors the default's "previous valid" fallback.
        target = min(max(at_index, 0), len(dlon) - 1)
        chosen = int(valid_idx[np.argmin(np.abs(valid_idx - target))])
    return float(np.degrees(np.arctan2(dlat[chosen], dlon[chosen])))


def _draw_ground_track(
    ax: Axes,
    traj: Trajectory,
    *,
    show_map_overlay: bool = True,
    color_by_time: bool = True,
    endpoint_labels: tuple[str, str] | None = None,
    suppress_end_marker: bool = False,
    extra_legend_handles: list[Line2D] | None = None,
) -> LineCollection | None:
    """Draw the ground track onto ``ax``; return the colorbar mappable (or ``None``).

    With ``color_by_time`` the track is a blue→red ``LineCollection`` whose colour
    encodes elapsed hours (the returned mappable, for a colorbar); otherwise it is a
    single dark-navy line and ``None`` is returned. ``show_map_overlay`` draws the
    bundled black coastline beneath. Start (blue circle) and end (red triangle oriented
    to the local track heading) markers and a legend are always drawn. Sets the
    equirectangular map framing; the caller owns the figure and any colorbar.

    The **return stays the colorbar mappable** (unlike the altitude/speed/sky
    primitives, which return their ``Line2D``) — ``plot_ground_track`` /
    ``plot_summary`` need it for the colorbar. The other static handle the live
    dashboard mutates on rebuild, the **start marker**, is not returned: it is the
    *sole* scatter ``PathCollection`` this primitive adds (the track and coastline are
    ``LineCollection``s), created here before the dashboard adds its own live/station
    scatters, so ``live.py`` captures it off ``ax.collections`` at build time
    (general-upgrades-1 "Live Dashboard Blitting").

    Three optional dashboard seams (for the live dashboard's centred buffer, where the
    "end" is the *future* leading edge, not where the satellite is — so the direction
    glyph belongs on the live marker, not the track end); all default to the shipped 1.1
    behaviour, so the standalone ``plot_ground_track`` output is unchanged:

    - ``endpoint_labels=(start_label, end_label)`` relabels the start/end legend keys
      (the dashboard passes ``("past edge", "future edge")``); ``None`` keeps
      ``"start"`` / ``"end"``.
    - ``suppress_end_marker=True`` omits the heading-oriented end triangle **and** its
      legend entry (only the start marker remains).
    - ``extra_legend_handles`` are appended to the legend after the built-in start/end
      keys (the dashboard adds its live-position and ground-station glyphs); the
      primitive stays generic — it only forwards the handles, never their meaning.
    """
    lon, lat = _geodetic_lonlat(traj)

    if show_map_overlay:
        _render_earth_basemap(ax)

    mappable: LineCollection | None = None
    if color_by_time:
        hours = _elapsed_hours(traj)
        segments, seg_hours = _dateline_segments(lon, lat, hours)
        # list(): LineCollection's stub wants a Sequence of segments, not a 3-D array.
        track = LineCollection(list(segments), cmap=TIME_CMAP, zorder=2)
        track.set_array(seg_hours)
        track.set_clim(0.0, float(hours[-1]))
        mappable = track
    else:
        segments, _ = _dateline_segments(lon, lat)
        track = LineCollection(list(segments), colors=TIMESERIES_COLOR, zorder=2)
    ax.add_collection(track)

    start_label, end_label = (
        endpoint_labels if endpoint_labels is not None else ("start", "end")
    )

    # Legend keys use upright glyphs (the start circle and a fixed north-pointing "^").
    # The on-map triangle's rotation encodes heading, but in the legend there is no
    # track to read it against, so a data-rotated handle is just noise — and when it
    # pointed at the start circle or the box edge it crowded the box. Proxy Line2D
    # handles aren't added to the axes, so the on-map collection count is unchanged.
    # Areas reuse MARKER_* (scatter `s` is points², Line2D markersize is points: √s).
    ax.scatter(lon[0], lat[0], **MARKER_START)
    legend_handles = [_marker_legend_handle(MARKER_START, start_label)]

    # End glyph: a triangle rotated to the local track heading (built by the shared
    # _heading_marker, which owns the per-sample rotation; MARKER_END carries no shape).
    # Suppressed for the centred buffer, where the direction glyph rides the live mark.
    if not suppress_end_marker:
        end_marker = _heading_marker(_track_heading_deg(lon, lat))
        ax.scatter(lon[-1], lat[-1], marker=end_marker, **MARKER_END)
        legend_handles.append(_marker_legend_handle(MARKER_END, end_label, marker="^"))

    # The dashboard's live-position / ground-station keys (generic — just forwarded).
    if extra_legend_handles is not None:
        legend_handles.extend(extra_legend_handles)
    ax.legend(handles=legend_handles, loc="upper right")

    ax.set_xlim(-180.0, 180.0)
    ax.set_ylim(-90.0, 90.0)
    ax.set_aspect("equal")
    ax.set_xticks(range(-180, 181, 60))
    ax.set_yticks(range(-90, 91, 30))
    ax.set_xlabel(_LON_LABEL)
    ax.set_ylabel(_LAT_LABEL)
    return mappable


def plot_ground_track(
    traj: Trajectory, *, show_map_overlay: bool = True, color_by_time: bool = True
) -> Figure:
    """Plot the sub-satellite ground track on a lon/lat map.

    The track is the geodetic (WGS84) sub-satellite point over time, coloured blue→red
    by elapsed time (``color_by_time=True``, with a time colorbar) or a single navy line
    otherwise. ``show_map_overlay`` draws the bundled low-resolution coastline beneath
    (no cartopy). A blue start circle and a red end triangle oriented to the local track
    heading flag the direction of travel. Returns the matplotlib figure; the JVM starts
    lazily on first call (frame conversion + geodetic projection).
    """
    import matplotlib.pyplot as plt

    _require_min_samples(traj)
    with _mpl_style():
        fig, ax = plt.subplots(figsize=FIGSIZE_GROUND_TRACK)
        mappable = _draw_ground_track(
            ax, traj, show_map_overlay=show_map_overlay, color_by_time=color_by_time
        )
        if mappable is not None:
            fig.colorbar(mappable, ax=ax, label=_TIME_LABEL)
        _suptitle_from_metadata(fig, traj)
        fig.tight_layout()
    logger.info("Rendered ground track over %d samples", len(traj))
    return fig


# ---------------------------------------------------------------------------
# Sky-track view (matplotlib polar, Feature 1.4)
# ---------------------------------------------------------------------------
#
# Geometry only (the 1.4 <-> 1.5 line): the raw azimuth/elevation path on an
# observer's sky dome — no passes, brightness, or lit/eclipse shading (those are
# Feature 1.5's plot_sky_chart). Shared with the live dashboard's sky panel via the
# azel= (precomputed look angles, no per-frame JVM) and track_style= (the dashboard's
# halo stroke) seams, and reused verbatim by 1.5.

#: The fixed light-blue sky disk (the standalone verb's background; the live dashboard
#: overrides the facecolor with its sun-tint after calling _draw_sky_track).
_SKY_DISK_COLOR = "#cfe8f3"
#: The contract sky track: a single dark-navy line (not the blue->red time gradient —
#: an observer reads a sky track as one continuous path). The dashboard overrides via
#: track_style (a halo path-effect for contrast against its day->night background).
_DEFAULT_SKY_TRACK_STYLE: dict[str, Any] = {"color": TIMESERIES_COLOR, "linewidth": 1.5}
#: Compass azimuth gridlines (degrees) and labels — North at top, increasing clockwise.
_SKY_AZIMUTH_TICKS = [0, 90, 180, 270]
_SKY_AZIMUTH_LABELS = ["N", "E", "S", "W"]
#: Radial gridlines. The matplotlib polar *radius* is the zenith angle (90 − elevation),
#: so the zenith sits at the centre and the horizon at the rim — but the rings are
#: **labelled in elevation** (the quantity an observer reads), so 90° reads at the
#: centre and 0° at the rim. Positions are zenith angles; each label is ``90 − pos``.
#: The zenith centre (position 0) is left unlabelled — its ring degenerates to the pole.
_SKY_RADIAL_POSITIONS_DEG = [30, 60, 90]
_SKY_RADIAL_LABELS = ["60", "30", "0"]


def _draw_sky_track(
    ax: PolarAxes,
    trajectory: Trajectory,
    station: GroundStation,
    *,
    min_elevation_deg: float = 0.0,
    azel: tuple[np.ndarray, np.ndarray, np.ndarray] | None = None,
    track_style: dict[str, Any] | None = None,
    warn_never_visible: bool = True,
) -> Line2D:
    """Draw the observer's sky track onto a polar ``ax`` (zenith centre, horizon rim).

    The geometry-only sky view (features.md §1.4): the satellite's azimuth/elevation
    path as seen from ``station``, on a matplotlib **polar** projection — North at top,
    azimuth clockwise, radius = zenith angle (90° − elevation), so the **zenith is at
    the centre and the horizon at the rim**. The radial rings are **labelled in
    elevation** (90° at the centre, 0° at the rim), the quantity an observer reads.
    Fixed light-blue disk, a single dark-navy track (not a time gradient). Shares one
    drawing path with the live dashboard's sky panel; reused verbatim by Feature 1.5's
    richer ``plot_sky_chart``.

    The look angles come from the batched
    :func:`~propygator.core.observation.look_angles_track` (one station
    ``TopocentricFrame``) — **unless** a precomputed ``azel=(azimuth_deg,
    elevation_deg, range_m)`` triple is supplied, the live dashboard's seam to avoid a
    per-frame JVM crossing (``range_m`` is ignored here).

    Samples below ``min_elevation_deg`` are masked to ``NaN`` so the pen lifts between
    successive passes (no chord across the disk). If **no** sample clears
    ``min_elevation_deg`` the empty disk is drawn and a one-time ``warnings.warn`` is
    emitted — suppressed when ``warn_never_visible=False`` (the live dashboard, where a
    transient blank sky is normal). ``track_style`` overrides the default line cosmetics
    (the dashboard supplies a halo ``path_effects`` for contrast); the standalone verb's
    output is unchanged. Draws onto the supplied ``ax``; the caller owns the figure.
    Returns the track :class:`~matplotlib.lines.Line2D` — the live dashboard's
    mutate-in-place seam (``set_data`` on rebuild, mirroring ``_draw_ground_track``'s
    returned colorbar mappable); the standalone ``plot_sky_track`` ignores it.
    """
    if azel is None:
        azimuth_deg, elevation_deg, _range_m = look_angles_track(station, trajectory)
    else:
        azimuth_deg, elevation_deg, _range_m = azel

    visible = elevation_deg >= min_elevation_deg
    if not np.any(visible) and warn_never_visible:
        warnings.warn(
            f"No sample rises above min_elevation_deg={min_elevation_deg}° as seen "
            f"from station {station.name!r} over this span; the satellite never clears "
            "the horizon (drawing an empty sky disk).",
            stacklevel=2,
        )

    # Lift the pen below the horizon clip so disjoint passes don't chord across the
    # disk; theta is the azimuth (radians), the radius is the zenith angle.
    theta = np.radians(azimuth_deg)
    radius = np.where(visible, 90.0 - elevation_deg, np.nan)
    style = {**_DEFAULT_SKY_TRACK_STYLE, **(track_style or {})}
    (track_line,) = ax.plot(theta, radius, **style)

    # Polar framing last so it is not perturbed by the plot's autoscale: North up,
    # azimuth clockwise, radius = zenith angle (zenith centre, horizon rim).
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(0.0, 90.0)
    ax.set_rgrids(_SKY_RADIAL_POSITIONS_DEG, labels=_SKY_RADIAL_LABELS)
    ax.set_thetagrids(_SKY_AZIMUTH_TICKS, labels=_SKY_AZIMUTH_LABELS)
    ax.set_facecolor(_SKY_DISK_COLOR)
    return track_line


def plot_sky_track(
    trajectory: Trajectory,
    station: GroundStation,
    *,
    min_elevation_deg: float = 0.0,
) -> Figure:
    """Plot the satellite's path across ``station``'s sky (geometry-only polar view).

    The observer's azimuth/elevation track on a polar sky dome — zenith at the centre,
    horizon at the rim, North up, azimuth clockwise, radial rings labelled in elevation
    (90° centre, 0° rim) — drawn as a single dark-navy line over a fixed light-blue
    disk. Samples below ``min_elevation_deg`` are lifted from
    the line so each visible pass draws as its own arc; if the satellite never clears
    that elevation over the span, an empty disk is drawn and a one-time warning is
    emitted. Geometry only — discrete passes, brightness, and lit/eclipse shading belong
    to Feature 1.5's ``plot_sky_chart`` (features.md §1.4). Returns the matplotlib
    figure; the JVM starts lazily on first call (the topocentric projection).
    """
    import matplotlib.pyplot as plt

    _require_min_samples(trajectory)
    with _mpl_style():
        fig, ax = plt.subplots(figsize=FIGSIZE_SKY, subplot_kw={"projection": "polar"})
        _draw_sky_track(
            cast("PolarAxes", ax),
            trajectory,
            station,
            min_elevation_deg=min_elevation_deg,
        )
        _suptitle_from_metadata(fig, trajectory)
        fig.tight_layout()
    logger.info("Rendered sky track over %d samples", len(trajectory))
    return fig


# ---------------------------------------------------------------------------
# 3-D view (Plotly, chunk 11e)
# ---------------------------------------------------------------------------


def _lonlat_to_xyz(
    lon_deg: np.ndarray, lat_deg: np.ndarray, radius_km: float
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map (longitude, latitude) in degrees onto a sphere of ``radius_km`` (ECEF xyz).

    NaNs pass through (``[NaN, NaN]`` polyline separators in the coastline asset become
    NaNs in xyz, which Plotly renders as line breaks).
    """
    lon = np.radians(lon_deg)
    lat = np.radians(lat_deg)
    x = radius_km * np.cos(lat) * np.cos(lon)
    y = radius_km * np.cos(lat) * np.sin(lon)
    z = radius_km * np.sin(lat)
    return x, y, z


def _sphere_surface() -> go.Surface:
    """A single-colour opaque Earth sphere (``go.Surface``) at the mean radius."""
    import plotly.graph_objects as go

    u = np.linspace(0.0, 2.0 * np.pi, _SPHERE_LON_POINTS)
    v = np.linspace(0.0, np.pi, _SPHERE_LAT_POINTS)
    x = _EARTH_RADIUS_KM * np.outer(np.cos(u), np.sin(v))
    y = _EARTH_RADIUS_KM * np.outer(np.sin(u), np.sin(v))
    z = _EARTH_RADIUS_KM * np.outer(np.ones_like(u), np.cos(v))
    return go.Surface(
        x=x,
        y=y,
        z=z,
        colorscale=[[0.0, _EARTH_COLOR], [1.0, _EARTH_COLOR]],
        showscale=False,
        opacity=_EARTH_OPACITY,
        lighting=_EARTH_LIGHTING,
        name="Earth",
        hoverinfo="skip",
        showlegend=False,
    )


def _coastline_trace() -> go.Scatter3d:
    """The bundled coastline draped just above the Earth sphere (ITRF/ECEF)."""
    import plotly.graph_objects as go

    lonlat = _coastline_lonlat()
    x, y, z = _lonlat_to_xyz(
        lonlat[:, 0], lonlat[:, 1], _EARTH_RADIUS_KM * _COASTLINE_DRAPE_FACTOR
    )
    return go.Scatter3d(
        x=x,
        y=y,
        z=z,
        mode="lines",
        line={"color": "black", "width": 1},
        name="coastline",
        hoverinfo="skip",
        showlegend=False,
    )


def _start_marker(x: float, y: float, z: float) -> go.Scatter3d:
    """The trajectory's start glyph: a single blue 3-D circle marker.

    Start-only by design: the end of the track is a velocity-oriented
    :func:`_velocity_cone`, not a marker, because 3-D ``Scatter3d`` markers have no
    rotation and no triangle symbol, so a static marker cannot convey direction of
    travel. Hence the fixed circle/colour/name — there is deliberately no end-marker
    knob to re-add a static (non-directional) end glyph.
    """
    import plotly.graph_objects as go

    return go.Scatter3d(
        x=[x],
        y=[y],
        z=[z],
        mode="markers",
        marker={
            "symbol": "circle",
            "size": _MARKER_SIZE_3D,
            "color": TIME_COLOR_START,
            "line": {"color": "black", "width": 1},
        },
        name="start",
    )


def _velocity_cone(
    position_km: np.ndarray,
    velocity: np.ndarray,
    *,
    sizeref: float,
    color: str,
    name: str,
) -> go.Cone:
    """A single direction-of-travel ``go.Cone`` at the trajectory end.

    Placed at ``position_km`` (data-space km) and oriented along ``velocity`` (any
    units; only the *direction* is used — the cone's size is set by ``sizeref``, not the
    speed, so it holds constant visual weight across orbit scales). ``go.Cone`` colours
    by vector magnitude, so a constant two-stop colorscale + ``showscale=False`` forces
    a single flat ``color`` (the trick :func:`_sphere_surface` uses for the globe).
    ``anchor="tip"`` pins the apex at ``position_km`` so the cone points forward.
    """
    import plotly.graph_objects as go

    norm = float(np.linalg.norm(velocity))
    direction = velocity / norm if norm > 0.0 else velocity
    return go.Cone(
        x=[float(position_km[0])],
        y=[float(position_km[1])],
        z=[float(position_km[2])],
        u=[float(direction[0])],
        v=[float(direction[1])],
        w=[float(direction[2])],
        sizemode="absolute",
        sizeref=sizeref,
        anchor=_CONE_ANCHOR,
        colorscale=[[0.0, color], [1.0, color]],
        showscale=False,
        # A cone is legend-eligible but defaults showlegend off (unlike a Scatter3d
        # marker); set it so the end glyph gets a legend entry like the start does.
        showlegend=True,
        name=name,
    )


def _scene_axis_ranges(
    pos_km: np.ndarray, *, show_earth: bool
) -> tuple[list[float], list[float], list[float]]:
    """Explicit, padded (x, y, z) ranges enclosing the orbit (and the Earth sphere).

    ``plot_3d`` fixes the 3-D axis ranges (paired with a manual aspect ratio derived
    from them; see :func:`_scene_aspect_ratio`) instead of letting Plotly auto-range.
    Bounds are taken from the data (centred on it), so an off-centre escape scene is
    still fully enclosed; the pad frames the orbit and leaves room for the end cone.
    """
    lo = pos_km.min(axis=0)
    hi = pos_km.max(axis=0)
    if show_earth:
        lo = np.minimum(lo, -_EARTH_RADIUS_KM)
        hi = np.maximum(hi, _EARTH_RADIUS_KM)
    pad = _SCENE_PAD_FRACTION * float((hi - lo).max())
    lo = lo - pad
    hi = hi + pad
    return (
        [float(lo[0]), float(hi[0])],
        [float(lo[1]), float(hi[1])],
        [float(lo[2]), float(hi[2])],
    )


def _scene_aspect_ratio(
    x_range: list[float], y_range: list[float], z_range: list[float]
) -> dict[str, float]:
    """Manual scene aspect ratio that renders the Earth round at the given ranges.

    Plotly's ``aspectmode="data"`` derives the aspect ratio from the *trace* data bounds
    (perturbed in z by the velocity cone's absolute size), not from the axis ranges, so
    a flat scene (e.g. GEO) comes out squashed. The rendered per-axis scale is
    ``aspectratio[o] / range_span[o]`` (the internal ``dataScale`` cancels in bounds
    normalization), so setting ``aspectratio[o] proportional to range_span[o]`` — and
    ``aspectmode="manual"`` so Plotly uses it verbatim — makes the scale equal on every
    axis by construction: a true-to-scale, round globe regardless of flatness. Spans are
    normalised by the largest (so the longest axis is 1.0).
    """
    spans = [
        x_range[1] - x_range[0],
        y_range[1] - y_range[0],
        z_range[1] - z_range[0],
    ]
    longest = max(spans)
    if longest <= 0.0:
        # Fully degenerate scene (every axis zero-width) — no aspect to derive, and the
        # ratio below would be 0/0. Only reachable with show_earth=False on a single
        # point (the Earth clamp otherwise floors every span); fall back to a cube.
        return {"x": 1.0, "y": 1.0, "z": 1.0}
    return {
        axis: max(span / longest, _MIN_ASPECT_RATIO) for axis, span in zip("xyz", spans)
    }


def _title_3d(traj: Trajectory, frame: Frame) -> str:
    """Figure title: the trajectory name (if any) plus the frame, else a default."""
    name = traj.metadata.get("name")
    base = str(name) if name else "3D trajectory"
    return f"{base} ({frame.value})"


def plot_3d(
    traj: Trajectory,
    *,
    frame: Frame = Frame.EME2000,
    show_earth: bool = True,
    show_map_overlay: bool = False,
    color_by_time: bool = True,
) -> go.Figure:
    """Render the trajectory in 3-D (Plotly) in ``frame``, optionally over the Earth.

    The track is a blue→red time-coloured line (``color_by_time=True``, with a time
    colorbar) or a single navy line. ``show_earth`` draws a sphere at the mean Earth
    radius. ``show_map_overlay`` drapes the bundled coastline on the sphere — honoured
    **only for the Earth-fixed ``ITRF`` frame**; for an inertial frame the Earth rotates
    under the orbit, so a coastline would misrepresent the geometry and the overlay is
    ignored with a warning. A blue start circle and a red end cone oriented along the
    final velocity flag the direction of travel. Returns a
    :class:`plotly.graph_objects.Figure`; the JVM starts lazily on first call when a
    frame conversion is needed.
    """
    import plotly.graph_objects as go

    _require_min_samples(traj)
    # to_frame crosses into Orekit (per-sample transform); convert once and read both
    # positions and the final velocity from the result.
    converted = traj.to_frame(frame)
    pos_km = converted.positions / 1000.0
    x, y, z = pos_km[:, 0], pos_km[:, 1], pos_km[:, 2]

    traces: list[go.Surface | go.Scatter3d | go.Cone] = []
    if show_earth:
        traces.append(_sphere_surface())

    if show_map_overlay:
        if frame is Frame.ITRF:
            traces.append(_coastline_trace())
        else:
            warnings.warn(
                f"show_map_overlay is ignored for the {frame.value} (inertial) 3D "
                "view: the Earth rotates under an inertial orbit, so a fixed coastline "
                "would misrepresent the geometry. Use frame=Frame.ITRF for the map "
                "overlay; drawing a featureless sphere instead.",
                stacklevel=2,
            )

    if color_by_time:
        hours = _elapsed_hours(traj)
        line = {
            "color": hours,
            "colorscale": PLOTLY_TIME_COLORSCALE,
            "width": 4,
            "cmin": 0.0,
            "cmax": float(hours[-1]),
            "showscale": True,
            # Centre + shorten the colorbar so it clears the top-corner legend.
            "colorbar": {
                "title": {"text": _TIME_LABEL},
                "len": 0.8,
                "y": 0.5,
                "yanchor": "middle",
            },
        }
    else:
        line = {"color": TIMESERIES_COLOR, "width": 4}
    traces.append(
        go.Scatter3d(
            x=x, y=y, z=z, mode="lines", line=line, name="trajectory", showlegend=False
        )
    )

    traces.append(_start_marker(x[0], y[0], z[0]))
    # Scene-relative cone: size from the orbit's own extent so it stays visible whether
    # the scene is LEO or GEO (go.Cone has no pixel size mode).
    scene_span = float(np.ptp(pos_km, axis=0).max())
    traces.append(
        _velocity_cone(
            pos_km[-1],
            converted.velocities[-1],
            sizeref=_CONE_SIZE_FRACTION * scene_span,
            color=TIME_COLOR_END,
            name="end",
        )
    )

    x_range, y_range, z_range = _scene_axis_ranges(pos_km, show_earth=show_earth)
    aspect_ratio = _scene_aspect_ratio(x_range, y_range, z_range)
    fig = go.Figure(data=traces)
    _apply_plotly_template(fig)
    fig.update_layout(
        title={"text": _title_3d(traj, frame)},
        width=FIGSIZE_3D_PX[0],
        height=FIGSIZE_3D_PX[1],
        scene={
            "xaxis": {"title": {"text": "x (km)"}, "range": x_range},
            "yaxis": {"title": {"text": "y (km)"}, "range": y_range},
            "zaxis": {"title": {"text": "z (km)"}, "range": z_range},
            # Manual aspect ratio matched to the ranges => equal scale on every axis =>
            # round Earth even on a flat scene. "data" mode squashes it (it derives the
            # aspect ratio from cone-perturbed trace bounds; see _scene_aspect_ratio).
            "aspectmode": "manual",
            "aspectratio": aspect_ratio,
        },
        # Legend in the top-left so it never collides with the right-side colorbar.
        legend={
            "x": 0.02,
            "y": 0.98,
            "xanchor": "left",
            "yanchor": "top",
            "bgcolor": "rgba(255,255,255,0.6)",
            "bordercolor": "black",
            "borderwidth": 1,
        },
    )
    logger.info("Rendered 3D view over %d samples (%s frame)", len(traj), frame.value)
    return fig
