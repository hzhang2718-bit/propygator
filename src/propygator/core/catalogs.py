"""Popular-satellite registry: friendly name -> NORAD catalog id (Feature 1.3 Chunk 6).

Reference data, **not** I/O — so it lives in ``core/`` (architecture §3, §7), is
pure-Python and **safe before JVM init**, and imports nothing from any sibling
subpackage (``tle/`` / ``tracking/`` / ``propagation/``). The fetch path
(``tle.sources.fetch_tle`` / ``TLE.from_norad_id``, Chunk 7) resolves a user's
``"ISS"`` / ``25544`` / ``"25544"`` argument to a catalog number through
:func:`_resolve_norad_id` here before hitting the network.

**Citations (architecture §3: "untraceable 'looks about right' values are not
acceptable").** Every catalog number below was verified on 2026-06-21 against
CelesTrak's GP/SATCAT data (https://celestrak.org/satcat/ ; the per-object name in
each inline comment is the exact CelesTrak GP object name), so the registry is
auditable and extensible.

**Standard-magnitude table (Feature 1.5).** The registry's companion table
``_STANDARD_MAGNITUDES`` (below) carries each object's standard visual magnitude in
the contract convention — intrinsic brightness at 1000 km range and **50%
illumination** (architecture §3; features.md §1.5 "Brightness") — seeded from Mike
McCants's ``qsmag`` database with the full-phase -> 50%-phase diffuse-sphere offset
(+2.5*log10(pi) ~= +1.24 mag) applied: the constant-offset reconciliation the
Feature-1.3-era note here anticipated, verified at the 1.5 build (see the table's
provenance block). The registry seed set was deliberately limited to bright **LEO**
objects appearing in ``qsmag`` so the two stay consistent (GEO / faint objects are
absent from visual-observer magnitude tables and so are omitted); the one exception
is Tianhe/CSS, which post-dates the archived ``qsmag`` and is sourced from
Heavens-Above instead.
"""

from __future__ import annotations

import math


def _normalize(name: str) -> str:
    """Canonical lookup key: uppercase, with all whitespace and hyphens removed.

    So ``"NOAA-19"``, ``"NOAA 19"``, and ``"noaa19"`` all map to one key
    (``"NOAA19"``), making lookup case-, whitespace-, and hyphen-insensitive
    without cluttering the registry with spelling-variant aliases.
    """
    return "".join(name.split()).upper().replace("-", "")


# Friendly name (and common aliases) -> NORAD catalog number. Keys are written in a
# readable form; lookup normalizes both sides via _normalize, so the exact spacing /
# hyphenation / case here does not matter for resolution. Each id verified 2026-06-21
# against CelesTrak GP (the comment is the exact CelesTrak GP object name).
_NAME_TO_NORAD: dict[str, int] = {
    "ISS": 25544,  # ISS (ZARYA) — LEO crewed
    "ZARYA": 25544,  # alias of ISS
    "HST": 20580,  # HST — Hubble Space Telescope, LEO science
    "HUBBLE": 20580,  # alias of HST
    "TIANGONG": 48274,  # CSS (TIANHE) — LEO crewed (China)
    "CSS": 48274,  # alias of Tiangong
    "TIANHE": 48274,  # alias of Tiangong (core module)
    "NOAA-19": 33591,  # NOAA 19 — LEO polar weather
    "TERRA": 25994,  # TERRA — LEO Earth observation
    "AQUA": 27424,  # AQUA — LEO Earth observation
    "ENVISAT": 27386,  # ENVISAT — LEO Earth observation (defunct, large/bright)
}

# Normalized-key view built once at import; the resolution lookup table.
_LOOKUP: dict[str, int] = {
    _normalize(name): norad_id for name, norad_id in _NAME_TO_NORAD.items()
}


# ---------------------------------------------------------------------------
# Standard-magnitude table (Feature 1.5)
# ---------------------------------------------------------------------------
#
# Standard visual magnitude in the *contract* convention (architecture §3;
# features.md §1.5 "Brightness"): intrinsic brightness at 1000 km range and 50%
# illumination (phase angle 90 deg, diffuse-sphere phase function).
#
# Primary source: Mike McCants's qsmag database — the file "qs.mag" dated
# 2020-09-14, retrieved 2026-07-07 via the Internet Archive snapshot of
# 2025-05-27 (the live https://www.mmccants.org/programs/qsmag.zip link 404s;
# the site is preserved but partially broken):
#   https://web.archive.org/web/20250527224825id_/https://www.mmccants.org/programs/qsmag.zip
# qsmag magnitudes are defined at 1000 km range and *full* phase — quicksat.txt
# (same site, snapshot 2025-05-28): "the intrinsic magnitude ... is defined to
# be the maximum apparent brightness of the satellite when it is seen at full
# phase at a range of 1000 kilometers" — so each raw value is converted to the
# 50%-phase convention by the diffuse-sphere offset +2.5*log10(pi) ~= +1.243 mag
# (phase function F(phi) = ((pi - phi)*cos(phi) + sin(phi))/pi; F(90deg)/F(0) = 1/pi).
#
# Offset direction check (2026-07-07, per the 1.5 build plan Chunk 1): with the
# offset applied, the converted values land within ~0.5 mag of Heavens-Above's
# independently maintained intrinsic magnitudes (same 1000 km / 50% convention):
# ISS -2.5 + 1.243 = -1.26 vs H-A -1.8; HST 1.5 + 1.243 = 2.74 vs H-A 2.2
# (https://www.heavens-above.com/satinfo.aspx?satid=25544 / 20580, retrieved
# 2026-07-07). With the opposite sign they would sit ~2 mag off. The residual
# ~0.5 mag is normal disagreement between observer-fit magnitude estimates.

