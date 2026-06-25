"""Real-time tracking (Feature 1.4).

Re-exports the cheap realtime primitives ``current_state`` /
``current_ground_position`` (``tracking/realtime.py``) and the live dashboard verb
``live_track`` (``tracking/live.py``). Importing this subpackage is JVM-free and does
not pull matplotlib — the JVM starts only when a verb is called, and the live view's
``plotting`` / matplotlib imports are deferred to ``live_track``'s function body.
"""

from __future__ import annotations

from .live import live_track
from .realtime import current_ground_position, current_state

__all__ = [
    "current_state",
    "current_ground_position",
    "live_track",
]
