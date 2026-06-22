"""Tests for the CelesTrak fetch path + on-disk TTL cache (Feature 1.3 Chunk 7).

All network is **mocked** (monkeypatched ``requests.get``) so the suite never hits
CelesTrak — there is no live network in CI (build-plan Chunk 7). The on-disk cache is
redirected to ``tmp_path`` via the single ``_orekit_init._cache_dir`` seam, so no test
touches the real ``~/.propygator/``. Pure-Python and JVM-free — no ``orekit`` fixture
(fetching does network I/O plus ``TLE.from_strings``' pure-Python parse, never Orekit).
"""

from __future__ import annotations

import os
import time

import pytest
import requests

from propygator import _orekit_init
from propygator.core.exceptions import TLEFetchError
from propygator.core.tle import TLE
from propygator.tle import sources

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3 tests.
ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

# A FORMAT=tle response from CelesTrak: name line + the two element lines, each
# terminated with CRLF (CelesTrak uses DOS line endings).
ISS_BLOCK = f"{ISS_NAME}\r\n{ISS_LINE1}\r\n{ISS_LINE2}\r\n"


class _Recorder:
    """A stand-in for ``requests.get`` that records calls and returns a fixed body."""

    def __init__(self, text: str, *, ok: bool = True, status_code: int = 200) -> None:
        self.text = text
        self.ok = ok
        self.status_code = status_code
        self.calls: list[dict] = []

    def __call__(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        return _FakeResponse(self.text, ok=self.ok, status_code=self.status_code)


class _FakeResponse:
    def __init__(self, text: str, *, ok: bool, status_code: int = 200) -> None:
        self.text = text
        self._ok = ok
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if not self._ok:
            # Mirror requests: an HTTPError carries the originating response.
            raise requests.HTTPError(f"{self.status_code} error", response=self)


@pytest.fixture
def cache_dir(tmp_path, monkeypatch):
    """Redirect the on-disk cache root to ``tmp_path`` for the duration of a test.

    Patches the single ``_orekit_init._cache_dir`` seam, which both the fetch path
    (``sources._cache_path``) and ``clear_cache`` resolve through.
    """
    monkeypatch.setattr(_orekit_init, "_cache_dir", lambda: tmp_path)
    return tmp_path


def _install_recorder(
    monkeypatch, text=ISS_BLOCK, *, ok=True, status_code=200
) -> _Recorder:
    rec = _Recorder(text, ok=ok, status_code=status_code)
    monkeypatch.setattr(requests, "get", rec)
    return rec


# --- fetch_tle: name resolution + parsing -------------------------------------


def test_fetch_tle_resolves_name_and_populates_tle(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    tle = sources.fetch_tle("ISS")

    assert isinstance(tle, TLE)
    assert tle.line1 == ISS_LINE1
    assert tle.line2 == ISS_LINE2
    # name is carried from CelesTrak's line 0 (so propagate_tle's name-fallback works).
    assert tle.name == ISS_NAME
    assert tle.norad_id == 25544
    # The friendly name "ISS" resolved to CATNR 25544 before the network call.
    assert len(rec.calls) == 1
    assert rec.calls[0]["params"] == {"CATNR": "25544", "FORMAT": "tle"}
    assert rec.calls[0]["url"] == sources._CELESTRAK_GP_URL


def test_fetch_tle_numeric_id_passthrough(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    sources.fetch_tle(25544)

    assert rec.calls[0]["params"]["CATNR"] == "25544"


def test_fetch_tle_two_line_block_sets_name_none(cache_dir, monkeypatch):
    # A bare 2-line block (no name line) is tolerated; tle.name is then None.
    _install_recorder(monkeypatch, text=f"{ISS_LINE1}\r\n{ISS_LINE2}\r\n")

    tle = sources.fetch_tle(25544)

    assert tle.name is None
    assert tle.line1 == ISS_LINE1


# --- caching: hit / miss / TTL / use_cache ------------------------------------


def test_second_call_within_ttl_served_from_cache(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    first = sources.fetch_tle("ISS")
    second = sources.fetch_tle("ISS")

    # Only one network call — the second read came from the on-disk cache.
    assert len(rec.calls) == 1
    assert first.line1 == second.line1 == ISS_LINE1


def test_past_ttl_refetches(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    sources.fetch_tle("ISS")
    # Age the cache file well past the 24 h general TTL by backdating its mtime.
    cache_file = sources._cache_path(25544)
    stale = time.time() - (sources._TTL_GENERAL_S + 3600.0)
    os.utime(cache_file, (stale, stale))

    sources.fetch_tle("ISS")

    assert len(rec.calls) == 2


def test_use_cache_false_always_fetches_and_skips_write(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    sources.fetch_tle("ISS", use_cache=False)
    sources.fetch_tle("ISS", use_cache=False)

    # Both calls hit the (mocked) network, and nothing was written to the cache.
    assert len(rec.calls) == 2
    assert not sources._cache_path(25544).exists()


def test_fetch_celestrak_custom_ttl(cache_dir, monkeypatch):
    # The realtime TTL (reserved for Feature 1.4) can be passed explicitly; an entry
    # older than it is a miss even though it is within the 24 h general TTL.
    rec = _install_recorder(monkeypatch)

    sources.fetch_celestrak(25544)
    cache_file = sources._cache_path(25544)
    age = time.time() - (sources._TTL_REALTIME_S + 600.0)
    os.utime(cache_file, (age, age))

    sources.fetch_celestrak(25544, ttl_s=sources._TTL_REALTIME_S)

    assert len(rec.calls) == 2


# --- error paths --------------------------------------------------------------


def test_unknown_source_raises_without_network(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    with pytest.raises(ValueError, match="celestrak"):
        sources.fetch_tle("ISS", source="spacetrack")

    assert rec.calls == []  # rejected before any network call


def test_no_gp_data_raises(cache_dir, monkeypatch):
    _install_recorder(monkeypatch, text="No GP data found\r\n")

    with pytest.raises(ValueError, match="no TLE"):
        sources.fetch_tle(99999999)

    # A "no data" response must not be cached.
    assert not sources._cache_path(99999999).exists()


def test_http_error_wrapped_with_status(cache_dir, monkeypatch):
    _install_recorder(monkeypatch, ok=False, status_code=503)

    with pytest.raises(TLEFetchError, match="HTTP 503") as excinfo:
        sources.fetch_tle("ISS")

    # The actionable offline hint is present, and the requests chain is suppressed.
    assert "from_strings" in str(excinfo.value)
    assert excinfo.value.__suppress_context__ is True


def test_connection_error_wrapped(cache_dir, monkeypatch):
    def _boom(url, params=None, timeout=None):
        raise requests.exceptions.ConnectionError("no route to host")

    monkeypatch.setattr(requests, "get", _boom)

    with pytest.raises(TLEFetchError, match="ConnectionError") as excinfo:
        sources.fetch_tle("ISS")

    msg = str(excinfo.value)
    assert "25544" in msg  # names the NORAD id
    assert "from_strings" in msg  # offline escape hatch
    assert excinfo.value.__suppress_context__ is True  # raised `from None`


# --- TLE.from_norad_id delegates to the fetch path ----------------------------


def test_from_norad_id_delegates_to_fetch(cache_dir, monkeypatch):
    rec = _install_recorder(monkeypatch)

    tle = TLE.from_norad_id(25544)

    assert isinstance(tle, TLE)
    assert tle.norad_id == 25544
    assert rec.calls[0]["params"]["CATNR"] == "25544"


def test_from_norad_id_unknown_source_raises(cache_dir, monkeypatch):
    _install_recorder(monkeypatch)

    with pytest.raises(ValueError, match="celestrak"):
        TLE.from_norad_id(25544, source="auto")


# --- clear_cache empties the TLE cache ----------------------------------------


def test_clear_cache_empties_tle_cache(cache_dir, monkeypatch):
    _install_recorder(monkeypatch)

    sources.fetch_tle("ISS")
    cache_file = sources._cache_path(25544)
    assert cache_file.exists()

    _orekit_init.clear_cache()

    assert not cache_file.exists()
    # The cache directory itself is preserved (architecture §10).
    assert cache_dir.is_dir()
