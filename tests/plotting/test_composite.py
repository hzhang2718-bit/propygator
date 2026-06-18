"""Tests for the composite summary plot (build-plan chunk 11d).

Headless (the ``tests/plotting`` conftest pins the Agg backend); every test starts the
JVM via the session-scoped ``orekit`` fixture (ground track + altitude are geodetic).
Structural assertions over the composed layout (the agreed chunk-11 snapshot strategy):
panel count tracks ``speed_frames``, the time-series rows share x while the ground track
does not, each panel is identified by its labels/aspect, and the figure renders.
"""

from __future__ import annotations

import io
import math

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.collections import LineCollection
from matplotlib.figure import Figure

from propygator import Frame
from propygator.core.states import Trajectory, _default_metadata
from propygator.plotting.composite import plot_summary

pytestmark = pytest.mark.usefixtures("orekit")

_MU = 3.986004418e14


def _inclined_trajectory(n: int = 80, name: str | None = None) -> Trajectory:
    """A circular EME2000 orbit inclined about x, sampled over ~one revolution."""
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


def _ground_track_ax(fig):
    return next(ax for ax in fig.axes if ax.get_aspect() == 1.0)


def _by_ylabel(fig, label):
    return [ax for ax in fig.axes if ax.get_ylabel() == label]


def test_summary_default_layout() -> None:
    fig = plot_summary(_inclined_trajectory())
    try:
        assert isinstance(fig, Figure)
        # Default = ground track + altitude + one speed panel; no extra colorbar axes.
        assert len(fig.axes) == 3

        ground = _ground_track_ax(fig)
        assert ground.get_xlabel() == "Longitude (°)"
        lcs = [c for c in ground.collections if isinstance(c, LineCollection)]
        assert len(lcs) == 2  # coastline + track (overlay on by default)

        (altitude,) = _by_ylabel(fig, "Altitude (km)")
        (speed,) = _by_ylabel(fig, "Speed (km/s)")
        assert speed.get_title() == "Inertial speed — EME2000"

        # Shared x across the time-series; only the bottom panel is x-labelled.
        assert altitude.get_shared_x_axes().joined(altitude, speed)
        assert altitude.get_xlabel() == ""
        assert speed.get_xlabel() == "Elapsed time (hours)"
        # Ground track keeps its own x-axis (longitude); not shared with time series.
        assert not ground.get_shared_x_axes().joined(ground, altitude)
    finally:
        plt.close(fig)


def test_summary_panel_count_tracks_speed_frames() -> None:
    fig = plot_summary(_inclined_trajectory(), speed_frames=(Frame.EME2000, Frame.ITRF))
    try:
        assert len(fig.axes) == 4  # ground track + altitude + two speed panels
        speeds = _by_ylabel(fig, "Speed (km/s)")
        titles = [ax.get_title() for ax in speeds]
        assert titles == ["Inertial speed — EME2000", "Ground-relative speed — ITRF"]
    finally:
        plt.close(fig)


def test_summary_dedupes_speed_frames() -> None:
    fig = plot_summary(
        _inclined_trajectory(), speed_frames=(Frame.EME2000, Frame.EME2000)
    )
    try:
        assert len(fig.axes) == 3  # one speed panel, not two
    finally:
        plt.close(fig)


def test_summary_empty_speed_frames_raises() -> None:
    with pytest.raises(ValueError, match="at least one frame"):
        plot_summary(_inclined_trajectory(), speed_frames=())


def test_summary_overlay_toggle() -> None:
    fig = plot_summary(_inclined_trajectory(), show_map_overlay=False)
    try:
        ground = _ground_track_ax(fig)
        lcs = [c for c in ground.collections if isinstance(c, LineCollection)]
        assert len(lcs) == 1  # track only, no coastline
    finally:
        plt.close(fig)


def test_summary_suptitle_from_metadata_name() -> None:
    fig = plot_summary(_inclined_trajectory(name="Summary demo"))
    try:
        assert fig.get_suptitle() == "Summary demo"
    finally:
        plt.close(fig)


def test_summary_render_to_buffer_smoke() -> None:
    fig = plot_summary(_inclined_trajectory(), speed_frames=(Frame.EME2000, Frame.ITRF))
    try:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        assert buffer.getbuffer().nbytes > 0
    finally:
        plt.close(fig)
