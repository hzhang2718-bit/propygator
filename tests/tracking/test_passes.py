"""Tests for the Feature 1.5 pass-search engine (`tracking/passes.py`, Chunk 3).

Two halves, split by JVM contact:

- **Pure Python** — the pre-flight ``ValueError`` table (validated before any
  JVM work), and the search plumbing on synthetic arrays: run detection,
  candidate bracketing (padding, the grazing local-max path, merging), the
  wrap-aware azimuth interpolation, and the fine-grid cap.
- **JVM** (``orekit`` fixture, scheduled last by the conftest hook) — the
  engine end-to-end on the fixed ISS TLE / Durham station fixture shared with
  ``test_visibility.py``: the known 2-day pass table (whose external
  cross-check against the committed Skyfield reference lands at Checkpoint A),
  the refinement pins, the visibility semantics rows from features.md §1.5
  (mid-shadow visible pass, daytime exclusion, never-up, always-up warn-once,
  window-straddle clamping), magnitude resolution, and progress reporting.
"""

from __future__ import annotations

import math
from datetime import timedelta

import numpy as np
import pandas as pd
import pytest

from propygator import (
    TLE,
    Epoch,
    Frame,
    GroundStation,
    Pass,
    State,
    TimeScale,
    USTimeZone,
    look_angles,
    passes_to_dataframe,
)
from propygator.core.exceptions import StaleTLEWarning
from propygator.core.frames import to_geodetic
from propygator.tle.propagator import _tle_state_at
from propygator.tracking.passes import (
    _MAX_FINE_SAMPLES,
    _PASS_TABLE_COLUMNS,
    _candidate_brackets,
    _fine_sample_count,
    _interp_azimuth_deg,
    _true_runs,
    find_passes,
)

# The same fixed, real ISS (ZARYA) TLE + station as test_visibility.py.
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

STATION = GroundStation("Durham", 35.99, -78.90, altitude_m=130.0)
START = Epoch.from_iso("2026-06-23T00:00:00", scale=TimeScale.UTC)
WINDOW_S = 2 * 86400.0

# The independent Skyfield reference for this exact search (committed at
# experiments/pass-verification/results.txt; generated 2026-07-08 with
# Skyfield 1.54 / python-sgp4 / DE421 — no Orekit in that stack). One row per
# geometric pass: (rise_utc, rise_az, culm_utc, culm_az, max_el, set_utc,
# set_az, sunlit_at_culmination). Observed agreement at pinning time: times
# within 0.1 s, azimuths within 0.15 deg, elevations within 0.01 deg.
_SKYFIELD_REFERENCE = [
    # fmt: off
    (
        "2026-06-23T06:11:54.158",
        156.86,
        "2026-06-23T06:13:33.606",
        127.16,
        13.10,
        "2026-06-23T06:15:13.272",
        97.51,
        False,
    ),
    (
        "2026-06-23T07:46:41.963",
        243.52,
        "2026-06-23T07:49:59.771",
        321.32,
        51.61,
        "2026-06-23T07:53:18.772",
        39.41,
        True,
    ),
    (
        "2026-06-23T09:26:40.651",
        326.40,
        "2026-06-23T09:27:25.519",
        339.24,
        10.53,
        "2026-06-23T09:28:10.550",
        352.12,
        True,
    ),
    (
        "2026-06-23T12:43:04.534",
        7.31,
        "2026-06-23T12:43:51.719",
        20.85,
        10.58,
        "2026-06-23T12:44:38.744",
        34.37,
        True,
    ),
    (
        "2026-06-23T14:17:58.506",
        320.27,
        "2026-06-23T14:21:16.839",
        38.59,
        52.63,
        "2026-06-23T14:24:33.790",
        117.07,
        True,
    ),
    (
        "2026-06-23T15:56:09.533",
        260.63,
        "2026-06-23T15:57:42.378",
        232.97,
        12.65,
        "2026-06-23T15:59:14.863",
        205.31,
        True,
    ),
    (
        "2026-06-24T06:58:48.665",
        225.44,
        "2026-06-24T07:02:10.703",
        137.38,
        84.25,
        "2026-06-24T07:05:33.892",
        49.66,
        False,
    ),
    (
        "2026-06-24T08:37:24.776",
        299.26,
        "2026-06-24T08:39:21.189",
        334.42,
        14.33,
        "2026-06-24T08:41:17.782",
        9.57,
        True,
    ),
    (
        "2026-06-24T13:30:20.848",
        329.95,
        "2026-06-24T13:33:23.799",
        34.55,
        30.68,
        "2026-06-24T13:36:25.440",
        99.08,
        True,
    ),
    (
        "2026-06-24T15:07:20.312",
        283.94,
        "2026-06-24T15:10:03.762",
        229.67,
        22.89,
        "2026-06-24T15:12:46.055",
        175.37,
        True,
    ),
    # fmt: on
]


