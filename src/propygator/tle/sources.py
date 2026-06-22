"""CelesTrak TLE fetching + the on-disk TTL cache (Feature 1.3 Chunk 7).

The network path behind ``fetch_tle("ISS")`` and :meth:`TLE.from_norad_id`: resolve a
friendly name / NORAD id (via ``core.catalogs``), GET CelesTrak's GP endpoint, and
return a validated propygator :class:`TLE`. Fetches are cached under
``~/.propygator/cache/`` (architecture §10) so notebook re-runs and repeated tracking
calls do not re-hit the network on every call.

**Source scope — CelesTrak only for v1** (architecture §3; Note 3). The ``source``
parameter is kept on the public signatures for forward-compatibility, but
``"celestrak"`` is its only valid value; ``"auto"`` multi-source resolution and the
Space-Track path are deferred until a second source is wired.

**Two TTLs** (architecture §10): the general path (:func:`fetch_celestrak` /
:func:`fetch_tle`) uses a **24 h** TTL — notebook re-runs within a day hit the cache
while daily re-issues are picked up automatically. A **6 h** TTL
(:data:`_TTL_REALTIME_S`) is reserved for Feature 1.4's realtime tracking path, which
will pass it explicitly; 1.3 never uses it.

**Architecture invariants.** This module is JVM-free — it does network I/O plus the
pure-Python :meth:`TLE.from_strings` parse, and never imports Orekit or starts the JVM.
``requests`` is imported lazily inside the one function that performs the HTTP GET, so
importing ``propygator`` neither starts the JVM nor pulls ``requests``.
"""

from __future__ import annotations

import logging
import time

from .. import _orekit_init
from ..core.catalogs import _resolve_norad_id
from ..core.exceptions import TLEFetchError
from ..core.tle import TLE

logger = logging.getLogger(__name__)

# CelesTrak's "general perturbations" query endpoint. CATNR selects a single catalog
# object and FORMAT=tle returns the classic 3-line (name + 2-line) block.
_CELESTRAK_GP_URL = "https://celestrak.org/NORAD/elements/gp.php"

# Cache TTLs in seconds (architecture §10). The general path uses 24 h; the 6 h
# realtime TTL is reserved for Feature 1.4 (current_position / live tracking), which
# passes it to fetch_celestrak explicitly — 1.3 never uses it.
_TTL_GENERAL_S = 24 * 3600.0
_TTL_REALTIME_S = 6 * 3600.0

# CelesTrak returns this plain-text body (HTTP 200) when a CATNR matches no object.
_NO_DATA_SENTINEL = "No GP data found"


def _cache_path(norad_id: int):
    """The cache file for one catalog object, under :func:`_orekit_init._cache_dir`.

    Keyed by source + NORAD id (``celestrak-<id>.tle``) so a future second source can
    coexist without colliding. ``_orekit_init._cache_dir`` is read through the module
    (not bound at import) so a single monkeypatch in tests redirects both this path and
    ``clear_cache``.
    """
    return _orekit_init._cache_dir() / f"celestrak-{norad_id}.tle"


def _read_cache(norad_id: int, ttl_s: float) -> str | None:
    """Return the cached TLE text for ``norad_id`` if fresh within ``ttl_s``, else None.

    Freshness is the file's modification age; a missing file (or one older than
    ``ttl_s``) is a miss. Never raises on a miss.
    """
    path = _cache_path(norad_id)
    if not path.is_file():
        return None
    age_s = time.time() - path.stat().st_mtime
    if age_s > ttl_s:
        logger.debug(
            "cache stale for NORAD %d (age %.0fs > %.0fs)", norad_id, age_s, ttl_s
        )
        return None
    logger.debug("cache hit for NORAD %d (age %.0fs)", norad_id, age_s)
    return path.read_text(encoding="utf-8")


