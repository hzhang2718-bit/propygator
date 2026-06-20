"""Tests for the ground-track plot (build-plan chunk 11c).

Headless (the ``tests/plotting`` conftest pins the Agg backend); every test starts the
JVM via the session-scoped ``orekit`` fixture (the ground track is geodetic). The
trajectory is a synthesized inclined circular orbit sampled over ~one revolution, so its
ground track sweeps a full turn of longitude and crosses the ±180° dateline — exercising
the segment-masking path.

"Snapshots" are realized as structural + numerical-content assertions (the agreed
chunk-11 strategy): collection/marker/legend/colorbar presence, lon/lat vs an
independent geodetic computation, the no-segment-crosses-the-dateline invariant, the map
framing, and a render-to-buffer smoke check.
"""

from __future__ import annotations

import io
import math

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.markers import MarkerStyle
from matplotlib.transforms import Affine2D

from propygator import Frame
from propygator.core.frames import to_geodetic
from propygator.core.states import Trajectory, _default_metadata
from propygator.plotting.style import TIME_CMAP, TIMESERIES_COLOR
from propygator.plotting.trajectories import (
    _dateline_segments,
    _draw_ground_track,
    _track_heading_deg,
    plot_ground_track,
)

pytestmark = pytest.mark.usefixtures("orekit")

_MU = 3.986004418e14


def _inclined_trajectory(
    n: int = 100, step_s: float = 60.0, inc_deg: float = 51.6, name: str | None = None
) -> Trajectory:
    """A circular EME2000 orbit inclined about x, sampled over ~one revolution.

    Over a full revolution the sub-satellite longitude sweeps a full turn and crosses
    the dateline, which is what the ground-track tests need.
    """
    radius_m = 7.0e6
    v = math.sqrt(_MU / radius_m)
    omega = v / radius_m
    t = np.arange(n) * step_s
    theta = omega * t
    pos = np.stack(
        [radius_m * np.cos(theta), radius_m * np.sin(theta), np.zeros(n)], axis=1
    )
    vel = np.stack([-v * np.sin(theta), v * np.cos(theta), np.zeros(n)], axis=1)
    inc = math.radians(inc_deg)
    rx = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(inc), -math.sin(inc)],
            [0.0, math.sin(inc), math.cos(inc)],
        ]
    )
    pos = pos @ rx.T
    vel = vel @ rx.T
    base = np.datetime64("2024-01-01T00:00:00", "ns")
    epochs = base + (t * 1e9).astype("int64").astype("timedelta64[ns]")
    meta = _default_metadata()
    if name is not None:
        meta["name"] = name
    return Trajectory.from_arrays(epochs, pos, vel, Frame.EME2000, metadata=meta)


def _line_collections(ax) -> list[LineCollection]:
    return [c for c in ax.collections if isinstance(c, LineCollection)]


def _scatter_collections(ax) -> list:
    return [c for c in ax.collections if not isinstance(c, LineCollection)]


# --- _dateline_segments (pure) ---------------------------------------------


def test_dateline_segments_drops_wrapping_segment() -> None:
    lon = np.array([170.0, 179.0, -179.0, -170.0])
    lat = np.array([0.0, 1.0, 2.0, 3.0])
    values = np.array([0.0, 1.0, 2.0, 3.0])

    segments, seg_values = _dateline_segments(lon, lat, values)
    # The 179 -> -179 segment wraps (|Δ| = 358 > 180) and is dropped; 2 remain.
    assert segments.shape == (2, 2, 2)
    assert seg_values is not None and seg_values.shape == (2,)

    segments_only, none_values = _dateline_segments(lon, lat)
    assert segments_only.shape == (2, 2, 2)
    assert none_values is None


# --- _track_heading_deg (pure) ---------------------------------------------


def test_track_heading_deg_uses_last_segment() -> None:
    lon = np.array([0.0, 1.0, 3.0])
    lat = np.array([0.0, 1.0, 3.0])  # last segment: Δlon=2, Δlat=2 -> 45°
    assert _track_heading_deg(lon, lat) == pytest.approx(45.0)