def _iss_tle() -> TLE:
    return TLE.from_strings(ISS_LINE1, ISS_LINE2, name="ISS (ZARYA)")


def _utc(iso: str) -> Epoch:
    return Epoch.from_iso(iso, scale=TimeScale.UTC)


def _azimuth_delta_deg(a: float, b: float) -> float:
    """Smallest unsigned angle between two compass azimuths (wrap-aware)."""
    return abs((a - b + 180.0) % 360.0 - 180.0)


# --- pre-flight ValueError table (pure Python, before any JVM) ----------------


@pytest.mark.parametrize("bad", [0.0, -1.0, math.nan, math.inf])
def test_bad_duration_raises(bad):
    with pytest.raises(ValueError, match="duration"):
        find_passes(_iss_tle(), STATION, bad, start=START, progress=False)


@pytest.mark.parametrize("bad", [-0.1, 90.0, 95.0, math.nan])
def test_bad_min_elevation_raises(bad):
    with pytest.raises(ValueError, match="min_elevation_deg"):
        find_passes(
            _iss_tle(),
            STATION,
            3600.0,
            start=START,
            min_elevation_deg=bad,
            progress=False,
        )


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_non_finite_standard_magnitude_raises(bad):
    with pytest.raises(ValueError, match="standard_magnitude"):
        find_passes(
            _iss_tle(),
            STATION,
            3600.0,
            start=START,
            standard_magnitude=bad,
            progress=False,
        )


def test_bad_progress_type_raises():
    with pytest.raises(TypeError, match="progress"):
        find_passes(_iss_tle(), STATION, 3600.0, start=START, progress="yes")  # type: ignore[arg-type]


# --- search plumbing on synthetic arrays (pure NumPy, no JVM) -----------------


def test_true_runs():
    mask = np.array([False, True, True, False, True])
    assert _true_runs(mask) == [(1, 2), (4, 4)]
    assert _true_runs(np.zeros(4, dtype=bool)) == []
    assert _true_runs(np.ones(3, dtype=bool)) == [(0, 2)]


def test_bracket_pads_a_run_by_one_sample():
    el = np.array([5.0, 11.0, 12.0, 11.0, 5.0])
    assert _candidate_brackets(el, 10.0) == [(0, 4)]


def test_bracket_clips_padding_at_the_grid_edges():
    el = np.array([11.0, 12.0, 5.0])
    assert _candidate_brackets(el, 10.0) == [(0, 2)]


def test_grazing_local_maximum_below_the_gate_is_a_candidate():
    # 9.5 deg peak against a 10 deg gate: within the ~2 deg graze margin.
    el = np.array([0.0, 9.5, 0.0])
    assert _candidate_brackets(el, 10.0) == [(0, 2)]


def test_local_maximum_below_the_graze_margin_is_not_a_candidate():
    el = np.array([0.0, 7.9, 0.0])
    assert _candidate_brackets(el, 10.0) == []


