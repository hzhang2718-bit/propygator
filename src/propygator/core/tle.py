"""``TLE`` — a two-line element set, propygator's SGP4/SDP4 input type.

A frozen dataclass wrapping the two 69-character TLE lines (plus an optional
name). Construction, parsing, the mod-10 checksum check, and the ``epoch`` /
``norad_id`` accessors are **pure-Python and safe before JVM init** (architecture
§10): a user can build and inspect a TLE, and Feature 1.3's pre-flight can read
``tle.epoch`` for its stale-TLE check, without starting the JVM. Only
:meth:`TLE.to_orekit` crosses into Orekit (the same lazy + ``TYPE_CHECKING``
pattern as :meth:`Epoch.to_orekit`).

``from_norad_id`` (the CelesTrak fetch path, below) is network-touching, and
``from_state_unfitted`` (the row -> format-valid TLE utility) is JVM-touching.
Neither is part of the safe-before-init surface.

The fixed-column layout parsed here follows the standard NORAD/Celestrak TLE
format (1-based columns; Python slices are 0-based, hence the ``-1`` offsets):

  Line 1: col 1 line number '1'; cols 3-7 catalog (NORAD) number; cols 19-20
  epoch year (2-digit); cols 21-32 epoch day-of-year + fraction; col 69 checksum.
  Line 2: col 1 line number '2'; cols 3-7 catalog number; col 69 checksum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from .time import Epoch, TimeScale

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.propagation.analytical.tle  # noqa: F401

    from .states import State

_LINE_LENGTH = 69

# The 2-digit-year window NORAD uses: 57-99 -> 1957-1999, 00-56 -> 2000-2056.
# (Picked so the Space Age, which began in 1957, has no pre-epoch ambiguity.)
_YEAR_PIVOT = 57

# Alpha-5 catalog encoding (NORAD, in use since ~2020 once the catalog passed 99,999):
# the first of the 5 catalog columns becomes a base-34 "high digit" — 0-9 then A-Z with
# I and O omitted (they read as 1 and 0) — and the remaining four stay decimal, so
# "A5544" -> 10*10000 + 5544 = 105544 and the range extends to Z9999 = 339,999. Orekit
# decodes the same way (its TLE.getSatelliteNumber() returns this exact int), so
# propygator stays in lock-step while keeping norad_id pure-Python / safe-before-init.
_ALPHA5_ALPHABET = "0123456789ABCDEFGHJKLMNPQRSTUVWXYZ"


def _line_checksum(line: str) -> int:
    """The mod-10 TLE checksum of ``line`` (computed over columns 1-68).

    Each digit adds its value, each minus sign adds 1, everything else
    (letters, '.', '+', blanks) adds 0; the result is taken mod 10. This is the
    standard NORAD line checksum the column-69 digit is meant to equal.
    """
    total = 0
    for ch in line[: _LINE_LENGTH - 1]:
        if ch.isdigit():
            total += int(ch)
        elif ch == "-":
            total += 1
    return total % 10


def _decode_catalog_number(field: str) -> int:
    """Decode a 5-character TLE catalog (NORAD) field to an ``int``.

    Handles both the classic all-numeric id and the modern **Alpha-5** form (a
    base-34 letter in the leading column for numbers >= 100000). A leading digit
    or blank is a classic id parsed with ``int`` (which tolerates the
    space-padding low historical numbers carry); a leading letter is Alpha-5.
    Pure-Python / safe before init, and bit-for-bit equal to Orekit's
    ``getSatelliteNumber()``.
    """
    high = field[0]
    if not high.isalpha():
        # All-numeric (possibly space-padded) — int() strips surrounding blanks.
        return int(field)
    try:
        high_value = _ALPHA5_ALPHABET.index(high.upper())
    except ValueError:
        raise ValueError(
            f"TLE catalog number {field!r} has an invalid leading character "
            f"{high!r}; expected a digit or an Alpha-5 letter (A-Z excluding I/O)."
        ) from None
    return high_value * 10000 + int(field[1:])


@dataclass(frozen=True)
class TLE:
    """A two-line element set: two 69-character lines plus an optional name.

    Build via :meth:`from_strings` (which validates the checksums) for any TLE
    coming from outside the library; the bare constructor runs only the cheap
    structural check in :meth:`__post_init__`. Immutable; all parsing is
    pure-Python and JVM-free except :meth:`to_orekit`.
    """

    line1: str
    line2: str
    name: str | None = None

    def __post_init__(self) -> None:
        # Cheap structural validation only (architecture §10 safe-before-init):
        # exact 69-char lines with the right leading line numbers. The mod-10
        # checksum is validated in from_strings, the parsing entry point.
        for label, line, number in (
            ("line1", self.line1, "1"),
            ("line2", self.line2, "2"),
        ):
            if len(line) != _LINE_LENGTH:
                raise ValueError(
                    f"TLE {label} must be exactly {_LINE_LENGTH} characters, "
                    f"got {len(line)}: {line!r}"
                )
            if line[0] != number:
                raise ValueError(
                    f"TLE {label} must begin with line number {number!r}, "
                    f"got {line[0]!r}: {line!r}"
                )

    # --- constructors ------------------------------------------------------

    @classmethod
    def from_strings(cls, line1: str, line2: str, name: str | None = None) -> "TLE":
        """Parse two TLE lines, validating structure **and** the mod-10 checksums.

        Trailing newlines / carriage returns are stripped (the fetch path splits
        a 3-line CelesTrak block, whose lines carry ``\\r\\n``); no other
        whitespace is touched, since the fixed-column layout is significant. A
        bad checksum, wrong length, or wrong line number raises ``ValueError``
        with an actionable message, so a constructed ``TLE`` is always
        well-formed and ``propagate_tle`` never receives a malformed one
        (architecture §10). Pure-Python / safe before init.
        """
        line1 = line1.rstrip("\r\n")
        line2 = line2.rstrip("\r\n")
        tle = cls(line1, line2, name)  # structural validation (__post_init__)
        for label, line in (("line1", line1), ("line2", line2)):
            stated = line[_LINE_LENGTH - 1]
            if not stated.isdigit():
                raise ValueError(
                    f"TLE {label} has a non-digit checksum character "
                    f"{stated!r} in column {_LINE_LENGTH}: {line!r}"
                )
            expected = _line_checksum(line)
            if int(stated) != expected:
                raise ValueError(
                    f"TLE {label} checksum mismatch: column {_LINE_LENGTH} is "
                    f"{stated} but the computed mod-10 checksum is {expected}. "
                    f"The line may be corrupted or mis-copied: {line!r}"
                )
        # The two lines must describe the same object: their catalog-number fields
        # (cols 3-7) have to agree, or one line was mis-paired/mis-copied. (Orekit's
        # TLE constructor enforces the same; catching it here keeps the failure a
        # clean propygator ValueError before any JVM call, architecture §10.)
        if line1[2:7] != line2[2:7]:
            raise ValueError(
                f"TLE line 1 and line 2 reference different catalog numbers "
                f"({line1[2:7]!r} vs {line2[2:7]!r}); the two lines must describe "
                f"the same object."
            )
        return tle

    @classmethod
    def from_norad_id(cls, norad_id: int, source: str = "celestrak") -> "TLE":
        """Fetch the current TLE for a NORAD catalog number (architecture §6).

        A thin convenience wrapper over :func:`propygator.fetch_tle`: it fetches from
        CelesTrak (24 h cache TTL) and returns a validated ``TLE``. ``source`` is kept
        for forward-compatibility but ``"celestrak"`` is its only valid value in v1
        (Space-Track / ``"auto"`` are deferred, architecture §3).

        **Network-touching, not safe-before-init.** ``tle.sources`` is imported lazily
        inside the method so the class keeps no static ``core -> tle`` import — only
        this classmethod-time call edge, acceptable because the fetch path is not part
        of the safe-before-init surface (Note 1).
        """
        from ..tle.sources import fetch_tle

        return fetch_tle(norad_id, source=source)

    @classmethod
    def from_state_unfitted(
        cls,
        state: "State",
        *,
        norad_id: int | None = None,
        bstar: float | None = None,
        name: str | None = None,
    ) -> "TLE":
        """Build a **format-valid, not round-trip-faithful** TLE from one state.

        The ``unfitted`` in the name is the warning: this produces a TLE with
        correct fixed-column formatting and checksums, but it will **not**
        reproduce the trajectory under SGP4. For a TLE that actually round-trips,
        use ``fit_tle`` (Feature 1.2), the faithful sibling that performs the
        proper iterative osculating -> mean fit. Three independent reasons this
        result is unfaithful:

        1. **Mean vs osculating.** A real TLE carries *mean* (Kozai-Brouwer)
           elements with periodic variations averaged out; the elements computed
           from one state are *osculating*. The J2 short-period term alone shifts
           the osculating semi-major axis by tens of kilometres relative to the
           mean value.
        2. **B\\* is not recoverable from a state.** B\\* is a drag *fit residual*,
           not a physical ballistic coefficient, so it cannot be derived from a
           position/velocity -- only passed in or defaulted. A default
           ``bstar=0.0`` gives the rebuilt TLE *no* drag, so it diverges
           immediately from any decaying orbit. The mean-motion 1st/2nd
           derivatives are zeroed for the same reason (also not recoverable from a
           single state).
        3. **Osculating values in mean-element slots.** The element fields hold
           osculating values placed in mean-element slots (reason 1), and the
           mean-motion field is derived as ``n = sqrt(mu / a**3)`` from the
           library's WGS84 GM (``Constants.WGS84_EARTH_MU``, the same source as
           :func:`core.bodies._earth_mu`) -- whereas a real TLE's mean motion is a
           WGS72/Kozai quantity, a further small constants offset folded under
           "format-valid, not faithful".

        Because osculating elements wobble over an orbit, emitting one TLE per row
        of a trajectory yields a *family* of slightly different TLEs for the same
        orbit, each epoch-stamped to its row. That is correct behaviour -- and is
        itself a picture of the osculating-vs-mean gap -- but it surprises anyone
        expecting identical element sets.

        **Mechanics.** Osculating classical elements are computed **in TEME**
        (``state.to_frame(Frame.TEME).to_keplerian()`` -- a TLE lives in TEME, so
        building from EME2000 elements would stack a frame error on the
        mean/osculating gap); true anomaly is mapped to mean anomaly
        (:meth:`KeplerianElements.mean_anomaly`); the mean-motion field is derived
        from the semi-major axis (reason 3). Orekit's ``TLE`` constructor formats
        the fixed columns and computes both checksums, and the lines are re-parsed
        through :meth:`from_strings`, so the return value is always a validated
        propygator ``TLE``.

        A bare :class:`State` carries neither a catalog number nor a drag term;
        ``norad_id`` and ``bstar`` are therefore passed explicitly or defaulted
        (``norad_id`` -> placeholder ``00000``; ``bstar`` -> ``0.0``). Every other
        TLE field a :class:`State` does not supply is pinned to a fixed
        placeholder: classification ``U``; international designator (launch
        year/number/piece) blank; ephemeris type ``0``; element-set number ``0``;
        revolution number at epoch ``0``; mean-motion 1st/2nd derivatives ``0.0``.

        **JVM-touching, not safe-before-init.** ``State.to_frame`` /
        ``State.to_keplerian`` start the JVM, so this constructor groups with
        :meth:`to_orekit` and :meth:`from_norad_id`, not with
        :meth:`from_strings`.

        Raises ``ValueError`` for a near-parabolic/hyperbolic osculating state
        (e >= 1 has no finite semi-major axis), surfaced cleanly by
        :meth:`State.to_keplerian` rather than as a Java trace.
        """
        from .._orekit_init import _ensure_started

        _ensure_started()
        from org.orekit.propagation.analytical.tle import TLE as OrekitTLE
        from org.orekit.utils import Constants

        from .frames import Frame

        # Osculating elements in TEME (the TLE's native frame); nu -> M for the
        # anomaly field. to_keplerian rejects e >= 1 with a clean ValueError.
        el = state.to_frame(Frame.TEME).to_keplerian()
        mean_anomaly = el.mean_anomaly()  # radians

        # Mean-motion field: n = sqrt(mu / a**3) with the library's single WGS84
        # GM. This is the osculating mean motion under WGS84 GM, not the TLE's
        # WGS72/Kozai mean motion -- a documented non-faithfulness (reason 3).
        mu = float(Constants.WGS84_EARTH_MU)
        mean_motion = math.sqrt(mu / el.semi_major_axis_m**3)  # rad/s

        # Pinned non-physical fields (see docstring). Only satellite number and
        # B* are caller-controllable; everything else a State cannot supply is a
        # fixed placeholder. Orekit computes the fixed-column formatting + the two
        # mod-10 checksums for us, avoiding a reimplementation of the layout.
        orekit_tle = OrekitTLE(
            norad_id if norad_id is not None else 0,  # satellite number (00000)
            "U",  # classification (always unclassified)
            0,  # launch year     -+
            0,  # launch number    |- international designator: placeholder
            "",  # launch piece    -+
            0,  # ephemeris type
            0,  # element-set number
            state.epoch.to_orekit(),
            mean_motion,
            0.0,  # mean-motion 1st derivative (not recoverable from one state)
            0.0,  # mean-motion 2nd derivative (")
            el.eccentricity,
            el.inclination_rad,
            el.arg_perigee_rad,
            el.raan_rad,
            mean_anomaly,
            0,  # revolution number at epoch (placeholder)
            bstar if bstar is not None else 0.0,
        )
        return cls.from_strings(
            str(orekit_tle.getLine1()), str(orekit_tle.getLine2()), name=name
        )

    # --- pure-Python accessors --------------------------------------------

    @property
    def norad_id(self) -> int:
        """The catalog (NORAD) number from line-1 columns 3-7. Safe before init.

        Decodes both the classic all-numeric id and the modern **Alpha-5** form
        (a base-34 letter in the leading column for numbers >= 100000, e.g.
        ``A5544`` -> 105544), matching Orekit's ``getSatelliteNumber()`` while
        staying pure-Python (see :func:`_decode_catalog_number`).
        """
        return _decode_catalog_number(self.line1[2:7])

    @property
    def epoch(self) -> Epoch:
        """The TLE epoch as a UTC :class:`Epoch`. Safe before init.

        Parses line-1 columns 19-32: a 2-digit year (windowed 57-99 -> 19xx,
        00-56 -> 20xx) and a fractional day-of-year (day 1.0 == Jan 1 00:00:00).
        This stays pure-Python so Feature 1.3's stale-TLE pre-flight and the
        ``start=tle.epoch`` default run before the JVM is started.
        """
        year_2digit = int(self.line1[18:20])
        day_of_year = float(self.line1[20:32])
        year = (1900 if year_2digit >= _YEAR_PIVOT else 2000) + year_2digit
        dt = datetime(year, 1, 1, tzinfo=timezone.utc) + timedelta(
            days=day_of_year - 1.0
        )
        return Epoch.from_datetime(dt, TimeScale.UTC)

    # --- Orekit crossing ---------------------------------------------------

    if TYPE_CHECKING:

        def to_orekit(self) -> "org.orekit.propagation.analytical.tle.TLE": ...
    else:

        def to_orekit(self):
            """Build the Orekit ``TLE`` for this element set.

            The only JVM-touching method: starts the JVM on first call via
            ``_ensure_started()``, then constructs Orekit's ``TLE`` from the two
            lines (same lazy + ``TYPE_CHECKING`` pattern as ``Epoch.to_orekit``).
            """
            from .._orekit_init import _ensure_started

            _ensure_started()
            from org.orekit.propagation.analytical.tle import TLE as OrekitTLE

            return OrekitTLE(self.line1, self.line2)
