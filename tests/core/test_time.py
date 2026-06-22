"""Pure-Python tests for ``Epoch`` / ``TimeScale`` (build-plan chunk 3).

None of these tests may start the JVM — they exercise the "safe before init"
surface (architecture §10). ``test_no_jvm_started`` guards that invariant.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from propygator import Epoch, TimeScale

# Scales whose construction is supported pure-Python (UT1 is deferred).
_SUPPORTED_SCALES = [TimeScale.UTC, TimeScale.TAI, TimeScale.TT]


def _instant_seconds(e: Epoch) -> float:
    """The stored absolute count as a single float (for offset comparisons)."""
    return e._int_seconds + e._frac_seconds


# --- JVM guard -------------------------------------------------------------


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- ISO round-trips -------------------------------------------------------


@pytest.mark.parametrize(
    "iso",
    [
        "2024-06-01T12:00:00",
        "2024-06-01T12:00:00.5",
        "2000-01-01T11:58:55.816",
        "1999-12-31T23:59:59.123456",
        "1980-03-15T06:30:00.25",
    ],
)
def test_iso_round_trip_utc(iso):
    e = Epoch.from_iso(iso, scale=TimeScale.UTC)
    assert e.to_iso() == iso


@pytest.mark.parametrize("scale", _SUPPORTED_SCALES)
def test_iso_round_trip_each_scale(scale):
    iso = "2024-06-01T12:34:56.25"
    e = Epoch.from_iso(iso, scale=scale)
    assert e.scale is scale
    assert e.to_iso() == iso
    # Re-parsing the rendered string reproduces the same Epoch exactly.
    assert Epoch.from_iso(e.to_iso(), scale=scale) == e


def test_from_iso_rejects_garbage():
    with pytest.raises(ValueError):
        Epoch.from_iso("not-a-date")


def test_from_iso_with_offset_fixes_instant():
    # +02:00 wall-clock 14:00 is the same instant as 12:00 UTC.
    a = Epoch.from_iso("2024-01-01T14:00:00+02:00")
    b = Epoch.from_iso("2024-01-01T12:00:00Z")
    c = Epoch.from_iso("2024-01-01T12:00:00", scale=TimeScale.UTC)
    assert a == b == c


def test_from_iso_offset_with_presentation_scale():
    # The offset fixes the instant; scale only changes presentation.
    e = Epoch.from_iso("2024-01-01T12:00:00Z", scale=TimeScale.TAI)
    assert e.scale is TimeScale.TAI
    assert e == Epoch.from_iso("2024-01-01T12:00:00", scale=TimeScale.UTC).in_scale(
        TimeScale.TAI
    )


# --- datetime round-trips + naive rejection --------------------------------


def test_datetime_round_trip_utc():
    dt = datetime(2024, 3, 1, 6, 30, 15, 250000, tzinfo=timezone.utc)
    assert Epoch.from_datetime(dt).to_datetime() == dt


def test_datetime_round_trip_nonutc_tz():
    tz = timezone(timedelta(hours=-5))
    dt = datetime(2024, 3, 1, 1, 30, 15, tzinfo=tz)
    # to_datetime always returns the instant in UTC.
    assert Epoch.from_datetime(dt).to_datetime() == dt.astimezone(timezone.utc)


def test_naive_datetime_rejected():
    with pytest.raises(ValueError):
        Epoch.from_datetime(datetime(2024, 1, 1, 0, 0, 0))


def test_now_is_recent_and_utc_default():
    before = datetime.now(timezone.utc)
    e = Epoch.now()
    after = datetime.now(timezone.utc)
    assert e.scale is TimeScale.UTC
    assert (
        before - timedelta(seconds=2) <= e.to_datetime() <= after + timedelta(seconds=2)
    )


# --- shifted_by renormalization --------------------------------------------


# These use the TT scale, where a whole-second wall-clock stores _frac_seconds
# == the wall-clock sub-second (TT is the internal calendar reference). On a TAI
# or UTC epoch the stored fraction carries the 0.184 s TT-TAI remainder, which
# is correct internal representation but would obscure the renormalization check.
def test_shifted_by_positive_frac():
    e = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.TT)
    e2 = e.shifted_by(1.75)
    assert e2._int_seconds == e._int_seconds + 1
    assert e2._frac_seconds == pytest.approx(0.75)
    assert e2.scale is TimeScale.TT
    assert _instant_seconds(e2) - _instant_seconds(e) == pytest.approx(1.75)


def test_shifted_by_carries_fraction():
    e = Epoch.from_iso("2024-01-01T00:00:00.6", scale=TimeScale.TT)
    e2 = e.shifted_by(0.6)
    assert e2._int_seconds == e._int_seconds + 1
    assert e2._frac_seconds == pytest.approx(0.2)


def test_shifted_by_negative_borrows():
    e = Epoch.from_iso("2024-01-01T00:00:00.25", scale=TimeScale.TT)
    e2 = e.shifted_by(-0.5)
    assert e2._int_seconds == e._int_seconds - 1
    assert e2._frac_seconds == pytest.approx(0.75)
    assert _instant_seconds(e2) - _instant_seconds(e) == pytest.approx(-0.5)


def test_shifted_by_round_trip():
    e = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    assert e.shifted_by(123.5).shifted_by(-123.5) == e


def test_frac_invariant_holds_after_shift():
    e = Epoch.from_iso("2024-01-01T00:00:00.5", scale=TimeScale.TAI)
    for delta in (-0.9, -0.5, 0.0, 0.4999, 0.5, 1.9, -1234.567):
        assert 0.0 <= e.shifted_by(delta)._frac_seconds < 1.0


# --- seconds_since (signed Epoch difference) -------------------------------


def test_seconds_since_inverts_shifted_by():
    """seconds_since is the inverse of shifted_by: it recovers the shift."""
    e = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    for delta in (0.0, 1.75, -0.5, 86400.0, -1234.567, 30.0 * 86400):
        assert e.shifted_by(delta).seconds_since(e) == pytest.approx(delta)


def test_seconds_since_is_antisymmetric():
    a = Epoch.from_iso("2026-06-20T09:57:02", scale=TimeScale.UTC)
    b = a.shifted_by(3600.25)
    assert a.seconds_since(b) == pytest.approx(-b.seconds_since(a))
    assert a.seconds_since(a) == 0.0


def test_seconds_since_is_scale_independent():
    """The same instant in two presentation scales differs by zero seconds."""
    e_utc = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    e_tt = e_utc.in_scale(TimeScale.TT)
    assert e_tt.seconds_since(e_utc) == 0.0


# --- scale conversions vs. known offsets -----------------------------------


def test_in_scale_preserves_instant():
    e = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    tt = e.in_scale(TimeScale.TT)
    assert tt.scale is TimeScale.TT
    assert tt._int_seconds == e._int_seconds
    assert tt._frac_seconds == e._frac_seconds


def test_in_scale_identity_returns_self():
    e = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    assert e.in_scale(TimeScale.UTC) is e


def test_tt_minus_tai_offset():
    # Same wall-clock numbers in TT denote an instant 32.184 s earlier than TAI.
    tai = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.TAI)
    tt = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.TT)
    assert _instant_seconds(tai) - _instant_seconds(tt) == pytest.approx(32.184)


def test_tai_minus_utc_offset_modern():
    # 2024 is in the TAI-UTC = 37 s era.
    tai = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.TAI)
    utc = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    assert _instant_seconds(utc) - _instant_seconds(tai) == pytest.approx(37.0)


def test_tai_minus_utc_offset_year_2000():
    # 1999-01-01 .. 2006-01-01 era: TAI-UTC = 32 s.
    tai = Epoch.from_iso("2000-06-01T00:00:00", scale=TimeScale.TAI)
    utc = Epoch.from_iso("2000-06-01T00:00:00", scale=TimeScale.UTC)
    assert _instant_seconds(utc) - _instant_seconds(tai) == pytest.approx(32.0)


def test_utc_presented_in_tai_reads_37s_later():
    utc = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    assert utc.in_scale(TimeScale.TAI).to_iso() == "2024-01-01T00:00:37"


def test_utc_presented_in_tt():
    # TT = UTC + 37 + 32.184 = UTC + 69.184 s.
    utc = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    assert utc.in_scale(TimeScale.TT).to_iso() == "2024-01-01T00:01:09.184"


# --- J2000 anchor ----------------------------------------------------------


def test_j2000_anchor_tt():
    e = Epoch.from_iso("2000-01-01T12:00:00", scale=TimeScale.TT)
    assert e._int_seconds == 0
    assert e._frac_seconds == 0.0


def test_j2000_anchor_tai():
    e = Epoch.from_iso("2000-01-01T11:59:27.816", scale=TimeScale.TAI)
    assert e._int_seconds == 0
    assert e._frac_seconds == pytest.approx(0.0, abs=1e-9)


# --- equality semantics ----------------------------------------------------


def test_same_instant_different_scale_not_equal():
    utc = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    tai = utc.in_scale(TimeScale.TAI)
    assert _instant_seconds(utc) == _instant_seconds(tai)
    assert utc != tai  # scale is part of identity


# --- UT1 deferral ----------------------------------------------------------


def test_ut1_construction_deferred():
    with pytest.raises(NotImplementedError):
        Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UT1)


def test_ut1_in_scale_deferred():
    e = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    with pytest.raises(NotImplementedError):
        e.in_scale(TimeScale.UT1)


# --- raw-field validation --------------------------------------------------


@pytest.mark.parametrize("bad_frac", [1.0, 1.5, -0.1, float("nan"), float("inf")])
def test_out_of_range_frac_rejected(bad_frac):
    with pytest.raises(ValueError):
        Epoch(0, bad_frac, TimeScale.TAI)


# --- to_iso sub-nanosecond carry -------------------------------------------


def test_to_iso_carries_near_one_fraction():
    # A fraction within ~5e-10 of 1.0 must carry into the whole second, not be
    # dropped (previously _format_frac rendered "1.000000000" and lost ~1 s).
    e = Epoch(1000, 0.9999999996, TimeScale.TT)  # J2000 TT + 1000 s
    assert e.to_iso() == "2000-01-01T12:16:41"


def test_to_iso_high_precision_fraction_not_lost():
    e = Epoch.from_iso("2024-06-01T12:00:00.9999999996", scale=TimeScale.TT)
    assert e.to_iso() == "2024-06-01T12:00:01"
