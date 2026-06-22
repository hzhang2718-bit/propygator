"""Pure-Python tests for the ``TLE`` core type (Feature 1.3, build-plan chunk 2).

None of these tests may start the JVM — ``TLE`` construction, parsing, the
checksum check, and the ``epoch`` / ``norad_id`` accessors are all part of the
"safe before init" surface (architecture §10). ``test_no_jvm_started`` guards
that invariant. The JVM-touching ``to_orekit()`` round-trip is covered separately
in ``tests/test_conversions.py`` (under the ``orekit`` fixture).
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from propygator import TLE
from propygator.core.tle import _decode_catalog_number, _line_checksum

# A fixed, real ISS (ZARYA) TLE — epoch 2026-06-20T09:57:02 UTC, NORAD 25544.
# Both lines are 69 chars with valid mod-10 checksums.
ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


# --- JVM guard -------------------------------------------------------------


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- from_strings parsing --------------------------------------------------


def test_from_strings_parses_iss():
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2, name=ISS_NAME)
    assert tle.line1 == ISS_LINE1
    assert tle.line2 == ISS_LINE2
    assert tle.name == ISS_NAME


def test_from_strings_strips_trailing_newlines():
    # The fetch path splits a 3-line CelesTrak block whose lines carry CRLF.
    tle = TLE.from_strings(ISS_LINE1 + "\r\n", ISS_LINE2 + "\n")
    assert tle.line1 == ISS_LINE1
    assert tle.line2 == ISS_LINE2
    assert tle.name is None


def test_norad_id():
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2)
    assert tle.norad_id == 25544
    assert isinstance(tle.norad_id, int)


def test_epoch_matches_known_iss_epoch_to_the_second():
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2)
    dt = tle.epoch.to_datetime()
    assert dt.replace(microsecond=0) == datetime(
        2026, 6, 20, 9, 57, 2, tzinfo=timezone.utc
    )


def test_epoch_year_window_pivot():
    # 00-56 -> 20xx; here year field "26" -> 2026.
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2)
    assert tle.epoch.to_datetime().year == 2026


# --- checksum / structural validation --------------------------------------


def test_corrupted_checksum_raises():
    # Flip the column-69 checksum digit of line 1 (0 -> 1).
    bad_line1 = ISS_LINE1[:-1] + "1"
    with pytest.raises(ValueError, match="checksum"):
        TLE.from_strings(bad_line1, ISS_LINE2)


def test_corrupted_body_digit_raises_checksum():
    # Mutate a body digit so the stored checksum no longer matches.
    bad_line2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572251"
    with pytest.raises(ValueError, match="checksum"):
        TLE.from_strings(ISS_LINE1, bad_line2)


def test_wrong_length_raises():
    with pytest.raises(ValueError, match="69 characters"):
        TLE.from_strings(ISS_LINE1[:-1], ISS_LINE2)


def test_wrong_line_number_raises():
    # Swap the lines so line-1 slot begins with '2'.
    with pytest.raises(ValueError, match="line number"):
        TLE.from_strings(ISS_LINE2, ISS_LINE1)


def test_line1_line2_catalog_mismatch_raises():
    # Two individually-valid lines from different objects (ISS line 1 +
    # Vanguard-1 line 2, catalog 00005) must be rejected as a mis-paired TLE.
    vanguard_line2 = (
        "2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667"  # noqa: E501
    )
    with pytest.raises(ValueError, match="different catalog numbers"):
        TLE.from_strings(ISS_LINE1, vanguard_line2)


# --- catalog-number decoding (classic + Alpha-5) ---------------------------


@pytest.mark.parametrize(
    "field, expected",
    [
        ("25544", 25544),  # classic ISS
        ("00005", 5),  # zero-padded
        (" 5544", 5544),  # space-padded historical id
        ("A5544", 105544),  # Alpha-5: A -> 10, so 10*10000 + 5544
        ("B0000", 110000),  # Alpha-5: B -> 11
        ("Z9999", 339999),  # Alpha-5 maximum (Z -> 33)
    ],
)
def test_decode_catalog_number(field, expected):
    assert _decode_catalog_number(field) == expected


def test_decode_catalog_number_rejects_excluded_letters():
    # I and O are not valid Alpha-5 high digits (they read as 1 and 0).
    with pytest.raises(ValueError, match="invalid leading character"):
        _decode_catalog_number("I0000")


def test_norad_id_decodes_alpha5_tle():
    # A real-shaped Alpha-5 TLE (catalog >= 100000) must parse — the naive int()
    # parse used to crash here. Reuse the ISS fixture with an Alpha-5 catalog on
    # both lines, recomputing each line's checksum so from_strings accepts it.
    body1 = ISS_LINE1[:2] + "A5544" + ISS_LINE1[7:-1]
    body2 = ISS_LINE2[:2] + "A5544" + ISS_LINE2[7:-1]
    line1 = body1 + str(_line_checksum(body1 + "0"))
    line2 = body2 + str(_line_checksum(body2 + "0"))
    tle = TLE.from_strings(line1, line2)
    assert tle.norad_id == 105544
    assert isinstance(tle.norad_id, int)


# --- bare construction (no JVM) --------------------------------------------


def test_bare_construction_runs_structural_check_only():
    # The bare constructor validates structure but not the checksum; it must not
    # touch the JVM (sits in the tests/core "no JVM started" suite).
    tle = TLE(ISS_LINE1, ISS_LINE2)
    assert tle.norad_id == 25544


def test_bare_construction_rejects_bad_structure():
    with pytest.raises(ValueError, match="69 characters"):
        TLE("too short", ISS_LINE2)


def test_tle_is_top_level_export():
    import propygator as pgr

    assert pgr.TLE is TLE
