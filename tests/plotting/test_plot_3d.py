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
from propygator.plotting.trajectories import plot_3d

pytestmark = pytest.mark.usefixtures("orekit")

_MU = 3.986004418e14


def _inclined_trajectory(n: int = 60, name: str | None = None) -> Trajectory:
    radius_m, step_s, inc = 7.0e6, 60.0, math.radians(51.6)
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
    fig = plot_3d(_inclined_trajectory())
    start, end = _named_trace(fig, "start"), _named_trace(fig, "end")
    assert start.mode == "markers" and end.mode == "markers"
    assert start.marker.symbol == "circle"
    assert end.marker.symbol == "diamond"  # Plotly 3-D has no star
    assert start.marker.color == TIME_COLOR_START
    assert end.marker.color == TIME_COLOR_END


def test_template_and_title_applied() -> None:
    fig = plot_3d(_inclined_trajectory(name="Orbit demo"), frame=Frame.ITRF)
    assert fig.layout.template.layout.paper_bgcolor == "white"
    assert fig.layout.title.text == "Orbit demo (ITRF)"
    assert fig.layout.scene.aspectmode == "data"


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
