"""``Frame`` — propygator's reference-frame sentinel.

A :class:`Frame` is an enum member that names a reference frame and knows how to
produce its Orekit counterpart on demand. Constructing/accessing frames is
pure-Python and safe before JVM init (architecture §10); only
:meth:`Frame.to_orekit` crosses into Orekit, and it is deferred to Feature 1.

v1 supported set (architecture §4/§6): ``EME2000`` (canonical), ``J2000`` (an
alias of the same member), ``ITRF`` (IERS 2010 conventions), and ``TEME`` (the
SGP4 output frame). Relative-motion frames (RTN/LVLH) are deferred — see
architecture §13.
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.frames  # noqa: F401


_TO_OREKIT_DEFERRED = (
    "Frame.to_orekit() is deferred to Feature 1. Resolving a Frame to its "
    "Orekit counterpart (e.g. FramesFactory.getEME2000()/getITRF()/getTEME()) "
    "requires the JVM and orekit-data, so it is not part of the pure-Python "
    "safe-before-init surface (architecture §6/§10)."
)


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
        """Return the Orekit frame for this member (deferred to Feature 1).

        Will start the JVM via ``_ensure_started()`` and look the frame up in
        ``FramesFactory`` once implemented; raises :class:`NotImplementedError`
        for now (build-plan chunk 4).
        """
        raise NotImplementedError(_TO_OREKIT_DEFERRED)
