"""Pass-prediction plots (Feature 1.5): the sky chart and the pass timeline.

The two rich outputs of ``find_passes`` (features.md §1.5 "Outputs"), both
matplotlib:

- :func:`plot_sky_chart` — the "where to look" polar view. It **recomputes** each
  pass's az/el arc (``propagate_tle`` over ``[rise, set]`` → ``look_angles_track``,
  the price of a light ``Pass`` that stores no arc) and draws it on the shared
  :func:`~propygator.plotting.trajectories._draw_sky_track` conventions — zenith
  centre, horizon rim, North up, azimuth clockwise — via that primitive's
  ``azel=`` / ``track_style=`` / ``warn_never_visible=`` seams, **without
  modifying it** (its ``plot_sky_track`` contract and snapshots are untouched).
  Each arc is split into **sunlit** and **eclipsed** segments (Chunk 2's
  ``_is_sunlit`` on the arc), styled differently, with rise/set/culmination
  markers, tz-formatted labels, and a peak-magnitude annotation. JVM-touching.
- :func:`plot_pass_timeline` — the "when" view. One bar per pass (rise→set,
  height = max elevation) on a wall-clock x-axis, styled by
  ``sunlit_at_culmination`` and annotated with the peak magnitude. Draws only the
  stored ``Pass`` scalar fields — **no TLE, no JVM**.

The lit/eclipse colours, bar cosmetics, and minimum bar width below are
**tunable placeholders, not contract** (the §1.4 buffer-magnitudes precedent);
the locked ``plotting.style`` baseline is reused, never restyled. ``plotting/``
is a leaf (nothing imports it, architecture §7): the sky chart's ``propagate_tle``
and ``tracking.visibility`` dependencies are imported **lazily inside the
function** so ``import propygator.plotting`` neither pulls ``tle`` / ``tracking``
at module load nor starts the JVM.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, cast

import numpy as np

from ..core.frames import Frame
from ..core.observation import Pass, look_angles_track
from ..core.time import _resolve_tz
from .style import FIGSIZE_SKY, FIGSIZE_TIMESERIES, _mpl_style
from .trajectories import (
    _SKY_AZIMUTH_LABELS,
    _SKY_AZIMUTH_TICKS,
    _SKY_DISK_COLOR,
    _SKY_RADIAL_LABELS,
    _SKY_RADIAL_POSITIONS_DEG,
    _draw_sky_track,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import tzinfo

    from matplotlib.figure import Figure
    from matplotlib.projections.polar import PolarAxes

    from ..core.observation import GroundStation
    from ..core.time import USTimeZone
    from ..core.tle import TLE

logger = logging.getLogger(__name__)

# --- sky-chart cosmetics (tunable placeholders) -----------------------------

# Samples per recomputed pass arc: a pass lasts minutes, so a fixed count gives a
# smooth curve at trivial cost (contract: "cheap over minutes-long arcs").
_SKY_ARC_SAMPLES = 121

#: Sunlit arc — warm gold, drawn a touch heavier (the "visible now" segment).
_LIT_TRACK_STYLE: dict[str, Any] = {"color": "#f5a623", "linewidth": 1.7, "zorder": 4}
#: Eclipsed arc — dark slate, dashed (the satellite is up but in Earth's shadow);
#: a high-contrast cool colour against the light-blue disk so shadow legs read.
_ECLIPSE_TRACK_STYLE: dict[str, Any] = {
    "color": "#34495e",
    "linewidth": 1.4,
    "linestyle": (0, (4, 3)),
    "zorder": 3,
}

# Endpoint / culmination glyphs are scatter markers (kept out of ``ax.lines`` so
# it holds only the two styled arcs per pass); ``s`` is in points². Kept small so
# a multi-pass chart stays legible.
_RISE_SET_MARKER: dict[str, Any] = {"marker": "o", "s": 16.0, "zorder": 6}
_CULMINATION_MARKER: dict[str, Any] = {"marker": "*", "s": 90.0, "zorder": 6}
_MARKER_COLOR = "#1f3b73"  # the locked dark-navy (TIMESERIES_COLOR)

#: Label styling — a high zorder plus a translucent white halo so the text reads
#: on top of the arcs and disk (the labels are the thing you read off the chart).
_LABEL_ZORDER = 10
_LABEL_BBOX: dict[str, Any] = {
    "boxstyle": "round,pad=0.15",
    "facecolor": "white",
    "edgecolor": "none",
    "alpha": 0.6,
}

# --- timeline cosmetics (tunable placeholders) ------------------------------

#: A pass lasts minutes, a sliver on a multi-day axis; floor the drawn width to
#: this many minutes so the fill (and the eclipse hatch) is legible. The rise
#: (left edge) stays exact — only the drawn width is padded.
_MIN_BAR_WIDTH_MINUTES = 25.0
_MIN_BAR_WIDTH_DAYS = _MIN_BAR_WIDTH_MINUTES / 1440.0

#: A pass sunlit at culmination — the same warm gold as the lit sky-track arc.
_SUNLIT_BAR_STYLE: dict[str, Any] = {
    "facecolor": "#f5a623",
    "edgecolor": "black",
    "linewidth": 0.8,
}
#: A pass eclipsed at culmination — cool slate fill, hatched (still a real pass);
#: the colour matches the sky chart's eclipse leg so the two plots read together.
_ECLIPSE_BAR_STYLE: dict[str, Any] = {
    "facecolor": "#9fb0c7",
    "edgecolor": "black",
    "linewidth": 0.8,
    "hatch": "///",
}
_DAY_BOUNDARY_STYLE: dict[str, Any] = {
    "color": "#9aa0a6",
    "linestyle": ":",
    "linewidth": 0.9,
}

#: Elevation tops out at 90°; the axis view goes a little higher so peak-magnitude
#: labels above tall bars have headroom (the ticks still stop at 90).
_TIMELINE_YLIM_TOP = 98.0


def _normalize_passes(passes: "Pass | Sequence[Pass]") -> list[Pass]:
    """Accept a single ``Pass`` or a sequence; always return a list."""
    if isinstance(passes, Pass):
        return [passes]
    return list(passes)


def _frame_empty_sky(ax: "PolarAxes") -> None:
    """Apply the shared sky-disk polar framing when no arc was drawn.

    Mirrors :func:`_draw_sky_track`'s framing (reusing its exact constants) for
    the degenerate no-pass case, where the primitive — which needs a propagated
    arc — is never called. Not a restyle of the primitive: same conventions,
    same constants.
    """
    ax.set_theta_zero_location("N")
    ax.set_theta_direction(-1)
    ax.set_rlim(0.0, 90.0)
    ax.set_rgrids(_SKY_RADIAL_POSITIONS_DEG, labels=_SKY_RADIAL_LABELS)
    ax.set_thetagrids(_SKY_AZIMUTH_TICKS, labels=_SKY_AZIMUTH_LABELS)
    ax.set_facecolor(_SKY_DISK_COLOR)


def _local_stamp(epoch, tzinfo: "tzinfo") -> str:
    """``MM-DD HH:MM`` wall-clock of ``epoch`` in ``tzinfo``.

    The date is carried (not just the time) so a label is unambiguous across a
    multi-day search window (``05:28`` alone doesn't say which night).
    """
    return epoch.to_datetime().astimezone(tzinfo).strftime("%m-%d %H:%M")


def _draw_one_pass(
    ax: "PolarAxes",
    tle: "TLE",
    station: "GroundStation",
    p: Pass,
    tzinfo: "tzinfo",
    *,
    propagate_tle,
    is_sunlit,
    sun_positions,
) -> None:
    """Recompute one pass's sky arc and draw it (lit/eclipse segments + labels)."""
    span_s = p.set.seconds_since(p.rise)
    if span_s <= 0.0:  # a degenerate/zero-length pass has no arc to draw
        return
    step_s = span_s / (_SKY_ARC_SAMPLES - 1)
    traj = propagate_tle(tle, span_s, output_step=step_s, start=p.rise)
    azimuth_deg, elevation_deg, range_m = look_angles_track(station, traj)

    epochs = [p.rise.shifted_by(k * step_s) for k in range(len(traj))]
    eme_positions = traj.to_frame(Frame.EME2000).positions
    lit = is_sunlit(eme_positions, sun_positions(epochs))

    # Include each lit/eclipse transition sample in *both* masks so the two
    # styled segments meet instead of leaving a one-sample gap at the boundary.
    boundary = np.zeros(lit.shape[0], dtype=bool)
    changes = lit[:-1] != lit[1:]
    boundary[:-1] |= changes
    boundary[1:] |= changes
    elev_lit = np.where(lit | boundary, elevation_deg, np.nan)
    elev_eclipse = np.where(~lit | boundary, elevation_deg, np.nan)

    # Reuse the shared primitive via its seams (precomputed azel, custom style,
    # no never-visible warning — the arc is by construction above the gate).
    _draw_sky_track(
        ax,
        traj,
        station,
        azel=(azimuth_deg, elev_lit, range_m),
        track_style=_LIT_TRACK_STYLE,
        warn_never_visible=False,
    )
    _draw_sky_track(
        ax,
        traj,
        station,
        azel=(azimuth_deg, elev_eclipse, range_m),
        track_style=_ECLIPSE_TRACK_STYLE,
        warn_never_visible=False,
    )

    _annotate_pass(ax, p, azimuth_deg, elevation_deg, tzinfo)


def _annotate_pass(
    ax: "PolarAxes",
    p: Pass,
    azimuth_deg: np.ndarray,
    elevation_deg: np.ndarray,
    tzinfo: "tzinfo",
) -> None:
    """Rise/set/culmination markers with tz-formatted times, azimuths, magnitude."""
    # Rise and set at the arc endpoints (theta = azimuth, r = zenith angle).
    for idx, epoch, az_field, label in (
        (0, p.rise, p.rise_azimuth_deg, "rise"),
        (-1, p.set, p.set_azimuth_deg, "set"),
    ):
        theta = np.radians(float(azimuth_deg[idx]))
        radius = 90.0 - float(elevation_deg[idx])
        ax.scatter(theta, radius, color=_MARKER_COLOR, **_RISE_SET_MARKER)
        az = az_field if az_field is not None else float(azimuth_deg[idx])
        ax.annotate(
            f"{label} {_local_stamp(epoch, tzinfo)}\naz {az:.0f}°",
            (theta, radius),
            textcoords="offset points",
            xytext=(4, 4),
            fontsize=6.5,
            zorder=_LABEL_ZORDER,
            bbox=_LABEL_BBOX,
        )

    # Culmination at the arc's elevation maximum, annotated with max el + mag.
    jmax = int(np.argmax(elevation_deg))
    theta = np.radians(float(azimuth_deg[jmax]))
    radius = 90.0 - float(elevation_deg[jmax])
    ax.scatter(theta, radius, color=_MARKER_COLOR, **_CULMINATION_MARKER)
    text = f"{p.max_elevation_deg:.0f}°"
    if p.peak_magnitude is not None:
        text += f"\nmag {p.peak_magnitude:.1f}"
    ax.annotate(
        text,
        (theta, radius),
        textcoords="offset points",
        xytext=(4, -2),
        fontsize=7,
        fontweight="bold",
        zorder=_LABEL_ZORDER,
        bbox=_LABEL_BBOX,
    )


def _add_sky_legend(ax: "PolarAxes") -> None:
    """A two-entry legend distinguishing the sunlit and eclipsed arc styles."""
    from matplotlib.lines import Line2D

    handles = [
        Line2D([], [], label="sunlit", **_LIT_TRACK_STYLE),
        Line2D([], [], label="eclipsed", **_ECLIPSE_TRACK_STYLE),
    ]
    ax.legend(
        handles=handles, loc="upper right", bbox_to_anchor=(1.12, 1.12), fontsize=8
    )


def plot_sky_chart(
    tle: "TLE",
    station: "GroundStation",
    passes: "Pass | Sequence[Pass]",
    *,
    tz: "USTimeZone | tzinfo | None" = None,
) -> "Figure":
    """Plot ``passes`` as arcs across ``station``'s sky (Feature 1.5 polar view).

    The "where to look" companion to :func:`plot_pass_timeline`: each pass's
    azimuth/elevation arc on a polar sky dome — zenith centre, horizon rim, North
    up, azimuth clockwise, radial rings labelled in elevation — in the shared
    :func:`~propygator.plotting.trajectories.plot_sky_track` conventions. Because a
    :class:`~propygator.core.observation.Pass` stores no arc, each is **recomputed**
    here (``propagate_tle`` over ``[rise, set]`` → ``look_angles_track``); the arc
    is split into **sunlit** (gold) and **eclipsed** (grey dashed) segments via the
    Chunk-2 ``_is_sunlit`` test, with rise/set/culmination markers, tz-formatted
    time labels, azimuths, and a peak-magnitude annotation. ``passes`` may be a
    single ``Pass`` or a sequence.

    ``tz`` (a :class:`~propygator.core.time.USTimeZone`, a ``datetime.tzinfo``, or
    ``None`` for UTC) sets the label clock via the shared ``core.time._resolve_tz``.
    The title is ``tle.name`` (a generic fallback when unset). Returns the
    matplotlib figure; the JVM starts lazily on the first pass propagation.
    """
    import matplotlib.pyplot as plt

    from ..tle.propagator import propagate_tle
    from ..tracking.visibility import _is_sunlit, _sun_positions_eme2000

    pass_list = _normalize_passes(passes)
    tzinfo = _resolve_tz(tz)

    with _mpl_style():
        fig, ax = plt.subplots(figsize=FIGSIZE_SKY, subplot_kw={"projection": "polar"})
        pax = cast("PolarAxes", ax)
        for p in pass_list:
            _draw_one_pass(
                pax,
                tle,
                station,
                p,
                tzinfo,
                propagate_tle=propagate_tle,
                is_sunlit=_is_sunlit,
                sun_positions=_sun_positions_eme2000,
            )
        # No arc drawn (empty input, or every pass degenerate) -> frame an empty
        # disk so the axes still read as a sky chart.
        if not pax.lines:
            _frame_empty_sky(pax)
        _add_sky_legend(pax)
        title = tle.name if tle.name else "satellite"
        fig.suptitle(f"{title} — sky chart")
        fig.tight_layout()

    logger.info("Rendered sky chart for %d pass(es)", len(pass_list))
    return fig


def _day_boundaries(rises: list, sets: list) -> list:
    """Local midnights strictly inside ``[min(rises), max(sets)]`` (day gridlines).

    Inputs are tz-aware datetimes already localized to the display zone, so
    ``replace(hour=0, …)`` is that zone's midnight.
    """
    from datetime import timedelta

    span_start, span_end = min(rises), max(sets)
    midnight = span_start.replace(hour=0, minute=0, second=0, microsecond=0)
    if midnight < span_start:
        midnight += timedelta(days=1)
    boundaries = []
    while midnight <= span_end:
        boundaries.append(midnight)
        midnight += timedelta(days=1)
    return boundaries


def plot_pass_timeline(
    passes: "Pass | Sequence[Pass]",
    *,
    tz: "USTimeZone | tzinfo | None" = None,
) -> "Figure":
    """Plot ``passes`` as bars on a wall-clock timeline (Feature 1.5 "when" view).

    The temporal companion to :func:`plot_sky_chart`: a wall-clock x-axis across
    the window, elevation 0–90° on y, and one bar per pass spanning rise→set with
    height = ``max_elevation_deg``. ``sunlit_at_culmination`` styles the bar (gold
    vs. grey hatched), the peak magnitude is annotated above it, and local-midnight
    gridlines mark the days. Short passes get a small minimum display width (the
    rise edge stays exact). ``passes`` may be a single ``Pass`` or a sequence.

    Draws only the stored ``Pass`` scalar fields — **no TLE and no JVM**. ``tz``
    (a :class:`~propygator.core.time.USTimeZone`, a ``datetime.tzinfo``, or ``None``
    for UTC) sets the display clock via ``core.time._resolve_tz``. Returns the
    matplotlib figure (empty axes for an empty ``passes`` list).
    """
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt

    pass_list = _normalize_passes(passes)
    tzinfo = _resolve_tz(tz)

    from matplotlib.patches import Patch

    with _mpl_style():
        # constrained layout so the outside-above legend (below) gets a reserved
        # strip and is never clipped — see the fig.legend call.
        fig, ax = plt.subplots(figsize=FIGSIZE_TIMESERIES, layout="constrained")
        # Elevation runs 0–90°, but the view tops out higher so a peak-magnitude
        # label above a near-overhead bar isn't clipped; ticks still stop at 90.
        ax.set_ylim(0.0, _TIMELINE_YLIM_TOP)
        ax.set_yticks([0, 30, 60, 90])
        ax.set_ylabel("Elevation (°)")
        ax.set_xlabel("Time")

        if pass_list:
            rises = [p.rise.to_datetime().astimezone(tzinfo) for p in pass_list]
            sets = [p.set.to_datetime().astimezone(tzinfo) for p in pass_list]

            for boundary in _day_boundaries(rises, sets):
                ax.axvline(mdates.date2num(boundary), zorder=0, **_DAY_BOUNDARY_STYLE)

            for p, rise_dt, set_dt in zip(pass_list, rises, sets):
                left = mdates.date2num(rise_dt)
                width = max(mdates.date2num(set_dt) - left, _MIN_BAR_WIDTH_DAYS)
                style = (
                    _SUNLIT_BAR_STYLE if p.sunlit_at_culmination else _ECLIPSE_BAR_STYLE
                )
                ax.bar(
                    left,
                    p.max_elevation_deg,
                    width=width,
                    bottom=0.0,
                    align="edge",
                    zorder=3,
                    **style,
                )
                if p.peak_magnitude is not None:
                    ax.annotate(
                        f"{p.peak_magnitude:.1f}",
                        (left + width / 2.0, p.max_elevation_deg),
                        textcoords="offset points",
                        xytext=(0, 3),
                        ha="center",
                        va="bottom",
                        fontsize=8,
                    )

            ax.xaxis.set_major_locator(mdates.AutoDateLocator(tz=tzinfo))
            ax.xaxis.set_major_formatter(
                mdates.ConciseDateFormatter(ax.xaxis.get_major_locator(), tz=tzinfo)
            )

        # Legend outside the data area, in a reserved strip above the axes — so it
        # can never cover a pass bar, whatever the times. An *axes* legend anchored
        # just above the axes (not a figure legend) lets constrained_layout stack
        # the suptitle cleanly above it: title on top, legend below, plot beneath.
        ax.legend(
            handles=[
                Patch(
                    facecolor=_SUNLIT_BAR_STYLE["facecolor"],
                    edgecolor="black",
                    label="sunlit at culmination",
                ),
                Patch(
                    facecolor=_ECLIPSE_BAR_STYLE["facecolor"],
                    edgecolor="black",
                    hatch="///",
                    label="eclipsed at culmination",
                ),
            ],
            loc="lower center",
            bbox_to_anchor=(0.5, 1.02),
            ncol=2,
            fontsize=8,
            borderaxespad=0.0,
        )
        fig.suptitle("Pass timeline")

    logger.info("Rendered pass timeline for %d pass(es)", len(pass_list))
    return fig
