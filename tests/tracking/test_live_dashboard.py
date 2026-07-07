"""Smoke tests for the live dashboard driver (Feature 1.4, build-plan chunk 8).

The live ``FuncAnimation`` loop is display-only and deliberately **not** snapshot-tested
(features.md §1.4). These are *wiring* smoke tests: ``live_track`` builds a
``FuncAnimation`` over the headless Chunk-7 engine, the adaptive 3-/4-panel layout is
correct, and a single frame tick runs clean against a frozen wall clock — exercising the
panel wiring (the chunk-6 ``_draw_*`` seams + ``observer_snapshot``) without asserting
pixels. The two display-seam helpers (``_format_clock`` / ``_twilight_facecolor``) are
unit-tested directly.

``Agg`` is forced so no GUI backend is needed; the session ``orekit`` fixture starts the
JVM (the buffer is a real SGP4 propagation + geodetic/topocentric projection), so
``conftest``'s ordering hook schedules this after the pure-Python ``tests/core/*``
"no JVM started" guards. The clock is frozen by monkeypatching ``Epoch.now`` so the
engine build and the ``update`` tick share one instant (the buffer stays fresh — no
stale notice — and the span arithmetic is deterministic).
"""

from __future__ import annotations

from datetime import timedelta, timezone

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import pytest
from matplotlib.collections import LineCollection, PathCollection

import propygator as pgr
from propygator import TLE, GroundStation
from propygator.core.time import Epoch, USTimeZone, _resolve_tz
from propygator.tracking.live import (
    _format_clock,
    _twilight_facecolor,
    live_track,
)

# Every dashboard test needs the JVM up + orekit-data loaded (real propagation). The
# filter is matplotlib's GC nag, which fires because we drive a single frame via
# ``anim._func(0)`` rather than a GUI event loop / ``plt.show()`` — it does not apply to
# a headless smoke test that never starts the animation's draw machinery.
pytestmark = [
    pytest.mark.usefixtures("orekit"),
    pytest.mark.filterwarnings(
        "ignore:Animation was deleted without rendering:UserWarning"
    ),
]

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3/1.4 tests.
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

# Compact buffer magnitudes — a cheap real propagation, not the §1.4 placeholders.
_STEP = 10.0
_HALF = 120.0
_REFRESH = 1.0


def _iss_tle() -> TLE:
    return TLE.from_strings(ISS_LINE1, ISS_LINE2)


@pytest.fixture(autouse=True)
def _close_figures():
    """Close any figure a dashboard build leaves open — even if an assertion or tick
    raises mid-test — so one red test can't leak Agg figures into the rest of the
    session (the figure tests in tests/plotting guard the same way with try/finally)."""
    yield
    plt.close("all")


@pytest.fixture
def frozen_now(monkeypatch) -> Epoch:
    """Freeze ``Epoch.now`` at the TLE epoch so the buffer stays fresh (no stale)."""
    fixed = _iss_tle().epoch
    monkeypatch.setattr(Epoch, "now", classmethod(lambda cls: fixed))
    return fixed


def _tick(anim) -> None:
    """Invoke the ``FuncAnimation``'s stored frame function once (no event loop).

    ``anim._func`` is the function ``FuncAnimation`` calls each tick — private but
    stable across matplotlib 3.x; there is no public single-step under the ``Agg``
    backend without a running event loop.
    """
    anim._func(0)


# --- adaptive layout + one clean frame --------------------------------------


