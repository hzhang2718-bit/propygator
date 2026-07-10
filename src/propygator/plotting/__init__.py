"""Visualization surface for a :class:`~propygator.core.states.Trajectory`.

Plotly for the interactive 3D view, matplotlib for everything else (architecture
§9). The public ``plot_*`` verbs (``plot_summary`` / ``plot_ground_track`` /
``plot_3d`` / ``plot_altitude`` / ``plot_speed``) land across build-plan chunks
11b–11e on the shared foundation chunk 11a established — the locked cosmetic baseline
(:mod:`~propygator.plotting.style`) and the bundled Earth coastline basemap
(:mod:`~propygator.plotting.basemap`). The time-series plots (``plot_altitude`` /
``plot_speed``) land in 11b; the rest follow. The top-level ``propygator.plot_*``
re-exports land with Chunk 12; for now import from this subpackage.

``plotting/`` is a leaf — nothing in the package imports it (architecture §7), so the
core stays testable headless. Styling is applied *per figure* via a context manager,
never by mutating global ``rcParams`` on import.
"""

from .composite import plot_summary
from .passes import plot_pass_timeline, plot_sky_chart
from .timeseries import plot_altitude, plot_speed
from .trajectories import plot_3d, plot_ground_track, plot_sky_track

__all__ = [
    "plot_3d",
    "plot_altitude",
    "plot_ground_track",
    "plot_pass_timeline",
    "plot_sky_chart",
    "plot_sky_track",
    "plot_speed",
    "plot_summary",
]
