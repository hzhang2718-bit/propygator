"""Tests for the Plotly 3-D view (build-plan chunk 11e).

Headless (the ``tests/plotting`` conftest pins the Agg matplotlib backend; Plotly needs
no display to build a figure). Tests start the JVM via the ``orekit`` fixture since the
ITRF view crosses into Orekit. "Snapshots" are structural Plotly-figure assertions plus
a ``to_json`` serialization smoke (pixel snapshots aren't practical for an interactive
3-D figure — the plan says "a snapshot where practical").
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import plotly.graph_objects as go
import pytest

from propygator import Frame
from propygator.core.states import Trajectory, _default_metadata
from propygator.plotting.style import TIME_COLOR_END, TIME_COLOR_START, TIMESERIES_COLOR
from propygator.plotting.trajectories import (
    _CONE_SIZE_FRACTION,
    _scene_aspect_ratio,
    plot_3d,
)

pytestmark = pytest.mark.usefixtures("orekit")

_MU = 3.986004418e14


def _inclined_trajectory(
    n: int = 60, name: str | None = None, radius_m: float = 7.0e6
) -> Trajectory:
    step_s, inc = 60.0, math.radians(51.6)
    v = math.sqrt(_MU / radius_m)
    omega = v / radius_m
    t = np.arange(n) * step_s
    theta = omega * t
    pos = np.stack(
        [radius_m * np.cos(theta), radius_m * np.sin(theta), np.zeros(n)], axis=1
    )
    vel = np.stack([-v * np.sin(theta), v * np.cos(theta), np.zeros(n)], axis=1)
    rx = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.0, math.cos(inc), -math.sin(inc)],
            [0.0, math.sin(inc), math.cos(inc)],
        ]
    )
    pos, vel = pos @ rx.T, vel @ rx.T
    base = np.datetime64("2024-01-01T00:00:00", "ns")
    epochs = base + (t * 1e9).astype("int64").astype("timedelta64[ns]")
    meta = _default_metadata()
    if name is not None:
        meta["name"] = name
    return Trajectory.from_arrays(epochs, pos, vel, Frame.EME2000, metadata=meta)


def _traces_of_type(fig, type_name: str) -> list:
    return [t for t in fig.data if t.type == type_name]


def _named_trace(fig, name: str):
    return next(t for t in fig.data if t.name == name)


def test_returns_plotly_figure() -> None:
    assert isinstance(plot_3d(_inclined_trajectory()), go.Figure)


def test_default_traces() -> None:
    fig = plot_3d(_inclined_trajectory())
    # show_earth=True, overlay off → Earth surface + line + start + end.
    assert len(_traces_of_type(fig, "surface")) == 1
    names = {t.name for t in fig.data}
    assert {"trajectory", "start", "end"} <= names
    assert "coastline" not in names

    track = _named_trace(fig, "trajectory")
    assert track.mode == "lines"
    # color_by_time → the line colour is the per-vertex elapsed-time array.
    assert np.asarray(track.line.color).shape == (len(_inclined_trajectory()),)


def test_show_earth_false_has_no_surface() -> None:
    fig = plot_3d(_inclined_trajectory(), show_earth=False)
    assert _traces_of_type(fig, "surface") == []


def test_map_overlay_itrf_adds_coastline() -> None:
    fig = plot_3d(_inclined_trajectory(), frame=Frame.ITRF, show_map_overlay=True)
    coastline = _named_trace(fig, "coastline")
    assert coastline.type == "scatter3d"
    assert coastline.mode == "lines"
    # NaN separators survive into xyz → the draped line is broken between polylines.
    assert np.isnan(np.asarray(coastline.x)).any()


def test_map_overlay_inertial_warns_and_skips() -> None:
    with pytest.warns(UserWarning, match="ignored for the EME2000"):
        fig = plot_3d(
            _inclined_trajectory(), frame=Frame.EME2000, show_map_overlay=True
        )
    assert "coastline" not in {t.name for t in fig.data}


def test_map_overlay_itrf_does_not_warn() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any warning would fail the test
        plot_3d(_inclined_trajectory(), frame=Frame.ITRF, show_map_overlay=True)


def test_color_by_time_false_is_uniform_navy() -> None:
    fig = plot_3d(_inclined_trajectory(), color_by_time=False)
    track = _named_trace(fig, "trajectory")
    assert track.line.color == TIMESERIES_COLOR


def test_endpoint_markers() -> None:
    traj = _inclined_trajectory()
    fig = plot_3d(traj)
    start, end = _named_trace(fig, "start"), _named_trace(fig, "end")

    # Start is unchanged: a blue circle marker.
    assert start.mode == "markers"
    assert start.marker.symbol == "circle"
    assert start.marker.color == TIME_COLOR_START

    # End is a velocity-oriented cone (Scatter3d markers have no rotation/triangle).
    assert end.type == "cone"
    # Positioned at the final sample (EME2000->EME2000 is identity, so == traj km).
    pos_km = traj.positions / 1000.0
    assert (end.x[0], end.y[0], end.z[0]) == pytest.approx(tuple(pos_km[-1]))
    # Oriented along the final velocity direction: u/v/w parallel to velocity.
    cone_vec = np.array([end.u[0], end.v[0], end.w[0]])
    vel = traj.velocities[-1]
    cos = float(
        np.dot(cone_vec, vel) / (np.linalg.norm(cone_vec) * np.linalg.norm(vel))
    )
    assert cos == pytest.approx(1.0, abs=1e-9)
    # Single flat red colour: a constant two-stop colorscale, no colorbar shown.
    assert end.showscale is False
    assert {stop[1] for stop in end.colorscale} == {TIME_COLOR_END}
    # The cone carries the "end" legend entry (a cone defaults showlegend off).
    assert end.showlegend is True


def test_end_cone_sized_to_scene_not_arc() -> None:
    """A short arc far from Earth still gets a visible end cone.

    go.Cone sizes in data units, so the cone must track the *rendered scene* extent
    (which show_earth=True clamps to enclose the globe), not the arc's own extent: a
    ~1000 km arc at 100,000 km radius sized to itself would be sub-pixel. Pin
    sizeref to the documented fraction of the largest fixed axis-range span.
    """
    fig = plot_3d(_inclined_trajectory(n=10, radius_m=1.0e8))
    end = _named_trace(fig, "end")
    scene = fig.layout.scene
    scene_span = max(
        axis.range[1] - axis.range[0]
        for axis in (scene.xaxis, scene.yaxis, scene.zaxis)
    )
    assert end.sizeref == pytest.approx(_CONE_SIZE_FRACTION * scene_span)


def test_scene_axis_ranges_explicit() -> None:
    """plot_3d fixes the 3-D axis ranges + a matching manual aspect ratio.

    aspectmode="data" derives the aspect ratio from cone-perturbed trace bounds, not the
    axis ranges, and squashes the globe on a flat scene. plot_3d instead sets explicit
    ranges and a manual aspect ratio proportional to those range spans, so the rendered
    per-axis scale (aspectratio/range_span) is equal => round Earth. Lock in that the
    ranges enclose the orbit and that aspectratio tracks the range spans.
    """
    traj = _inclined_trajectory()
    fig = plot_3d(traj)
    scene = fig.layout.scene
    assert scene.aspectmode == "manual"
    pos_km = traj.positions / 1000.0
    scales = []
    aspect = (scene.aspectratio.x, scene.aspectratio.y, scene.aspectratio.z)
    for i, axis in enumerate((scene.xaxis, scene.yaxis, scene.zaxis)):
        assert axis.range is not None
        assert axis.range[0] <= float(pos_km[:, i].min())
        assert axis.range[1] >= float(pos_km[:, i].max())
        scales.append(aspect[i] / (axis.range[1] - axis.range[0]))
    # Equal scale on every axis is what makes the Earth render round.
    assert scales[0] == pytest.approx(scales[1])
    assert scales[0] == pytest.approx(scales[2])


def test_scene_aspect_ratio_handles_degenerate_spans() -> None:
    """Zero-width spans (planar / single-point scenes) don't crash or zero the box.

    Only reachable with show_earth=False (the Earth clamp otherwise floors every span),
    but plot_3d is public, so guard it: a fully degenerate scene falls back to a cube
    (no 0/0), and a planar axis is floored to a thin slab rather than zero thickness.
    """
    # Fully degenerate (single point, no Earth): a cube, not a ZeroDivisionError.
    assert _scene_aspect_ratio([0.0, 0.0], [0.0, 0.0], [0.0, 0.0]) == {
        "x": 1.0,
        "y": 1.0,
        "z": 1.0,
    }
    # Planar (zero z-span): x/y unaffected, z floored to a thin (non-zero) slab.
    ar = _scene_aspect_ratio([-10.0, 10.0], [-10.0, 10.0], [5.0, 5.0])
    assert ar["x"] == 1.0
    assert ar["y"] == 1.0
    assert 0.0 < ar["z"] < 0.01


def test_template_and_title_applied() -> None:
    fig = plot_3d(_inclined_trajectory(name="Orbit demo"), frame=Frame.ITRF)
    assert fig.layout.template.layout.paper_bgcolor == "white"
    assert fig.layout.title.text == "Orbit demo (ITRF)"
    assert fig.layout.scene.aspectmode == "manual"


def test_title_default_without_name() -> None:
    fig = plot_3d(_inclined_trajectory())
    assert fig.layout.title.text == "3D trajectory (EME2000)"


def test_legend_and_colorbar_positioned_apart() -> None:
    """Legend is moved top-left and the colorbar centred, so the two don't collide."""
    fig = plot_3d(_inclined_trajectory())
    assert fig.layout.legend.x < 0.5
    assert fig.layout.legend.xanchor == "left"
    colorbar = _named_trace(fig, "trajectory").line.colorbar
    assert colorbar.len < 1.0
    assert colorbar.y == 0.5


def test_serialization_smoke() -> None:
    fig = plot_3d(_inclined_trajectory(), frame=Frame.ITRF, show_map_overlay=True)
    assert len(fig.to_json()) > 0
