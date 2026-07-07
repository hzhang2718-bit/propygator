"""The live-tracker buffer engine + dashboard driver (Feature 1.4, chunks 7–8).

The pure, headless state machine the live dashboard's ``FuncAnimation`` driver sits on
(chunk 7), plus the ``live_track`` verb and per-frame panel drawing that sit on top of
it (chunk 8, in the *Live dashboard* section at the foot of this module). The engine
maintains a rolling ``Trajectory`` **buffer centred on now** (the interval
``[now − half_window_s, now +
half_window_s]``) — so the ground track is a fixed trailing (flown) + leading
(predicted) path with a live marker sliding between them, and rebuilds the buffer by
re-propagating when the wall clock drains to the displayed leading edge (features.md
§1.4 "Buffer engine").

It is deliberately **display-free**: no matplotlib and no Orekit code live here. Every
JVM/topocentric crossing is delegated to the shipped verbs — ``propagate_tle`` (the
buffer), ``Trajectory.to_frame`` / ``Trajectory.at`` (the ground-relative speed + the
per-frame state), ``look_angles_track`` (the sky az/el), ``fetch_tle`` (auto-refresh) —
so the engine is pure composition and trivially testable headlessly. The clock is read
**once per frame by the driver** and threaded into the state-machine methods as an
explicit ``now`` (``needs_rebuild`` / ``maybe_rebuild`` / ``state_at``), so a single
frame never sees two different ``Epoch.now()`` readings.

**Per-rebuild precompute seam** (features.md §1.4 "Per-frame work"): the expensive,
JVM-crossing arrays are derived **once per buffer** and held for its lifetime — the
ground-relative (ITRF) speed (one ``to_frame``), the inertial speed read straight off
``buffer.velocities`` (``|v|`` is rotation-invariant, so no conversion), and (with a
station) the ``look_angles_track`` az/el/range. The chunk-8 redraw hands these to the
``_draw_*`` precomputed-array seams so a tick never re-runs an O(N) JVM loop.
``geodetic_track`` stays auto-memoized on the buffer, so the ground-track/altitude
panels pay their projection once on the first frame after a rebuild.

**Architecture invariants** (CLAUDE.md / architecture §7/§10): ``tracking/`` →
``tle/``/``core/`` is inward-legal; all module-top imports here are JVM-free *and*
matplotlib-free (the matplotlib / ``plotting`` imports stay in chunk 8's ``live_track``
body, the ``export_all`` precedent), so importing this module neither starts the JVM nor
pulls matplotlib. No Orekit type appears on any signature.
"""

from __future__ import annotations

import logging
import math
import warnings
from datetime import timezone
from typing import TYPE_CHECKING, Any, NamedTuple, cast

import numpy as np

from ..core.exceptions import StaleTLEWarning
from ..core.frames import Frame
from ..core.observation import look_angles_track
from ..core.time import Epoch, USTimeZone, _resolve_tz
from ..core.tle import TLE
from ..tle.propagator import propagate_tle
from ..tle.sources import _TTL_REALTIME_S, fetch_tle

if TYPE_CHECKING:
    from datetime import tzinfo

    from matplotlib.animation import FuncAnimation
    from matplotlib.artist import Artist
    from matplotlib.axes import Axes
    from matplotlib.collections import PathCollection
    from matplotlib.lines import Line2D
    from matplotlib.projections.polar import PolarAxes

    from ..core.observation import AzElRange, GeodeticPosition, GroundStation
    from ..core.states import State, Trajectory

logger = logging.getLogger(__name__)

# Leading guard margin (seconds): the buffer is propagated this far past the displayed
# leading edge (``now + half_window_s``) so the realized last sample sits beyond it even
# across a blocking rebuild — the live marker keeps sliding instead of freezing during
# the brief re-propagation stall. ``state_at``'s clamp is the safety net if a stall ever
# exceeds it. Engine-internal, not a ``live_track`` parameter (its signature is the §1.4
# three-magnitude one); the constructor accepts it for tests.
_LEADING_GUARD_S = 60.0


