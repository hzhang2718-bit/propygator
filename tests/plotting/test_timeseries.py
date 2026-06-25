"""Tests for the time-series plots (build-plan chunk 11b).

Headless (the ``tests/plotting`` conftest pins the Agg backend). Every test starts the
JVM via the session-scoped ``orekit`` fixture: altitude is geodetic (ITRF conversion +
projection) and ITRF speed needs a frame transform. Trajectories are synthesized from a
circular orbit rather than propagated — exercising the full plot plumbing cheaply.

"Snapshots" are realized as structural + numerical-content assertions (the agreed
strategy for chunk 11): the plotted arrays are checked against the analytically-expected
altitude / speed, labels / titles / panel counts are pinned exactly, and the figure is
rendered to a buffer as a smoke check — robust across the Linux CI / Windows dev split,
where pixel baselines would be fragile.
"""

from __future__ import annotations

import io
import math

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.figure import Figure

from propygator import Frame
from propygator.core.frames import to_geodetic
from propygator.core.states import Trajectory, _default_metadata
from propygator.plotting.style import TIMESERIES_COLOR
from propygator.plotting.timeseries import (
    _HOURS_XLABEL,
    _draw_altitude,
    _draw_speed,
    _elapsed_hours,
    _speed_descriptor,
    plot_altitude,
    plot_speed,
)

pytestmark = pytest.mark.usefixtures("orekit")

# WGS84 mu, matching the conversion layer.
_MU = 3.986004418e14


def _circular_trajectory(
    n: int = 12, radius_m: float = 7.0e6, step_s: float = 600.0, name: str | None = None
) -> Trajectory:
    """A self-consistent circular EME2000 orbit in the equatorial (xy) plane."""
    v = math.sqrt(_MU / radius_m)
    omega = v / radius_m  # mean motion (rad/s)
    t = np.arange(n) * step_s
    theta = omega * t
    pos = np.stack(
        [radius_m * np.cos(theta), radius_m * np.sin(theta), np.zeros(n)], axis=1
    )
    vel = np.stack([-v * np.sin(theta), v * np.cos(theta), np.zeros(n)], axis=1)
    base = np.datetime64("2024-01-01T00:00:00", "ns")
    epochs = base + (t * 1e9).astype("int64").astype("timedelta64[ns]")
    meta = _default_metadata()
    if name is not None:
        meta["name"] = name
    return Trajectory.from_arrays(epochs, pos, vel, Frame.EME2000, metadata=meta)


# --- helpers ---------------------------------------------------------------


def test_elapsed_hours_starts_at_zero_and_increases() -> None:
    traj = _circular_trajectory(n=12, step_s=600.0)
    hours = _elapsed_hours(traj)
    assert hours[0] == 0.0
    assert np.all(np.diff(hours) > 0)
    assert hours[-1] == pytest.approx(11 * 600.0 / 3600.0)


def test_speed_descriptor_mapping() -> None:
    assert _speed_descriptor(Frame.ITRF) == "Ground-relative"
    assert _speed_descriptor(Frame.EME2000) == "Inertial"
    assert _speed_descriptor(Frame.TEME) == "Inertial"


# --- plot_altitude ---------------------------------------------------------


def test_plot_altitude_content_and_labels() -> None:
    traj = _circular_trajectory()
    fig = plot_altitude(traj)
    try:
        assert isinstance(fig, Figure)
        assert len(fig.axes) == 1
        ax = fig.axes[0]
        assert ax.get_ylabel() == "Altitude (km)"
        assert ax.get_xlabel() == _HOURS_XLABEL

        (line,) = ax.lines
        np.testing.assert_allclose(line.get_xdata(), _elapsed_hours(traj))

        itrf = traj.to_frame(Frame.ITRF)
        expected_km = np.array([to_geodetic(s).altitude_m for s in itrf]) / 1000.0
        np.testing.assert_allclose(line.get_ydata(), expected_km, rtol=1e-9)

        # Independent sanity: equatorial 7000 km orbit sits ~622 km up, in km not m.
        assert np.all((line.get_ydata() > 600.0) & (line.get_ydata() < 650.0))
        assert mcolors.to_hex(line.get_color()) == TIMESERIES_COLOR
    finally:
        plt.close(fig)


# --- plot_speed ------------------------------------------------------------


def test_plot_speed_default_single_panel() -> None:
    traj = _circular_trajectory()
    fig = plot_speed(traj)
    try:
        assert len(fig.axes) == 1
        ax = fig.axes[0]
        assert ax.get_ylabel() == "Speed (km/s)"
        assert ax.get_title() == "Inertial speed — EME2000"
        assert ax.get_xlabel() == _HOURS_XLABEL

        (line,) = ax.lines
        expected_kms = math.sqrt(_MU / 7.0e6) / 1000.0
        np.testing.assert_allclose(line.get_ydata(), expected_kms, rtol=1e-9)
        assert mcolors.to_hex(line.get_color()) == TIMESERIES_COLOR
    finally:
        plt.close(fig)


def test_plot_speed_panel_count_tracks_frames() -> None:
    traj = _circular_trajectory()
    fig = plot_speed(traj, frames=(Frame.EME2000, Frame.ITRF))
    try:
        assert len(fig.axes) == 2
        top, bottom = fig.axes
        assert top.get_title() == "Inertial speed — EME2000"
        assert bottom.get_title() == "Ground-relative speed — ITRF"
        # Shared x: only the bottom panel carries the x-axis label.
        assert top.get_xlabel() == ""
        assert bottom.get_xlabel() == _HOURS_XLABEL
        assert top.get_shared_x_axes().joined(top, bottom)

        # ITRF (ground-relative) speed is slower than inertial for a prograde orbit.
        assert np.mean(bottom.lines[0].get_ydata()) < np.mean(top.lines[0].get_ydata())
    finally:
        plt.close(fig)


