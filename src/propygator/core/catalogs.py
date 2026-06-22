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

**Magnitude alignment for Feature 1.5.** The same file will later carry the
standard-magnitude table (architecture §3); this seed set is deliberately limited to
bright **LEO** objects that appear in Mike McCants's ``qsmag`` standard-magnitude
database (https://www.mmccants.org/programs/qsmag.zip), so the registry and that
future table stay consistent (GEO / faint objects are absent from visual-observer
magnitude tables and so are omitted here). Note when 1.5 lands: ``qsmag`` magnitudes
assume 100% illumination, while architecture §3's "standard magnitude at 1000 km,
50% phase angle" is the Heavens-Above convention — a constant-offset difference to
reconcile then, not here.
"""

from __future__ import annotations


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
