"""Pure-Python tests for the popular-satellite registry (Feature 1.3 Chunk 6).

``core.catalogs`` is reference data: friendly name -> NORAD id resolution with no
I/O and no JVM. These tests exercise the "safe before init" surface (architecture
§10) and must not start the JVM.
"""

from __future__ import annotations

import pytest

from propygator.core.catalogs import (
    _NAME_TO_NORAD,
    _QSMAG_TO_STD_OFFSET,
    _STANDARD_MAGNITUDES,
    _resolve_norad_id,
    _standard_magnitude,
)

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


# --- standard-magnitude table (Feature 1.5 Chunk 1) --------------------------


def test_qsmag_offset_is_the_dimming_direction():
    # Full phase -> 50% phase makes a diffuse sphere *dimmer* (larger magnitude):
    # the offset must be positive, and equal 2.5*log10(pi) ~= +1.243.
    assert _QSMAG_TO_STD_OFFSET == pytest.approx(1.2434, abs=1e-3)
    assert _QSMAG_TO_STD_OFFSET > 0


def test_standard_magnitudes_finite_and_in_visual_band():
    # All values finite and inside a sane visual-observer band. The bright edge
    # is the ISS (~ -1.3 in the 50%-phase convention); the faint edge is a small
    # LEO bus a visual observer can still track (~ +7).
    for norad_id, mag in _STANDARD_MAGNITUDES.items():
        assert isinstance(norad_id, int)
        assert -3.0 <= mag <= 8.0, f"{norad_id}: {mag}"


def test_standard_magnitudes_cover_the_whole_registry():
    # Every registry object carries a magnitude entry (the registry seed set was
    # chosen for exactly this alignment — catalogs.py module docstring).
    assert set(_NAME_TO_NORAD.values()) <= set(_STANDARD_MAGNITUDES)


def test_standard_magnitude_lookup_hit():
    # ISS: qsmag -2.5 converted by the full->50% phase offset; still bright (< 0).
    mag = _standard_magnitude(25544)
    assert mag == pytest.approx(-2.5 + _QSMAG_TO_STD_OFFSET)
    assert mag < 0


def test_standard_magnitude_css_is_heavens_above_sourced():
    # Tianhe/CSS post-dates the archived qsmag; its H-A value carries no offset.
    assert _standard_magnitude(48274) == pytest.approx(0.0)


def test_standard_magnitude_lookup_miss_returns_none():
    assert _standard_magnitude(99999) is None