def test_overlapping_run_and_graze_brackets_merge():
    # A run at index 1 (bracket 0-2) and a graze maximum at index 3
    # (bracket 2-4) share sample 2: one merged candidate, refined once.
    el = np.array([5.0, 11.0, 5.0, 9.5, 5.0])
    assert _candidate_brackets(el, 10.0) == [(0, 4)]


def test_interp_azimuth_crosses_the_north_seam_the_short_way():
    assert _interp_azimuth_deg(350.0, 10.0, 0.5) == pytest.approx(0.0)
    assert _interp_azimuth_deg(10.0, 350.0, 0.5) == pytest.approx(0.0)
    assert _interp_azimuth_deg(359.0, 3.0, 0.75) == pytest.approx(2.0)


def test_interp_azimuth_plain_case_and_endpoints():
    assert _interp_azimuth_deg(90.0, 180.0, 0.5) == pytest.approx(135.0)
    assert _interp_azimuth_deg(90.0, 180.0, 0.0) == pytest.approx(90.0)
    assert _interp_azimuth_deg(90.0, 180.0, 1.0) == pytest.approx(180.0)


def test_fine_sample_count_caps():
    assert _fine_sample_count(60.0) == 61
    assert _fine_sample_count(1.0e6) == _MAX_FINE_SAMPLES


# --- passes_to_dataframe (pure Python, no JVM) --------------------------------


def _hand_pass(
    rise_iso: str,
    culm_iso: str,
    set_iso: str,
    *,
    max_el: float = 45.0,
    peak_mag: float | None = -3.2,
    sunlit: bool = True,
    azimuths: tuple[float, float, float] = (120.0, 155.0, 200.0),
) -> Pass:
    """A hand-built ``Pass`` with known fields (no JVM — construction is pure)."""
    return Pass(
        rise=_utc(rise_iso),
        culmination=_utc(culm_iso),
        set=_utc(set_iso),
        max_elevation_deg=max_el,
        peak_magnitude=peak_mag,
        sunlit_at_culmination=sunlit,
        rise_azimuth_deg=azimuths[0],
        culmination_azimuth_deg=azimuths[1],
        set_azimuth_deg=azimuths[2],
    )


def test_passes_to_dataframe_columns_and_dtypes():
    p = _hand_pass("2026-06-23T06:11:54", "2026-06-23T06:13:33", "2026-06-23T06:15:13")
    df = passes_to_dataframe([p])
    assert list(df.columns) == list(_PASS_TABLE_COLUMNS)
    for col in ("rise", "culmination", "set"):
        assert str(df[col].dtype) == "datetime64[ns, UTC]"
    for col in (
        "duration_s",
        "max_elevation_deg",
        "rise_azimuth_deg",
        "culmination_azimuth_deg",
        "set_azimuth_deg",
        "peak_magnitude",
    ):
        assert df[col].dtype == np.float64
    assert df["sunlit_at_culmination"].dtype == np.bool_


def test_passes_to_dataframe_values():
    p = _hand_pass(
        "2026-06-23T07:46:41",
        "2026-06-23T07:49:59",
        "2026-06-23T07:53:18",
        max_el=51.61,
        peak_mag=-2.4,
        sunlit=True,
        azimuths=(243.5, 321.3, 39.4),
    )
    df = passes_to_dataframe([p])
    row = df.iloc[0]
    assert row["rise"] == pd.Timestamp("2026-06-23T07:46:41", tz="UTC")
    assert row["set"] == pd.Timestamp("2026-06-23T07:53:18", tz="UTC")
    assert row["duration_s"] == pytest.approx(p.set.seconds_since(p.rise))
    assert row["duration_s"] == pytest.approx((53 * 60 + 18) - (46 * 60 + 41))  # 397 s
    assert row["max_elevation_deg"] == pytest.approx(51.61)
    assert row["rise_azimuth_deg"] == pytest.approx(243.5)
    assert row["peak_magnitude"] == pytest.approx(-2.4)
    assert bool(row["sunlit_at_culmination"]) is True