def _write_cache(norad_id: int, text: str) -> None:
    """Write ``text`` to the cache for ``norad_id``, creating the dir if needed."""
    path = _cache_path(norad_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    logger.debug("cached TLE for NORAD %d at %s", norad_id, path)


def fetch_celestrak(
    norad_id: int,
    *,
    use_cache: bool = True,
    ttl_s: float = _TTL_GENERAL_S,
) -> str:
    """Fetch the raw 3-line CelesTrak TLE block for a NORAD catalog number.

    GETs CelesTrak's GP endpoint (``CATNR=<norad_id>&FORMAT=tle``) and returns the raw
    text (name line + the two element lines). With ``use_cache`` (the default), a cache
    entry younger than ``ttl_s`` is returned without a network call, and a fresh fetch
    is written back; ``use_cache=False`` bypasses **both** the read and the write.

    ``requests`` is imported lazily here so importing the package stays light. Raises
    :class:`TLEFetchError` on a transport failure (no network / DNS / timeout / HTTP
    error status), wrapping ``requests``' deep traceback in a clean, actionable
    message (architecture §3); raises ``ValueError`` if CelesTrak reports no object
    for the id (or returns an unrecognizably short body).
    """
    if use_cache:
        cached = _read_cache(norad_id, ttl_s)
        if cached is not None:
            return cached

    import requests

    logger.info("fetching TLE for NORAD %d from CelesTrak", norad_id)
    try:
        response = requests.get(
            _CELESTRAK_GP_URL,
            params={"CATNR": str(norad_id), "FORMAT": "tle"},
            timeout=30,
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as exc:
        # Translate requests' deep urllib3 traceback into one clean propygator error
        # (architecture §3). HTTP errors carry a status code; connection/timeout
        # failures are named by their requests class. The chain is suppressed
        # (`from None`) so users see only the actionable message.
        if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
            reason = f"HTTP {exc.response.status_code}"
        else:
            reason = type(exc).__name__
        raise TLEFetchError(
            f"Could not fetch TLE for NORAD catalog number {norad_id} from CelesTrak "
            f"({reason}). Check your network connection; if you are offline, build the "
            f"TLE directly from saved lines with TLE.from_strings(line1, line2)."
        ) from None
    text = response.text

    if _NO_DATA_SENTINEL.lower() in text.lower() or len(text.split()) < 2:
        raise ValueError(
            f"CelesTrak returned no TLE for NORAD catalog number {norad_id}. "
            "Check the id is correct and that the object is in CelesTrak's GP catalog."
        )

    if use_cache:
        _write_cache(norad_id, text)
    return text


def _split_tle_block(text: str) -> tuple[str | None, str, str]:
    """Split a raw CelesTrak block into ``(name, line1, line2)``.

    A FORMAT=tle response is three ``\\r\\n``-terminated lines (name, line 1, line 2);
    a bare 2-line block (no name) is tolerated with ``name=None``. Anything else is a
    malformed response -> ``ValueError``. Leading/trailing whitespace on the name is
    stripped; the two element lines are handed to :meth:`TLE.from_strings` verbatim
    (its own ``rstrip`` removes the line terminators, and the fixed columns are
    significant).
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if len(lines) == 3:
        return lines[0].strip(), lines[1], lines[2]
    if len(lines) == 2:
        return None, lines[0], lines[1]
    raise ValueError(
        f"Expected a 2- or 3-line TLE block from CelesTrak, got {len(lines)} "
        f"non-empty line(s): {text!r}"
    )


def fetch_tle(
    name_or_id: str | int,
    source: str = "celestrak",
    *,
    use_cache: bool = True,
) -> TLE:
    """Fetch a satellite's current TLE by friendly name or NORAD id (architecture §6).

    Resolves ``name_or_id`` through the popular-satellite registry
    (``core.catalogs._resolve_norad_id`` — ``"ISS"`` / ``25544`` / ``"25544"`` all
    work), fetches from CelesTrak (24 h cache TTL by default; ``use_cache=False``
    forces a network hit), and returns a validated :class:`TLE` whose ``name`` is set
    from CelesTrak's line-0 so :func:`~propygator.propagate_tle`'s name-fallback carries
    the satellite's identity (features.md §1.3).

    ``source`` is kept for forward-compatibility but ``"celestrak"`` is its only valid
    value in v1 (Space-Track / ``"auto"`` are deferred, architecture §3); any other
    value raises ``ValueError``. JVM-free (network + pure-Python parse only).
    """
    if source != "celestrak":
        raise ValueError(
            f"Unknown TLE source {source!r}. v1 supports only 'celestrak' "
            "(Space-Track and 'auto' multi-source resolution are deferred)."
        )
    norad_id = _resolve_norad_id(name_or_id)
    raw = fetch_celestrak(norad_id, use_cache=use_cache)
    name, line1, line2 = _split_tle_block(raw)
    return TLE.from_strings(line1, line2, name=name)
