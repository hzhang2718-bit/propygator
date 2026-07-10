"""Tests for the Feature 1.5 pass plots (``plot_sky_chart`` / ``plot_pass_timeline``,
build-plan Chunk 5).

Headless (the ``tests/plotting`` conftest pins the Agg backend). Two halves,
split by JVM contact:

- **Timeline** (pure Python, hand-built ``Pass`` fixtures, **no JVM**) —
  ``plot_pass_timeline`` draws only stored ``Pass`` scalar fields, so its tests
  never request the ``orekit`` fixture: bar count/heights, the 0–90 elevation
  axis, sunlit-vs-eclipse styling, magnitude annotations, the minimum bar width,
  the empty case, and a single-``Pass`` argument.
- **Sky chart** (``orekit`` fixture) — ``plot_sky_chart`` recomputes each pass's
  arc, so it is JVM-touching: the polar conventions (shared with ``plot_sky_track``,
  which stays untouched — its own suite guards that), two styled arcs per pass,
  the presence of both lit and eclipsed segments over a 2-day window, the title,
  and the single/sequence argument forms. The reference geometry is the fixed
  ISS (ZARYA) / Durham fixture shared with ``test_passes`` / ``test_visibility``.

"Snapshots" are structural + numerical-content assertions (the chunk-11 strategy),
not image diffs.
"""

from __future__ import annotations

import io

import matplotlib.colors as mcolors
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.figure import Figure

import propygator as pgr
from propygator import (
    TLE,
    Epoch,
    GroundStation,
    Pass,
    TimeScale,
    USTimeZone,
    plot_pass_timeline,
    plot_sky_chart,
)
from propygator.plotting.passes import (
    _ECLIPSE_BAR_STYLE,
    _ECLIPSE_TRACK_STYLE,
    _LIT_TRACK_STYLE,
    _MIN_BAR_WIDTH_DAYS,
    _SUNLIT_BAR_STYLE,
)


def _utc(iso: str) -> Epoch:
    return Epoch.from_iso(iso, scale=TimeScale.UTC)


def _hand_pass(
    rise_iso: str,
    culm_iso: str,
    set_iso: str,
    *,
    max_el: float,
    peak_mag: float | None,
    sunlit: bool = True,
    azimuths: tuple[float, float, float] = (120.0, 155.0, 200.0),
) -> Pass:
    return Pass(
        rise=_utc(rise_iso),
        culmination=_utc(culm_iso),
        set=_utc(set_iso),
        max_elevation_deg=max_el,
        peak_magnitude=peak_mag,
        sunlit_at_culmination=sunlit,
        rise_azimuth_deg=azimuths[0],
        culmination_azimuth_deg=azimuths[1],
        set_azimuth_deg=azimuths[2],
    )


def _timeline_passes() -> list[Pass]:
    """Three passes: two magnitude-annotated (one eclipsed at culmination)."""
    return [
        _hand_pass(
            "2026-06-23T07:46:41",
            "2026-06-23T07:49:59",
            "2026-06-23T07:53:18",
            max_el=51.6,
            peak_mag=-3.2,
            sunlit=True,
        ),
        _hand_pass(
            "2026-06-23T22:10:00",
            "2026-06-23T22:13:00",
            "2026-06-23T22:16:00",
            max_el=30.0,
            peak_mag=None,
            sunlit=False,
        ),
        _hand_pass(
            "2026-06-24T05:00:00",
            "2026-06-24T05:02:00",
            "2026-06-24T05:04:00",
            max_el=18.4,
            peak_mag=-1.1,
            sunlit=True,
        ),
    ]


# --- plot_pass_timeline (pure Python, no JVM) --------------------------------


def test_pass_timeline_returns_figure_with_bars():
    passes = _timeline_passes()
    fig = plot_pass_timeline(passes)
    try:
        assert isinstance(fig, Figure)
        ax = fig.axes[0]
        assert len(ax.patches) == len(passes)  # one bar per pass
        # Bar heights are the max elevations (order preserved).
        heights = [patch.get_height() for patch in ax.patches]
        assert heights == pytest.approx([p.max_elevation_deg for p in passes])
    finally:
        plt.close(fig)