def test_passes_to_dataframe_none_magnitude_is_nan():
    df = passes_to_dataframe(
        [
            _hand_pass(
                "2026-06-23T06:11:54",
                "2026-06-23T06:13:33",
                "2026-06-23T06:15:13",
                peak_mag=None,
            )
        ]
    )
    assert df["peak_magnitude"].dtype == np.float64
    assert math.isnan(df["peak_magnitude"].iloc[0])


def test_passes_to_dataframe_tz_conversion_is_dst_correct():
    # Same civil zone, two seasons: EDT (UTC-4) in June, EST (UTC-5) in January.
    summer = _hand_pass(
        "2026-06-23T06:11:54", "2026-06-23T06:13:33", "2026-06-23T06:15:13"
    )
    winter = _hand_pass(
        "2026-01-15T06:11:54", "2026-01-15T06:13:33", "2026-01-15T06:15:13"
    )
    df = passes_to_dataframe([summer, winter], tz=USTimeZone.EASTERN)
    assert str(df["rise"].dtype) == "datetime64[ns, America/New_York]"
    # The UTC instant is preserved; only the displayed offset changes with DST.
    assert df["rise"].iloc[0].utcoffset() == timedelta(hours=-4)  # EDT
    assert df["rise"].iloc[0].hour == 2
    assert df["rise"].iloc[1].utcoffset() == timedelta(hours=-5)  # EST
    assert df["rise"].iloc[1].hour == 1
    # duration_s is tz-independent.
    expected_s = summer.set.seconds_since(summer.rise)
    assert df["duration_s"].iloc[0] == pytest.approx(expected_s)


def test_passes_to_dataframe_empty_keeps_columns_and_dtypes():
    df = passes_to_dataframe([])
    assert len(df) == 0
    assert list(df.columns) == list(_PASS_TABLE_COLUMNS)
    assert str(df["rise"].dtype) == "datetime64[ns, UTC]"
    assert df["duration_s"].dtype == np.float64
    assert df["sunlit_at_culmination"].dtype == np.bool_


# --- the engine end-to-end (JVM) ----------------------------------------------


@pytest.fixture(scope="module")
def iss_window(orekit) -> tuple[list, list]:
    """The fixed 2-day ISS/Durham search, both filter modes, computed once."""
    tle = _iss_tle()
    geometric = find_passes(
        tle, STATION, WINDOW_S, start=START, visible_only=False, progress=False
    )
    visible = find_passes(tle, STATION, WINDOW_S, start=START, progress=False)
    return geometric, visible


def _pass_near(passes: list, rise_iso: str, tolerance_s: float = 30.0):
    """The single pass rising within ``tolerance_s`` of ``rise_iso`` (UTC)."""
    target = Epoch.from_iso(rise_iso, scale=TimeScale.UTC)
    matches = [p for p in passes if abs(p.rise.seconds_since(target)) <= tolerance_s]
    assert len(matches) == 1, (
        f"expected exactly one pass rising near {rise_iso}, found {len(matches)}"
    )
    return matches[0]