class _TrackerEngine:
    """The rolling now-centred buffer state machine behind ``live_track`` (chunk 8).

    Resolves the ``target`` (a ``TLE`` → re-propagate only; a name / NORAD id → fetched
    and **auto-refreshed**), builds the initial buffer eagerly, and then advances on an
    explicit per-frame ``now``. Holds the per-rebuild precomputed arrays the dashboard's
    speed and sky panels consume. Pure: no matplotlib, no Orekit code.
    """

    def __init__(
        self,
        target: TLE | str | int,
        station: GroundStation | None = None,
        *,
        output_step: float,
        half_window_s: float,
        guard_s: float = _LEADING_GUARD_S,
        now: Epoch | None = None,
    ) -> None:
        self.station = station
        self._output_step = float(output_step)
        self._half_window_s = float(half_window_s)
        self._guard_s = float(guard_s)
        # First build may surface propagate_tle's stale notice once; later builds
        # suppress the per-rebuild repeat (flipped True in _build_buffer).
        self._suppress_stale = False

        # Target resolution: a raw TLE is only ever re-propagated; a name / NORAD id is
        # fetched (realtime 6 h TTL) and re-fetched on every rebuild so a long-running
        # view stays accurate. ``_fetch_id`` is the refetch key (None <=> a raw TLE),
        # so ``auto_refresh`` reads straight off it.
        if isinstance(target, TLE):
            self._tle: TLE = target
            self._fetch_id: str | int | None = None
        else:
            self._tle = fetch_tle(target, ttl_s=_TTL_REALTIME_S)
            self._fetch_id = target

        self._build_buffer(now if now is not None else Epoch.now())
        logger.info(
            "live engine started: auto_refresh=%s station=%s output_step=%.1fs "
            "half_window=%.1fs guard=%.1fs",
            self.auto_refresh,
            None if station is None else station.name,
            self._output_step,
            self._half_window_s,
            self._guard_s,
        )

    @property
    def auto_refresh(self) -> bool:
        """Whether the target is re-fetched on rebuild (a fetched name/id, not a raw
        TLE)."""
        return self._fetch_id is not None

    # --- buffer construction ----------------------------------------------

    def _build_buffer(self, now: Epoch) -> None:
        """(Re)build the now-centred buffer and refresh the precomputed arrays.

        The buffer spans ``[now − half_window_s, now + half_window_s + guard_s]`` so the
        realized last sample sits past the displayed leading edge. The first build lets
        ``propagate_tle``'s ``StaleTLEWarning`` surface (the single startup notice, only
        if the TLE is genuinely stale); every later build filters **only** that
        category, so a real decay still raises ``TLEPropagationError`` (features §1.4).
        """
        start = now.shifted_by(-self._half_window_s)
        duration = 2.0 * self._half_window_s + self._guard_s
        with warnings.catch_warnings():
            if self._suppress_stale:
                warnings.simplefilter("ignore", StaleTLEWarning)
            buffer = propagate_tle(
                self._tle, duration, output_step=self._output_step, start=start
            )
        self._suppress_stale = True

        self.buffer = buffer
        # The displayed leading edge (drain trigger), distinct from the realized last
        # sample (buffer.end_epoch ≈ this + guard) the per-frame query clamps to.
        self._display_end_epoch = now.shifted_by(self._half_window_s)
        self._refresh_precompute()

    def _refresh_precompute(self) -> None:
        """Derive the per-buffer JVM-crossing arrays once (the chunk-8 redraw seam).

        ``inertial_speed_kms`` is read straight off ``buffer.velocities`` — the buffer
        is TEME (inertial) and ``|v|`` is rotation-invariant, so no conversion — while
        ``ground_speed_kms`` pays the single ``to_frame(ITRF)``. ``azel`` is the station
        look-angle track (or ``None`` with no station). ``geodetic_track`` is left to
        the first draw, which memoizes it on the buffer.
        """
        buf = self.buffer
        self.inertial_speed_kms = np.linalg.norm(buf.velocities, axis=1) / 1000.0
        self.ground_speed_kms = (
            np.linalg.norm(buf.to_frame(Frame.ITRF).velocities, axis=1) / 1000.0
        )
        self.azel = (
            None if self.station is None else look_angles_track(self.station, buf)
        )

    # --- per-frame state machine (pure functions of an explicit ``now``) --

    def needs_rebuild(self, now: Epoch) -> bool:
        """True once ``now`` has drained to the displayed leading edge.

        Drain-triggered, **not** on the ``refresh_s`` redraw tick: the path is static
        between re-propagations and rebuilds only as the buffer empties forward.
        """
        return now.seconds_since(self._display_end_epoch) >= 0.0

    def rebuild(self, now: Epoch) -> None:
        """Re-centre the buffer on ``now``; re-fetch first iff the target is fetched.

        The realtime cache TTL collapses repeated re-fetches to at most one CelesTrak
        round-trip per window, so this rides on the (rare) rebuild, never the tick.
        """
        if self._fetch_id is not None:
            self._tle = fetch_tle(self._fetch_id, ttl_s=_TTL_REALTIME_S)
        self._build_buffer(now)

    def maybe_rebuild(self, now: Epoch) -> bool:
        """Rebuild iff ``now`` has reached the leading edge; report whether it did."""
        if self.needs_rebuild(now):
            self.rebuild(now)
            return True
        return False

    def state_at(self, now: Epoch) -> State:
        """The interpolated state at ``now``, clamped to the realized last sample.

        ``buffer.at(min(now, buffer.end_epoch))`` reads the realized span endpoint
        through the public ``end_epoch`` accessor rather than re-deriving the sample
        grid, so a stall longer than the guard degrades to a momentarily frozen marker
        instead of a ``Trajectory.at`` out-of-span ``ValueError`` (features.md §1.4).
        """
        end = self.buffer.end_epoch
        clamped = end if now.seconds_since(end) > 0.0 else now
        return self.buffer.at(clamped)