# Full-phase (qsmag) -> 50%-phase (contract) diffuse-sphere offset, ~= +1.243.
_QSMAG_TO_STD_OFFSET = 2.5 * math.log10(math.pi)

# NORAD id -> standard magnitude (1000 km, 50% illumination). Raw qsmag values
# quoted per entry; each converts through _QSMAG_TO_STD_OFFSET.
_STANDARD_MAGNITUDES: dict[int, float] = {
    25544: -2.5 + _QSMAG_TO_STD_OFFSET,  # ISS — qs.mag: "ISS  -2.5"
    20580: 1.5 + _QSMAG_TO_STD_OFFSET,  # HST — qs.mag: "HST  1.5" (occ flare to -4)
    33591: 5.0 + _QSMAG_TO_STD_OFFSET,  # NOAA 19 — qs.mag: "NOAA 19  5.0"
    25994: 2.0 + _QSMAG_TO_STD_OFFSET,  # TERRA — qs.mag: "Terra  2.0"
    27424: 4.0 + _QSMAG_TO_STD_OFFSET,  # AQUA — qs.mag: "AQUA  4.0"
    27386: 3.0 + _QSMAG_TO_STD_OFFSET,  # ENVISAT — qs.mag: "EnviSat  3.0"
    # Tianhe/CSS post-dates the archived qsmag (launched 2021-04), so its value
    # comes from Heavens-Above directly — already in the 1000 km / 50% contract
    # convention, no offset: "Intrinsic brightness ... 0.0 (at 1000km distance,
    # 50% illuminated)", https://www.heavens-above.com/satinfo.aspx?satid=48274,
    # retrieved 2026-07-07.
    48274: 0.0,  # CSS (TIANHE)
}


def _standard_magnitude(norad_id: int) -> float | None:
    """Standard magnitude (1000 km, 50% illumination) for ``norad_id``, or ``None``.

    ``None`` means the satellite is outside the curated table: ``find_passes``
    then returns passes without magnitude estimates (architecture §3) unless the
    caller supplies ``standard_magnitude=`` explicitly. Pure-Python, safe before
    init.
    """
    return _STANDARD_MAGNITUDES.get(norad_id)


def _check_positive(norad_id: int) -> int:
    """Return ``norad_id`` if it is a positive catalog number, else raise."""
    if norad_id <= 0:
        raise ValueError(
            f"NORAD catalog number must be a positive integer, got {norad_id!r}."
        )
    return norad_id


def _resolve_norad_id(name_or_id: str | int) -> int:
    """Resolve a friendly name or raw catalog number to a NORAD catalog id.

    - an ``int`` (or a purely numeric string like ``"25544"``) passes through after a
      positive-value check;
    - any other string is resolved through the popular-satellite registry,
      case-, whitespace-, and hyphen-insensitively;
    - an unknown name raises ``ValueError`` naming how to pass a raw id.

    Pure-Python / safe before init; the fetch path (Chunk 7) calls this before any
    network or JVM work.
    """
    if isinstance(name_or_id, bool):
        # bool is an int subclass; reject it so True/False can't slip through as 1/0.
        raise TypeError(
            f"name_or_id must be a satellite name (str) or NORAD id (int), "
            f"not a bool: {name_or_id!r}."
        )
    if isinstance(name_or_id, int):
        return _check_positive(name_or_id)
    if not isinstance(name_or_id, str):
        raise TypeError(
            f"name_or_id must be a satellite name (str) or NORAD id (int), "
            f"got {type(name_or_id).__name__}."
        )

    text = name_or_id.strip()
    try:
        parsed = int(text)
    except ValueError:
        parsed = None  # not numeric -> treat as a name
    if parsed is not None:
        return _check_positive(parsed)

    try:
        return _LOOKUP[_normalize(text)]
    except KeyError:
        known = ", ".join(sorted(_NAME_TO_NORAD))
        raise ValueError(
            f"Unknown satellite name {name_or_id!r}. Pass one of the known names "
            f"({known}) or a raw NORAD catalog number (an int or a numeric string, "
            f"e.g. 25544)."
        ) from None