@pytest.mark.usefixtures("orekit")
class TestFindPassesISS:
    """The fixed ISS/Durham 2-day window (the Checkpoint-A fixture geometry)."""

    def test_pass_counts_and_ordering(self, iss_window):
        geometric, visible = iss_window
        assert len(geometric) == 10
        assert len(visible) == 4
        for p in geometric:
            assert p.culmination.seconds_since(p.rise) > 0.0
            assert p.set.seconds_since(p.culmination) > 0.0
        rises = [p.rise.seconds_since(START) for p in geometric]
        assert rises == sorted(rises)

    def test_agrees_with_the_skyfield_reference(self, iss_window):
        """The external cross-check (Checkpoint A): every geometric pass vs the
        committed independent Skyfield table, pass for pass.

        Tolerances are ~20x looser than the agreement observed at pinning time
        (see the reference block) but far tighter than the contract's "within
        seconds / ~1 deg" — a real frame or convention bug (wrong Earth
        rotation, refraction sneaking in, a swapped azimuth convention) misses
        by much more than this.
        """
        geometric, _ = iss_window
        assert len(geometric) == len(_SKYFIELD_REFERENCE)
        for p, ref in zip(geometric, _SKYFIELD_REFERENCE):
            rise, rise_az, culm, culm_az, max_el, set_, set_az, lit = ref
            assert abs(p.rise.seconds_since(_utc(rise))) < 2.0
            assert abs(p.culmination.seconds_since(_utc(culm))) < 2.0
            assert abs(p.set.seconds_since(_utc(set_))) < 2.0
            assert p.max_elevation_deg == pytest.approx(max_el, abs=0.1)
            assert p.rise_azimuth_deg is not None
            assert p.culmination_azimuth_deg is not None
            assert p.set_azimuth_deg is not None
            assert _azimuth_delta_deg(p.rise_azimuth_deg, rise_az) < 1.0
            assert _azimuth_delta_deg(p.culmination_azimuth_deg, culm_az) < 1.0
            assert _azimuth_delta_deg(p.set_azimuth_deg, set_az) < 1.0
            # Shadow-model conventions differ slightly (conical umbra vs
            # Skyfield's); these ten culminations are all well clear of a
            # shadow crossing, so the flags must agree outright.
            assert p.sunlit_at_culmination is lit

    def test_visible_is_a_subset_of_geometric(self, iss_window):
        geometric, visible = iss_window
        geometric_rises = [p.rise for p in geometric]
        for p in visible:
            assert any(abs(p.rise.seconds_since(r)) < 1.0 for r in geometric_rises)

    def test_azimuths_populated_and_in_range(self, iss_window):
        geometric, _ = iss_window
        for p in geometric:
            for az in (
                p.rise_azimuth_deg,
                p.culmination_azimuth_deg,
                p.set_azimuth_deg,
            ):
                assert az is not None
                assert 0.0 <= az < 360.0

    def test_refined_events_pin_to_the_gate_and_the_maximum(self, iss_window):
        """Elevation at rise/set equals the gate; culmination is the local max.

        Re-evaluated through the independent single-shot route
        (``_tle_state_at`` + ``look_angles``), not the engine's own grids.
        """
        geometric, _ = iss_window
        tle = _iss_tle()
        for p in geometric:
            el_rise = look_angles(STATION, _tle_state_at(tle, p.rise)).elevation_deg
            el_set = look_angles(STATION, _tle_state_at(tle, p.set)).elevation_deg
            assert el_rise == pytest.approx(10.0, abs=0.05)
            assert el_set == pytest.approx(10.0, abs=0.05)

            el_culm = look_angles(
                STATION, _tle_state_at(tle, p.culmination)
            ).elevation_deg
            assert el_culm == pytest.approx(p.max_elevation_deg, abs=0.02)
            for offset in (-2.0, 2.0):
                neighbor = look_angles(
                    STATION, _tle_state_at(tle, p.culmination.shifted_by(offset))
                ).elevation_deg
                assert el_culm >= neighbor - 1e-3

    def test_mid_shadow_pass_is_visible_with_unlit_culmination(self, iss_window):
        # The near-zenith pre-dawn pass: in shadow at culmination yet visible
        # earlier/later in the arc — the semantics row that justifies keeping
        # sunlit_at_culmination informative (features.md §1.5 "Pass semantics").
        _, visible = iss_window
        p = _pass_near(visible, "2026-06-24T06:58:49")
        assert p.sunlit_at_culmination is False
        assert p.peak_magnitude is not None
        assert p.max_elevation_deg == pytest.approx(84.3, abs=0.5)

    def test_daytime_pass_excluded_by_default_and_annotated_otherwise(self, iss_window):
        geometric, visible = iss_window
        # Mid-afternoon local time: geometric-only (observer never dark).
        p = _pass_near(geometric, "2026-06-23T14:17:58")
        assert p.sunlit_at_culmination is True
        assert p.peak_magnitude is None  # no visible portion -> no magnitude
        target = Epoch.from_iso("2026-06-23T14:17:58", scale=TimeScale.UTC)
        assert all(abs(q.rise.seconds_since(target)) > 120.0 for q in visible)

    def test_fully_shadowed_night_pass_is_not_visible(self, iss_window):
        geometric, visible = iss_window
        p = _pass_near(geometric, "2026-06-23T06:11:54")
        assert p.sunlit_at_culmination is False
        assert p.peak_magnitude is None
        target = Epoch.from_iso("2026-06-23T06:11:54", scale=TimeScale.UTC)
        assert all(abs(q.rise.seconds_since(target)) > 120.0 for q in visible)

    def test_peak_magnitude_is_plausibly_bright_for_the_best_pass(self, iss_window):
        # The 51.6-deg-max pre-dawn pass: the ISS around magnitude -3 (its
        # familiar brighter-than-any-star range; the Heavens-Above sanity leg
        # of Checkpoint A eyeballs the same convention on live predictions).
        _, visible = iss_window
        p = _pass_near(visible, "2026-06-23T07:46:42")
        assert p.peak_magnitude is not None
        assert -3.3 <= p.peak_magnitude <= -2.6


