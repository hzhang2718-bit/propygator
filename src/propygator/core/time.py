"""``Epoch`` and ``TimeScale`` — propygator's time representation.

``Epoch`` is the most-used boundary type and is fully pure-Python: constructing
and manipulating epochs never starts the JVM (architecture §10 "safe before
init" surface). Only :meth:`Epoch.to_orekit` crosses into Orekit.

Storage (architecture §6). An ``Epoch`` holds the absolute instant as a
two-part count of seconds since the J2000 epoch instant: ``_int_seconds`` (the
whole-second part) and ``_frac_seconds`` in ``[0, 1)``. The J2000 epoch instant
is Orekit's ``AbsoluteDate.J2000_EPOCH`` — 2000-01-01T12:00:00 TT, equivalently
2000-01-01T11:59:27.816 TAI — so the J2000 instant itself is ``(0, 0.0)``.

Why a TT calendar stores "TAI seconds since J2000" without contradiction.
Architecture §6 specifies the stored count as "TAI seconds since J2000" — an
*elapsed* count measured on a continuous, leap-free scale. This module computes
that count as ``TT(t) - TT(J2000)``, but the value is identical to the TAI
count, because TT and TAI differ by a *constant* (``TT = TAI + 32.184 s``) that
cancels in the difference::

    TT(t) - TT(J2000) = (TAI(t) + 32.184) - (TAI(J2000) + 32.184)
                      = TAI(t) - TAI(J2000)

So the stored number is bit-for-bit "TAI seconds since J2000"; TT is only the
computation route. The route matters for exactness, not meaning: J2000 is exact
on the TT calendar (12:00:00.000, zero sub-second), whereas the TAI calendar
puts it at the fractional ...27.816, so computing via TT keeps the anchor exact
(``durationFrom(J2000_EPOCH) == 0.0``) and avoids carrying a ``.816`` reference
constant and its round-off. What would genuinely break §6 is using a *UTC*
calendar: UTC's offset to TAI is non-constant (leap seconds), so it would not
cancel and the stored count would be wrong. TAI and TT are interchangeable here
precisely because both are leap-free with a constant mutual offset; UTC is not.

The ``scale`` field is only a *presentation* tag for output (``to_iso`` /
``to_datetime``); it never changes the stored instant (``in_scale`` relabels
without touching the count). A timezone-aware input fixes the instant, with
``scale`` choosing presentation; a naive ISO string is interpreted in ``scale``.

UT1 is deferred. UT1<->TAI needs continuously-varying Earth-orientation (EOP)
data that only orekit-data provides, so UT1 is outside the pure-Python surface
and raises ``NotImplementedError`` until Feature 1 wires it to the JVM
(architecture §6).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import TYPE_CHECKING

from . import _leap_seconds

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.time  # noqa: F401


class TimeScale(Enum):
    """Time scale tagging an :class:`Epoch`'s presentation.

    UTC and TT are the user-facing / dynamics convention pair (architecture §4);
    TAI is the continuous scale the instant is stored against; UT1 is named here
    but its construction/conversion is deferred to Feature 1 (needs EOP data).
    """

    UTC = "UTC"
    TAI = "TAI"
    TT = "TT"
    UT1 = "UT1"


# TT - TAI is fixed by definition.
_TT_MINUS_TAI = 32.184

# The J2000 epoch instant on the (leap-free) TT calendar: exactly noon TT.
# Using TT — where J2000 has a zero sub-second part — keeps the conversion
# arithmetic exact for the anchor and avoids a fractional reference constant.
_J2000_TT = datetime(2000, 1, 1, 12, 0, 0)

# ISO 8601 parser: date, time, optional fractional seconds (arbitrary digits),
# optional 'Z' or +/-HH[:]MM offset. The fraction is captured as a string so
# from_iso keeps full precision instead of rounding through microseconds.
_ISO_RE = re.compile(
    r"^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})"
    r"[T ](?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2})"
    r"(?P<frac>\.\d+)?"
    r"(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)

_UT1_MESSAGE = (
    "UT1 time scale is not yet supported. UT1<->TAI requires continuously-"
    "varying Earth-orientation (EOP) data from orekit-data, available only "
    "once the JVM is started, so UT1 is outside the pure-Python Epoch surface "
    "and is deferred to Feature 1 (architecture §6)."
)


def _normalize(int_s: int, frac: float) -> tuple[int, float]:
    """Fold ``frac`` back into ``[0, 1)``, carrying whole seconds into ``int_s``."""
    carry = math.floor(frac)
    new_frac = frac - carry
    # Guard the float edge where ``frac - floor(frac)`` rounds up to exactly 1.0
    # (e.g. frac = -1e-20): keep the invariant _frac_seconds in [0, 1).
    if new_frac >= 1.0:
        carry += 1
        new_frac = 0.0
    return int_s + int(carry), new_frac


def _tt_offset_for_scale(scale: TimeScale, utc_wallclock: datetime) -> float:
    """Seconds to add to a ``scale`` wall-clock to reach the TT wall-clock.

    i.e. ``TT - scale``. For UTC the leap offset is looked up from the (UTC)
    wall-clock passed in. UT1 is deferred.
    """
    if scale is TimeScale.TT:
        return 0.0
    if scale is TimeScale.TAI:
        return _TT_MINUS_TAI
    if scale is TimeScale.UTC:
        return _TT_MINUS_TAI + _leap_seconds.tai_minus_utc_for_utc(utc_wallclock)
    raise NotImplementedError(_UT1_MESSAGE)


def _count_from_wallclock(
    whole_dt: datetime, frac: float, scale: TimeScale
) -> tuple[int, float]:
    """Absolute seconds-since-J2000 count from a wall-clock in ``scale``.

    ``whole_dt`` is a naive datetime with ``microsecond == 0`` (the whole-second
    part); ``frac`` is the sub-second part in ``[0, 1)``. The wall-clock is first
    counted as if it were TT, then corrected by ``TT - scale``.
    """
    delta = whole_dt - _J2000_TT
    int_s = delta.days * 86400 + delta.seconds
    offset = _tt_offset_for_scale(scale, whole_dt)
    return _normalize(int_s, frac + offset)


def _wallclock_from_count(
    int_s: int, frac: float, scale: TimeScale
) -> tuple[datetime, float]:
    """Wall-clock (naive whole-second datetime + sub-second frac) in ``scale``.

    Inverse of :func:`_count_from_wallclock`. The count is TT-relative, so the
    target wall-clock is reached by adding ``scale - TT``. For UTC the leap
    offset is looked up from the reconstructed TAI wall-clock (TAI is monotonic,
    so the lookup is unambiguous). UT1 is deferred.
    """
    if scale is TimeScale.TT:
        scale_minus_tt = 0.0
    elif scale is TimeScale.TAI:
        scale_minus_tt = -_TT_MINUS_TAI
    elif scale is TimeScale.UTC:
        tai_int, tai_frac = _normalize(int_s, frac - _TT_MINUS_TAI)
        tai_whole = _J2000_TT + timedelta(seconds=tai_int)
        leap = _leap_seconds.tai_minus_utc_for_tai(tai_whole)
        scale_minus_tt = -(_TT_MINUS_TAI + leap)
    else:
        raise NotImplementedError(_UT1_MESSAGE)

    s_int, s_frac = _normalize(int_s, frac + scale_minus_tt)
    return _J2000_TT + timedelta(seconds=s_int), s_frac


def _format_frac(frac: float) -> str:
    """Render a sub-second fraction as an ISO suffix (``""`` when zero).

    Up to 9 digits (nanosecond display); trailing zeros stripped. Sub-nanosecond
    precision is retained in storage but not shown.
    """
    if frac == 0.0:
        return ""
    s = f"{frac:.9f}"[1:].rstrip("0")  # drop leading "0", keep ".ddd"
    return "" if s == "." else s


def _parse_tz_offset_seconds(tz: str) -> int:
    """Seconds east of UTC for an ISO offset token (``Z`` or ``+/-HH[:]MM``)."""
    if tz == "Z":
        return 0
    sign = 1 if tz[0] == "+" else -1
    digits = tz[1:].replace(":", "")
    return sign * (int(digits[:2]) * 3600 + int(digits[2:4]) * 60)


@dataclass(frozen=True)
class Epoch:
    """An instant in time, stored as seconds since J2000 with a presentation scale.

    Construct via :meth:`from_iso`, :meth:`from_datetime`, or :meth:`now`; the
    leading-underscore fields are the internal two-part store (architecture §6),
    not a supported positional API.
    """

    _int_seconds: int
    _frac_seconds: float
    scale: TimeScale

    def __post_init__(self) -> None:
        # UT1 Epochs cannot be represented without EOP data (deferred). Rejecting
        # here is the single chokepoint covering every construction path,
        # including ``in_scale``/``shifted_by`` (which go through ``replace``).
        if self.scale is TimeScale.UT1:
            raise NotImplementedError(_UT1_MESSAGE)
        if not math.isfinite(self._frac_seconds):
            raise ValueError(f"_frac_seconds must be finite, got {self._frac_seconds!r}")
        if not (0.0 <= self._frac_seconds < 1.0):
            raise ValueError(
                f"_frac_seconds must be in [0.0, 1.0), got {self._frac_seconds!r}; "
                "construct via Epoch.from_iso/from_datetime/now, not the raw fields."
            )

    # --- constructors ------------------------------------------------------

    @classmethod
    def from_iso(cls, iso: str, scale: TimeScale = TimeScale.UTC) -> "Epoch":
        """Parse an ISO 8601 datetime string.

        A naive string (``"2024-01-01T00:00:00"``) is interpreted with its
        wall-clock numbers in ``scale``. A string carrying a UTC offset (``Z`` or
        ``+/-HH:MM``) fixes the physical instant; ``scale`` then only sets the
        presentation. Requires full ``YYYY-MM-DDThh:mm:ss`` (optionally with a
        fractional second); raises ``ValueError`` otherwise.
        """
        m = _ISO_RE.match(iso.strip())
        if m is None:
            raise ValueError(f"Could not parse ISO 8601 datetime: {iso!r}")
        g = m.groupdict()
        whole_dt = datetime(
            int(g["year"]), int(g["month"]), int(g["day"]),
            int(g["hour"]), int(g["minute"]), int(g["second"]),
        )
        frac = float(g["frac"]) if g["frac"] else 0.0
        tz = g["tz"]
        if tz is not None:
            # Offset present: the string denotes an instant. Convert to the UTC
            # wall-clock, interpret as UTC; ``scale`` is presentation only.
            utc_whole = whole_dt - timedelta(seconds=_parse_tz_offset_seconds(tz))
            int_s, fr = _count_from_wallclock(utc_whole, frac, TimeScale.UTC)
            return cls(int_s, fr, scale)
        int_s, fr = _count_from_wallclock(whole_dt, frac, scale)
        return cls(int_s, fr, scale)

    @classmethod
    def from_datetime(cls, dt: datetime, scale: TimeScale = TimeScale.UTC) -> "Epoch":
        """Build from a timezone-aware ``datetime``.

        Naive datetimes (``tzinfo is None``) are rejected at the boundary
        (architecture §4). The aware datetime fixes the physical instant; the
        wall-clock is taken in UTC and ``scale`` sets the presentation.
        """
        if dt.tzinfo is None or dt.utcoffset() is None:
            raise ValueError(
                "from_datetime requires a timezone-aware datetime; naive "
                "datetimes are rejected (architecture §4). Attach tzinfo "
                "(e.g. datetime.timezone.utc) or use Epoch.from_iso."
            )
        utc_dt = dt.astimezone(timezone.utc)
        whole_dt = utc_dt.replace(microsecond=0, tzinfo=None)
        int_s, fr = _count_from_wallclock(whole_dt, utc_dt.microsecond * 1e-6, TimeScale.UTC)
        return cls(int_s, fr, scale)

    @classmethod
    def now(cls, scale: TimeScale = TimeScale.UTC) -> "Epoch":
        """Current instant from the system clock, presented in ``scale``."""
        return cls.from_datetime(datetime.now(timezone.utc), scale)

    # --- transforms --------------------------------------------------------

    def in_scale(self, scale: TimeScale) -> "Epoch":
        """Return the same instant presented in ``scale``.

        Pure relabeling — the stored count is unchanged (architecture §6).
        ``scale=TimeScale.UT1`` is deferred (``NotImplementedError``).
        """
        if scale is self.scale:
            return self
        return replace(self, scale=scale)

    def shifted_by(self, seconds: float) -> "Epoch":
        """Return the instant ``seconds`` later (negative shifts earlier).

        The fraction is renormalized back into ``[0, 1)``; the scale is kept.
        """
        add_int = math.floor(seconds)
        new_int, new_frac = _normalize(
            self._int_seconds + add_int, self._frac_seconds + (seconds - add_int)
        )
        return replace(self, _int_seconds=new_int, _frac_seconds=new_frac)

    # --- output ------------------------------------------------------------

    def to_iso(self) -> str:
        """ISO 8601 string of the wall-clock in ``self.scale`` (no zone suffix).

        The scale is carried by the Epoch, so no suffix is appended; round-trip
        via ``Epoch.from_iso(s, scale=epoch.scale)``.
        """
        whole_dt, frac = _wallclock_from_count(
            self._int_seconds, self._frac_seconds, self.scale
        )
        return whole_dt.strftime("%Y-%m-%dT%H:%M:%S") + _format_frac(frac)

    def to_datetime(self) -> datetime:
        """The instant as a timezone-aware (UTC) ``datetime``, microsecond precision.

        Always UTC-referenced regardless of ``scale`` — Python's ``tzinfo`` models
        civil UTC offsets, not TAI/TT. Sub-microsecond precision is truncated.
        """
        whole_dt, frac = _wallclock_from_count(
            self._int_seconds, self._frac_seconds, TimeScale.UTC
        )
        return whole_dt.replace(tzinfo=timezone.utc) + timedelta(
            microseconds=round(frac * 1e6)
        )

    if TYPE_CHECKING:
        def to_orekit(self) -> "org.orekit.time.AbsoluteDate": ...
    else:
        def to_orekit(self):
            """Build the Orekit ``AbsoluteDate`` for this instant.

            The only JVM-touching Epoch method: starts the JVM on first call via
            ``_ensure_started()``. The two ``shiftedBy`` steps preserve precision —
            an exact integer-second shift lands on a whole TAI second (Orekit
            keeps the long part exact), then the sub-second fraction is added.
            """
            from .._orekit_init import _ensure_started

            _ensure_started()
            from org.orekit.time import AbsoluteDate

            return AbsoluteDate.J2000_EPOCH.shiftedBy(
                float(self._int_seconds)
            ).shiftedBy(self._frac_seconds)
