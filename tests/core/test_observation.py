"""Pure-Python tests for observation value types (build-plan chunk 4).

Construction is part of the "safe before init" surface (architecture §10) —
these tests must not start the JVM.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from propygator import (
    AzElRange,
    Epoch,
    GeodeticPosition,
    GroundStation,
    Pass,
    TimeScale,
)


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- GroundStation ---------------------------------------------------------


def test_ground_station_valid_and_default_altitude():
    gs = GroundStation("Durham", 35.99, -78.90)
    assert gs.name == "Durham"
    assert gs.latitude_deg == 35.99
    assert gs.longitude_deg == -78.90
    assert gs.altitude_m == 0.0


def test_ground_station_frozen():
    gs = GroundStation("Durham", 35.99, -78.90, altitude_m=130.0)
    with pytest.raises(FrozenInstanceError):
        gs.name = "Elsewhere"


@pytest.mark.parametrize("lat", [-90.0, 0.0, 90.0])
def test_ground_station_latitude_bounds_ok(lat):
    GroundStation("x", lat, 0.0)


@pytest.mark.parametrize("lon", [-180.0, 0.0, 180.0])
def test_ground_station_longitude_bounds_ok(lon):
    GroundStation("x", 0.0, lon)


@pytest.mark.parametrize("lat", [-90.001, 90.001, float("nan"), float("inf")])
def test_ground_station_bad_latitude(lat):
    with pytest.raises(ValueError):
        GroundStation("x", lat, 0.0)


@pytest.mark.parametrize("lon", [-180.001, 180.001, float("nan"), float("inf")])
def test_ground_station_bad_longitude(lon):
    with pytest.raises(ValueError):
        GroundStation("x", 0.0, lon)


def test_ground_station_bad_altitude():
    with pytest.raises(ValueError):
        GroundStation("x", 0.0, 0.0, altitude_m=float("inf"))


# --- GeodeticPosition ------------------------------------------------------


def test_geodetic_position_valid():
    gp = GeodeticPosition(35.99, -78.90, 130.0)
    assert gp.latitude_deg == 35.99
    assert gp.altitude_m == 130.0


def test_geodetic_position_bad_latitude():
    with pytest.raises(ValueError):
        GeodeticPosition(91.0, 0.0, 0.0)


def test_geodetic_position_bad_altitude():
    with pytest.raises(ValueError):
        GeodeticPosition(0.0, 0.0, float("nan"))


def test_geodetic_position_frozen():
    gp = GeodeticPosition(0.0, 0.0, 0.0)
    with pytest.raises(FrozenInstanceError):
        gp.altitude_m = 5.0


# --- AzElRange -------------------------------------------------------------


def test_azelrange_valid_and_access():
    ae = AzElRange(azimuth_deg=123.5, elevation_deg=42.0, range_m=1_234_567.0)
    assert ae.azimuth_deg == 123.5
    assert ae.elevation_deg == 42.0
    assert ae.range_m == 1_234_567.0


def test_azelrange_allows_negative_elevation():
    # Below the horizon is a legitimate look angle (the value type does not
    # clip it; the sky plot masks below-horizon samples downstream).
    ae = AzElRange(azimuth_deg=0.0, elevation_deg=-30.0, range_m=5.0e6)
    assert ae.elevation_deg == -30.0


def test_azelrange_frozen():
    ae = AzElRange(10.0, 20.0, 30.0)
    with pytest.raises(FrozenInstanceError):
        ae.elevation_deg = 25.0


@pytest.mark.parametrize("az", [float("nan"), float("inf"), float("-inf")])
def test_azelrange_bad_azimuth(az):
    with pytest.raises(ValueError):
        AzElRange(az, 0.0, 0.0)


@pytest.mark.parametrize("el", [float("nan"), float("inf"), float("-inf")])
def test_azelrange_bad_elevation(el):
    with pytest.raises(ValueError):
        AzElRange(0.0, el, 0.0)


@pytest.mark.parametrize("rng", [float("nan"), float("inf"), -1.0, -1.0e-9])
def test_azelrange_bad_range(rng):
    with pytest.raises(ValueError):
        AzElRange(0.0, 0.0, rng)


# --- Pass ------------------------------------------------------------------


def test_pass_construction_and_access():
    rise = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    culmination = rise.shifted_by(300.0)
    set_ = rise.shifted_by(600.0)
    p = Pass(
        rise=rise,
        culmination=culmination,
        set=set_,
        max_elevation_deg=45.0,
        peak_magnitude=None,
        sunlit_at_culmination=True,
    )
    assert p.rise is rise
    assert p.culmination is culmination
    assert p.set is set_
    assert p.max_elevation_deg == 45.0
    assert p.peak_magnitude is None
    assert p.sunlit_at_culmination is True


def test_pass_accepts_numeric_magnitude():
    rise = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    p = Pass(rise, rise, rise, 10.0, 3.5, False)
    assert p.peak_magnitude == 3.5


def test_pass_frozen():
    rise = Epoch.from_iso("2024-01-01T00:00:00", scale=TimeScale.UTC)
    p = Pass(rise, rise, rise, 10.0, 3.5, False)
    with pytest.raises(FrozenInstanceError):
        p.max_elevation_deg = 20.0