def test_pass_timeline_elevation_axis_from_0_with_headroom_above_90():
    fig = plot_pass_timeline(_timeline_passes())
    try:
        ax = fig.axes[0]
        bottom, top = ax.get_ylim()
        assert bottom == pytest.approx(0.0)
        assert top >= 90.0  # headroom above the 90° max for magnitude labels
        assert max(ax.get_yticks()) == pytest.approx(90.0)  # ticks stop at 90
    finally:
        plt.close(fig)


def test_pass_timeline_styles_bars_by_sunlit_at_culmination():
    passes = _timeline_passes()
    fig = plot_pass_timeline(passes)
    try:
        ax = fig.axes[0]
        sunlit_rgba = mcolors.to_rgba(_SUNLIT_BAR_STYLE["facecolor"])
        eclipse_rgba = mcolors.to_rgba(_ECLIPSE_BAR_STYLE["facecolor"])
        for patch, p in zip(ax.patches, passes):
            expected = sunlit_rgba if p.sunlit_at_culmination else eclipse_rgba
            assert np.allclose(patch.get_facecolor(), expected)
        # The eclipsed pass is hatched, the sunlit ones are not.
        hatches = [patch.get_hatch() for patch in ax.patches]
        assert hatches == [None, "///", None]
    finally:
        plt.close(fig)


def test_pass_timeline_annotates_only_passes_with_magnitude():
    passes = _timeline_passes()  # two of three carry a magnitude
    fig = plot_pass_timeline(passes)
    try:
        # The only ax.annotate calls are the peak-magnitude labels.
        labels = {t.get_text() for t in fig.axes[0].texts}
        assert labels == {"-3.2", "-1.1"}
    finally:
        plt.close(fig)


def test_pass_timeline_floors_short_bar_width_keeping_rise_exact():
    # A 1-second pass would be an invisible sliver; the drawn width is floored,
    # but the left edge (rise) stays exact.
    short = _hand_pass(
        "2026-06-23T07:46:41",
        "2026-06-23T07:46:41",
        "2026-06-23T07:46:42",
        max_el=20.0,
        peak_mag=None,
    )
    fig = plot_pass_timeline([short])
    try:
        patch = fig.axes[0].patches[0]
        assert patch.get_width() == pytest.approx(_MIN_BAR_WIDTH_DAYS)
        rise_local = short.rise.to_datetime()
        assert patch.get_x() == pytest.approx(mdates.date2num(rise_local))
    finally:
        plt.close(fig)


def test_pass_timeline_tz_changes_axis_but_not_instant():
    passes = _timeline_passes()
    fig_utc = plot_pass_timeline(passes, tz=None)
    fig_est = plot_pass_timeline(passes, tz=USTimeZone.EASTERN)
    try:
        # The bar's absolute position (a UTC-referenced date number) is identical;
        # only the tick formatter's zone differs.
        x_utc = fig_utc.axes[0].patches[0].get_x()
        x_est = fig_est.axes[0].patches[0].get_x()
        assert x_utc == pytest.approx(x_est)
    finally:
        plt.close(fig_utc)
        plt.close(fig_est)


def test_pass_timeline_empty_is_a_valid_figure():
    fig = plot_pass_timeline([])
    try:
        ax = fig.axes[0]
        assert len(ax.patches) == 0
        bottom, top = ax.get_ylim()
        assert bottom == pytest.approx(0.0)
        assert top >= 90.0
    finally:
        plt.close(fig)


def test_pass_timeline_accepts_a_single_pass():
    (one,) = _timeline_passes()[:1]
    fig = plot_pass_timeline(one)
    try:
        assert len(fig.axes[0].patches) == 1
    finally:
        plt.close(fig)


# --- plot_sky_chart (JVM) ----------------------------------------------------

ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


@pytest.fixture(scope="module")
def iss_passes(orekit):
    """The fixed ISS/Durham 2-day search (all geometric passes), computed once."""
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2, name="ISS (ZARYA)")
    station = GroundStation("Durham", 35.99, -78.90, altitude_m=130.0)
    start = Epoch.from_iso("2026-06-23T00:00:00", scale=TimeScale.UTC)
    passes = pgr.find_passes(
        tle, station, 2 * 86400.0, start=start, visible_only=False, progress=False
    )
    return tle, station, passes