# ---------------------------------------------------------------------------
# Live dashboard (build-plan chunk 8): the FuncAnimation driver + panels.
# ---------------------------------------------------------------------------
#
# The display layer over the engine above. Every matplotlib / plotting import stays
# inside ``live_track``'s body (the ``export_all`` precedent), so this module's top
# stays JVM- *and* matplotlib-free (pinned by an AST test); the one tracking -> plotting
# edge exists only at call time, when the user asks for a live view. The scene is built
# **once** and thereafter only *mutated in place* (build-once / mutate-in-place, not
# clear-and-redraw), so a user's toolbar zoom/pan survives every redraw and a buffer
# rebuild -- the general-upgrades-1 "Live Dashboard Blitting" contract; the panels reuse
# the shipped 1.1 ``_draw_*`` primitives via their chunk-6 default-preserving seams plus
# ``_draw_sky_track``, capturing each primitive's artist handle to mutate on rebuild.

#: Figure sizes (inches) for the two adaptive layouts (tunable placeholders).
_FIGSIZE_DASHBOARD_3 = (11.0, 9.0)
_FIGSIZE_DASHBOARD_4 = (13.5, 9.0)

#: ``GridSpec`` ratios straight from features.md §1.4 (tunable placeholders): the ground
#: track is the double-height hero row; the sky column is the wider of the two.
_HEIGHT_RATIOS = (2, 1, 1)
_WIDTH_RATIOS = (1.4, 1)

#: ``GridSpec`` spacing + outer margins (a manual layout, set once — no per-frame
#: ``constrained_layout`` re-solve / jitter): inter-panel gaps (``hspace``/``wspace``)
#: plus margins that reserve room for the suptitle (``top``) and axis labels. The
#: 4-panel view wants a slightly taller gap. All tunable.
_GRID_KW_3: dict[str, float] = {
    "hspace": 0.3,
    "wspace": 0.2,
    "top": 0.90,
    "bottom": 0.08,
    "left": 0.08,
    "right": 0.95,
}
_GRID_KW_4: dict[str, float] = {
    "hspace": 0.4,
    "wspace": 0.2,
    "top": 0.90,
    "bottom": 0.08,
    "left": 0.07,
    "right": 0.95,
}

#: Suptitle vertical position (figure fraction). Below the matplotlib default (0.98) so
#: the live readout sits a little closer to the panels rather than at the very top edge.
_SUPTITLE_Y = 0.95

#: Speed overlay: inertial (EME2000 — reuses the shipped navy ``TIMESERIES_COLOR``,
#: imported in-body) vs ground-relative (ITRF, a contrasting rust). The gap between the
#: two curves *is* the Earth-rotation contribution — the speed panel's teaching point.
_SPEED_GROUND_COLOR = "#c1440e"
_SPEED_INERTIAL_LABEL = "Inertial (EME2000)"
_SPEED_GROUND_LABEL = "Ground-relative (ITRF)"

#: The moving now-cursor on the two time-series panels (a dashed vertical line).
_CURSOR_STYLE: dict[str, Any] = {
    "color": "#444444",
    "linestyle": "--",
    "linewidth": 1.0,
    "zorder": 6,
}

#: The live heading-oriented sub-satellite triangle on the ground track — bright yellow
#: so it reads against the blue start circle and the blue->red track. No ``"marker"``
#: key (the rotated ``MarkerStyle`` is passed alongside), mirroring ``MARKER_END``.
_LIVE_MARKER: dict[str, Any] = {
    "c": "#ffd400",
    "edgecolors": "black",
    "s": 130.0,
    "zorder": 7,
}

#: The observer's ground station on the map (4-panel only): a dark-blue star, distinct
#: in both shape and colour from the start circle and the yellow live triangle.
_STATION_MARKER: dict[str, Any] = {
    "marker": "*",
    "c": "#00008b",
    "edgecolors": "white",
    "s": 200.0,
    "zorder": 6,
}

#: Sky-panel glyphs: Sun (orange, so it never reads as the yellow satellite), Moon
#: (pale), and the live satellite (a yellow star). Identified by the sky-panel legend.
_SUN_MARKER: dict[str, Any] = {
    "marker": "o",
    "c": "#ff8c00",
    "edgecolors": "#b3560b",
    "s": 180.0,
    "zorder": 6,
}
_MOON_MARKER: dict[str, Any] = {
    "marker": "o",
    "c": "#dfe6ef",
    "edgecolors": "#6b7280",
    "s": 110.0,
    "zorder": 6,
}
_LIVE_SKY_MARKER: dict[str, Any] = {
    "marker": "*",
    "c": "#ffd400",
    "edgecolors": "black",
    "s": 220.0,
    "zorder": 7,
}

#: Sky-panel glyph legend: a horizontal 3-entry strip *below* the polar disk (a corner
#: box overlapped the rim), with roomy spacing so the keys don't crowd. All tunable.
_SKY_LEGEND_KW: dict[str, Any] = {
    "loc": "upper center",
    "bbox_to_anchor": (0.5, -0.08),
    "ncol": 3,
    "fontsize": 11,
    "framealpha": 0.9,
    "columnspacing": 1.6,
    "handletextpad": 0.5,
    "borderaxespad": 0.35,
}