def test_three_panel_builds_and_ticks(frozen_now):
    from matplotlib.animation import FuncAnimation

    anim = live_track(
        _iss_tle(), output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    assert isinstance(anim, FuncAnimation)

    fig = anim._fig
    # Three panels, none polar (no station -> no sky view).
    assert len(fig.axes) == 3
    assert all(ax.name != "polar" for ax in fig.axes)

    _tick(anim)  # one redraw must run clean
    # The live readout now lives in the figure suptitle (no per-panel titles): coords,
    # altitude, both speeds (inertial + ground), and a UTC clock.
    suptitle = fig._suptitle.get_text()
    assert "alt" in suptitle
    assert "km/s" in suptitle
    assert "gnd" in suptitle
    assert "UTC" in suptitle
    # The ground-track panel itself no longer carries a title.
    assert fig.axes[0].get_title() == ""
    # The legend gained the live-position key; no station key without a station.
    labels = [t.get_text() for t in fig.axes[0].get_legend().get_texts()]
    assert "current position" in labels
    assert "ground station" not in labels


def test_four_panel_with_station_builds_and_ticks(frozen_now):
    station = GroundStation("Durham", 36.0, -78.9)
    anim = live_track(
        _iss_tle(), station, output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )

    fig = anim._fig
    # Four panels, exactly one of them the polar sky view.
    assert len(fig.axes) == 4
    assert sum(ax.name == "polar" for ax in fig.axes) == 1

    _tick(anim)  # first frame
    _tick(anim)  # a second tick (still pre-drain) stays clean

    ground_ax = fig.axes[0]
    sky_ax = next(ax for ax in fig.axes if ax.name == "polar")
    # The ground-track legend gains both the live-position and ground-station keys.
    ground_labels = [t.get_text() for t in ground_ax.get_legend().get_texts()]
    assert "current position" in ground_labels
    assert "ground station" in ground_labels
    # The sky panel identifies its otherwise-unlabeled glyphs via a corner legend,
    # and carries no panel title (the suptitle owns the readout).
    sky_labels = [t.get_text() for t in sky_ax.get_legend().get_texts()]
    assert sky_labels == ["Sun", "Moon", "satellite"]
    assert sky_ax.get_title() == ""


def test_raw_tle_target_is_not_auto_refreshed(frozen_now):
    """A directly-supplied TLE builds the dashboard without any fetch path."""
    anim = live_track(
        _iss_tle(), output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    _tick(anim)


# --- mutate-in-place / interactivity (build-plan blitting chunk 2) -----------
#
# The interactivity headline: the scene is built once and mutated in place (no
# ax.clear(), no autoscale), so a user's zoom/pan survives every redraw *and* a buffer
# rebuild. These pass at blit=False. Artists are located off the axes: the live marker
# is the sole Line2D on the ground panel; the gradient track is the ground
# LineCollection carrying a colour array (the coastline has none); the start marker is
# the sole scatter PathCollection; the altitude curve/cursor are ground-adjacent lines.


def _ground_track_lc(fig) -> LineCollection:
    """The blue->red gradient track (the ground LineCollection with a colour array; the
    coastline LineCollection has none)."""
    return next(
        c
        for c in fig.axes[0].collections
        if isinstance(c, LineCollection) and c.get_array() is not None
    )


def _start_marker(fig) -> PathCollection:
    """The start-of-buffer marker: the first scatter PathCollection on the ground axis
    (created before any station/live scatter)."""
    return next(c for c in fig.axes[0].collections if isinstance(c, PathCollection))


def test_zoom_survives_redraw_three_panel(frozen_now):
    anim = live_track(
        _iss_tle(), output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    fig = anim._fig
    ax_ground, ax_alt = fig.axes[0], fig.axes[1]
    # A user zoom via the toolbar sets explicit limits (and disables autoscale).
    ax_ground.set_xlim(-40.0, 20.0)
    ax_ground.set_ylim(-10.0, 30.0)
    ax_alt.set_ylim(500.0, 520.0)

    _tick(anim)  # a non-rebuild redraw under the frozen clock

    assert ax_ground.get_xlim() == pytest.approx((-40.0, 20.0))
    assert ax_ground.get_ylim() == pytest.approx((-10.0, 30.0))
    assert ax_alt.get_ylim() == pytest.approx((500.0, 520.0))


def test_zoom_survives_redraw_four_panel_including_sky(frozen_now):
    station = GroundStation("Durham", 36.0, -78.9)
    anim = live_track(
        _iss_tle(), station, output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    fig = anim._fig
    ax_ground = fig.axes[0]
    sky_ax = next(ax for ax in fig.axes if ax.name == "polar")
    ax_ground.set_xlim(0.0, 60.0)
    sky_ax.set_rlim(0.0, 45.0)  # zoom the sky disk (radial limit == the polar y-axis)

    _tick(anim)  # updates glyph offsets + disk tint, must not reset the view

    assert ax_ground.get_xlim() == pytest.approx((0.0, 60.0))
    assert sky_ax.get_ylim() == pytest.approx((0.0, 45.0))


def test_rebuild_preserves_zoom_and_refreshes_curves(monkeypatch):
    base = _iss_tle().epoch
    monkeypatch.setattr(Epoch, "now", classmethod(lambda cls: base))
    anim = live_track(
        _iss_tle(), output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    fig = anim._fig
    ax_ground, ax_alt = fig.axes[0], fig.axes[1]
    alt_line = ax_alt.lines[0]
    start_marker = _start_marker(fig)

    ax_ground.set_xlim(-40.0, 20.0)
    ax_alt.set_ylim(500.0, 520.0)
    before_alt = np.array(alt_line.get_ydata())
    before_offset = np.array(start_marker.get_offsets())

    # Advance the wall clock past the displayed leading edge -> the tick rebuilds.
    monkeypatch.setattr(
        Epoch, "now", classmethod(lambda cls: base.shifted_by(_HALF + 5.0))
    )
    _tick(anim)

    # The zoom survives even a rebuild (limits are pinned, never autoscaled).
    assert ax_ground.get_xlim() == pytest.approx((-40.0, 20.0))
    assert ax_alt.get_ylim() == pytest.approx((500.0, 520.0))
    # The static curves refreshed to the new (re-centred) buffer.
    assert not np.array_equal(before_alt, np.array(alt_line.get_ydata()))
    assert not np.array_equal(before_offset, np.array(start_marker.get_offsets()))


def test_rebuild_widens_default_ylim_when_curve_exceeds(monkeypatch):
    """Untouched default y-limits widen (never shrink) when a rebuild's curve exceeds
    the first-buffer envelope, so the refreshed curve can't clip out of view.

    The short test buffer (~4 min) sees only a thin slice of the ISS's ~20 km
    per-orbit altitude oscillation, so a rebuild 15 min later is guaranteed to exceed
    the first envelope — the clipping this guards against. The other half of the
    property (a user-zoomed panel is never touched, even when the new curve exceeds
    its limits) is ``test_rebuild_preserves_zoom_and_refreshes_curves`` above.
    """
    base = _iss_tle().epoch
    monkeypatch.setattr(Epoch, "now", classmethod(lambda cls: base))
    anim = live_track(
        _iss_tle(), output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    fig = anim._fig
    ax_alt = fig.axes[1]
    lo0, hi0 = ax_alt.get_ylim()

    # 15 min later the re-centred buffer sits on a different part of the altitude
    # oscillation, outside the first envelope -> the rebuild must widen.
    monkeypatch.setattr(Epoch, "now", classmethod(lambda cls: base.shifted_by(900.0)))
    _tick(anim)

    lo1, hi1 = ax_alt.get_ylim()
    assert lo1 <= lo0 and hi1 >= hi0  # widen-only: neither edge ever moves inward
    assert (lo1, hi1) != (lo0, hi0)  # and it genuinely widened
    # The refreshed altitude curve fits inside the widened range.
    ydata = np.asarray(ax_alt.lines[0].get_ydata())
    assert lo1 <= float(ydata.min()) and float(ydata.max()) <= hi1


def test_dynamic_artists_mutate_in_place(monkeypatch):
    base = _iss_tle().epoch
    # One clock read at build, then one per tick (both pre-drain, so no rebuild).
    times = iter([base, base.shifted_by(10.0), base.shifted_by(40.0)])
    monkeypatch.setattr(Epoch, "now", classmethod(lambda cls: next(times)))
    anim = live_track(
        _iss_tle(), output_step=_STEP, half_window_s=_HALF, refresh_s=_REFRESH
    )
    fig = anim._fig
    live_marker = fig.axes[0].lines[0]
    alt_cursor = fig.axes[1].lines[1]
    readout = fig._suptitle

    _tick(anim)  # now = base + 10 s
    marker_1 = np.array(live_marker.get_xdata())
    cursor_1 = list(alt_cursor.get_xdata())
    text_1 = readout.get_text()

    _tick(anim)  # now = base + 40 s
    marker_2 = np.array(live_marker.get_xdata())
    cursor_2 = list(alt_cursor.get_xdata())
    text_2 = readout.get_text()

    # The dynamic artists' data changes across frames...
    assert not np.array_equal(marker_1, marker_2)
    assert cursor_1 != cursor_2
    assert text_1 != text_2
    # ...and the SAME artist objects persist (mutated in place, never recreated).
    assert fig.axes[0].lines[0] is live_marker
    assert fig.axes[1].lines[1] is alt_cursor
    assert fig._suptitle is readout


# --- display-seam helpers ----------------------------------------------------


def test_format_clock_defaults_to_utc():
    epoch = _iss_tle().epoch
    text = _format_clock(epoch)
    assert "UTC" in text
    # Matches the underlying timezone-aware UTC datetime to the second.
    assert epoch.to_datetime().strftime("%Y-%m-%d %H:%M:%S") in text


def test_format_clock_tz_shifts_civil_time():
    epoch = _iss_tle().epoch
    utc_text = _format_clock(epoch, tz=timezone.utc)
    # A fixed-offset zone (no IANA db / tzdata needed on Windows) proves the seam:
    # same instant, different civil offset -> different wall-clock string.
    shifted = _format_clock(epoch, tz=timezone(timedelta(hours=5)))
    assert shifted != utc_text


def test_format_clock_us_zone_renders_dst_correctly():
    # The shipped tz= path end-to-end (resolution + seam): a July instant renders
    # PDT, a January instant PST — the DST flip needs no caller code change. The
    # July string is the contract's worked example, pinned byte-for-byte.
    pacific = _resolve_tz(USTimeZone.PACIFIC)
    july = Epoch.from_iso("2026-07-05T18:42:03", scale=pgr.TimeScale.UTC)
    january = Epoch.from_iso("2026-01-05T18:42:03", scale=pgr.TimeScale.UTC)
    assert _format_clock(july, tz=pacific) == "2026-07-05 11:42:03 PDT"
    assert _format_clock(january, tz=pacific) == "2026-01-05 10:42:03 PST"


def test_twilight_facecolor_spans_day_to_night():
    day = _twilight_facecolor(10.0)
    civil = _twilight_facecolor(-3.0)
    nautical = _twilight_facecolor(-9.0)
    astro = _twilight_facecolor(-15.0)
    night = _twilight_facecolor(-30.0)
    # Five distinct bands.
    assert len({day, civil, nautical, astro, night}) == 5
    # Upper edges are inclusive; just past -18° tips into full night.
    assert _twilight_facecolor(0.0) == day
    assert _twilight_facecolor(-18.0) == astro
    assert _twilight_facecolor(-18.001) == night


# --- re-export ---------------------------------------------------------------


def test_live_track_reexported_at_top_level():
    assert pgr.live_track is live_track
