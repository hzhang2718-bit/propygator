"""``Frame`` — propygator's reference-frame sentinel.

A :class:`Frame` is an enum member that names a reference frame and knows how to
produce its Orekit counterpart on demand. Constructing/accessing frames is
pure-Python and safe before JVM init (architecture §10); only
:meth:`Frame.to_orekit` crosses into Orekit (Feature 1.1) — it starts the JVM
lazily and resolves the member through ``FramesFactory``.

v1 supported set (architecture §4/§6): ``EME2000`` (canonical), ``J2000`` (an
alias of the same member), ``ITRF`` (IERS 2010 conventions), and ``TEME`` (the
SGP4 output frame). Relative-motion frames (RTN/LVLH) are deferred — see
architecture §13.
"""

from __future__ import annotations

import math
from enum import Enum
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.frames  # noqa: F401

    from .observation import GeodeticPosition  # noqa: F401
    from .states import State, Trajectory  # noqa: F401


class Frame(Enum):
    """A reference frame; each member maps to an Orekit frame on demand.

    ``EME2000`` is canonical because Orekit prefers that name
    (``FramesFactory.getEME2000()``); ``J2000`` is declared with the same value
    so Python's enum-alias mechanism makes it the *same* member —
    ``Frame.J2000 is Frame.EME2000`` is ``True``, ``Frame("EME2000")`` returns
    the canonical member, and ``J2000`` does not appear in ``list(Frame)``. The
    two names refer to the same frame (mean equator and equinox of J2000.0) and
    coexist for readability.
    """

    EME2000 = "EME2000"  # canonical; Orekit's preferred name for the frame
    J2000 = "EME2000"  # same value → automatic alias of EME2000
    ITRF = "ITRF"  # IERS 2010 conventions
    TEME = "TEME"  # SGP4 output frame

    def to_orekit(self) -> "org.orekit.frames.Frame":
        """Return the Orekit frame for this member.

        The only JVM-touching ``Frame`` method: starts the JVM on first call via
        ``_ensure_started()`` (lazy-JVM contract, architecture §10), then resolves
        the member through ``FramesFactory``. ``ITRF`` uses the IERS 2010
        conventions with simplified EOP (``getITRF(IERS_2010, True)``), matching
        the v1 frame set (architecture §4/§6). ``J2000`` is an alias of
        ``EME2000`` (same enum member), so it resolves through the ``EME2000``
        branch.
        """
        from .._orekit_init import _ensure_started

        _ensure_started()
        from org.orekit.frames import FramesFactory
        from org.orekit.utils import IERSConventions

        if self is Frame.EME2000:
            return FramesFactory.getEME2000()
        if self is Frame.ITRF:
            return FramesFactory.getITRF(IERSConventions.IERS_2010, True)
        if self is Frame.TEME:
            return FramesFactory.getTEME()
        # Unreachable: every defined member is handled above. Guards against a
        # new member being added without a mapping (fail loud, not silent).
        raise NotImplementedError(f"No Orekit frame mapping for {self!r}")


def _require_pseudo_inertial(
    frame: "Frame", method: str, remedy: str
) -> "org.orekit.frames.Frame":
    """Return ``frame.to_orekit()``, raising ``ValueError`` if it is not inertial.

    The shared guard for the classical-element conversions
    (:meth:`State.to_keplerian`, :meth:`KeplerianElements.to_state`): both are
    undefined in a rotating frame such as ``ITRF``, so they fail fast with a clean
    ``ValueError`` rather than leaking the raw Orekit exception. ``method`` names
    the caller and ``remedy`` is the caller-specific fix appended to the common
    message. The resolved Orekit frame is returned so the caller reuses it instead
    of a second ``to_orekit()`` lookup. Starts the JVM lazily via ``to_orekit``.
    """
    ok_frame = frame.to_orekit()
    if not ok_frame.isPseudoInertial():
        raise ValueError(
            f"{method} requires a pseudo-inertial frame, got {frame.name}; "
            f"classical orbital elements are undefined in a rotating frame. {remedy}"
        )
    return ok_frame


def to_geodetic(state: "State") -> "GeodeticPosition":
    """Convert an Earth-fixed (ITRF) :class:`State` to WGS84 geodetic lat/lon/alt.

    Returns a :class:`~propygator.core.observation.GeodeticPosition` with latitude
    and longitude in degrees and geodetic altitude above the WGS84 ellipsoid in
    meters, computed by projecting the state's position onto the canonical Earth
    ellipsoid (:func:`core.bodies._earth`).

    **Strict Earth-fixed-input contract.** ``state`` must be in :attr:`Frame.ITRF`;
    a state in ``EME2000``/``TEME`` raises ``ValueError`` rather than silently
    auto-converting — geodetic lat/lon/alt is only meaningful in an Earth-fixed
    frame, and the explicit-frame rule (architecture §6/§10) keeps this low-level
    function from hiding a frame conversion. Convert first with
    ``state.to_frame(Frame.ITRF)``. The JVM starts lazily on first call.
    """
    if state.frame is not Frame.ITRF:
        raise ValueError(
            f"to_geodetic requires an Earth-fixed ITRF state, got {state.frame.name}; "
            "convert first with state.to_frame(Frame.ITRF). This function does not "
            "auto-convert (architecture §6/§10)."
        )

    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.hipparchus.geometry.euclidean.threed import Vector3D

    from .bodies import _earth
    from .observation import GeodeticPosition

    earth = _earth()
    point = Vector3D(
        float(state.position[0]),
        float(state.position[1]),
        float(state.position[2]),
    )
    # Project onto the ellipsoid in its own body frame (ITRF); reuse the bound
    # earth's body frame rather than re-resolving Frame.ITRF.to_orekit().
    geo = earth.transform(point, earth.getBodyFrame(), state.epoch.to_orekit())
    return GeodeticPosition(
        math.degrees(geo.getLatitude()),
        math.degrees(geo.getLongitude()),
        float(geo.getAltitude()),
    )


def geodetic_track(
    traj: "Trajectory",
) -> "tuple[Trajectory, np.ndarray, np.ndarray, np.ndarray]":
    """Return ``traj`` in ITRF plus per-sample geodetic latitude/longitude/altitude.

    Converts to ITRF once (:func:`to_geodetic` requires an Earth-fixed state — its
    strict Chunk 3 contract) and projects every sample, returning ``(itrf_trajectory,
    latitude_deg, longitude_deg, altitude_m)`` as parallel ``float64`` arrays. Shared
    by CSV export and the ground-track / altitude plots so the per-sample Orekit
    transform + geodetic projection (a bulk-path hotspot) is computed once per
    consumer rather than re-derived in three places.

    Memoized on the trajectory (:meth:`Trajectory._geodetic_track`, the same lazy
    cache-on-first-call pattern as the ``at()`` ephemeris), so the dedup spans the
    trajectory's whole lifetime — ``plot_summary`` (ground track + altitude) and a full
    ``export_all`` reuse one projection instead of recomputing it 2–3×. The returned
    lat/lon/alt arrays are read-only. The JVM starts lazily.
    """
    return traj._geodetic_track()