#: Sun-tint background bands, keyed on the observer's Sun elevation (degrees): day, the
#: three twilight bands (civil/nautical/astronomical), and full night.
_TWILIGHT_DAY = "#bfe3f2"
_TWILIGHT_CIVIL = "#8fb7d8"
_TWILIGHT_NAUTICAL = "#52739f"
_TWILIGHT_ASTRO = "#2c3c66"
_TWILIGHT_NIGHT = "#0b1233"


def _format_clock(epoch: Epoch, *, tz: tzinfo = timezone.utc) -> str:
    """Format ``epoch`` as a civil wall-clock string in ``tz`` (UTC by default).

    The features.md §1.4 tz-ready clock seam, now fed by ``live_track``'s ``tz=``
    (the v0.5.0 civil-time upgrade): ``Epoch.to_datetime()`` returns a
    timezone-aware UTC ``datetime``, and ``.astimezone(tz)`` re-expresses it as civil
    local time (DST included) — a pure *display* offset, never a ``TimeScale`` change,
    so it never touches the leap-second / deferred-UT1 machinery. ``live_track``
    resolves its ``tz=`` once at entry (``core.time._resolve_tz``; a ``USTimeZone``
    member lowers to ``zoneinfo.ZoneInfo``, which needs the declared ``tzdata``
    package on Windows) and threads the result here; the ``%Z`` token renders the
    active zone abbreviation ("UTC", "EST"/"EDT") so the offset self-documents.
    """
    return epoch.to_datetime().astimezone(tz).strftime("%Y-%m-%d %H:%M:%S %Z")


def _format_latlon(geo: GeodeticPosition) -> str:
    """Hemisphere-tagged ``12.34°N, 56.78°W`` sub-satellite coordinates."""
    lat_hemi = "N" if geo.latitude_deg >= 0.0 else "S"
    lon_hemi = "E" if geo.longitude_deg >= 0.0 else "W"
    return (
        f"{abs(geo.latitude_deg):.2f}°{lat_hemi}, "
        f"{abs(geo.longitude_deg):.2f}°{lon_hemi}"
    )


def _twilight_facecolor(sun_elevation_deg: float) -> str:
    """Map the observer's Sun elevation to the sky-disk background tint.

    Ambient context only (not pass-visibility shading — that stays a Feature 1.5
    concern): day (Sun up) -> light blue; the three twilight bands (civil 0..-6°,
    nautical -6..-12°, astronomical -12..-18°) -> a dusk gradient; full night
    (< -18°) -> navy. Upper edges are inclusive.
    """
    if sun_elevation_deg >= 0.0:
        return _TWILIGHT_DAY
    if sun_elevation_deg >= -6.0:
        return _TWILIGHT_CIVIL
    if sun_elevation_deg >= -12.0:
        return _TWILIGHT_NAUTICAL
    if sun_elevation_deg >= -18.0:
        return _TWILIGHT_ASTRO
    return _TWILIGHT_NIGHT


def _sky_glyph_offset(azel: AzElRange) -> tuple[float, float]:
    """Polar ``(theta, radius)`` offset for a sky glyph.

    The mapping shared with ``_draw_sky_track``: theta = azimuth (radians), radius =
    zenith angle (90° − elevation). A below-horizon body (radius > 90°) lands outside
    the ``rlim`` and is clipped — the desired "not currently up" behaviour. Fed to
    ``PathCollection.set_offsets`` each frame (the mutate-in-place sky seam).
    """
    return math.radians(azel.azimuth_deg), 90.0 - azel.elevation_deg


def _plot_sky_glyph(ax: Axes, style: dict[str, Any]) -> PathCollection:
    """Create one persistent body/satellite glyph on the polar sky axis (build-once).

    The live dashboard's mutate-in-place sky seam (wrinkle 4): a single-point scatter
    whose position ``update()`` drives each frame via ``set_offsets`` (from
    :func:`_sky_glyph_offset`). Built with a NaN placeholder offset so nothing shows
    before the first frame sets a real position, and so the NaN can't perturb the polar
    ``rlim``. Returns the ``PathCollection`` handle.
    """
    return ax.scatter([math.nan], [math.nan], **style)


#: Fractional margin above/below the fixed altitude/speed y-ranges. The ranges come from
#: the first buffer and are held across rebuilds (contract "Fixed axis limits"); a small
#: pad keeps the curve off the panel edges without ever autoscaling.
_Y_PAD_FRACTION = 0.05


def _padded_limits(
    values: np.ndarray, *, frac: float = _Y_PAD_FRACTION
) -> tuple[float, float]:
    """A ``(low, high)`` range enclosing ``values`` with a small fractional margin.

    The fixed-limit helper for the altitude/speed panels: the first buffer's envelope
    plus a ``frac`` margin, set once and never autoscaled. A flat array (zero span) gets
    a nonzero margin anyway so the line isn't pinned to the panel edge.
    """
    low = float(np.min(values))
    high = float(np.max(values))
    span = high - low
    pad = frac * span if span > 0.0 else frac * max(abs(high), 1.0)
    return low - pad, high + pad


