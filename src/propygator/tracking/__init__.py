"""Real-time tracking (Feature 1.4) and pass prediction (Feature 1.5).

Re-exports the cheap realtime primitives ``current_state`` /
``current_ground_position`` (``tracking/realtime.py``), the live dashboard verb
``live_track`` (``tracking/live.py``), and the pass-search verbs ``find_passes`` /
``passes_to_dataframe`` (``tracking/passes.py``). Importing this subpackage is
JVM-free and does not pull matplotlib/pandas — the JVM starts only when a verb is
called, and the live view's ``plotting`` / matplotlib and the pass table's pandas
imports are deferred to their function bodies.
"""

from __future__ import annotations

from .live import live_track
from .passes import find_passes, passes_to_dataframe
from .realtime import current_ground_position, current_state

__all__ = [
    "current_state",
    "current_ground_position",
    "live_track",
    "find_passes",
    "passes_to_dataframe",
]