def test_track_heading_deg_skips_dateline_wrap() -> None:
    # Final segment wraps the dateline (179 -> -179); fall back to the previous one,
    # which heads due east (Δlat=0, Δlon>0) -> 0°.
    lon = np.array([170.0, 179.0, -179.0])
    lat = np.array([10.0, 10.0, 20.0])
    assert _track_heading_deg(lon, lat) == pytest.approx(0.0)


def test_track_heading_deg_degenerate_points_north() -> None:
    # A single point and a coincident pair both lack a usable segment -> north (90°).
    assert _track_heading_deg(np.array([5.0]), np.array([5.0])) == pytest.approx(90.0)
    assert _track_heading_deg(
        np.array([5.0, 5.0]), np.array([5.0, 5.0])
    ) == pytest.approx(90.0)


# --- plot_ground_track structure -------------------------------------------


def test_ground_track_with_overlay_structure() -> None:
    fig = plot_ground_track(_inclined_trajectory())
    try:
        assert isinstance(fig, Figure)
        ax = fig.axes[0]
        # Basemap + track = two LineCollections; two scatter markers; a legend.
        assert len(_line_collections(ax)) == 2
        assert len(_scatter_collections(ax)) == 2
        assert ax.get_legend() is not None
        # Map framing.
        assert ax.get_xlim() == (-180.0, 180.0)
        assert ax.get_ylim() == (-90.0, 90.0)
        assert ax.get_aspect() == 1.0
        assert ax.get_xlabel() == "Longitude (°)"
        assert ax.get_ylabel() == "Latitude (°)"
        # Colorbar (default color_by_time=True) → a second figure axes labeled by time.
        assert len(fig.axes) == 2
        assert fig.axes[1].get_ylabel() == "Elapsed time (hours)"
    finally:
        plt.close(fig)


def test_ground_track_without_overlay_has_no_basemap() -> None:
    fig = plot_ground_track(_inclined_trajectory(), show_map_overlay=False)
    try:
        ax = fig.axes[0]
        assert len(_line_collections(ax)) == 1  # track only, no coastline
    finally:
        plt.close(fig)


def test_ground_track_markers_match_geodetic_endpoints() -> None:
    traj = _inclined_trajectory()
    fig = plot_ground_track(traj, show_map_overlay=False)
    try:
        ax = fig.axes[0]
        itrf = traj.to_frame(Frame.ITRF)
        start, end = to_geodetic(itrf[0]), to_geodetic(itrf[-1])
        start_marker, end_marker = _scatter_collections(ax)
        np.testing.assert_allclose(
            start_marker.get_offsets()[0],
            [start.longitude_deg, start.latitude_deg],
            rtol=1e-9,
        )
        np.testing.assert_allclose(
            end_marker.get_offsets()[0],
            [end.longitude_deg, end.latitude_deg],
            rtol=1e-9,
        )
    finally:
        plt.close(fig)


def test_ground_track_end_marker_oriented_to_heading() -> None:
    """The end triangle is rotated to the track heading (pinned heading-90 offset)."""
    traj = _inclined_trajectory()
    fig = plot_ground_track(traj, show_map_overlay=False)
    try:
        ax = fig.axes[0]
        _start_marker, end_marker = _scatter_collections(ax)

        # Independently recover the end heading from the last two geodetic points (this
        # trajectory's final segment does not wrap the dateline).
        itrf = traj.to_frame(Frame.ITRF)
        prev, last = to_geodetic(itrf[-2]), to_geodetic(itrf[-1])
        dlon = last.longitude_deg - prev.longitude_deg
        dlat = last.latitude_deg - prev.latitude_deg
        assert abs(dlon) <= 180.0  # guards the simple two-point heading below
        heading = math.degrees(math.atan2(dlat, dlon))

        # Rebuild the expected rotated-triangle path and compare to the rendered glyph.
        expected = MarkerStyle("^").transformed(Affine2D().rotate_deg(heading - 90.0))
        expected_path = expected.get_path().transformed(expected.get_transform())
        np.testing.assert_allclose(
            end_marker.get_paths()[0].vertices, expected_path.vertices, atol=1e-12
        )
        # Still a single scatter collection per endpoint.
        assert len(_scatter_collections(ax)) == 2
    finally:
        plt.close(fig)