def _widen_ylim_if_untouched(
    ax: Axes, auto_ylim: tuple[float, float], values: np.ndarray
) -> tuple[float, float]:
    """Widen the dashboard-set y-limits to enclose ``values``; never shrink, never
    touch a user's zoom.

    The rebuild-time companion to the pinned-limits rule (contract "Fixed axis limits"
    caveat): the y-range is pinned from the *first* buffer, but a later buffer can
    exceed that envelope — a buffer shorter than one orbit sees only a slice of the
    per-orbit altitude oscillation, and an eccentric orbit or drag decay drifts the
    same way — which would clip the refreshed curve out of view. On rebuild the range
    is therefore widened to the union of the stored auto-limits and the new buffer's
    padded envelope, **widen-only** (shrinking mid-session would fight the very zoom
    the pinned limits protect) and **only while the axes still sit at the dashboard's
    own last-applied limits** (``auto_ylim``): once the user zooms or pans the panel,
    their viewport is never touched. Returns the limits the dashboard now considers
    its own (``auto_ylim`` unchanged if nothing was applied).
    """
    needed = _padded_limits(values)
    widened = (min(auto_ylim[0], needed[0]), max(auto_ylim[1], needed[1]))
    if widened == auto_ylim:
        return auto_ylim  # new envelope already fits; nothing to do
    if tuple(ax.get_ylim()) != auto_ylim:
        return auto_ylim  # the user zoomed/panned this panel; leave their view alone
    ax.set_ylim(*widened)
    return widened


class _SkyArtists(NamedTuple):
    """The 4-panel sky-panel artist handles (``None`` in the 3-panel layout).

    Groups the persistent sky handles so the mutate-in-place closures narrow the whole
    optional panel with one ``if sky is not None`` check: the static ``track`` line
    (reset on rebuild) and the three dynamic Sun/Moon/satellite glyph collections
    (``set_offsets`` each frame). ``ax`` and ``station`` ride along for the per-frame
    facecolor retint and the ``observer_snapshot`` call.
    """

    ax: PolarAxes
    station: GroundStation
    track: Line2D
    sun: PathCollection
    moon: PathCollection
    sat: PathCollection


