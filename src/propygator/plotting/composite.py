"""The composite summary plot (build-plan chunk 11d).

``plot_summary`` is propygator's default visual: one stacked ``GridSpec`` figure that
composes the *same* ``_draw_*`` primitives as the standalone plots (chunks 11b/11c) onto
its own axes — the ground track spanning the top row at a larger height weight, altitude
beneath, then one speed panel per requested frame (features.md §1.1 "Outputs"). Building
from the supplied-axes primitives is required, not stylistic: matplotlib cannot move
axes between figures, so a composite cannot be assembled from standalone figures.

Layout notes:

- **Shared x.** The altitude + speed rows share one elapsed-hours x-axis (only the
  bottom panel is labelled); the ground track keeps its own longitude axis and is not
  shared with them.
- **Equal-aspect map.** The ground track keeps ``aspect="equal"`` (from its
  primitive), so it centres within its row; ``constrained_layout`` packs the rest
  around it and the shared axes.
- **No map colorbar.** Unlike standalone ``plot_ground_track``, the summary omits the
  ground-track colorbar — the altitude/speed panels directly below share the same
  0→T elapsed-time span, and the start/end markers anchor direction.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from ..core.frames import Frame
from .style import FIGSIZE_SUMMARY, _dedupe_frames, _mpl_style, _require_min_samples
from .timeseries import (
    _HOURS_XLABEL,
    _draw_altitude,
    _draw_speed,
    _suptitle_from_metadata,
)
from .trajectories import _draw_ground_track

if TYPE_CHECKING:
    from collections.abc import Sequence

    from matplotlib.figure import Figure

    from ..core.states import Trajectory

logger = logging.getLogger(__name__)

# Per-row heights (inches). The map row matches its natural equal-aspect height at the
# summary width (≈ width / 2), so little vertical whitespace is left around it; each
# time-series row is shorter. These double as the GridSpec height_ratios, so the figure
# height and the row split stay consistent.
_MAP_ROW_HEIGHT_IN = 4.0
_TS_ROW_HEIGHT_IN = 1.9


def plot_summary(
    traj: Trajectory,
    *,
    speed_frames: Sequence[Frame] = (Frame.EME2000,),
    show_map_overlay: bool = True,
) -> Figure:
    """Render the default stacked summary: ground track, altitude, speed panel(s).

    ``speed_frames`` selects one speed panel per frame (inertial and/or ITRF
    ground-relative — see :func:`~propygator.plotting.timeseries.plot_speed`).
    Duplicates are collapsed (order preserved); an empty sequence raises ``ValueError``.
    ``show_map_overlay`` toggles the coastline on the ground track. Returns one composed
    matplotlib figure; the JVM starts lazily on first call (frame/geodetic conversion).
    """
    import matplotlib.pyplot as plt

    _require_min_samples(traj)
    ordered = _dedupe_frames(speed_frames, what="plot_summary `speed_frames`")

    n_timeseries = 1 + len(ordered)  # altitude + one panel per speed frame
    height_ratios = [_MAP_ROW_HEIGHT_IN] + [_TS_ROW_HEIGHT_IN] * n_timeseries

    with _mpl_style():
        fig = plt.figure(
            figsize=(FIGSIZE_SUMMARY[0], sum(height_ratios)), constrained_layout=True
        )
        gs = fig.add_gridspec(1 + n_timeseries, 1, height_ratios=height_ratios)

        ax_ground = fig.add_subplot(gs[0])
        _draw_ground_track(
            ax_ground, traj, show_map_overlay=show_map_overlay, color_by_time=True
        )

        ax_altitude = fig.add_subplot(gs[1])
        _draw_altitude(ax_altitude, traj)

        timeseries_axes = [ax_altitude]
        for row, frame in enumerate(ordered, start=2):
            ax_speed = fig.add_subplot(gs[row], sharex=ax_altitude)
            _draw_speed(ax_speed, traj, frame=frame)
            timeseries_axes.append(ax_speed)

        # Shared x: hide the inner panels' tick labels, label only the bottom one.
        for ax in timeseries_axes[:-1]:
            ax.tick_params(labelbottom=False)
        timeseries_axes[-1].set_xlabel(_HOURS_XLABEL)

        _suptitle_from_metadata(fig, traj)

    logger.info(
        "Rendered summary over %d samples (%d speed panel(s))", len(traj), len(ordered)
    )
    return fig
