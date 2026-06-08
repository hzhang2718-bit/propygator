"""Bundled static leap-second table for pure-Python UTC<->TAI conversion.

``Epoch`` construction must work *before* the JVM starts (architecture §10
"safe before init" surface), so the leap-second data needed for UTC<->TAI
cannot be read from orekit-data (which requires a running JVM). propygator
therefore bundles this small static table, transcribed verbatim from the
IERS-maintained ``tai-utc.dat`` shipped inside orekit-data.

Scope: the integer-leap-second era (1972-01-01 onward). Every step since 1972
is a whole-second change in TAI-UTC. The pre-1972 era used a drifting rational
offset that is out of scope for a satellite library targeting J2000+ epochs;
UTC instants before 1972-01-01 clamp to the earliest tabulated offset (10 s).

Maintenance: refresh this table when the IERS announces a new leap second
(none since 2017-01-01 — TAI-UTC has held constant at 37 s). At first JVM
touch, Feature 1 will cross-check this table against orekit-data's UTC-TAI
history and warn on mismatch (architecture §6).
"""

from __future__ import annotations

import bisect
from datetime import datetime, timedelta

# (UTC instant at which the new offset takes effect, TAI - UTC in seconds).
# Transcribed from orekit-data/tai-utc.dat, integer-leap-second era only.
_LEAP_SECONDS: tuple[tuple[datetime, int], ...] = (
    (datetime(1972, 1, 1), 10),
    (datetime(1972, 7, 1), 11),
    (datetime(1973, 1, 1), 12),
    (datetime(1974, 1, 1), 13),
    (datetime(1975, 1, 1), 14),
    (datetime(1976, 1, 1), 15),
    (datetime(1977, 1, 1), 16),
    (datetime(1978, 1, 1), 17),
    (datetime(1979, 1, 1), 18),
    (datetime(1980, 1, 1), 19),
    (datetime(1981, 7, 1), 20),
    (datetime(1982, 7, 1), 21),
    (datetime(1983, 7, 1), 22),
    (datetime(1985, 7, 1), 23),
    (datetime(1988, 1, 1), 24),
    (datetime(1990, 1, 1), 25),
    (datetime(1991, 1, 1), 26),
    (datetime(1992, 7, 1), 27),
    (datetime(1993, 7, 1), 28),
    (datetime(1994, 7, 1), 29),
    (datetime(1996, 1, 1), 30),
    (datetime(1997, 7, 1), 31),
    (datetime(1999, 1, 1), 32),
    (datetime(2006, 1, 1), 33),
    (datetime(2009, 1, 1), 34),
    (datetime(2012, 7, 1), 35),
    (datetime(2015, 7, 1), 36),
    (datetime(2017, 1, 1), 37),
)

# Earliest tabulated offset, used to clamp pre-1972 instants.
_EARLIEST_OFFSET = _LEAP_SECONDS[0][1]

# Newest entry's UTC instant; informational (e.g. for the Feature-1 cross-check).
TABLE_VALID_FROM = _LEAP_SECONDS[-1][0]

# Forward path: UTC thresholds and matching offsets, split for bisect.
_UTC_THRESHOLDS: tuple[datetime, ...] = tuple(t for t, _ in _LEAP_SECONDS)
_OFFSETS: tuple[int, ...] = tuple(o for _, o in _LEAP_SECONDS)

# Reverse path: the TAI instant at which each step takes effect
# (= UTC threshold + the new offset). Strictly increasing, so bisect applies.
_TAI_THRESHOLDS: tuple[datetime, ...] = tuple(
    t + timedelta(seconds=o) for t, o in _LEAP_SECONDS
)


def tai_minus_utc_for_utc(utc: datetime) -> int:
    """TAI - UTC (whole seconds) for a UTC wall-clock instant.

    ``utc`` is a naive datetime carrying UTC wall-clock components. Instants
    before 1972-01-01 clamp to the earliest tabulated offset.
    """
    idx = bisect.bisect_right(_UTC_THRESHOLDS, utc) - 1
    if idx < 0:
        return _EARLIEST_OFFSET
    return _OFFSETS[idx]


def tai_minus_utc_for_tai(tai: datetime) -> int:
    """TAI - UTC (whole seconds) for a TAI wall-clock instant.

    The reverse of :func:`tai_minus_utc_for_utc`, used when reconstructing a UTC
    wall-clock from internal TAI storage. ``tai`` is a naive datetime carrying
    TAI wall-clock components. Pre-1972 instants clamp to the earliest offset.
    """
    idx = bisect.bisect_right(_TAI_THRESHOLDS, tai) - 1
    if idx < 0:
        return _EARLIEST_OFFSET
    return _OFFSETS[idx]