def test_ground_track_legend_glyphs_are_upright() -> None:
    """Legend keys are canonical upright proxies, not the data-rotated map markers."""
    traj = _inclined_trajectory()  # its end heading is well off due north
    fig = plot_ground_track(traj, show_map_overlay=False)
    try:
        leg = fig.axes[0].get_legend()
        assert [t.get_text() for t in leg.get_texts()] == ["start", "end"]
        start_handle, end_handle = leg.legend_handles
        # Proxy Line2D handles, not the rotated scatter PathCollections.
        assert isinstance(start_handle, Line2D)
        assert isinstance(end_handle, Line2D)
        assert end_handle.get_marker() == "^"
        # The handle's triangle points straight up (apex x ≈ 0): upright, un-rotated.
        mk = MarkerStyle(end_handle.get_marker())
        verts = mk.get_path().transformed(mk.get_transform()).vertices
        apex = verts[np.argmax(verts[:, 1])]
        assert abs(apex[0]) < 1e-9
    finally:
        plt.close(fig)


def test_ground_track_no_segment_crosses_dateline() -> None:
    traj = _inclined_trajectory()
    # Sanity: the raw track really does wrap the dateline (else the test is vacuous).
    itrf = traj.to_frame(Frame.ITRF)
    lon = np.array([to_geodetic(s).longitude_deg for s in itrf])
    assert np.any(np.abs(np.diff(lon)) > 180.0)

    fig = plot_ground_track(traj, show_map_overlay=False)
    try:
        (track,) = _line_collections(fig.axes[0])
        for seg in track.get_segments():
            assert abs(seg[1][0] - seg[0][0]) <= 180.0
    finally:
        plt.close(fig)


# --- colour modes ----------------------------------------------------------


def test_color_by_time_sets_cmap_and_colorbar() -> None:
    traj = _inclined_trajectory()
    fig = plot_ground_track(traj, show_map_overlay=False)
    try:
        (track,) = _line_collections(fig.axes[0])
        assert track.get_array() is not None
        assert track.cmap.name == TIME_CMAP.name == "propygator_time"
        assert len(fig.axes) == 2  # colorbar present
    finally:
        plt.close(fig)


def test_color_by_time_false_is_uniform_navy_no_colorbar() -> None:
    fig = plot_ground_track(
        _inclined_trajectory(), show_map_overlay=False, color_by_time=False
    )
    try:
        assert len(fig.axes) == 1  # no colorbar
        (track,) = _line_collections(fig.axes[0])
        assert track.get_array() is None
        assert np.allclose(track.get_colors()[0], mcolors.to_rgba(TIMESERIES_COLOR))
    finally:
        plt.close(fig)


# --- primitive contract (chunk 11d depends on this) ------------------------


def test_primitive_returns_mappable_only_when_coloured() -> None:
    traj = _inclined_trajectory()
    fig, ax = plt.subplots()
    try:
        mappable = _draw_ground_track(
            ax, traj, color_by_time=True, show_map_overlay=False
        )
        assert isinstance(mappable, LineCollection)
        assert mappable.get_array() is not None
    finally:
        plt.close(fig)

    fig2, ax2 = plt.subplots()
    try:
        assert (
            _draw_ground_track(ax2, traj, color_by_time=False, show_map_overlay=False)
            is None
        )
    finally:
        plt.close(fig2)


# --- metadata + smoke ------------------------------------------------------


def test_suptitle_from_metadata_name() -> None:
    fig = plot_ground_track(_inclined_trajectory(name="Demo pass"))
    try:
        assert fig.get_suptitle() == "Demo pass"
    finally:
        plt.close(fig)


def test_render_to_buffer_smoke() -> None:
    fig = plot_ground_track(_inclined_trajectory())
    try:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        assert buffer.getbuffer().nbytes > 0
    finally:
        plt.close(fig)