def live_track(
    target: TLE | str | int,
    station: GroundStation | None = None,
    *,
    output_step: float = 10.0,
    half_window_s: float = 2700.0,
    refresh_s: float = 1.0,
    tz: USTimeZone | tzinfo | None = None,
) -> FuncAnimation:
    """Launch a live, self-updating dashboard tracking ``target`` in real time.

    The headline live verb (features.md §1.4): a ``matplotlib.animation.FuncAnimation``
    over the rolling now-centred :class:`_TrackerEngine` buffer, drawn across **three or
    four panels** — ground track, altitude, speed, plus a polar **sky view** when a
    ``station`` is supplied. ``target`` is a :class:`~propygator.core.tle.TLE`
    (re-propagated only) or a friendly name / NORAD id (fetched and **auto-refreshed**).

    The three time parameters are distinct clocks (all tunable placeholders, not
    contract): ``output_step`` and ``half_window_s`` are *simulation-time* (the buffer's
    sample spacing and per-side span), while ``refresh_s`` is the *wall-clock* redraw
    cadence; the view is real-time, so one wall second advances ``now`` by one sim
    second. Re-propagation is drain-triggered (never on the redraw tick); between
    rebuilds the panels are static save the **now-indicators** — a sliding
    heading-marked sub-satellite point on the ground track and a star on the sky, a
    moving vertical cursor on the two time-series — so every panel reads as live, and
    the per-frame redraw is O(1) (the engine's precomputed speed/az-el arrays feed the
    chunk-6 ``_draw_*`` seams, so no tick re-crosses the JVM in an O(N) loop). The scene
    is **built once and mutated in place** — nothing is ever cleared or re-autoscaled,
    and every axis limit is pinned from the first buffer — so a toolbar zoom/pan
    survives every redraw *and* every buffer rebuild (the v0.5.0 mutate-in-place
    upgrade; blitting stays a named later optimization).

    ``tz`` localizes the **suptitle readout clock only** (the v0.5.0 civil-time
    upgrade; a pure display offset, never a ``TimeScale`` change): ``None`` keeps
    the UTC default (byte-identical to before), a
    :class:`~propygator.core.time.USTimeZone` member renders DST-correct US civil
    time (the ``%Z`` token shows the active abbreviation, so ``PDT``/``PST`` flips
    automatically), and a raw ``tzinfo`` is the non-US escape hatch. Every other
    panel is elapsed-hours or spatial, so nothing else has a wall clock to localize.

    Returns the native ``FuncAnimation`` (consistent with "every ``plot_*`` returns its
    native figure", architecture §10). **You must keep a reference to it** —
    ``anim = live_track(...)`` — or matplotlib garbage-collects the animation and it
    silently stops. Live animation needs a GUI backend (``%matplotlib qt`` / ``tk``, or
    running as a script) or the in-notebook ``%matplotlib widget``; the notebook
    *default* ``%matplotlib inline`` backend draws only a static first frame (documented
    caveat). The JVM starts on the first propagation; matplotlib / ``plotting`` are
    imported here in-body (the ``export_all`` precedent), so importing ``propygator``
    neither starts the JVM nor adds any matplotlib import beyond what the top-level
    ``plot_*`` verbs already load.
    """
    # Resolve tz ONCE at entry (contract: Part A -> Resolution) -- a bad value
    # fails fast, before any fetch/propagation or figure work.
    tz_resolved = _resolve_tz(tz)

    import matplotlib.pyplot as plt
    from matplotlib.animation import FuncAnimation
    from matplotlib.collections import PathCollection
    from matplotlib.patheffects import withStroke

    from ..core.frames import geodetic_track, to_geodetic
    from ..core.observation import observer_snapshot
    from ..plotting.style import (
        TIMESERIES_COLOR,
        _heading_marker,
        _marker_legend_handle,
        _mpl_style,
    )
    from ..plotting.timeseries import (
        _HOURS_XLABEL,
        _draw_altitude,
        _draw_speed,
        _elapsed_hours,
    )
    from ..plotting.trajectories import (
        _dateline_segments,
        _draw_ground_track,
        _draw_sky_track,
        _track_heading_deg,
    )

    engine = _TrackerEngine(
        target,
        station,
        output_step=output_step,
        half_window_s=half_window_s,
    )
    # The dashboard's halo-stroked sky track (contrast against the day->night tint); the
    # default disk-blue line stays the standalone verb's, overridden only here.
    sky_track_style = {
        "color": TIMESERIES_COLOR,
        "linewidth": 1.8,
        "path_effects": [withStroke(linewidth=3.5, foreground="white")],
    }

    with _mpl_style():
        if station is not None:
            fig = plt.figure(figsize=_FIGSIZE_DASHBOARD_4)
            gs = fig.add_gridspec(
                3,
                2,
                height_ratios=_HEIGHT_RATIOS,
                width_ratios=_WIDTH_RATIOS,
                **_GRID_KW_4,
            )
            ax_ground = fig.add_subplot(gs[0, :])
            ax_alt = fig.add_subplot(gs[1, 0])
            ax_speed = fig.add_subplot(gs[2, 0], sharex=ax_alt)
            ax_sky: Axes | None = fig.add_subplot(gs[1:, 1], projection="polar")
        else:
            fig = plt.figure(figsize=_FIGSIZE_DASHBOARD_3)
            gs = fig.add_gridspec(3, 1, height_ratios=_HEIGHT_RATIOS, **_GRID_KW_3)
            ax_ground = fig.add_subplot(gs[0, 0])
            ax_alt = fig.add_subplot(gs[1, 0])
            ax_speed = fig.add_subplot(gs[2, 0], sharex=ax_alt)
            ax_sky = None

        # --- Build the scene once (contract: Artist split). Every artist is created
        # here and thereafter only *mutated* -- static artists refreshed on rebuild by
        # _draw_static (never ax.clear(), which re-autoscales and would wipe a user's
        # zoom); dynamic artists mutated each frame by update(), which returns the
        # animated set (unused at blit=False -- blitting stays a named later
        # optimization). All axis limits are pinned once, never autoscaled, so a rebuild
        # can't blow away zoom.
        buffer0 = engine.buffer

        # Ground track (static): the gradient LineCollection + start marker + (4-panel)
        # station marker + legend. The end triangle is suppressed (in a centred buffer
        # the "end" is the future leading edge, not the satellite); its direction glyph
        # rides the live marker below. The legend gains a "current position" key, plus a
        # "ground station" key with a station (forwarded as proxies into the primitive).
        ground_handles = [
            _marker_legend_handle(_LIVE_MARKER, "current position", marker="^"),
        ]
        if station is not None:
            ground_handles.append(
                _marker_legend_handle(_STATION_MARKER, "ground station")
            )
        ground_lc = _draw_ground_track(
            ax_ground,
            buffer0,
            endpoint_labels=("past edge", "future edge"),
            suppress_end_marker=True,
            extra_legend_handles=ground_handles,
        )
        assert ground_lc is not None  # color_by_time default True -> gradient mappable
        # The start marker is the sole scatter PathCollection _draw_ground_track adds
        # (the track and coastline are LineCollections); capture it *before* we add our
        # own scatters. It re-centres each rebuild (set_offsets in _draw_static). Assert
        # the "sole PathCollection" invariant so a future primitive scatter fails loudly
        # here instead of silently binding start_marker to the wrong collection.
        scatters = [c for c in ax_ground.collections if isinstance(c, PathCollection)]
        assert len(scatters) == 1, (
            f"expected exactly 1 start-marker scatter from _draw_ground_track, "
            f"found {len(scatters)}"
        )
        start_marker = scatters[0]
        if station is not None:
            ax_ground.scatter(
                station.longitude_deg, station.latitude_deg, **_STATION_MARKER
            )
        # Wrinkle 1 -- the live sub-satellite marker as one persistent Line2D (a single
        # point) whose rotated marker + position update each frame. Built through the
        # shared _marker_legend_handle so the _LIVE_MARKER scatter-kwargs -> Line2D
        # mapping (c/edgecolors/s -> markerfacecolor/markeredgecolor/markersize=root-s)
        # lives in one place; a "_"-prefixed label keeps it out of any auto-legend.
        live_marker = _marker_legend_handle(_LIVE_MARKER, "_live_marker", marker="^")
        live_marker.set_zorder(_LIVE_MARKER["zorder"])
        ax_ground.add_line(live_marker)

        # Altitude (static curve) + the moving now-cursor (dynamic).
        alt_line = _draw_altitude(ax_alt, buffer0)
        alt_cursor = ax_alt.axvline(0.0, **_CURSOR_STYLE)

        # Speed (static): inertial + ground-relative overlaid (their gap is the
        # Earth-rotation story), both from the engine's precomputed arrays (no per-frame
        # to_frame); + the now-cursor. The bottom panel owns the x-axis label.
        inertial_line = _draw_speed(
            ax_speed,
            buffer0,
            speeds_kms=engine.inertial_speed_kms,
            color=TIMESERIES_COLOR,
            label=_SPEED_INERTIAL_LABEL,
        )
        ground_line = _draw_speed(
            ax_speed,
            buffer0,
            speeds_kms=engine.ground_speed_kms,
            color=_SPEED_GROUND_COLOR,
            label=_SPEED_GROUND_LABEL,
        )
        speed_cursor = ax_speed.axvline(0.0, **_CURSOR_STYLE)
        ax_speed.set_xlabel(_HOURS_XLABEL)

        # Fixed, never-autoscaled limits from the first buffer (contract: Fixed axis
        # limits) -- held across rebuilds so a user zoom survives. Ground and sky are
        # already pinned by their primitives; give the altitude/speed panels stable
        # y-ranges and a shared x-range here. The dashboard remembers the y-limits it
        # set itself so _draw_static can widen them (never shrink) if a later buffer's
        # curve would clip -- without ever touching a panel the user has zoomed.
        elapsed_h0 = _elapsed_hours(buffer0)
        _itrf0, _lat0, _lon0, alt_m0 = geodetic_track(buffer0)
        auto_alt_ylim = _padded_limits(alt_m0 / 1000.0)
        ax_alt.set_ylim(*auto_alt_ylim)
        auto_speed_ylim = _padded_limits(
            np.concatenate([engine.inertial_speed_kms, engine.ground_speed_kms])
        )
        ax_speed.set_ylim(*auto_speed_ylim)
        ax_alt.set_xlim(0.0, float(elapsed_h0[-1]))  # shared x -> ax_speed follows

        # Sky (4-panel): the static az/el track/disk/legend + the dynamic Sun/Moon/sat
        # glyphs (persistent PathCollections mutated via set_offsets -- wrinkle 4). The
        # corner legend identifies the otherwise-unlabeled glyphs; no panel title (the
        # readout owns it). ax_sky is non-None iff station is non-None.
        sky: _SkyArtists | None = None
        if ax_sky is not None and station is not None:
            polar = cast("PolarAxes", ax_sky)
            sky_track_line = _draw_sky_track(
                polar,
                buffer0,
                station,
                azel=engine.azel,
                track_style=sky_track_style,
                warn_never_visible=False,
            )
            sky = _SkyArtists(
                ax=polar,
                station=station,
                track=sky_track_line,
                sun=_plot_sky_glyph(ax_sky, _SUN_MARKER),
                moon=_plot_sky_glyph(ax_sky, _MOON_MARKER),
                sat=_plot_sky_glyph(ax_sky, _LIVE_SKY_MARKER),
            )
            ax_sky.legend(
                handles=[
                    _marker_legend_handle(_SUN_MARKER, "Sun"),
                    _marker_legend_handle(_MOON_MARKER, "Moon"),
                    _marker_legend_handle(_LIVE_SKY_MARKER, "satellite"),
                ],
                **_SKY_LEGEND_KW,
            )

        # Live readout (still the figure suptitle in this chunk): created once, set_text
        # each frame -- a mutate-in-place artist so fig._suptitle stays stable.
        readout = fig.suptitle("", y=_SUPTITLE_Y)

    # The dynamic (animated) artist set -- created once, thereafter only mutated in
    # place each frame by update(), which returns it (unused at blit=False, but names
    # the animated set a blit layer would hand to FuncAnimation).
    dynamic: list[Artist] = [live_marker, alt_cursor, speed_cursor, readout]
    if sky is not None:
        dynamic += [sky.sun, sky.moon, sky.sat]

    def _draw_static(buffer: Trajectory) -> None:
        """Refresh the static artists for ``buffer`` in place (no clearing).

        Called on each buffer rebuild. Re-setting existing artists' data (never
        ``ax.clear()``) is why a rebuild can't reset a user's zoom -- the limits stay
        pinned. Must **not** re-invoke the ``_draw_*`` primitives -- they create fresh
        artists, re-pin limits, and re-rasterize the basemap (contract: Artist split).
        """
        # One geodetic projection (memoized on the buffer) gives lon/lat for the track +
        # start marker and the altitude in a single unpack.
        _itrf, lat, lon, alt_m = geodetic_track(buffer)
        hours = _elapsed_hours(buffer)
        # The kept-segment count varies as the track crosses the dateline differently,
        # so recompute the segments and the colour array together.
        segments, seg_hours = _dateline_segments(lon, lat, hours)
        ground_lc.set_segments(list(segments))
        ground_lc.set_array(seg_hours)
        ground_lc.set_clim(0.0, float(hours[-1]))
        start_marker.set_offsets([[lon[0], lat[0]]])

        alt_line.set_data(hours, alt_m / 1000.0)
        inertial_line.set_data(hours, engine.inertial_speed_kms)
        ground_line.set_data(hours, engine.ground_speed_kms)

        # A new buffer can exceed the first buffer's pinned y-envelope (short buffer,
        # eccentric orbit, drag decay) and would clip out of view: widen the
        # dashboard's own limits to fit -- never shrinking, and never touching a panel
        # the user has zoomed/panned (see _widen_ylim_if_untouched).
        nonlocal auto_alt_ylim, auto_speed_ylim
        auto_alt_ylim = _widen_ylim_if_untouched(ax_alt, auto_alt_ylim, alt_m / 1000.0)
        auto_speed_ylim = _widen_ylim_if_untouched(
            ax_speed,
            auto_speed_ylim,
            np.concatenate([engine.inertial_speed_kms, engine.ground_speed_kms]),
        )

        if sky is not None and engine.azel is not None:
            azimuth_deg, elevation_deg, _range_m = engine.azel
            visible = elevation_deg >= 0.0
            sky.track.set_data(
                np.radians(azimuth_deg),
                np.where(visible, 90.0 - elevation_deg, np.nan),
            )

    def update(_frame: object) -> list[Artist]:
        # One wall-clock read per frame, threaded through the pure engine methods.
        now = Epoch.now()
        # Drain-triggered rebuild: mutate the static curves in place (never ax.clear()).
        if engine.maybe_rebuild(now):
            _draw_static(engine.buffer)
        buffer = engine.buffer

        state_now = engine.state_at(now)  # .epoch is clamped to the realized edge
        clamped = state_now.epoch
        # One ITRF conversion per frame, reused for the sub-point *and* ground speed;
        # the inertial speed reads off the TEME state directly (|v| invariant).
        itrf_now = state_now.to_frame(Frame.ITRF)
        geo = to_geodetic(itrf_now)
        v_inertial_kms = float(np.linalg.norm(state_now.velocity)) / 1000.0
        v_ground_kms = float(np.linalg.norm(itrf_now.velocity)) / 1000.0
        elapsed_s = clamped.seconds_since(buffer.start_epoch)
        elapsed_h = elapsed_s / 3600.0

        # Ground: rotate + move the live sub-satellite marker (wrinkle 1). The heading
        # reads the direction *now* (the valid segment nearest the clamped sample),
        # not at the buffer's leading edge; _track_heading_deg clamps the index.
        _itrf, lat, lon, _alt = geodetic_track(buffer)  # memoized on the buffer
        heading = _track_heading_deg(
            lon, lat, at_index=int(round(elapsed_s / output_step))
        )
        live_marker.set_marker(_heading_marker(heading))
        live_marker.set_data([geo.longitude_deg], [geo.latitude_deg])

        # The two time-series now-cursors (blended transform: x in data, y in axes).
        alt_cursor.set_xdata([elapsed_h, elapsed_h])
        speed_cursor.set_xdata([elapsed_h, elapsed_h])

        # Sky (4-panel): move the Sun/Moon/sat glyphs and retint the disk -- every JVM
        # quantity from one observer_snapshot station-frame build.
        if sky is not None:
            sat_ae, sun_ae, moon_ae = observer_snapshot(sky.station, now, state_now)
            sky.sun.set_offsets([_sky_glyph_offset(sun_ae)])
            sky.moon.set_offsets([_sky_glyph_offset(moon_ae)])
            sky.sat.set_offsets([_sky_glyph_offset(sat_ae)])
            sky.ax.set_facecolor(_twilight_facecolor(sun_ae.elevation_deg))

        # Live readout: sub-satellite position, altitude, both speeds, and the
        # wall clock (UTC by default; tz-localized when live_track got a tz=).
        readout.set_text(
            f"{_format_latlon(geo)} · alt {geo.altitude_m / 1000.0:.0f} km · "
            f"{v_inertial_kms:.2f} km/s (gnd {v_ground_kms:.2f}) · "
            f"{_format_clock(now, tz=tz_resolved)}"
        )
        return dynamic

    # blit=False: the mutate-in-place rewrite delivers the interactivity headline
    # (zoom/pan survives every redraw and rebuild) on its own; no blit layer. No
    # init_func -- FuncAnimation's initial draw then runs update() itself, so the first
    # frame is fully populated; an init_func would draw only the static artists, leaving
    # the marker/glyphs/readout/twilight-tint blank until the first timer tick.
    anim = FuncAnimation(
        fig,
        update,
        blit=False,
        interval=int(refresh_s * 1000.0),
        cache_frame_data=False,
    )
    logger.info(
        "live dashboard started: panels=%d auto_refresh=%s refresh=%.1fs",
        4 if station is not None else 3,
        engine.auto_refresh,
        refresh_s,
    )
    return anim