def _arcs_of_color(ax, hex_color: str):
    """The ``ax.lines`` whose colour matches ``hex_color`` (a styled arc group)."""
    target = mcolors.to_rgba(hex_color)
    return [
        ln for ln in ax.lines if np.allclose(mcolors.to_rgba(ln.get_color()), target)
    ]


@pytest.mark.usefixtures("orekit")
def test_sky_chart_polar_conventions(iss_passes):
    tle, station, passes = iss_passes
    fig = plot_sky_chart(tle, station, passes[:3])
    try:
        ax = fig.axes[0]
        assert ax.name == "polar"
        assert np.degrees(ax.get_theta_offset()) == pytest.approx(90.0)  # North up
        assert ax.get_theta_direction() == -1  # clockwise
        assert ax.get_rmin() == pytest.approx(0.0)  # zenith centre
        assert ax.get_rmax() == pytest.approx(90.0)  # horizon rim
    finally:
        plt.close(fig)


@pytest.mark.usefixtures("orekit")
def test_sky_chart_draws_two_arcs_per_pass(iss_passes):
    tle, station, passes = iss_passes
    subset = passes[:4]
    fig = plot_sky_chart(tle, station, subset)
    try:
        ax = fig.axes[0]
        # Each pass contributes exactly one lit and one eclipse arc line; the
        # rise/set/culmination glyphs are scatter collections, not lines.
        assert len(_arcs_of_color(ax, _LIT_TRACK_STYLE["color"])) == len(subset)
        assert len(_arcs_of_color(ax, _ECLIPSE_TRACK_STYLE["color"])) == len(subset)
        assert len(ax.lines) == 2 * len(subset)
    finally:
        plt.close(fig)


@pytest.mark.usefixtures("orekit")
def test_sky_chart_has_both_lit_and_eclipsed_segments(iss_passes):
    """Over 2 days Durham sees both daylight-shadow and fully-lit passes, so the
    figure carries finite data on both the lit and the eclipse arcs."""
    tle, station, passes = iss_passes
    fig = plot_sky_chart(tle, station, passes)
    try:
        ax = fig.axes[0]

        def _any_finite(arcs):
            return any(np.isfinite(a.get_ydata()).any() for a in arcs)

        assert _any_finite(_arcs_of_color(ax, _LIT_TRACK_STYLE["color"]))
        assert _any_finite(_arcs_of_color(ax, _ECLIPSE_TRACK_STYLE["color"]))
    finally:
        plt.close(fig)


@pytest.mark.usefixtures("orekit")
def test_sky_chart_title_from_tle_name(iss_passes):
    tle, station, passes = iss_passes
    fig = plot_sky_chart(tle, station, passes[:2])
    try:
        assert "ISS (ZARYA)" in fig._suptitle.get_text()
    finally:
        plt.close(fig)


@pytest.mark.usefixtures("orekit")
def test_sky_chart_accepts_single_pass_and_sequence(iss_passes):
    tle, station, passes = iss_passes
    fig_one = plot_sky_chart(tle, station, passes[0])
    fig_seq = plot_sky_chart(tle, station, passes[:1])
    try:
        assert len(fig_one.axes[0].lines) == 2  # one pass -> two arcs
        assert len(fig_seq.axes[0].lines) == 2
    finally:
        plt.close(fig_one)
        plt.close(fig_seq)


@pytest.mark.usefixtures("orekit")
def test_sky_chart_renders_to_buffer(iss_passes):
    tle, station, passes = iss_passes
    fig = plot_sky_chart(tle, station, passes[:3], tz=USTimeZone.EASTERN)
    try:
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        assert buffer.getbuffer().nbytes > 0
    finally:
        plt.close(fig)


def test_sky_chart_empty_frames_a_disk():
    """No passes -> a framed (empty) sky disk, no JVM needed (no arc to recompute)."""
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2, name="ISS (ZARYA)")
    station = GroundStation("Durham", 35.99, -78.90, altitude_m=130.0)
    fig = plot_sky_chart(tle, station, [])
    try:
        ax = fig.axes[0]
        assert ax.name == "polar"
        assert ax.get_rmax() == pytest.approx(90.0)
        assert len(ax.lines) == 0
    finally:
        plt.close(fig)
