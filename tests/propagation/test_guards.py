"""Pure-Python tests for ``AltitudeLimits`` and the escape-parity constant.

Chunk 5 of the drag-validity & altitude-guards addendum lands only the
safe-before-init surface of the guard system (addendum §6.4) — construction and
validation never touch Orekit. These tests must not start the JVM (architecture
§10); the JVM-touching detectors arrive in later chunks with the ``orekit``
fixture.
"""

from __future__ import annotations

import math
from dataclasses import FrozenInstanceError

import pytest

from propygator.propagation import AltitudeLimits
from propygator.propagation.guards import (
    _ESCAPE_PARITY_ALTITUDE_KM,
    _KINETIC_DIAMETER_M,
    _characteristic_length_m,
    _classify_termination,
    _floor_altitude_km,
    _interp_log,
    _is_reentry_failure,
    _mean_free_path_m,
)
from propygator.propagation.spacecraft import SpacecraftGeometry

# A representative re-entry floor radius (≈ R⊕ + 150 km) for the pure classifier tests;
# the JVM-backed _reentry_floor_radius_m() is exercised by the runtime suite.
_FLOOR_M = 6_528_137.0


def test_no_jvm_started():
    import jpype

    assert not jpype.isJVMStarted()


# --- construction ----------------------------------------------------------


def test_defaults_are_none():
    lim = AltitudeLimits()
    assert lim.min_altitude_km is None
    assert lim.max_altitude_km is None


def test_is_frozen():
    lim = AltitudeLimits()
    with pytest.raises(FrozenInstanceError):
        lim.min_altitude_km = 100.0  # type: ignore[misc]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"min_altitude_km": 200.0, "max_altitude_km": 2000.0},
        {"min_altitude_km": 200.0},  # min only; max unbounded -> system backstop
        {"max_altitude_km": 2000.0},  # max only; min unbounded -> system backstop
        {"min_altitude_km": 0.0},  # boundary: a zero floor is reasonable
        {"max_altitude_km": 320_000.0},  # just under the escape-parity altitude
    ],
)
def test_accepts_reasonable_limits(kwargs):
    lim = AltitudeLimits(**kwargs)
    assert lim.min_altitude_km == kwargs.get("min_altitude_km")
    assert lim.max_altitude_km == kwargs.get("max_altitude_km")


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize("field", ["min_altitude_km", "max_altitude_km"])
@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_rejects_nonfinite(field, bad):
    with pytest.raises(ValueError):
        AltitudeLimits(**{field: bad})


def test_rejects_negative_min():
    # Below the surface — the impact backstop fires first, so it can never bind.
    with pytest.raises(ValueError, match="min_altitude_km must be >= 0"):
        AltitudeLimits(min_altitude_km=-50.0)


def test_rejects_max_above_escape_parity():
    # Above the escape-parity altitude — the escape backstop fires first.
    with pytest.raises(ValueError, match="escape-parity altitude"):
        AltitudeLimits(max_altitude_km=400_000.0)


def test_rejects_min_not_below_max():
    with pytest.raises(ValueError, match="min_altitude_km must be < max_altitude_km"):
        AltitudeLimits(min_altitude_km=2000.0, max_altitude_km=200.0)


def test_rejects_min_equal_max():
    with pytest.raises(ValueError, match="min_altitude_km must be < max_altitude_km"):
        AltitudeLimits(min_altitude_km=500.0, max_altitude_km=500.0)


# --- escape-parity constant ------------------------------------------------


def test_escape_parity_altitude_in_expected_band():
    # ≈ 327,000 km parity radius minus the WGS84 equatorial radius (addendum §6.3).
    assert 320_000.0 < _ESCAPE_PARITY_ALTITUDE_KM < 321_000.0


def test_construction_does_not_start_jvm():
    import jpype

    AltitudeLimits()
    AltitudeLimits(min_altitude_km=200.0, max_altitude_km=2000.0)
    with pytest.raises(ValueError):
        AltitudeLimits(min_altitude_km=-1.0)
    assert not jpype.isJVMStarted()