@pytest.mark.usefixtures("orekit")
class TestFindPassesEdges:
    def test_never_up_returns_empty(self):
        # ISS (i = 51.6 deg) from the high Arctic: never above a 10 deg gate.
        arctic = GroundStation("Arctic", 85.0, 0.0)
        passes = find_passes(
            _iss_tle(),
            arctic,
            86400.0,
            start=START,
            visible_only=False,
            progress=False,
        )
        assert passes == []

    def test_always_up_yields_one_clamped_window_pass_and_warns(self):
        # A near-GEO satellite seen from (almost) directly underneath. Built
        # from a hand-made state via from_state_unfitted (format-valid TLE, no
        # committed GEO fixture needed); 1 deg inclination keeps the elements
        # away from the circular-equatorial singularity.
        mu = 3.986004418e14
        r = 42_164_000.0
        v = math.sqrt(mu / r)
        inc = math.radians(1.0)
        state = State(
            START,
            np.array([r, 0.0, 0.0]),
            np.array([0.0, v * math.cos(inc), v * math.sin(inc)]),
            Frame.TEME,
        )
        geo_tle = TLE.from_state_unfitted(state, norad_id=99999)
        sub_point = to_geodetic(state.to_frame(Frame.ITRF))
        station = GroundStation("SubGEO", 0.0, sub_point.longitude_deg)

        with pytest.warns(UserWarning, match="continuously above"):
            passes = find_passes(
                geo_tle,
                station,
                10800.0,
                start=START,
                visible_only=False,
                progress=False,
            )
        assert len(passes) == 1
        p = passes[0]
        # Clamped to the window edges: not true rise/set times.
        assert p.rise.seconds_since(START) == pytest.approx(0.0, abs=1e-6)
        assert p.set.seconds_since(START) == pytest.approx(10800.0, abs=1e-6)
        assert p.max_elevation_deg > 80.0
        # Off-registry NORAD id and no explicit override: magnitude-less.
        assert p.peak_magnitude is None

    def test_window_straddle_clamps_the_rise(self, iss_window):
        # Start the window at (roughly) the culmination of a known pass: the
        # first returned pass is clamped to the window start, and its true set
        # matches the full-window solution.
        geometric, _ = iss_window
        full = _pass_near(geometric, "2026-06-23T14:17:58")
        mid = Epoch.from_iso("2026-06-23T14:21:16", scale=TimeScale.UTC)
        passes = find_passes(
            _iss_tle(),
            STATION,
            5400.0,
            start=mid,
            visible_only=False,
            progress=False,
        )
        assert len(passes) == 1
        p = passes[0]
        assert p.rise.seconds_since(mid) == pytest.approx(0.0, abs=1e-6)
        assert p.max_elevation_deg == pytest.approx(full.max_elevation_deg, abs=0.2)
        assert abs(p.set.seconds_since(full.set)) < 1.0

    def test_grazing_pass_shorter_than_the_coarse_step_is_found(self):
        # The 10.53-deg-max pass against a 10.5 deg gate: above the gate for
        # ~20 s, shorter than the 30 s coarse step — reachable only through
        # run samples by luck or the graze-candidate path by design.
        start = Epoch.from_iso("2026-06-23T09:00:00", scale=TimeScale.UTC)
        passes = find_passes(
            _iss_tle(),
            STATION,
            3600.0,
            start=start,
            min_elevation_deg=10.5,
            visible_only=False,
            progress=False,
        )
        assert len(passes) == 1
        p = passes[0]
        assert p.max_elevation_deg == pytest.approx(10.53, abs=0.05)
        assert p.set.seconds_since(p.rise) < 60.0

    def test_grazing_candidate_that_misses_the_gate_is_discarded(self):
        # Same pass against an 11 deg gate: a graze candidate (within the 2 deg
        # margin) whose refined arc never reaches the gate — no pass.
        start = Epoch.from_iso("2026-06-23T09:00:00", scale=TimeScale.UTC)
        passes = find_passes(
            _iss_tle(),
            STATION,
            3600.0,
            start=start,
            min_elevation_deg=11.0,
            visible_only=False,
            progress=False,
        )
        assert passes == []

    def test_explicit_standard_magnitude_shifts_the_peak_linearly(self):
        # The formula is std + geometry: an explicit override must shift
        # peak_magnitude by exactly the std difference (same window, same arc).
        start = Epoch.from_iso("2026-06-23T07:40:00", scale=TimeScale.UTC)
        default = find_passes(_iss_tle(), STATION, 1200.0, start=start, progress=False)
        override = find_passes(
            _iss_tle(),
            STATION,
            1200.0,
            start=start,
            standard_magnitude=5.0,
            progress=False,
        )
        assert len(default) == 1 and len(override) == 1
        assert default[0].peak_magnitude is not None
        assert override[0].peak_magnitude is not None
        iss_std = -2.5 + 2.5 * math.log10(math.pi)  # the registry value
        assert override[0].peak_magnitude - default[0].peak_magnitude == (
            pytest.approx(5.0 - iss_std, abs=1e-9)
        )

    def test_stale_tle_warns_once(self):
        # A window ~42 days from the TLE epoch: the coarse scan warns once;
        # the per-candidate fine scans are suppressed as redundant sub-spans.
        far = Epoch.from_iso("2026-08-01T00:00:00", scale=TimeScale.UTC)
        with pytest.warns(StaleTLEWarning) as record:
            find_passes(
                _iss_tle(),
                STATION,
                21600.0,
                start=far,
                visible_only=False,
                progress=False,
            )
        stale = [w for w in record if w.category is StaleTLEWarning]
        assert len(stale) == 1

    def test_progress_callable_receives_a_monotonic_fraction(self):
        fractions: list[float] = []
        start = Epoch.from_iso("2026-06-23T07:40:00", scale=TimeScale.UTC)
        find_passes(_iss_tle(), STATION, 1200.0, start=start, progress=fractions.append)
        assert fractions, "the callable was never invoked"
        assert all(0.0 <= f <= 1.0 for f in fractions)
        assert fractions == sorted(fractions)
        assert fractions[-1] == pytest.approx(1.0)
