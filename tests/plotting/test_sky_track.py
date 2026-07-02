"""Tests for the polar sky-track plot (Feature 1.4, build-plan chunk 5).

Headless (the ``tests/plotting`` conftest pins the Agg backend); every test starts the
JVM via the session-scoped ``orekit`` fixture (the sky track is a topocentric
projection). The reference geometry is a real ISS TLE propagated over 24 h as seen from
a mid-latitude station (Durham, NC), which yields several discrete visible passes — so
the disjoint-arc (NaN-masking) path is genuinely exercised and the snapshot is not
vacuous.

"Snapshots" are realized as structural + numerical-content assertions (the chunk-11
strategy): the polar conventions (zenith-centre / horizon-rim, North-up clockwise), the
single dark-navy track, the NaN pen-lift between passes, the never-visible warn-once,
and the dashboard seams (precomputed ``azel=`` bypasses the JVM; ``track_style=``
overrides the line cosmetics).
"""

from __future__ import annotations

import io
import warnings

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.figure import Figure

import propygator as pgr
from propygator.plotting import trajectories as traj_mod
from propygator.plotting.style import TIMESERIES_COLOR
from propygator.plotting.trajectories import (
    _SKY_DISK_COLOR,
    _draw_sky_track,
    plot_sky_track,
)

pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3/1.4 tests.
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


@pytest.fixture(scope="module")
def iss_sky(orekit):
    """An ISS TEME trajectory over 24 h plus a mid-latitude station (built once).

    Durham sees ~8 discrete ISS passes over a day (max elevation ~43°), so the track
    has multiple visible arcs separated by long below-horizon stretches.
    """
    tle = pgr.TLE.from_strings(ISS_LINE1, ISS_LINE2)
    traj = pgr.propagate_tle(tle, 86400.0, output_step=60.0, start=tle.epoch)
    station = pgr.GroundStation("Durham", 35.99, -78.90, 130.0)
    return traj, station


# --- polar conventions + structure -----------------------------------------


def test_plot_sky_track_polar_conventions(iss_sky):
    traj, station = iss_sky
    fig = plot_sky_track(traj, station)
    try:
        assert isinstance(fig, Figure)
        ax = fig.axes[0]
        assert ax.name == "polar"
        # North at top, azimuth increasing clockwise.
        assert np.degrees(ax.get_theta_offset()) == pytest.approx(90.0)
        assert ax.get_theta_direction() == -1
        # Radius = zenith angle: zenith at the centre (0), horizon at the rim (90).
        assert ax.get_rmin() == pytest.approx(0.0)
        assert ax.get_rmax() == pytest.approx(90.0)
        # Fixed light-blue disk.
        assert np.allclose(ax.get_facecolor(), mcolors.to_rgba(_SKY_DISK_COLOR))
        # A single dark-navy track line (not the blue->red time gradient).
        assert len(ax.lines) == 1
        assert np.allclose(
            mcolors.to_rgba(ax.lines[0].get_color()), mcolors.to_rgba(TIMESERIES_COLOR)
        )
    finally:
        plt.close(fig)


def test_sky_track_radial_labels_read_as_elevation(iss_sky):
    """Radial rings are labelled in elevation (90° at the zenith centre, 0° at the
    horizon rim), even though the plotted radius is the zenith angle."""
    traj, station = iss_sky
    fig = plot_sky_track(traj, station)
    try:
        ax = fig.axes[0]
        # Each drawn ring's label is its elevation = 90 − (zenith-angle position); the
        # zenith centre (position 0) is intentionally left unlabelled.
        rings = {
            round(pos): text.get_text()
            for pos, text in zip(ax.get_yticks(), ax.get_yticklabels())
            if text.get_text()
        }
        assert rings == {30: "60", 60: "30", 90: "0"}
    finally:
        plt.close(fig)


def test_sky_track_lifts_pen_between_passes(iss_sky):
    """Below-horizon samples are NaN so the pen lifts between the discrete passes."""
    traj, station = iss_sky
    fig = plot_sky_track(traj, station)
    try:
        radius = fig.axes[0].lines[0].get_ydata()
        assert np.isfinite(radius).any()  # at least one visible pass is drawn
        assert np.isnan(radius).any()  # gaps between passes lift the pen (no chord)
    finally:
        plt.close(fig)


def test_render_to_buffer_smoke(iss_sky):
    traj, station = iss_sky
    fig = plot_sky_track(traj, station)
    try:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        assert buffer.getbuffer().nbytes > 0
    finally:
        plt.close(fig)


# --- never-visible span -----------------------------------------------------


def test_never_visible_warns_once(iss_sky):
    """min_elevation_deg above any reachable elevation -> empty disk + one warning."""
    traj, station = iss_sky
    # 91° is physically unreachable (elevation maxes at 90°), so no sample clears it.
    with pytest.warns(UserWarning, match="never clears the horizon"):
        fig = plot_sky_track(traj, station, min_elevation_deg=91.0)
    try:
        # The empty disk is still drawn (a line whose radii are all NaN).
        assert np.all(np.isnan(fig.axes[0].lines[0].get_ydata()))
    finally:
        plt.close(fig)


def test_never_visible_suppressed_when_flag_false(iss_sky):
    """warn_never_visible=False suppresses the warning (the live-dashboard path)."""
    traj, station = iss_sky
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    try:
        with warnings.catch_warnings(record=True) as records:
            warnings.simplefilter("always")
            _draw_sky_track(
                ax, traj, station, min_elevation_deg=91.0, warn_never_visible=False
            )
        assert not any("never clears the horizon" in str(w.message) for w in records)
    finally:
        plt.close(fig)


# --- dashboard seams --------------------------------------------------------


def test_azel_seam_bypasses_look_angles_track(monkeypatch, iss_sky):
    """A precomputed azel= triple draws without calling look_angles_track (no JVM)."""
    traj, station = iss_sky
    azimuth_deg = np.array([0.0, 90.0, 180.0])
    elevation_deg = np.array([10.0, 80.0, -5.0])  # last is below the horizon
    range_m = np.array([1.0e6, 1.0e6, 1.0e6])

    def _boom(*args, **kwargs):
        raise AssertionError("look_angles_track must not be called when azel is given")

    monkeypatch.setattr(traj_mod, "look_angles_track", _boom)

    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    try:
        _draw_sky_track(ax, traj, station, azel=(azimuth_deg, elevation_deg, range_m))
        radius = ax.lines[0].get_ydata()
        # Visible samples -> r = 90 - elevation; the below-horizon one -> NaN.
        np.testing.assert_allclose(radius[:2], [80.0, 10.0])
        assert np.isnan(radius[2])
    finally:
        plt.close(fig)


def test_track_style_overrides_line_color(iss_sky):
    """track_style overrides the default cosmetics (the dashboard's halo seam)."""
    traj, station = iss_sky
    fig, ax = plt.subplots(subplot_kw={"projection": "polar"})
    try:
        _draw_sky_track(ax, traj, station, track_style={"color": "red"})
        assert np.allclose(
            mcolors.to_rgba(ax.lines[0].get_color()), mcolors.to_rgba("red")
        )
    finally:
        plt.close(fig)
