"""TLE propagation (Feature 1.3) and TLE fitting (Feature 1.2).

Re-exports the SGP4/SDP4 ``propagate_tle`` verb, the CelesTrak ``fetch_tle``
path, and the least-squares fitter surface (``fit_tle`` / ``fit_tle_detailed``
/ ``FitResult``). The ``TLE`` type itself lives in ``core/tle.py`` (so the
inward dependency rule stays pure — see
``docs/history/build-plan-feature-1.3.md`` Decision a); the fitter's
``tle → propagation`` edge exists only at call time (architecture §7 sanctioned
exception). Importing this subpackage is JVM-free (and does not pull
``requests`` — it is imported lazily inside the one HTTP function); the JVM
starts only when ``propagate_tle`` / the fit verbs are called, and ``fetch_tle``
does network I/O without ever starting it.
"""

from __future__ import annotations

from .fitter import FitResult, fit_tle, fit_tle_detailed
from .propagator import propagate_tle
from .sources import fetch_tle

__all__ = [
    "propagate_tle",
    "fetch_tle",
    "fit_tle",
    "fit_tle_detailed",
    "FitResult",
]
