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
from typing import TYPE_CHECKING

import numpy as np
from matplotlib.collections import LineCollection

from ..core.frames import Frame, geodetic_track
from .basemap import _coastline_lonlat, _render_earth_basemap
from .style import (
    FIGSIZE_3D_PX,
    FIGSIZE_GROUND_TRACK,
    MARKER_END,
    MARKER_START,
    PLOTLY_TIME_COLORSCALE,
    TIME_CMAP,
    TIME_COLOR_END,
    TIME_COLOR_START,
    TIMESERIES_COLOR,
    _apply_plotly_template,
    _mpl_style,
    _require_min_samples,
)
from .timeseries import _elapsed_hours, _suptitle_from_metadata

if TYPE_CHECKING:
    import plotly.graph_objects as go
    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

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


def _draw_ground_track(
    ax: Axes,
    traj: Trajectory,
    *,
    show_map_overlay: bool = True,
    color_by_time: bool = True,
) -> LineCollection | None:
    """Draw the ground track onto ``ax``; return the colorbar mappable (or ``None``).

    With ``color_by_time`` the track is a blue→red ``LineCollection`` whose colour
    encodes elapsed hours (the returned mappable, for a colorbar); otherwise it is a
    single dark-navy line and ``None`` is returned. ``show_map_overlay`` draws the
    bundled black coastline beneath. Start (blue circle) / end (red star) markers and a
    legend are always drawn. Sets the equirectangular map framing; the caller owns the
    figure and any colorbar.
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

    ax.scatter(lon[0], lat[0], **MARKER_START)
    ax.scatter(lon[-1], lat[-1], **MARKER_END)
    ax.legend(loc="upper right")

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
    (no cartopy). Start / end markers flag the direction. Returns the matplotlib figure;
    the JVM starts lazily on first call (frame conversion + geodetic projection).
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


def _endpoint_marker(
    x: float, y: float, z: float, *, symbol: str, color: str, name: str
) -> go.Scatter3d:
    """A single start/end 3-D marker (Plotly 3-D has no star, so end uses a diamond)."""
    import plotly.graph_objects as go

    return go.Scatter3d(
        x=[x],
        y=[y],
        z=[z],
        mode="markers",
        marker={
            "symbol": symbol,
            "size": _MARKER_SIZE_3D,
            "color": color,
            "line": {"color": "black", "width": 1},
        },
        name=name,
    )


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
    ignored with a warning. Start (blue circle) / end (red diamond) markers
    flag the direction. Returns a :class:`plotly.graph_objects.Figure`; the JVM starts
    lazily on first call when a frame conversion is needed.
    """
    import plotly.graph_objects as go

    _require_min_samples(traj)
    pos_km = traj.to_frame(frame).positions / 1000.0
    x, y, z = pos_km[:, 0], pos_km[:, 1], pos_km[:, 2]

    traces: list[go.Surface | go.Scatter3d] = []
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

    traces.append(
        _endpoint_marker(
            x[0], y[0], z[0], symbol="circle", color=TIME_COLOR_START, name="start"
        )
    )
    traces.append(
        _endpoint_marker(
            x[-1], y[-1], z[-1], symbol="diamond", color=TIME_COLOR_END, name="end"
        )
    )

    fig = go.Figure(data=traces)
    _apply_plotly_template(fig)
    fig.update_layout(
        title={"text": _title_3d(traj, frame)},
        width=FIGSIZE_3D_PX[0],
        height=FIGSIZE_3D_PX[1],
        scene={
            "xaxis": {"title": {"text": "x (km)"}},
            "yaxis": {"title": {"text": "y (km)"}},
            "zaxis": {"title": {"text": "z (km)"}},
            "aspectmode": "data",  # equal scaling so the Earth stays round
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
