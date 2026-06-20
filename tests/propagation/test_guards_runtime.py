"""Runtime (JVM) tests for the altitude/regime guard system (addendum §6).

These exercise the terminal radius backstops *inside real ``propagate_numerical``
calls* — the only place the JPype default-method behavior and the ephemeris
sampling clamp actually surface (Chunk 6). The pure-Python ``AltitudeLimits`` /
escape-parity tests live in ``test_guards.py`` and keep the JVM down; here every
test starts the JVM once via the session-scoped ``orekit`` fixture.
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from propygator import (
    AltitudeLimits,
    Epoch,
    Frame,
    NumericalPropagationError,
    PropagationError,
    State,
    TimeScale,
    Trajectory,
)
from propygator.propagation import (
    ForceModelConfig,
    IntegratorConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
    propagate_numerical,
)
from propygator.propagation.numerical import _sample_count

# Drag-only force config (no third body / SRP) so the drag-regime signal is isolated.
_DRAG_ONLY = ForceModelConfig(
    gravity_degree=4,
    gravity_order=4,
    sun_third_body=False,
    moon_third_body=False,
    drag=True,
    srp=False,
)

_MU = 3.986004418e14  # Earth GM (m^3/s^2)


def _vis_viva_perpendicular(r: float, r_other: float) -> float:
    """Perpendicular speed at radius ``r`` of the two-body orbit through apsides
    ``r`` and ``r_other`` (vis-viva with ``a = (r + r_other) / 2``)."""
    a = 0.5 * (r + r_other)
    return float((_MU * (2.0 / r - 1.0 / a)) ** 0.5)


# Every test here needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")

_EPOCH = Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC)

# WGS84 equatorial radius (impact backstop) and the ≈ 327,000 km escape-parity radius
# (the Chunk-5 altitude lowered back through the same equatorial radius).
_R_EARTH_M = 6_378_137.0
_ESCAPE_RADIUS_M = 327_000_000.0


def _state(position: list[float], velocity: list[float]) -> State:
    return State(
        _EPOCH,
        np.array(position, dtype=np.float64),
        np.array(velocity, dtype=np.float64),
        Frame.EME2000,
    )


def _radius(traj: Trajectory, i: int) -> float:
    return float(np.linalg.norm(traj.positions[i]))


# --- impact backstop -------------------------------------------------------


def test_subsurface_orbit_stops_at_impact():
    # Start at apogee (r = 6800 km); the perpendicular velocity gives a ~6000 km
    # perigee (below R⊕ = 6378 km), so the two-body orbit descends through R⊕ and the
    # impact detector stops it. Drag off (keplerian) — a clean geometric impact, not a
    # re-entry (§8: "impact" is reserved for a drag-off sub-surface orbit).
    state = _state([6.8e6, 0.0, 0.0], [0.0, 7413.0, 0.0])
    duration, output_step = 3000.0, 30.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
    )

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "impact"
    assert traj.metadata["termination_epoch"].endswith("Z")
    # Partial: fewer than the planned samples, but a usable (>= 2) trajectory ending
    # just above the crossing radius.
    assert 2 <= len(traj) < _sample_count(duration, output_step)
    assert _radius(traj, -1) >= _R_EARTH_M
    assert _radius(traj, -1) < _radius(traj, 0)  # descended


def test_termination_within_first_output_step_stays_usable():
    # A terminal crossing before the first output_step would clamp to one on-grid
    # sample (the start); the guard appends the achieved-span endpoint so the partial
    # Trajectory keeps the >= 2 samples downstream verbs need. Same impact orbit as
    # above (6800 km apogee -> 6000 km perigee, crosses R-Earth near 1370 s), now with
    # a 2000 s output_step so the crossing lands inside the first step.
    state = _state([6.8e6, 0.0, 0.0], [0.0, 7413.0, 0.0])
    duration, output_step = 4000.0, 2000.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
    )

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "impact"
    # Start + appended crossing endpoint -> exactly 2 samples, not a degenerate 1.
    assert len(traj) == 2
    assert _radius(traj, -1) < _radius(traj, 0)  # descended toward the surface
    # Usable: interpolation between the two samples does not raise.
    assert traj.at(_EPOCH.shifted_by(500.0)) is not None


# --- escape backstop -------------------------------------------------------


def test_hyperbolic_orbit_stops_at_escape():
    # Strongly hyperbolic, radial-dominant climb (speed ~11.4 km/s > escape ~10.7 km/s
    # at 7000 km), so it runs out to the ≈ 327,000 km escape-parity radius. Drag off.
    state = _state([7.0e6, 0.0, 0.0], [11000.0, 3000.0, 0.0])
    duration, output_step = 3.0 * 86400.0, 600.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
    )

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "escape"
    assert traj.metadata["termination_epoch"].endswith("Z")
    assert 2 <= len(traj) < _sample_count(duration, output_step)
    # Climbed: the last sample is below the escape radius (samples stop just short of
    # the crossing) but far above the start.
    assert _radius(traj, -1) > _radius(traj, 0)
    assert _radius(traj, -1) < _ESCAPE_RADIUS_M


def test_hyperbolic_escape_full_force_models():
    # Chunk 10 (addendum §6.5/§8): verify a hyperbolic Cartesian State round-trips
    # end-to-end through the FULL default force-model stack — leo_default: 70x70 gravity
    # + Sun/Moon third body + drag (NRLMSISE-00) + SRP — and that the escape detector
    # catches the climb-out, terminating with reason "escape". Unlike the keplerian case
    # above this proves the whole perturbation stack tolerates an unbound (e>1) orbit
    # (the CartesianOrbit path has no bound check; §6.5 retains the eccentricity gates
    # and only ADDS the escape backstop).
    #
    # Perigee-injection hyperbola: r = 7000 km (perigee, ~622 km altitude), v = 11.5
    # km/s purely tangential > the local escape speed 10.67 km/s -> e ≈ 1.32,
    # v_inf ≈ 4.29 km/s, C3 ≈ 18.4 km^2/s^2. It reaches the ≈ 327,000 km parity radius
    # (≈ 51x the LEO radius) in ~18 h, comfortably inside the 10-day planned span.
    state = _state([7.0e6, 0.0, 0.0], [0.0, 11500.0, 0.0])
    # The input is genuinely hyperbolic through the conversion layer too
    # (core/elements.py e>1 branch) — the already-supported case §6.5 makes safe.
    assert state.to_keplerian().eccentricity > 1.0

    duration, output_step = 10.0 * 86400.0, 3600.0
    traj = propagate_numerical(state, duration, output_step=output_step)  # leo_default

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "escape"
    assert traj.metadata["termination_epoch"].endswith("Z")
    # Partial trajectory: stopped at the crossing, far short of the 10-day sample count.
    assert 2 <= len(traj) < _sample_count(duration, output_step)
    # Climbed monotonically to just below the escape radius, never overshooting it.
    assert _radius(traj, 0) < _radius(traj, -1) < _ESCAPE_RADIUS_M
    # The single crossing was resolved cleanly (not run on to absurd distances): the
    # last on-grid sample sits within one output_step's radial climb of the escape
    # radius (radial speed near escape is ~4.6 km/s, so < 6 km/s * output_step bounds
    # it) — i.e. the 60 s maxCheck / 1e-3 s threshold tuning scales fine at ~51x LEO.
    assert _ESCAPE_RADIUS_M - _radius(traj, -1) < 6000.0 * output_step


# --- normal-run regression (the common path is unchanged) ------------------


def test_normal_leo_run_is_unchanged():
    # ISS-like circular LEO (alt ~400 km): well inside both backstops, so it runs to
    # completion with NO termination metadata and exactly the planned sample count —
    # byte-identical to before the guard system landed.
    r = 6.778e6
    v = (_MU / r) ** 0.5  # circular speed
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    duration, output_step = 3600.0, 60.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
    )

    assert "terminated" not in traj.metadata
    assert "termination_reason" not in traj.metadata
    assert "termination_epoch" not in traj.metadata
    assert len(traj) == _sample_count(duration, output_step)


# --- user altitude limits (Chunk 7; addendum §6.4/§6.6) --------------------


def test_user_min_crossing_stops_and_reports():
    # Eccentric orbit started at apogee (r = 6900 km, alt ~522 km) descending toward a
    # 6650 km perigee (alt ~272 km, still above R⊕ = 6378 km so impact never fires). A
    # reasonable min_altitude_km=350 km -> radius ~6728 km, between apogee and perigee:
    # the inner user_min radius is reached on the descent BEFORE impact, so it fires
    # first (the tightest-of rule, low side) and the run stops & reports user_min. Drag
    # off (keplerian) for a deterministic two-body descent.
    r_apo, r_per = 6.9e6, 6.65e6
    state = _state([r_apo, 0.0, 0.0], [0.0, _vis_viva_perpendicular(r_apo, r_per), 0.0])
    min_altitude_km = 350.0
    min_radius_m = _R_EARTH_M + min_altitude_km * 1000.0
    duration, output_step = 3000.0, 30.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
        limits=AltitudeLimits(min_altitude_km=min_altitude_km),
    )

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "user_min"
    assert traj.metadata["termination_epoch"].endswith("Z")
    # Partial: stopped at the user_min crossing, not the planned end.
    assert 2 <= len(traj) < _sample_count(duration, output_step)
    # Descended to (just above) the user_min radius — and well above R⊕, i.e. user_min
    # fired before the impact backstop could.
    assert _radius(traj, -1) < _radius(traj, 0)
    assert _R_EARTH_M < min_radius_m <= _radius(traj, -1) + 1.0


def test_user_max_crossing_stops_and_reports():
    # Eccentric orbit started at perigee (r = 6778 km, alt ~400 km) climbing toward an
    # 8200 km apogee (alt ~1822 km, far below the ~327,000 km escape radius). A
    # reasonable max_altitude_km=1500 km -> radius ~7878 km, between perigee and apogee:
    # the user_max radius is reached on the climb BEFORE escape, so it fires first (the
    # tightest-of rule, high side) and the run stops & reports user_max.
    r_per, r_apo = 6.778e6, 8.2e6
    state = _state([r_per, 0.0, 0.0], [0.0, _vis_viva_perpendicular(r_per, r_apo), 0.0])
    max_altitude_km = 1500.0
    max_radius_m = _R_EARTH_M + max_altitude_km * 1000.0
    duration, output_step = 3000.0, 30.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
        limits=AltitudeLimits(max_altitude_km=max_altitude_km),
    )

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "user_max"
    assert traj.metadata["termination_epoch"].endswith("Z")
    assert 2 <= len(traj) < _sample_count(duration, output_step)
    # Climbed to (just below) the user_max radius — far below escape, i.e. user_max
    # fired before the escape backstop could.
    assert _radius(traj, -1) > _radius(traj, 0)
    assert _radius(traj, -1) - 1.0 <= max_radius_m < _ESCAPE_RADIUS_M


def test_in_band_run_with_limits_is_unchanged():
    # Circular ~400 km LEO that stays strictly inside reasonable user limits
    # (200–2000 km): no crossing, so the run completes with NO termination metadata and
    # the full planned sample count — passing `limits` does not perturb the common path.
    r = 6.778e6
    v = (_MU / r) ** 0.5  # circular speed
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    duration, output_step = 3600.0, 60.0
    traj = propagate_numerical(
        state,
        duration,
        output_step=output_step,
        force_models=ForceModelConfig.keplerian(),
        limits=AltitudeLimits(min_altitude_km=200.0, max_altitude_km=2000.0),
    )

    assert "terminated" not in traj.metadata
    assert "termination_reason" not in traj.metadata
    assert "termination_epoch" not in traj.metadata
    assert len(traj) == _sample_count(duration, output_step)


# --- min-step re-entry classifier (Chunk 8; addendum §6.6) -----------------


def test_drag_decay_stops_and_reports_reentry():
    # A 140 km circular LEO with drag on (leo_default) spirals in and the propagation
    # fails near the surface (the atmosphere model rejects the sub-surface query). The
    # failure is caught, the partial ephemeris recovered, and classified as a physical
    # re-entry (drag on + descending + osculating perigee below the ~150 km floor) -> it
    # stops & reports "reentry" instead of raising. (~1.5 s wall: the decay is fast.)
    r = _R_EARTH_M + 140_000.0
    v = (_MU / r) ** 0.5
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    duration, output_step = 1.5 * 86400.0, 600.0
    # The decay dips below the Kn floor, so the loud free-molecular-flow warning fires
    # (its own emission is pinned by test_drag_below_kn_floor_warns_loud_once). Here it
    # is expected and incidental to the reentry stop-and-report under test, so suppress
    # it to keep this test focused and the suite's warning summary clean.
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        traj = propagate_numerical(
            state,
            duration,
            output_step=output_step,
            force_models=ForceModelConfig.leo_default(),
        )

    assert traj.metadata["terminated"] is True
    assert traj.metadata["termination_reason"] == "reentry"
    assert traj.metadata["termination_epoch"].endswith("Z")
    # Partial: stopped at re-entry, not the planned end, but a usable trajectory that
    # descended to near the surface.
    assert 2 <= len(traj) < _sample_count(duration, output_step)
    assert _radius(traj, -1) < _radius(traj, 0)
    assert _radius(traj, -1) < _R_EARTH_M + 150_000.0  # below the drag-table floor


def test_overtight_tolerance_failure_still_raises():
    # A healthy 400 km circular orbit with drag OFF (keplerian) and an unmeetable
    # min_step_s=120 s saturates the integrator. Drag off -> the classifier rejects
    # re-entry, so it RE-RAISES PropagationError (invariant: a false re-raise beats a
    # false reentry) — but carries the recoverable partial for advanced recovery.
    r = _R_EARTH_M + 400_000.0
    v = (_MU / r) ** 0.5
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    stiff = IntegratorConfig(
        abs_tolerance_m=1e-12, rel_tolerance=1e-12, min_step_s=120.0, max_step_s=300.0
    )
    with pytest.raises(PropagationError) as excinfo:
        propagate_numerical(
            state,
            1800.0,
            output_step=60.0,
            force_models=ForceModelConfig.keplerian(),
            integrator=stiff,
        )
    # No raw Java trace leaks (architecture §3).
    assert "org.orekit" not in str(excinfo.value)
    assert isinstance(excinfo.value, NumericalPropagationError)
    # A recoverable partial is attached, and it is a plain (non-terminated) Trajectory.
    partial = excinfo.value.partial_trajectory
    assert isinstance(partial, Trajectory)
    assert "terminated" not in partial.metadata


def test_no_good_steps_failure_raises_without_partial():
    # min_step_s == max_step_s with a tight tolerance: the first step is rejected, so NO
    # good steps are generated and getGeneratedEphemeris() itself raises (edge a). The
    # run fails loudly with no partial attached.
    r = _R_EARTH_M + 400_000.0
    v = (_MU / r) ** 0.5
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    stiff = IntegratorConfig(
        abs_tolerance_m=1e-12, rel_tolerance=1e-12, min_step_s=300.0, max_step_s=300.0
    )
    with pytest.raises(PropagationError) as excinfo:
        propagate_numerical(
            state,
            1800.0,
            output_step=60.0,
            force_models=ForceModelConfig.keplerian(),
            integrator=stiff,
        )
    assert excinfo.value.partial_trajectory is None


# --- two-tier drag-regime warnings (Chunk 9; addendum §6.2) ----------------
#
# The pure-Python Kn-floor scan (geometry -> floor) is unit-tested in test_guards.py;
# these exercise the *emission* of the warn-once messages inside a real propagation,
# the only place the per-substep drag-path hook actually fires.


def test_drag_below_kn_floor_warns_loud_once():
    # A large body (30 m sphere -> floor ~200+ km) on a low ~175 km circular orbit is
    # below its free-molecular floor with drag on, so the loud regime warning fires
    # exactly once. Fixed Cd (no table) isolates the Kn-floor warning from table-edge
    # ones; the high mass keeps the low orbit from decaying within the short run.
    r = _R_EARTH_M + 175_000.0
    v = (_MU / r) ** 0.5
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    spacecraft = SpacecraftConfig(
        mass_kg=400_000.0,
        geometry=SpacecraftGeometry.sphere(area_m2=700.0, drag_coefficient=2.2),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        propagate_numerical(
            state,
            600.0,
            output_step=60.0,
            force_models=_DRAG_ONLY,
            spacecraft=spacecraft,
        )
    floor_warnings = [
        w for w in caught if "free-molecular flow floor" in str(w.message)
    ]
    assert len(floor_warnings) == 1
    # The message is body-specific (L = 2*sqrt(700/pi) ~ 29.9 m).
    assert "29.9 m body" in str(floor_warnings[0].message)


def test_drag_above_table_ceiling_warns_soft_once():
    # A ~1500 km circular orbit (above the ~1400 km Cd-table ceiling) with the shipped
    # sphere_default table and drag on: the radius clamps to the table's high edge, so
    # soft "drag negligible" note fires once. Far above the Kn floor -> no loud warning.
    r = _R_EARTH_M + 1_500_000.0
    v = (_MU / r) ** 0.5
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    spacecraft = SpacecraftConfig(
        mass_kg=500.0,
        geometry=SpacecraftGeometry.sphere(
            area_m2=2.0, drag_coefficient=VariableCd.sphere_default()
        ),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        propagate_numerical(
            state,
            3600.0,
            output_step=600.0,
            force_models=_DRAG_ONLY,
            spacecraft=spacecraft,
        )
    soft = [w for w in caught if "above the drag-table grid" in str(w.message)]
    loud = [w for w in caught if "free-molecular flow floor" in str(w.message)]
    assert len(soft) == 1
    assert loud == []  # 1500 km is far above the Kn floor


def test_drag_off_emits_no_regime_warning():
    # The same low ~175 km orbit with drag OFF (keplerian): no drag model is wired, so
    # neither tier of drag-regime warning fires (the drag-evaluation hook never runs).
    r = _R_EARTH_M + 175_000.0
    v = (_MU / r) ** 0.5
    state = _state([r, 0.0, 0.0], [0.0, v, 0.0])
    spacecraft = SpacecraftConfig(
        mass_kg=400_000.0,
        geometry=SpacecraftGeometry.sphere(area_m2=700.0),
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        propagate_numerical(
            state,
            600.0,
            output_step=60.0,
            force_models=ForceModelConfig.keplerian(),
            spacecraft=spacecraft,
        )
    regime = [
        w
        for w in caught
        if "free-molecular flow floor" in str(w.message)
        or "drag-table grid" in str(w.message)
    ]
    assert regime == []
