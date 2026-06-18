"""Time-series plots: altitude and speed vs elapsed time (build-plan chunk 11b).

Two of the simplest outputs, and the place the ``_draw_*(ax, traj, ...)`` **primitive
pattern** is pinned: each plot's drawing logic lives in a private primitive that draws
onto a *supplied* ``Axes``; the public ``plot_*`` functions are thin wrappers that
create the figure, apply the per-figure style, and own the shared x-axis label. The
composite ``plot_summary`` (chunk 11d) reuses these same primitives — matplotlib cannot
move axes between figures, so a composite must be assembled from primitives, not from
standalone figures (features.md §1.1 "Outputs").

Conventions (locked in chunk 11a): x-axis is **elapsed hours** since the first sample;
altitude is geodetic (WGS84) in **km**; speed is the velocity *magnitude* in **km/s**
(one dark-navy line, not components). ``plot_speed`` draws one stacked panel per frame —
inertial (EME2000/TEME) or ITRF ground-relative.

Primitive contract (depended on by chunk 11d): ``_draw_altitude`` / ``_draw_speed``
draw onto the given ``ax`` and set the y-axis label (and, for speed, a frame title);
they do **not** create a figure, set the x-axis label, or apply the style — the caller
owns those so a shared-x composite labels only its bottom panel.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import numpy as np

from ..core.frames import Frame, geodetic_track
from .style import (
    FIGSIZE_TIMESERIES,
    TIMESERIES_COLOR,
    _dedupe_frames,
    _mpl_style,
    _require_min_samples,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from matplotlib.axes import Axes
    from matplotlib.figure import Figure

    from ..core.states import Trajectory

logger = logging.getLogger(__name__)

_HOURS_XLABEL = "Elapsed time (hours)"
_SECONDS_PER_HOUR = 3600.0


def _elapsed_hours(traj: Trajectory) -> np.ndarray:
    """Elapsed time of each sample since the first, in hours.

    Computed straight from the trajectory's two-part TAI count (``_epochs_int`` +
    ``_epochs_frac``) — TAI is uniform, so the differences are exact physical seconds
    and need no JVM (the conversions are reserved for altitude / non-inertial speed).
    """
    seconds = (traj._epochs_int - traj._epochs_int[0]).astype(np.float64) + (
        traj._epochs_frac - traj._epochs_frac[0]
    )
    return seconds / _SECONDS_PER_HOUR


def _speed_descriptor(frame: Frame) -> str:
    """Human label for a speed frame: ITRF is ground-relative, others inertial."""
    return "Ground-relative" if frame is Frame.ITRF else "Inertial"


def _draw_altitude(ax: Axes, traj: Trajectory) -> None:
    """Draw geodetic altitude (km) vs elapsed hours onto ``ax``.

    Altitude is WGS84 geodetic height from the shared
    :func:`~propygator.core.frames.geodetic_track` (convert to ITRF, project each
    sample). Sets the y-axis label only; the caller owns the x-axis label and figure.
    """
    _itrf, _lat, _lon, alt_m = geodetic_track(traj)
    altitude_km = alt_m / 1000.0
    ax.plot(_elapsed_hours(traj), altitude_km, color=TIMESERIES_COLOR)
    ax.set_ylabel("Altitude (km)")


def _draw_speed(ax: Axes, traj: Trajectory, *, frame: Frame) -> None:
    """Draw speed magnitude (km/s) in ``frame`` vs elapsed hours onto ``ax``.

    Speed is ``‖velocity‖`` after expressing the trajectory in ``frame``: inertial
    (EME2000/TEME) gives the orbital speed; ITRF gives the **ground-relative** speed
    (relative to the rotating Earth). Sets the y-axis label and a frame-naming title;
    the caller owns the x-axis label and the figure.
    """
    in_frame = traj.to_frame(frame)
    speed_kms = np.linalg.norm(in_frame.velocities, axis=1) / 1000.0
    ax.plot(_elapsed_hours(traj), speed_kms, color=TIMESERIES_COLOR)
    ax.set_ylabel("Speed (km/s)")
    ax.set_title(f"{_speed_descriptor(frame)} speed — {frame.value}")


def _suptitle_from_metadata(fig: Figure, traj: Trajectory) -> None:
    """Add the trajectory's ``name`` (if any) as the figure suptitle."""
    name = traj.metadata.get("name")
    if name:
        fig.suptitle(str(name))


def plot_altitude(traj: Trajectory) -> Figure:
    """Plot geodetic altitude (km) vs elapsed time (hours).

    Returns the matplotlib :class:`~matplotlib.figure.Figure` (post-process with the
    native API). Altitude is WGS84 geodetic height. The JVM starts lazily on first
    call (frame conversion + geodetic projection).
    """
    import matplotlib.pyplot as plt

    _require_min_samples(traj)
    with _mpl_style():
        fig, ax = plt.subplots(figsize=FIGSIZE_TIMESERIES)
        _draw_altitude(ax, traj)
        ax.set_xlabel(_HOURS_XLABEL)
        _suptitle_from_metadata(fig, traj)
        fig.tight_layout()
    logger.info("Rendered altitude plot over %d samples", len(traj))
    return fig


def plot_speed(
    traj: Trajectory, *, frames: Sequence[Frame] = (Frame.EME2000,)
) -> Figure:
    """Plot speed magnitude (km/s) vs elapsed time (hours), one panel per frame.

    ``frames`` selects which speed(s): an inertial frame (``EME2000`` / ``TEME``)
    gives the orbital speed; ``ITRF`` gives the **ground-relative** speed (relative to
    the rotating Earth — most uses want inertial; ITRF is for ground-relative motion,
    e.g. near-GEO stationkeeping). Requesting several yields stacked, x-axis-sharing
    panels, each titled by frame. Duplicate frames are collapsed (order preserved); an
    empty ``frames`` raises ``ValueError``. Returns the matplotlib figure.
    """
    import matplotlib.pyplot as plt

    _require_min_samples(traj)
    ordered = _dedupe_frames(frames, what="plot_speed `frames`")

    height = FIGSIZE_TIMESERIES[1] * len(ordered)
    with _mpl_style():
        fig, axes = plt.subplots(
            len(ordered),
            1,
            sharex=True,
            figsize=(FIGSIZE_TIMESERIES[0], height),
            squeeze=False,
        )
        panels = axes[:, 0]
        for ax, frame in zip(panels, ordered):
            _draw_speed(ax, traj, frame=frame)
        panels[-1].set_xlabel(_HOURS_XLABEL)
        _suptitle_from_metadata(fig, traj)
        fig.tight_layout()
    logger.info(
        "Rendered speed plot over %d samples for frames %s",
        len(traj),
        [frame.value for frame in ordered],
    )
    return fig
