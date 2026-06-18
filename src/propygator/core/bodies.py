"""Canonical Earth model and celestial-body accessors (architecture §7).

The Orekit body models reused across Feature 1.1: the WGS84 Earth ellipsoid (for
geodetic lat/lon/alt, the conical SRP shadow, and the drag atmosphere body shape)
and the Sun/Moon celestial bodies (third-body attraction, SRP, Sun-relative
attitude).

These accessors return Orekit Java objects and are therefore **module-internal**
(leading underscore): no Orekit type ever appears on a public propygator
signature (architecture §4/§10). Each accessor crosses into the JVM, so each
calls ``_ensure_started()`` first and imports ``org.orekit.*`` lazily inside the
function — importing this module never starts the JVM (the lazy-JVM contract,
same pattern as :meth:`Epoch.to_orekit`).

The Earth ellipsoid and Earth µ are built once and memoized (``functools.cache``)
— the WGS84 constants and the ITRF frame are process-stable, and the JVM cannot be
restarted, so the cached handles never go stale. This mirrors how the Sun/Moon
factory already returns Orekit's cached singletons, so a hot-loop caller (e.g.
per-sample geodetic conversion) pays the construction cost once per process.
"""

from __future__ import annotations

from functools import cache
from typing import TYPE_CHECKING

from .frames import Frame

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.bodies  # noqa: F401


@cache
def _earth() -> "org.orekit.bodies.OneAxisEllipsoid":
    """Return the canonical WGS84 Earth ellipsoid, expressed in ITRF.

    A ``OneAxisEllipsoid`` built on the WGS84 equatorial radius and flattening
    (``Constants.WGS84_*``) in ``Frame.ITRF``. This is the Earth-fixed body shape
    used for geodetic conversion (``frames.to_geodetic``), the conical SRP shadow,
    and the drag atmosphere — all later Feature 1.1 chunks. Built once and memoized
    (see the module docstring).
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.bodies import OneAxisEllipsoid
    from org.orekit.utils import Constants

    return OneAxisEllipsoid(
        Constants.WGS84_EARTH_EQUATORIAL_RADIUS,
        Constants.WGS84_EARTH_FLATTENING,
        Frame.ITRF.to_orekit(),
    )


@cache
def _earth_mu() -> float:
    """Return Earth's gravitational parameter µ (WGS84), in m³/s².

    The single µ used by the data-model conversions that need one —
    :meth:`State.to_keplerian`, :meth:`KeplerianElements.to_state`, and the
    derived-anomaly methods go through this so a round-trip is exact and the
    absolute element values match the textbook (Vallado) WGS84 GM,
    ``Constants.WGS84_EARTH_MU`` = 3.986004418e14. A numerical *propagation* uses
    its own configured gravity field's µ instead (the ``propagation`` layer); this
    accessor is only for the standalone osculating-element conversions. Resolved
    once and memoized (see the module docstring).
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.utils import Constants

    return float(Constants.WGS84_EARTH_MU)


def _sun() -> "org.orekit.bodies.CelestialBody":
    """Return the Sun as an Orekit ``CelestialBody`` (third-body, SRP, pointing)."""
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.bodies import CelestialBodyFactory

    return CelestialBodyFactory.getSun()


def _moon() -> "org.orekit.bodies.CelestialBody":
    """Return the Moon as an Orekit ``CelestialBody`` (third-body attraction)."""
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.bodies import CelestialBodyFactory

    return CelestialBodyFactory.getMoon()
