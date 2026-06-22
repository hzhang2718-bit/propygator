"""Pure-Python tests for the popular-satellite registry (Feature 1.3 Chunk 6).

``core.catalogs`` is reference data: friendly name -> NORAD id resolution with no
I/O and no JVM. These tests exercise the "safe before init" surface (architecture
§10) and must not start the JVM.
"""

from __future__ import annotations

import pytest

from propygator.core.catalogs import _NAME_TO_NORAD, _resolve_norad_id

# --- JVM guard -------------------------------------------------------------


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- name resolution -------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("ISS", 25544),
        ("ZARYA", 25544),  # alias of ISS
        ("HST", 20580),
        ("HUBBLE", 20580),  # alias of HST
        ("TIANGONG", 48274),
        ("CSS", 48274),  # alias of Tiangong
        ("NOAA-19", 33591),
        ("TERRA", 25994),
        ("AQUA", 27424),
        ("ENVISAT", 27386),
    ],
)
def test_known_names_resolve(name, expected):
    assert _resolve_norad_id(name) == expected


def test_lookup_is_case_insensitive():
    assert _resolve_norad_id("iss") == 25544
    assert _resolve_norad_id("Hubble") == 20580


def test_lookup_is_whitespace_and_hyphen_insensitive():
    # "NOAA-19", "NOAA 19", "noaa19", and padded variants all resolve identically.
    for spelling in ("NOAA-19", "NOAA 19", "noaa19", "  NOAA-19  "):
        assert _resolve_norad_id(spelling) == 33591


# --- raw id pass-through ---------------------------------------------------


def test_int_passes_through():
    assert _resolve_norad_id(25544) == 25544


def test_numeric_string_passes_through():
    assert _resolve_norad_id("25544") == 25544
    assert _resolve_norad_id("  25544  ") == 25544


# --- error paths -----------------------------------------------------------


def test_unknown_name_raises_actionable_error():
    with pytest.raises(ValueError, match="Unknown satellite name"):
        _resolve_norad_id("NOTASAT")


def test_unknown_name_message_lists_known_names_and_raw_id_hint():
    with pytest.raises(ValueError) as excinfo:
        _resolve_norad_id("NOTASAT")
    message = str(excinfo.value)
    assert "ISS" in message  # lists the known names
    assert "NORAD catalog number" in message  # tells the user how to pass a raw id


@pytest.mark.parametrize("bad_id", [0, -1, "0", "-5"])
def test_non_positive_id_raises(bad_id):
    with pytest.raises(ValueError, match="positive integer"):
        _resolve_norad_id(bad_id)


def test_bool_is_rejected():
    # bool is an int subclass; True must not silently resolve to NORAD id 1.
    with pytest.raises(TypeError, match="not a bool"):
        _resolve_norad_id(True)  # type: ignore[arg-type]


def test_wrong_type_raises():
    with pytest.raises(TypeError, match="satellite name"):
        _resolve_norad_id(25544.0)  # type: ignore[arg-type]


# --- registry sanity -------------------------------------------------------


def test_every_registry_id_is_positive():
    assert all(norad_id > 0 for norad_id in _NAME_TO_NORAD.values())