# --- min-step re-entry classifier (pure-Python; addendum §6.6) -------------


def test_reentry_classifier_true_when_drag_descending_perigee_below_floor():
    # All three conditions hold -> physical re-entry.
    assert _is_reentry_failure(
        drag_enabled=True,
        radial_velocity_m_s=-90.0,
        perigee_radius_m=_FLOOR_M - 50_000.0,  # below the floor
        floor_radius_m=_FLOOR_M,
    )


def test_reentry_classifier_false_when_drag_off():
    # Drag off -> never a drag-driven re-entry, even if descending below the floor.
    assert not _is_reentry_failure(
        drag_enabled=False,
        radial_velocity_m_s=-90.0,
        perigee_radius_m=_FLOOR_M - 50_000.0,
        floor_radius_m=_FLOOR_M,
    )


def test_reentry_classifier_false_when_climbing():
    # Ascending (radial velocity >= 0) -> not a re-entry (a healthy low pass climbs).
    assert not _is_reentry_failure(
        drag_enabled=True,
        radial_velocity_m_s=10.0,
        perigee_radius_m=_FLOOR_M - 50_000.0,
        floor_radius_m=_FLOOR_M,
    )


def test_reentry_classifier_false_when_perigee_above_floor():
    # Perigee still above the floor -> a genuine failure to re-raise, not a re-entry
    # (the invariant: prefer a false re-raise over a false reentry).
    assert not _is_reentry_failure(
        drag_enabled=True,
        radial_velocity_m_s=-90.0,
        perigee_radius_m=_FLOOR_M + 50_000.0,
        floor_radius_m=_FLOOR_M,
    )


# --- termination-reason classifier (pure-Python; addendum §6.1/§6.6) -------

_IMPACT_R = 6_378_137.0
_ESCAPE_R = 327_000_000.0


def test_classify_termination_picks_nearest_threshold():
    specs = [(_IMPACT_R, "impact"), (_ESCAPE_R, "escape")]
    assert _classify_termination(_IMPACT_R + 400.0, specs) == "impact"
    assert _classify_termination(_ESCAPE_R - 1_000_000.0, specs) == "escape"


def test_classify_termination_system_reason_wins_exact_tie():
    # A user limit can land EXACTLY on a system threshold: min_altitude_km == 0
    # coincides with the impact radius, and max at escape-parity coincides with escape.
    # The call site keeps the system backstops FIRST in `specs`, so min() resolves the
    # degenerate tie to the system reason. Pins that ordering invariant (see the
    # _classify_termination docstring) so a future reorder/sort can't mislabel a system
    # stop as user_min/user_max.
    specs = [
        (_IMPACT_R, "impact"),
        (_ESCAPE_R, "escape"),
        (_IMPACT_R, "user_min"),  # min_altitude_km == 0 -> coincides with impact
        (_ESCAPE_R, "user_max"),  # max at escape-parity -> coincides with escape
    ]
    assert _classify_termination(_IMPACT_R, specs) == "impact"
    assert _classify_termination(_ESCAPE_R, specs) == "escape"


# --- free-molecular (Knudsen) validity floor (pure-Python; addendum §6.2/§6.3) ----
#
# The runtime re-implements the experiment's §3.4 λ/σ/Kn/scan method over the embedded
# conservative-profile composition. All of it is JVM-free, so it is unit-tested here
# without the orekit fixture; the propagation-time warning emission is in the runtime
# (JVM) suite. Lowering the floor altitude to a radius is the only JVM-touching step.

# The committed experiment curve (experiments/.../kn_floor_results.txt, conservative
# high-activity): the runtime scan must reproduce these once the real composition is in.
_EXPERIMENT_FLOOR_KM = {0.1: 110.5, 1.0: 128.4, 10.0: 177.2, 30.0: 222.5}


def test_characteristic_length_sphere_is_diameter():
    # L = 2*sqrt(A/pi): area = pi -> diameter 2.0.
    assert _characteristic_length_m(
        SpacecraftGeometry.sphere(area_m2=math.pi)
    ) == pytest.approx(2.0)


