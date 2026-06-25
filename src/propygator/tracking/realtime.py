"""Real-time satellite primitives — "where is it now" (Feature 1.4).

The cheap query layer of the tracker: :func:`current_state` and
:func:`current_ground_position` answer "where is this satellite *now*?" for a given
:class:`~propygator.core.tle.TLE`. Both ride the single-shot TEME-``State`` helper
``_tle_state_at`` (``tle/propagator.py``) at ``Epoch.now()`` rather than building a
throwaway ``Trajectory`` for one instant (features.md §1.4 "Real-time primitives").

**Architecture invariants** (architecture §7/§10). ``tracking/`` → ``tle/``/``core/``
is inward-legal, and this module holds no Orekit code — it is pure composition over
``_tle_state_at`` / ``State.to_frame`` / ``to_geodetic``. No Orekit type appears on
either public signature. ``current_state`` returns :data:`Frame.TEME` with **no**
silent conversion (the native SGP4 frame; call ``.to_frame(...)`` to convert), while
``current_ground_position`` returns a frame-less :class:`GeodeticPosition`, so its
internal TEME→ITRF→geodetic conversion is allowed (the ``to_geodetic`` precedent,
architecture §6/§10). The JVM starts lazily on the first call (via the helpers), never
at import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..core.frames import Frame, to_geodetic
from ..core.time import Epoch
from ..tle.propagator import _tle_state_at

if TYPE_CHECKING:
    from ..core.observation import GeodeticPosition
    from ..core.states import State
    from ..core.tle import TLE


def current_state(tle: "TLE") -> "State":
    """Return the satellite's current state (at ``Epoch.now()``) in TEME.

    TEME is the native SGP4 frame — no silent conversion (architecture §10); call
    ``.to_frame(...)`` to express it in another frame. Starts the JVM on first call.
    """
    return _tle_state_at(tle, Epoch.now())


def current_ground_position(tle: "TLE") -> "GeodeticPosition":
    """Return the satellite's current sub-point as WGS84 geodetic lat/lon/alt.

    Evaluates the state at ``Epoch.now()`` and projects it TEME→ITRF→geodetic. The
    result is a frame-less :class:`GeodeticPosition`, so the internal conversion is
    allowed (architecture §6/§10, the ``to_geodetic`` precedent). Starts the JVM on
    first call.
    """
    return to_geodetic(_tle_state_at(tle, Epoch.now()).to_frame(Frame.ITRF))