def test_plot_speed_dedupes_frames() -> None:
    traj = _circular_trajectory()
    fig = plot_speed(traj, frames=(Frame.EME2000, Frame.EME2000))
    try:
        assert len(fig.axes) == 1
    finally:
        plt.close(fig)


def test_plot_speed_empty_frames_raises() -> None:
    traj = _circular_trajectory()
    with pytest.raises(ValueError, match="at least one frame"):
        plot_speed(traj, frames=())


def test_plot_functions_reject_too_few_samples() -> None:
    """A degenerate (<2-sample) trajectory raises a clean ValueError from every
    public plot, not a bare IndexError from inside the drawing primitives."""
    import propygator as pgr

    single = _circular_trajectory(n=1)
    for plot in (
        pgr.plot_altitude,
        pgr.plot_speed,
        pgr.plot_ground_track,
        pgr.plot_3d,
        pgr.plot_summary,
    ):
        with pytest.raises(ValueError, match="at least 2 trajectory samples"):
            plot(single)


# --- primitive contract (chunk 11d depends on this) ------------------------


def test_draw_primitives_supplied_axes_no_xlabel() -> None:
    """Primitives draw onto the supplied ax, set the y-label, and leave the x-label."""
    traj = _circular_trajectory()
    fig, (ax_alt, ax_spd) = plt.subplots(2, 1)
    try:
        _draw_altitude(ax_alt, traj)
        assert ax_alt.get_ylabel() == "Altitude (km)"
        assert ax_alt.get_xlabel() == ""  # caller owns the x-label
        assert len(ax_alt.lines) == 1

        _draw_speed(ax_spd, traj, frame=Frame.ITRF)
        assert ax_spd.get_ylabel() == "Speed (km/s)"
        assert ax_spd.get_title() == "Ground-relative speed — ITRF"
        assert ax_spd.get_xlabel() == ""
        assert len(ax_spd.lines) == 1
    finally:
        plt.close(fig)


# --- _draw_speed precomputed-array seam (Feature 1.4, chunk 6) --------------


def test_draw_speed_precomputed_array_plots_directly_with_legend() -> None:
    """A supplied ``speeds_kms`` array is drawn verbatim (no ``to_frame``), with the
    caller's colour/label and a legend in place of the single-frame title."""
    traj = _circular_trajectory()
    speeds = np.linspace(7.0, 8.0, len(traj))
    fig, ax = plt.subplots()
    try:
        _draw_speed(ax, traj, speeds_kms=speeds, color="tab:red", label="inertial")
        (line,) = ax.lines
        # Plotted verbatim against elapsed hours — no frame conversion.
        np.testing.assert_array_equal(line.get_ydata(), speeds)
        np.testing.assert_allclose(line.get_xdata(), _elapsed_hours(traj))
        assert mcolors.to_hex(line.get_color()) == mcolors.to_hex("tab:red")
        assert ax.get_ylabel() == "Speed (km/s)"
        # Legend instead of a frame-naming title.
        assert ax.get_title() == ""
        legend = ax.get_legend()
        assert legend is not None
        assert [t.get_text() for t in legend.get_texts()] == ["inertial"]
    finally:
        plt.close(fig)


def test_draw_speed_two_frames_share_one_axis() -> None:
    """Two precomputed curves co-plot on one axis with a two-entry legend — the
    dashboard's inertial + ITRF speed overlay."""
    traj = _circular_trajectory()
    inertial = np.full(len(traj), 7.5)
    ground = np.full(len(traj), 7.0)
    fig, ax = plt.subplots()
    try:
        _draw_speed(ax, traj, speeds_kms=inertial, color="tab:blue", label="EME2000")
        _draw_speed(ax, traj, speeds_kms=ground, color="tab:orange", label="ITRF")
        assert len(ax.lines) == 2
        assert [t.get_text() for t in ax.get_legend().get_texts()] == [
            "EME2000",
            "ITRF",
        ]
        assert ax.get_title() == ""
    finally:
        plt.close(fig)


def test_draw_speed_requires_frame_or_array() -> None:
    """With neither a frame nor a precomputed array there is nothing to draw."""
    traj = _circular_trajectory()
    fig, ax = plt.subplots()
    try:
        with pytest.raises(ValueError, match="either"):
            _draw_speed(ax, traj)
    finally:
        plt.close(fig)


# --- metadata + smoke ------------------------------------------------------


def test_suptitle_from_metadata_name() -> None:
    named = _circular_trajectory(name="ISS demo")
    fig = plot_altitude(named)
    try:
        assert fig.get_suptitle() == "ISS demo"
    finally:
        plt.close(fig)

    unnamed = _circular_trajectory()
    fig2 = plot_altitude(unnamed)
    try:
        assert fig2.get_suptitle() == ""
    finally:
        plt.close(fig2)


def test_render_to_buffer_smoke() -> None:
    traj = _circular_trajectory()
    fig = plot_speed(traj, frames=(Frame.EME2000, Frame.ITRF))
    try:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        assert buffer.getbuffer().nbytes > 0
    finally:
        plt.close(fig)