def test_characteristic_length_box_is_max_edge():
    # Box -> max edge length (conservative: largest dimension -> highest, safest floor).
    box = SpacecraftGeometry.box_and_panels(
        x_length_m=2.0, y_length_m=1.5, z_length_m=6.0
    )
    assert _characteristic_length_m(box) == pytest.approx(6.0)


def test_interp_log_clamps_outside_bracket():
    # Out-of-bracket x returns the nearest edge value (clamped), never extrapolated.
    xs = (0.0, 1.0, 2.0)
    ys = (1.0, 10.0, 100.0)
    assert _interp_log(-5.0, xs, ys) == pytest.approx(1.0)  # below -> low edge
    assert _interp_log(99.0, xs, ys) == pytest.approx(100.0)  # above -> high edge
    assert _interp_log(0.5, xs, ys) == pytest.approx(10.0**0.5)  # log-linear midpoint


def test_mean_free_path_increases_with_altitude():
    # λ ∝ 1/Σ n σ, and density falls with altitude -> λ rises monotonically.
    assert (
        _mean_free_path_m(100.0) < _mean_free_path_m(200.0) < _mean_free_path_m(400.0)
    )


def test_floor_altitude_monotonic_in_length():
    # Kn = λ/L, so a larger body reaches Kn = 10 only higher up -> a higher floor.
    floors = [_floor_altitude_km(length) for length in (0.1, 1.0, 10.0, 30.0)]
    assert all(f is not None for f in floors)
    assert floors == sorted(floors)
    assert floors[0] < floors[-1]  # strictly higher for the bigger body


def test_bigger_body_has_higher_floor_from_geometry():
    small = SpacecraftGeometry.sphere(area_m2=0.0079)  # ~0.1 m diameter CubeSat
    big = SpacecraftGeometry.sphere(area_m2=700.0)  # ~30 m diameter station
    floor_small = _floor_altitude_km(_characteristic_length_m(small))
    floor_big = _floor_altitude_km(_characteristic_length_m(big))
    assert floor_small is not None and floor_big is not None
    assert floor_big > floor_small


def test_floor_none_for_unphysical_length():
    # A body so huge the Kn = 10 crossing is above the captured band -> no floor (None),
    # so no nuisance warning. (And the symmetric tiny-body case.)
    assert _floor_altitude_km(1.0e6) is None
    assert _floor_altitude_km(1.0e-9) is None


@pytest.mark.parametrize("length_m, expected_km", _EXPERIMENT_FLOOR_KM.items())
def test_runtime_floor_matches_experiment_curve(length_m, expected_km):
    # The §5 equivalence obligation extended to the runtime Kn scan: a few floor
    # points must reproduce the committed experiment curve. The grid bisection vs the
    # experiment's continuous brentq differ only by sub-km interpolation error (the
    # generator's own self-check bounds it < 1 km), so 2 km is a comfortable tolerance.
    assert _floor_altitude_km(length_m) == pytest.approx(expected_km, abs=2.0)


def test_kn_floor_scan_does_not_start_jvm():
    import jpype

    _floor_altitude_km(_characteristic_length_m(SpacecraftGeometry.sphere(area_m2=1.0)))
    _mean_free_path_m(150.0)
    assert not jpype.isJVMStarted()


def test_sigma_table_pinned():
    # The kinetic-diameter / sigma table is hand-duplicated in THREE files that MUST
    # stay identical (addendum §5): src/.../guards.py (here), scripts/generate_kn_floor_
    # composition.py, and experiments/.../kn_floor.py. A src/ module cannot import the
    # other two, so this pins the shipped copy: a drift fails here, self-explained,
    # instead of surfacing as a mysterious test_runtime_floor_matches_experiment_curve
    # miss. If the change is intentional, update all three copies and regenerate the
    # embedded composition.
    assert _KINETIC_DIAMETER_M == {
        "N2": 3.64e-10,
        "O2": 3.46e-10,
        "O": 3.00e-10,
        "HE": 2.18e-10,
        "H": 2.40e-10,
        "AR": 3.40e-10,
        "N": 3.00e-10,
    }
