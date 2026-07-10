"""TLE propagation (Feature 1.3).

Re-exports the SGP4/SDP4 ``propagate_tle`` verb and the CelesTrak ``fetch_tle`` path.
The ``TLE`` type itself lives in ``core/tle.py`` (so the inward dependency rule stays
pure — see ``docs/history/build-plan-feature-1.3.md`` Decision a). Importing this
subpackage is JVM-free (and does not pull ``requests`` — it is imported lazily inside
the one HTTP function); the JVM starts only when ``propagate_tle`` is called, and
``fetch_tle`` does network I/O without ever starting it.
"""

from __future__ import annotations

from .propagator import propagate_tle
from .sources import fetch_tle

__all__ = [
    "propagate_tle",
    "fetch_tle",
]
