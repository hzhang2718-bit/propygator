"""Numerical propagator tests (Feature 1.1, build-plan chunks 7-9).

Covers ``propagate_numerical``: input validation, sample counting, integrator/gravity
resolution, the analytical two-body cross-check, a full-degree LEO sanity check, the
integrator presets, the chunk-8 perturbation set on the sphere — third body, drag with
fixed and :class:`VariableCd` coefficients, SRP, tides, relativity — and the chunk-9
**box geometry + full attitude family**: box drag/SRP via
``BoxAndSolarArraySpacecraft``, a box ``VariableCd``, each attitude mode end-to-end, the
attitude/geometry consistency warning, the Tier B per-face ``BoxFaceCd`` box drag
runtime, and the ``force_models`` / ``spacecraft`` / ``attitude`` metadata grammar. Like
``test_conversions`` / ``test_stack_compat``, every test starts the JVM once via the
session-scoped ``orekit`` fixture (the pure-Python config tests live in
``test_force_models`` / ``test_integrators`` / ``test_spacecraft`` / ``test_attitude``
and assert the JVM stays down).
"""

from __future__ import annotations

import warnings

import numpy as np
import pytest

from propygator import (
    Epoch,
    Frame,
    KeplerianElements,
    NumericalPropagationError,
    Orientation,
    PropagationError,
    State,
    TimeScale,
    Trajectory,
)
from propygator.propagation import (
    BoxFaceCd,
    CustomAttitude,
    ForceModelConfig,
    Inertial,
    InPlaneTracking,
    IntegratorConfig,
    LofAligned,
    LofOffset,
    NadirPointing,
    SpacecraftConfig,
    SpacecraftGeometry,
    SunPointing,
    VariableCd,
    propagate_numerical,
)

# Every test here needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")

_EPOCH = Epoch.from_iso("2026-01-01T00:00:00", scale=TimeScale.UTC)


def _state_from_elements(*, a_m: float, e: float = 0.001, i_deg: float = 51.6) -> State:
    """Build an EME2000 initial ``State`` from classical elements."""
    elements = KeplerianElements(
        semi_major_axis_m=a_m,
        eccentricity=e,
        inclination_rad=np.radians(i_deg),
        raan_rad=0.0,
        arg_perigee_rad=0.0,
        true_anomaly_rad=0.0,
    )
    return elements.to_state(_EPOCH, Frame.EME2000)


def _keplerian_state() -> State:
    """A near-circular ~620 km LEO test orbit (a = 7000 km)."""
    return _state_from_elements(a_m=7000e3)


def _leo_state() -> State:
    """An ISS-like ~500 km near-circular LEO orbit (a = 6878 km)."""
    return _state_from_elements(a_m=6878e3)


def _point_mass_mu() -> float:
    """The central mu the keplerian (point-mass) propagation actually uses."""
    from org.orekit.forces.gravity.potential import GravityFieldFactory

    return float(GravityFieldFactory.getNormalizedProvider(0, 0).getMu())


def _drag_eval_setup(mass_kg: float = 200.0):
    """A ~400 km EME2000 ``SpacecraftState`` + a Harris-Priester atmosphere.

    For acceleration-level drag comparisons: a shared atmosphere + state means the only
    thing that can differ between two drag ``ForceModel``s is the drag formula itself.
    """
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.propagation import SpacecraftState

    from propygator.core.bodies import _earth, _sun
    from propygator.propagation.numerical import _resolve_atmosphere

    initial = _state_from_elements(a_m=6778e3)  # ~400 km, well within the drag regime
    orbit = CartesianOrbit(
        initial.to_orekit().getPVCoordinates(),
        Frame.EME2000.to_orekit(),
        _EPOCH.to_orekit(),
        _point_mass_mu(),
    )
    state = SpacecraftState(orbit, mass_kg)
    atmosphere = _resolve_atmosphere("Harris-Priester", _sun(), _earth())
    return state, atmosphere


# --- sample counting --------------------------------------------------------


def test_sample_count_divisible_lands_on_duration():
    """An exact multiple yields floor(d/s)+1 samples, last exactly at duration."""
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
    )
    assert len(traj) == 11
    assert traj[0].epoch == _EPOCH
    assert traj[-1].epoch == _EPOCH.shifted_by(600.0)


def test_sample_count_non_divisible_ends_shy_of_duration():
    """A non-multiple drops the partial final step; no synthesized sample."""
    traj = propagate_numerical(
        _keplerian_state(),
        665.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
    )
    # floor(665/60 + tol) + 1 = 11 + 1 = 12, last at +660 s (< 665).
    assert len(traj) == 12
    assert traj[-1].epoch == _EPOCH.shifted_by(660.0)
    # The last sample is strictly inside the requested span.
    assert traj[-1].epoch != _EPOCH.shifted_by(665.0)


# --- input validation -------------------------------------------------------


def test_non_inertial_frame_raises():
    itrf_state = _keplerian_state().to_frame(Frame.ITRF)
    with pytest.raises(ValueError, match="inertial"):
        propagate_numerical(itrf_state, 600.0, output_step=60.0)


@pytest.mark.parametrize(
    "duration, output_step",
    [
        (0.0, 60.0),  # duration not positive
        (-100.0, 60.0),  # backward propagation unsupported
        (600.0, 0.0),  # output_step not positive
        (600.0, -60.0),  # negative output_step
        (60.0, 120.0),  # output_step > duration
    ],
)
def test_duration_output_step_validation(duration, output_step):
    with pytest.raises(ValueError):
        propagate_numerical(
            _keplerian_state(),
            duration,
            output_step=output_step,
            force_models=ForceModelConfig.keplerian(),
        )


def test_excessive_sample_count_raises():
    """A tiny output_step over a long duration is rejected before any allocation."""
    with pytest.raises(ValueError, match="output samples"):
        propagate_numerical(
            _keplerian_state(),
            1.0e9,  # ~32 years; at 1 ms output_step that is ~1e12 samples
            output_step=1.0e-3,
            force_models=ForceModelConfig.keplerian(),
        )


def test_unknown_integrator_type_raises():
    with pytest.raises(ValueError, match="integrator type"):
        propagate_numerical(
            _keplerian_state(),
            600.0,
            output_step=60.0,
            force_models=ForceModelConfig.keplerian(),
            integrator=IntegratorConfig(type="RK45"),
        )


def test_classical_rk4_requires_fixed_step():
    with pytest.raises(ValueError, match="fixed_step_s"):
        propagate_numerical(
            _keplerian_state(),
            600.0,
            output_step=60.0,
            force_models=ForceModelConfig.keplerian(),
            integrator=IntegratorConfig(type="ClassicalRK4"),
        )


def test_classical_rk4_with_fixed_step_runs():
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
        integrator=IntegratorConfig(type="ClassicalRK4", fixed_step_s=10.0),
    )
    assert len(traj) == 11
    # Fixed-step metadata records the step that actually drove the run, not the
    # adaptive tolerances (which never act on ClassicalRK4) — reproducible record.
    assert traj.metadata["integrator_tolerances"] == {"fixed_step_s": 10.0}


def test_high_precision_preset_runs_on_leo_and_geo():
    """The high_precision preset (rel_tol 1e-12) must not drive the adaptive step
    below min_step on representative LEO/GEO orbits (features.md §1.1 flags this for
    verification; if this ever raises, loosen the preset to 1e-11)."""
    cases = (
        (_leo_state(), ForceModelConfig.leo_default()),
        (_state_from_elements(a_m=42164e3, i_deg=0.1), ForceModelConfig.geo_default()),
    )
    for state, fm in cases:
        traj = propagate_numerical(
            state,
            600.0,
            output_step=60.0,
            force_models=fm,
            integrator=IntegratorConfig.high_precision(),
        )
        assert len(traj) == 11


def test_unknown_gravity_field_raises():
    with pytest.raises(ValueError, match="gravity_field"):
        propagate_numerical(
            _keplerian_state(),
            600.0,
            output_step=60.0,
            force_models=ForceModelConfig(gravity_field="BOGUS-99"),
        )


def test_unknown_atmosphere_model_raises_when_drag_on():
    with pytest.raises(ValueError, match="atmosphere_model"):
        propagate_numerical(
            _leo_state(),
            600.0,
            output_step=60.0,
            force_models=ForceModelConfig(atmosphere_model="BOGUS"),
        )


def test_unknown_atmosphere_model_ignored_when_drag_off():
    """A bogus atmosphere name is harmless when drag is off (the model is unused)."""
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig(
            gravity_degree=0,
            gravity_order=0,
            sun_third_body=False,
            moon_third_body=False,
            drag=False,
            srp=False,
            atmosphere_model="BOGUS",
        ),
    )
    assert len(traj) == 11


# --- physics: analytical two-body cross-check -------------------------------


def test_keplerian_matches_analytical_two_body():
    """Point-mass numerical propagation matches Orekit's analytical Kepler.

    The §11 cross-check: with no perturbations the numerical integrator must
    reproduce the closed-form two-body motion (catches "imports work but the math
    is wrong" — frame, dtype, or mu mistakes). Built with the *same* mu the
    point-mass propagation uses so the comparison is internally exact.
    """
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.propagation.analytical import KeplerianPropagator

    initial = _keplerian_state()
    traj = propagate_numerical(
        initial,
        5800.0,  # ~ one orbital period
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
    )

    mu = _point_mass_mu()
    eme2000 = Frame.EME2000.to_orekit()
    start = initial.epoch.to_orekit()
    orbit = CartesianOrbit(initial.to_orekit().getPVCoordinates(), eme2000, start, mu)
    analytical = KeplerianPropagator(orbit)

    max_pos_err = 0.0
    max_vel_err = 0.0
    for k, sample in enumerate(traj):
        pv = analytical.propagate(start.shiftedBy(float(k * 60.0))).getPVCoordinates()
        ref_p = np.array(
            [pv.getPosition().getX(), pv.getPosition().getY(), pv.getPosition().getZ()]
        )
        ref_v = np.array(
            [pv.getVelocity().getX(), pv.getVelocity().getY(), pv.getVelocity().getZ()]
        )
        max_pos_err = max(max_pos_err, float(np.linalg.norm(sample.position - ref_p)))
        max_vel_err = max(max_vel_err, float(np.linalg.norm(sample.velocity - ref_v)))

    assert max_pos_err < 1e-2  # < 1 cm over a full orbit
    assert max_vel_err < 1e-5  # < 10 micron/s


def test_leo_full_gravity_altitude_bounded():
    """A full-degree (70x70) gravity-only LEO run stays bounded (no decay/blowup).

    Gravity alone is conservative, so over a few orbits the geocentric radius
    oscillates in a tight band around the initial radius — a sanity check that the
    high-degree field is wired correctly and the integration is stable.
    """
    initial = _leo_state()
    r0 = float(np.linalg.norm(initial.position))
    traj = propagate_numerical(
        initial,
        3 * 5550.0,  # ~3 orbital periods
        output_step=60.0,
        force_models=ForceModelConfig.leo_default(),
    )
    radii = np.linalg.norm(traj.positions, axis=1)
    # J2 makes the osculating radius wobble by tens of km on a near-circular LEO;
    # a 50 km band is comfortably loose yet catches secular decay or a blowup.
    assert np.all(np.abs(radii - r0) < 50e3)


@pytest.mark.parametrize(
    "integrator",
    [
        IntegratorConfig.default(),
        IntegratorConfig.fast(),
        IntegratorConfig.high_precision(),
    ],
)
def test_integrator_presets_run(integrator):
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
        integrator=integrator,
    )
    assert len(traj) == 11


def test_min_step_saturation_raises_propagation_error():
    """An unmeetable tolerance drives the adaptive step below min_step_s; Orekit stops
    ("minimal step size reached") and we surface it as PropagationError with the Orekit
    message only — no raw Java trace (features.md §1.1 failure table)."""
    # min_step_s far above the step the controller needs at rel=1e-14: Hipparchus
    # raises rather than continuing at an oversized step (the real saturation
    # behavior — it does NOT clamp-and-warn).
    stiff = IntegratorConfig(
        type="DOP853",
        min_step_s=120.0,
        max_step_s=1000.0,
        abs_tolerance_m=1e-9,
        rel_tolerance=1e-14,
    )
    with pytest.raises(PropagationError) as exc_info:
        propagate_numerical(_leo_state(), 600.0, output_step=60.0, integrator=stiff)
    # propagate_numerical raises the numerical subclass (still a PropagationError).
    assert isinstance(exc_info.value, NumericalPropagationError)
    msg = str(exc_info.value)
    assert msg.strip()  # carries the underlying Orekit message
    # No raw Java trace leaks to the caller.
    assert "org.orekit" not in msg
    assert "\tat " not in msg


# --- output frame + metadata ------------------------------------------------


def test_output_frame_is_eme2000():
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
    )
    assert traj.frame is Frame.EME2000


def test_force_models_metadata_leo_and_keplerian():
    """``force_models`` lists exactly the wired forces in token order (features.md).

    ``leo_default`` (sphere) wires gravity + Sun/Moon third body + drag + SRP;
    ``keplerian`` wires only the point-mass gravity token. Pins the byte-exact
    grammar and that the metadata reflects what is acting, not the config booleans.
    """
    leo = propagate_numerical(
        _leo_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.leo_default(),
    )
    assert leo.metadata["force_models"] == [
        "gravity:EIGEN-6S:70x70",
        "third_body:sun",
        "third_body:moon",
        "drag:NRLMSISE-00",
        "srp",
    ]

    kep = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
    )
    assert kep.metadata["force_models"] == ["gravity:EIGEN-6S:0x0"]


def test_force_models_metadata_geo_and_tides_relativity():
    """GEO preset (no drag) and a tides+relativity config serialize byte-exactly.

    Also exercises the solid-tide / ocean-tide / relativity build paths (off in every
    preset) and confirms a run with no surface force (drag/SRP) omits ``spacecraft``.
    """
    geo = propagate_numerical(
        _state_from_elements(a_m=42164e3, e=1e-4, i_deg=0.1),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.geo_default(),
    )
    assert geo.metadata["force_models"] == [
        "gravity:EIGEN-6S:12x12",
        "third_body:sun",
        "third_body:moon",
        "srp",
    ]

    tides = ForceModelConfig(
        gravity_degree=8,
        gravity_order=8,
        sun_third_body=False,
        moon_third_body=False,
        drag=False,
        srp=False,
        solid_tides=True,
        ocean_tides=True,
        relativity=True,
    )
    traj = propagate_numerical(
        _leo_state(), 600.0, output_step=60.0, force_models=tides
    )
    assert traj.metadata["force_models"] == [
        "gravity:EIGEN-6S:8x8",
        "tides:solid",
        "tides:ocean",
        "relativity",
    ]
    # No drag/SRP wired -> the spacecraft had no effect -> key omitted.
    assert "spacecraft" not in traj.metadata


def test_spacecraft_metadata_present_when_surface_force_wired():
    """``spacecraft`` is recorded when drag or SRP (which consume it) is wired."""
    leo = propagate_numerical(
        _leo_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.leo_default(),
    )
    assert leo.metadata["spacecraft"] == "sphere:A=1.0;m=1000.0,Cd=2.2,Cr=1.5"
    # GEO has SRP but no drag -> still consumes the spacecraft -> present.
    geo = propagate_numerical(
        _state_from_elements(a_m=42164e3, e=1e-4, i_deg=0.1),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.geo_default(),
    )
    assert "spacecraft" in geo.metadata
    # A sphere is orientation-independent, so the attitude key is never recorded for it
    # (it is gated on box geometry + a surface force; see the chunk-9 tests below).
    assert "attitude" not in leo.metadata


def test_metadata_required_and_optional_keys():
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
        integrator=IntegratorConfig.default(),
        name="run-7",
    )
    md = traj.metadata
    assert md["propagator"] == "numerical"
    assert md["propygator_version"]  # non-empty
    assert md["orekit_version"] != "unknown"  # resolved from orekit_jpype
    assert md["integrator"] == "DOP853"
    assert md["integrator_tolerances"] == {
        "abs_m": 1e-3,
        "rel": 1e-10,
        "min_step_s": 1e-3,
        "max_step_s": 1000.0,
    }
    assert md["output_step_s"] == 60.0
    assert md["created_at"]  # ISO timestamp present
    assert md["name"] == "run-7"
    # keplerian wires no surface force, so neither the spacecraft nor the attitude has
    # any effect on the result and both optional keys are omitted.
    assert "spacecraft" not in md
    assert "attitude" not in md


def test_metadata_name_absent_when_not_supplied():
    traj = propagate_numerical(
        _keplerian_state(),
        600.0,
        output_step=60.0,
        force_models=ForceModelConfig.keplerian(),
    )
    assert "name" not in traj.metadata


# --- chunk 8: perturbation physics + variable drag --------------------------

# A draggy ~400 km sphere (low ballistic coefficient) to amplify drag in the tests.
_DRAGGY_SPHERE = SpacecraftConfig(
    mass_kg=100.0, geometry=SpacecraftGeometry.sphere(area_m2=10.0)
)

# Drag-only force config (no third body / SRP) so the drag signal is isolated.
_DRAG_ONLY = ForceModelConfig(
    gravity_degree=4,
    gravity_order=4,
    sun_third_body=False,
    moon_third_body=False,
    drag=True,
    srp=False,
)


def test_variable_cd_constant_matches_fixed_drag():
    """A constant ``VariableCd`` and a fixed scalar Cd give the same trajectory.

    Since chunk 9 both feed the *same* custom ``DragSensitive`` (a fixed Cd through
    ``_constant_cd``, a ``VariableCd`` through its callable), so this is an end-to-end
    consistency check of the two ``cd_lookup`` paths — **not** a stock-Orekit
    comparison. That independent pin now lives in
    ``test_fixed_cd_sphere_matches_stock_isotropic_drag`` (acceleration level), since
    routing fixed Cd through the proxy means this propagation can no longer witness it.
    """
    initial = _state_from_elements(a_m=6778e3)
    common = dict(duration=3600.0, output_step=600.0, force_models=_DRAG_ONLY)

    fixed = propagate_numerical(
        initial,
        spacecraft=SpacecraftConfig(
            mass_kg=200.0,
            geometry=SpacecraftGeometry.sphere(area_m2=5.0, drag_coefficient=2.2),
        ),
        **common,
    )
    variable = propagate_numerical(
        initial,
        spacecraft=SpacecraftConfig(
            mass_kg=200.0,
            geometry=SpacecraftGeometry.sphere(
                area_m2=5.0, drag_coefficient=VariableCd.from_callable(lambda r, d: 2.2)
            ),
        ),
        **common,
    )
    diff = np.linalg.norm(fixed.positions - variable.positions, axis=1)
    assert np.max(diff) < 1e-3  # sub-mm: identical physics, identical sign


def test_fixed_cd_sphere_matches_stock_isotropic_drag():
    """The custom sphere drag formula reproduces Orekit's stock ``IsotropicDrag``.

    Chunk 9 routes *all* drag — fixed Cd included — through propygator's own
    ``_sphere_accel`` formula rather than stock ``IsotropicDrag``, which made
    ``test_variable_cd_constant_matches_fixed_drag`` tautological (both sides became
    the custom proxy). This restores the independent pin at the acceleration level:
    same atmosphere + state, so only the drag formula differs, catching a sign / scale
    / mass regression the propagation test can no longer see.
    """
    from org.orekit.forces.drag import DragForce, IsotropicDrag

    from propygator.propagation.numerical import _build_drag_force

    area, cd = 5.0, 2.2
    state, atmosphere = _drag_eval_setup()
    geom = SpacecraftGeometry.sphere(area_m2=area, drag_coefficient=cd)
    custom = _build_drag_force(geom, atmosphere, None)
    stock = DragForce(atmosphere, IsotropicDrag(area, cd))
    a_custom = custom.acceleration(state, custom.getParameters())
    a_stock = stock.acceleration(state, stock.getParameters())
    assert a_custom.subtract(a_stock).getNorm() < 1e-15  # machine-level identical


def test_drag_lowers_semi_major_axis():
    """Drag removes energy: drag-on final SMA is below drag-off (same other forces).

    The differential (only the drag boolean differs) cancels the shared J2 / luni-
    solar / SRP wobble, leaving the secular drag decay as the signal.
    """
    initial = _state_from_elements(a_m=6778e3)  # ~400 km
    shared = dict(
        gravity_degree=8,
        gravity_order=8,
        sun_third_body=True,
        moon_third_body=True,
        srp=True,
    )
    common = dict(duration=21600.0, output_step=600.0, spacecraft=_DRAGGY_SPHERE)

    drag_on = propagate_numerical(
        initial, force_models=ForceModelConfig(drag=True, **shared), **common
    )
    drag_off = propagate_numerical(
        initial, force_models=ForceModelConfig(drag=False, **shared), **common
    )
    a_on = drag_on[-1].to_keplerian().semi_major_axis_m
    a_off = drag_off[-1].to_keplerian().semi_major_axis_m
    assert a_on < a_off - 100.0  # clearly decayed, beyond the shared wobble


def test_geo_default_runs_and_stays_near_geo():
    """The GEO preset (gravity-degree-limited, SRP, no drag) runs and stays bounded."""
    geo = _state_from_elements(a_m=42164e3, e=1e-4, i_deg=0.1)
    traj = propagate_numerical(
        geo, 6 * 3600.0, output_step=600.0, force_models=ForceModelConfig.geo_default()
    )
    radii = np.linalg.norm(traj.positions, axis=1)
    assert np.all(np.abs(radii - 42164e3) < 100e3)  # bounded near GEO; no drag decay


def test_variable_cd_differs_from_fixed_and_clamps_once():
    """A table-Cd sphere differs from fixed-Cd and warns exactly once out-of-grid.

    The table spans radii entirely below the orbit, so every lookup clamps to the top
    edge (Cd = 3.0 there), warning once per table; the result must differ from a fixed
    Cd = 2.2 run.
    """
    initial = _leo_state()  # r ~ 6878 km, above the table's 6.0-6.1e6 m span
    table = VariableCd.from_table(
        np.full((2, 2), 3.0),
        radius_axis=np.array([6.0e6, 6.1e6]),
        density_axis=np.array([1e-13, 1e-11]),
    )
    common = dict(duration=3600.0, output_step=600.0, force_models=_DRAG_ONLY)
    fixed = propagate_numerical(
        initial,
        spacecraft=SpacecraftConfig(
            mass_kg=200.0,
            geometry=SpacecraftGeometry.sphere(area_m2=5.0, drag_coefficient=2.2),
        ),
        **common,
    )
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        variable = propagate_numerical(
            initial,
            spacecraft=SpacecraftConfig(
                mass_kg=200.0,
                geometry=SpacecraftGeometry.sphere(area_m2=5.0, drag_coefficient=table),
            ),
            **common,
        )
    # The clamp triggers on every substep of the integration loop, but the table must
    # emit the edge warning *exactly once* per boundary (features.md §1.1; addendum §6)
    # — assert the count, not merely "at least one". The toy table's radii sit below the
    # orbit, so every lookup clamps to the high (upper-altitude) edge → the soft note.
    regime_warnings = [
        w for w in caught if "above the drag-table grid" in str(w.message)
    ]
    assert len(regime_warnings) == 1
    diff = np.linalg.norm(fixed.positions - variable.positions, axis=1)
    assert np.max(diff) > 1e-3  # clamped Cd 3.0 != fixed 2.2 -> visibly different


# --- chunk 9: box geometry + attitude wiring --------------------------------

# A non-cube box so attitude visibly changes the ram cross-section, plus a force
# config with drag + SRP (the only forces a box's attitude affects) at a low gravity
# degree to keep the box runs fast.
_BOX = SpacecraftConfig(
    mass_kg=200.0,
    geometry=SpacecraftGeometry.box_and_panels(
        x_length_m=2.0, y_length_m=1.0, z_length_m=1.5, solar_array_area_m2=4.0
    ),
)
_BOX_FORCES = ForceModelConfig(
    gravity_degree=8,
    gravity_order=8,
    sun_third_body=False,
    moon_third_body=False,
    drag=True,
    srp=True,
)


def _identity_law(state: State) -> Orientation:  # noqa: ARG001 - law ignores the state
    return Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)


def test_box_attitude_changes_drag_cross_section():
    """A non-cube box drags differently under InPlaneTracking vs LofAligned.

    InPlaneTracking holds body +Y (whose ram face spans x*z) on velocity; LofAligned
    (TNW) holds body +X (ram face y*z) on velocity. For a 2x1x1.5 box those ram areas
    differ (3.0 vs 1.5 m^2), so the drag — and thus the trajectory — must visibly
    diverge. The only difference between the two runs is the attitude provider, so the
    separation is purely the attitude-driven cross-section (no numerical noise floor).
    """
    initial = _state_from_elements(a_m=6778e3)  # ~400 km, draggy
    common = dict(
        duration=3600.0, output_step=600.0, force_models=_DRAG_ONLY, spacecraft=_BOX
    )
    in_plane = propagate_numerical(initial, attitude=InPlaneTracking(), **common)
    lof = propagate_numerical(initial, attitude=LofAligned(), **common)
    diff = np.linalg.norm(in_plane.positions - lof.positions, axis=1)
    assert np.max(diff) > 1e-2  # cm-plus: a real, attitude-driven drag difference


_ATTITUDE_MODES = [
    LofAligned(),
    LofOffset(roll_deg=30.0),
    Inertial(),
    SunPointing(phasing_reference="orbit_normal"),
    NadirPointing(),  # "inertial"
    InPlaneTracking(),
    CustomAttitude(_identity_law),
]


@pytest.mark.parametrize("attitude", _ATTITUDE_MODES, ids=lambda a: type(a).__name__)
def test_box_each_attitude_mode_runs(attitude):
    """Every attitude mode drives a box drag+SRP propagation to a Trajectory."""
    traj = propagate_numerical(
        _leo_state(),
        1200.0,
        output_step=600.0,
        force_models=_BOX_FORCES,
        spacecraft=_BOX,
        attitude=attitude,
    )
    assert isinstance(traj, Trajectory)
    assert traj.frame is Frame.EME2000
    assert len(traj) == 3


def test_custom_attitude_completes_real_propagation():
    """Guard the interface-default-method overrides in
    ``attitude._build_law_backed_provider`` (``getEventDetectors`` /
    ``getAttitudeRotation``).

    Those defaults are queried only by ``NumericalPropagator.propagate()``, never by a
    direct ``getAttitude()`` call — so a real propagation is the only faithful
    regression test. JPype cannot dispatch an inherited interface *default* method on a
    Python proxy, and the ``test_attitude_providers`` direct-``getAttitude`` cases were
    blind to this bug (it surfaces as "no such method ... invokeSpecial" inside
    ``propagate()``). This is the dedicated, refactor-proof guard for that fix — the
    ``_ATTITUDE_MODES`` parametrization above also covers ``CustomAttitude``, but as one
    incidental entry in a list that could be trimmed. The recording law additionally
    proves the provider is driven inside the integration loop, not silently ignored.
    """
    calls = {"n": 0}

    def recording_law(state: State) -> Orientation:  # noqa: ARG001 - law ignores state
        calls["n"] += 1
        return Orientation.from_quaternion(1.0, 0.0, 0.0, 0.0)

    traj = propagate_numerical(
        _leo_state(),
        1200.0,
        output_step=600.0,
        force_models=_BOX_FORCES,
        spacecraft=_BOX,
        attitude=CustomAttitude(recording_law),
    )
    # Completing propagate() proves getEventDetectors/getAttitudeRotation dispatched
    # cleanly (a missing override raises inside Orekit); calls > 0 proves getAttitude
    # dispatched and the law actually drove the integration loop.
    assert isinstance(traj, Trajectory)
    assert calls["n"] > 0


@pytest.mark.parametrize(
    "attitude, expected",
    [
        (LofAligned(), "lof_aligned:TNW"),
        (LofOffset(roll_deg=30.0), "lof_offset:TNW;roll=30.0,pitch=0.0,yaw=0.0"),
        (Inertial(), "inertial:EME2000;roll=0.0,pitch=0.0,yaw=0.0"),
        (InPlaneTracking(), "in_plane_tracking:vel=inertial"),
        (InPlaneTracking(velocity_reference="ecef"), "in_plane_tracking:vel=ecef"),
        (NadirPointing(), "nadir_pointing:vel=inertial"),
        (NadirPointing(velocity_reference="ecef"), "nadir_pointing:vel=ecef"),
        (SunPointing(), "sun_pointing:point=(0,0,1),phase=(1,0,0):orbit_normal"),
    ],
)
def test_box_attitude_metadata_byte_exact(attitude, expected):
    """The ``attitude`` metadata string is byte-exact per mode (features.md §1.1)."""
    traj = propagate_numerical(
        _leo_state(),
        1200.0,
        output_step=600.0,
        force_models=_BOX_FORCES,
        spacecraft=_BOX,
        attitude=attitude,
    )
    assert traj.metadata["attitude"] == expected


def test_box_attitude_metadata_gated_on_surface_force():
    """``attitude`` is recorded for a box only when drag or SRP is wired.

    Mirrors the ``spacecraft``-key gate: a gravity-only box leaves the attitude
    dynamically inert, so the key is omitted even though geometry is a box.
    """
    gravity_only = ForceModelConfig(
        gravity_degree=4,
        gravity_order=4,
        sun_third_body=False,
        moon_third_body=False,
        drag=False,
        srp=False,
    )
    traj = propagate_numerical(
        _leo_state(),
        600.0,
        output_step=600.0,
        force_models=gravity_only,
        spacecraft=_BOX,
        attitude=InPlaneTracking(),
    )
    assert "attitude" not in traj.metadata
    assert "spacecraft" not in traj.metadata  # no surface force consumes it either


def test_sphere_non_default_attitude_warns_once_and_omits_key():
    """A non-default attitude on a sphere warns exactly once and is ignored.

    A sphere's cross-section is orientation-invariant, so the attitude has no effect:
    the propagator emits one consistency warning, still returns a Trajectory, and omits
    the ``attitude`` metadata key (features.md §1.1).
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        traj = propagate_numerical(
            _keplerian_state(),
            600.0,
            output_step=600.0,
            force_models=ForceModelConfig.keplerian(),
            attitude=InPlaneTracking(),
        )
    att_warnings = [w for w in caught if "orientation-independent" in str(w.message)]
    assert len(att_warnings) == 1
    # The warning must surface at the caller (this test), not propygator internals —
    # pins the stacklevel in _resolve_attitude (warn -> _resolve_attitude ->
    # propagate_numerical -> here). stacklevel=2 would report numerical.py instead.
    assert att_warnings[0].filename == __file__
    assert isinstance(traj, Trajectory)
    assert "attitude" not in traj.metadata


@pytest.mark.parametrize(
    "attitude",
    [
        NadirPointing(velocity_reference="ecef"),
        InPlaneTracking(velocity_reference="ecef"),
    ],
    ids=lambda a: type(a).__name__,
)
def test_sphere_ecef_attitude_warns_and_falls_back(attitude):
    """An ``ecef`` attitude on a sphere is ignored like any non-default mode.

    The ecef path lowers to a custom ``TargetProvider``, but a sphere's cross-section
    is orientation-invariant, so ``_resolve_attitude`` warns once and falls back to
    ``LofAligned`` *before* lowering — the ecef provider never participates.
    Confirms the sphere short-circuit (features.md §1.1) is untouched for both ecef
    consumers (``NadirPointing`` secondary-slot, ``InPlaneTracking`` primary-slot).
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        traj = propagate_numerical(
            _keplerian_state(),
            600.0,
            output_step=600.0,
            force_models=ForceModelConfig.keplerian(),
            attitude=attitude,
        )
    att_warnings = [w for w in caught if "orientation-independent" in str(w.message)]
    assert len(att_warnings) == 1
    assert isinstance(traj, Trajectory)
    assert "attitude" not in traj.metadata


def test_box_in_plane_tracking_ecef_propagates_end_to_end():
    """A box under ``InPlaneTracking(velocity_reference="ecef")`` completes a real
    ``propagate()`` — the contract's de-risk item (general-upgrades-1.md "ECEF
    InPlaneTracking" -> Provider lowering): the custom ECEF ``TargetProvider`` had
    only ever run in ``AlignedAndConstrained``'s *secondary* slot (NadirPointing),
    and the ``@JImplements`` default-method traps surface only inside the real call
    path. A full orbit with drag + SRP wired proves the primary-slot dispatch and
    records the new metadata token.
    """
    traj = propagate_numerical(
        _leo_state(),
        5550.0,  # ~1 orbit
        output_step=600.0,
        force_models=_BOX_FORCES,
        spacecraft=_BOX,
        attitude=InPlaneTracking(velocity_reference="ecef"),
    )
    assert isinstance(traj, Trajectory)
    assert traj.metadata["attitude"] == "in_plane_tracking:vel=ecef"
    assert "terminated" not in traj.metadata


def test_in_plane_tracking_ecef_near_geostationary_completes():
    """The degenerate near-ground-stationary domain does NOT raise (verified at
    build, 2026-07-04): the primary wind target ``v_rel = v − ω⊕×r`` is singular
    only at *exactly* zero (Hipparchus ``normalize()`` throws on exact zero), which
    floating point never reaches — the EME2000-equator vs true-spin-axis offset
    alone keeps |v_rel| at ~15 m/s for an EME2000-equatorial GEO orbit. The run
    completes carrying a physically meaningless attitude; LEO is the validated
    domain (the failure-mode docs describe the exact-zero singularity, not a
    guaranteed error — this pins that reading against future Orekit changes).
    """
    mu = 3.986004418e14
    omega = 7.292115e-5
    a_geo = (mu / omega**2) ** (1.0 / 3.0)
    traj = propagate_numerical(
        _state_from_elements(a_m=a_geo, e=0.0, i_deg=0.0),
        1200.0,
        output_step=600.0,
        force_models=ForceModelConfig.keplerian(),
        spacecraft=_BOX,
        attitude=InPlaneTracking(velocity_reference="ecef"),
    )
    assert isinstance(traj, Trajectory)
    assert "terminated" not in traj.metadata


def test_box_face_cd_constant_matches_total_area_sphere():
    """A constant per-face ``BoxFaceCd`` == an ``IsotropicDrag`` of total surface area.

    With ``Cd = K`` on every face the assembled ``CdA = Σ K·A_i = K · 2(xy+yz+zx)`` is
    the box's total surface area times ``K``, independent of attitude — so the per-face
    drag must equal a sphere drag with that area and Cd. Pins the full-area six-face
    summation and the sphere-style ``½`` formula exactly (general-upgrades-1 "Tier B
    Drag", Runtime).
    """
    from propygator.propagation.numerical import _build_drag_force

    state, atmosphere = _drag_eval_setup()
    x, y, z, k = 2.0, 1.0, 1.5, 2.3
    surface = 2.0 * (x * y + y * z + z * x)
    box_geom = SpacecraftGeometry.box_and_panels(
        x_length_m=x,
        y_length_m=y,
        z_length_m=z,
        drag_coefficient=BoxFaceCd.from_callable(lambda r, d, th: k),
    )
    sphere_geom = SpacecraftGeometry.sphere(area_m2=surface, drag_coefficient=k)
    box_force = _build_drag_force(box_geom, atmosphere, None)
    sphere_force = _build_drag_force(sphere_geom, atmosphere, None)
    a_box = box_force.acceleration(state, box_force.getParameters())
    a_sphere = sphere_force.acceleration(state, sphere_force.getParameters())
    # Same ρ, relVel, mass; only the effective CdA can differ, and it is K·surface in
    # both — so the two accelerations are bit-for-bit the same formula.
    assert a_box.subtract(a_sphere).getNorm() < 1e-15


def test_box_face_cd_windward_projection_matches_orekit_box():
    """A windward-projection ``BoxFaceCd`` reproduces Orekit's native box drag exactly.

    With per-face ``Cd = K·max(0, cos θ)`` — the windward projected-area convention —
    the per-face sum ``CdA = Σ K·max(0,cos θ_i)·A_i`` equals Orekit's own
    ``BoxAndSolarArraySpacecraft`` drag at uniform ``Cd = K``. Agreement to machine
    precision confirms the inertial→body rotation sense (``applyTo``, not
    ``applyInverseTo`` which is ~9 % off), the ``θ = arccos(n·flow)`` round-trip, and
    the ±X/±Y/±Z face normals + areas (general-upgrades-1 "Tier B Drag", Convention).
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.forces import BoxAndSolarArraySpacecraft
    from org.orekit.forces.drag import DragForce

    from propygator.core.bodies import _sun
    from propygator.propagation.numerical import _build_drag_force

    state, atmosphere = _drag_eval_setup()
    x, y, z, k = 2.0, 1.0, 1.5, 2.4
    box_geom = SpacecraftGeometry.box_and_panels(
        x_length_m=x,
        y_length_m=y,
        z_length_m=z,
        drag_coefficient=BoxFaceCd.from_callable(
            lambda r, d, th: k * max(0.0, float(np.cos(th)))
        ),
    )
    per_face = _build_drag_force(box_geom, atmosphere, None)
    # Orekit native box at uniform Cd = K (windward projected area, zero lift ratio).
    native_box = BoxAndSolarArraySpacecraft(
        x, y, z, _sun(), 0.0, Vector3D(0.0, 1.0, 0.0), k, 0.0, 0.3, 0.6
    )
    native = DragForce(atmosphere, native_box)
    a_face = per_face.acceleration(state, per_face.getParameters())
    a_native = native.acceleration(state, native.getParameters())
    # Independent summation orders, so compare relative to the drag magnitude (~1e-11
    # m/s²): the reconstructions agree to ~machine precision, far inside 1e-9 relative.
    assert a_face.subtract(a_native).getNorm() < 1e-9 * a_native.getNorm()


def test_box_face_cd_sums_leeward_faces():
    """All six faces contribute: a leeward-dropping windward-only sum is strictly less.

    A constant per-face Cd over all six faces gives ``CdA = K·(total surface area)``; a
    windward-only variant (Cd → 0 past θ = π/2) drops the faces the flow does not
    directly strike. For a cube at a generic attitude exactly three faces are windward,
    so the all-faces drag is ~2× the windward-only drag — proving the leeward shear tail
    the per-face table carries is summed, not dropped (general-upgrades-1 "Tier B Drag",
    Why all faces; the real default table's face-on bus gap is the documented ~5–11 %).
    """
    from propygator.propagation.numerical import _build_drag_force

    state, atmosphere = _drag_eval_setup()
    edge = 1.0  # a cube: 3 windward + 3 leeward faces at a generic attitude
    all_faces = SpacecraftGeometry.box_and_panels(
        x_length_m=edge,
        y_length_m=edge,
        z_length_m=edge,
        drag_coefficient=BoxFaceCd.from_callable(lambda r, d, th: 0.07),
    )
    windward_only = SpacecraftGeometry.box_and_panels(
        x_length_m=edge,
        y_length_m=edge,
        z_length_m=edge,
        drag_coefficient=BoxFaceCd.from_callable(
            lambda r, d, th: 0.07 if th < np.pi / 2 else 0.0
        ),
    )
    a_all = _build_drag_force(all_faces, atmosphere, None)
    a_wind = _build_drag_force(windward_only, atmosphere, None)
    n_all = a_all.acceleration(state, a_all.getParameters()).getNorm()
    n_wind = a_wind.acceleration(state, a_wind.getParameters()).getNorm()
    assert n_wind > 0.0
    assert n_all / n_wind > 1.5  # leeward faces add real drag (cube: ~2×)


def test_box_face_cd_radius_edge_warn_once():
    """A ``BoxFaceCd`` whose radius span misses the orbit clamps + warns once per edge.

    Mirrors the ``VariableCd`` edge-warning contract: the clamp fires every integration
    substep, but each boundary's edge-tailored message is emitted exactly once per run.
    The orbit (r ~ 6878 km) sits above a low table span (soft "above" note) and below a
    high table span (loud "below" note); θ spans the full [0, π] so it never clamps.
    """
    initial = _leo_state()  # r ~ 6878 km

    def _box(radius_axis: np.ndarray) -> SpacecraftConfig:
        return SpacecraftConfig(
            mass_kg=200.0,
            geometry=SpacecraftGeometry.box_and_panels(
                x_length_m=1.0,
                y_length_m=1.0,
                z_length_m=1.0,
                drag_coefficient=BoxFaceCd.from_table(
                    np.full((2, 2, 2), 2.5),
                    radius_axis=radius_axis,
                    density_axis=np.array([1e-13, 1e-11]),
                    incidence_axis=np.array([0.0, np.pi]),
                ),
            ),
        )

    common = dict(duration=1800.0, output_step=600.0, force_models=_DRAG_ONLY)
    # Table entirely below the orbit -> every lookup clamps to the HIGH edge (soft).
    with warnings.catch_warnings(record=True) as caught_high:
        warnings.simplefilter("always")
        propagate_numerical(
            initial, spacecraft=_box(np.array([6.0e6, 6.1e6])), **common
        )
    high = [w for w in caught_high if "above the drag-table grid" in str(w.message)]
    assert len(high) == 1
    # Table entirely above the orbit -> every lookup clamps to the LOW edge (loud note).
    with warnings.catch_warnings(record=True) as caught_low:
        warnings.simplefilter("always")
        propagate_numerical(
            initial, spacecraft=_box(np.array([7.0e6, 7.1e6])), **common
        )
    low = [w for w in caught_low if "below the drag-table grid" in str(w.message)]
    assert len(low) == 1


def test_box_face_cd_default_box_propagates():
    """A convex box with ``BoxFaceCd.default()`` propagates under drag end-to-end.

    The headline Tier B path: ``solar_array_area_m2 = 0`` (a convex bus), the shipped
    per-face table drives drag, and the metadata records ``Cd=table:box_face_default``.
    """
    traj = propagate_numerical(
        _leo_state(),
        1200.0,
        output_step=600.0,
        force_models=_BOX_FORCES,
        spacecraft=SpacecraftConfig(
            mass_kg=300.0,
            geometry=SpacecraftGeometry.box_and_panels(
                x_length_m=1.0,
                y_length_m=1.0,
                z_length_m=1.0,
                solar_array_area_m2=0.0,
                drag_coefficient=BoxFaceCd.default(),
            ),
        ),
        attitude=InPlaneTracking(),
    )
    assert isinstance(traj, Trajectory)
    assert traj.frame is Frame.EME2000
    assert "Cd=table:box_face_default" in traj.metadata["spacecraft"]


def test_box_variable_cd_matches_fixed_drag():
    """A constant box ``VariableCd`` and a fixed box Cd give the same trajectory.

    Since chunk 9 both route through the *same* custom box ``DragSensitive`` (base Cd
    1.0 + the scalar Cd as the box's global drag factor), so this is an end-to-end
    consistency check of the two ``cd_lookup`` paths — **not** a stock-box comparison.
    The independent pin against a stock box built with the native Cd now lives in
    ``test_box_drag_matches_stock_box_with_native_cd`` (acceleration level).
    """
    initial = _state_from_elements(a_m=6778e3)
    common = dict(duration=3600.0, output_step=600.0, force_models=_DRAG_ONLY)
    fixed = propagate_numerical(
        initial,
        spacecraft=SpacecraftConfig(
            mass_kg=200.0,
            geometry=SpacecraftGeometry.box_and_panels(
                x_length_m=2.0, y_length_m=1.0, z_length_m=1.5, drag_coefficient=2.2
            ),
        ),
        attitude=InPlaneTracking(),
        **common,
    )
    variable = propagate_numerical(
        initial,
        spacecraft=SpacecraftConfig(
            mass_kg=200.0,
            geometry=SpacecraftGeometry.box_and_panels(
                x_length_m=2.0,
                y_length_m=1.0,
                z_length_m=1.5,
                drag_coefficient=VariableCd.from_callable(lambda r, d: 2.2),
            ),
        ),
        attitude=InPlaneTracking(),
        **common,
    )
    diff = np.linalg.norm(fixed.positions - variable.positions, axis=1)
    assert np.max(diff) < 1e-3  # sub-mm: identical box drag physics


def test_box_drag_matches_stock_box_with_native_cd():
    """Custom box drag (base dragCoeff 1.0 + Cd as global factor) == a native-Cd box.

    Chunk 9 makes every box build at base dragCoeff 1.0 and apply the scalar Cd through
    the custom ``DragSensitive``, replacing the pre-chunk-9 fixed-Cd path that fed the
    Cd to the box constructor and used a stock ``DragForce``. This pins the "drag is
    exactly linear in the global drag factor" premise against a stock box carrying the
    native Cd — identical geometry fields, shared atmosphere + state, so only the Cd
    routing differs.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.forces import BoxAndSolarArraySpacecraft
    from org.orekit.forces.drag import DragForce

    from propygator.core.bodies import _sun
    from propygator.propagation.numerical import (
        _build_box_spacecraft,
        _build_drag_force,
    )

    cd = 2.2
    state, atmosphere = _drag_eval_setup()
    geom = SpacecraftGeometry.box_and_panels(
        x_length_m=2.0, y_length_m=1.0, z_length_m=1.5, drag_coefficient=cd
    )
    box_custom = _build_box_spacecraft(geom, _sun())  # base dragCoeff 1.0
    custom = _build_drag_force(geom, atmosphere, box_custom)
    # Stock reference: same geometry fields, native dragCoeff = cd (pre-chunk-9 path).
    box_stock = BoxAndSolarArraySpacecraft(
        geom.x_length_m,
        geom.y_length_m,
        geom.z_length_m,
        _sun(),
        geom.solar_array_area_m2,
        Vector3D(*geom.solar_array_axis),
        cd,
        0.0,
        geom.absorption_coefficient,
        geom.specular_reflection_coefficient,
    )
    stock = DragForce(atmosphere, box_stock)
    a_custom = custom.acceleration(state, custom.getParameters())
    a_stock = stock.acceleration(state, stock.getParameters())
    assert a_custom.subtract(a_stock).getNorm() < 1e-15  # machine-level identical


def test_features_box_bus_example_runs():
    """features.md "box bus, in-plane tracking" example (reduced to ~2 orbits).

    The verbatim 1-day run is exercised end-to-end in chunk 12; here the same
    geometry + ``VariableCd.sphere_default`` + ``InPlaneTracking`` config is run over
    ~2 LEO orbits to prove every box drag/SRP + attitude path wires correctly.
    """
    traj = propagate_numerical(
        _leo_state(),
        duration=2 * 5550.0,  # ~2 orbits, not the literal 86400 s
        output_step=60.0,
        spacecraft=SpacecraftConfig(
            mass_kg=420,
            geometry=SpacecraftGeometry.box_and_panels(
                x_length_m=2.0,
                y_length_m=1.0,
                z_length_m=1.0,
                solar_array_area_m2=10.0,
                drag_coefficient=VariableCd.sphere_default(),
            ),
        ),
        attitude=InPlaneTracking(),
    )
    assert isinstance(traj, Trajectory)
    assert traj.frame is Frame.EME2000
    assert traj.metadata["attitude"] == "in_plane_tracking:vel=inertial"
    assert "Cd=table:sphere_default" in traj.metadata["spacecraft"]


def test_features_solar_sail_example_runs():
    """features.md "solar sail rolled 30 deg" example (reduced to ~2 orbits).

    Same thin specular box + ``LofOffset(roll_deg=30)`` config as the docs (the
    verbatim 7-day run lands in chunk 12); proves the box SRP + offset attitude path.
    """
    sail = SpacecraftConfig(
        mass_kg=50,
        geometry=SpacecraftGeometry.box_and_panels(
            x_length_m=10.0,
            y_length_m=10.0,
            z_length_m=0.001,
            solar_array_area_m2=0.0,
            specular_reflection_coefficient=0.85,
            absorption_coefficient=0.10,
        ),
    )
    traj = propagate_numerical(
        _leo_state(),
        duration=2 * 5550.0,  # ~2 orbits, not the literal 604800 s
        output_step=60.0,
        spacecraft=sail,
        attitude=LofOffset(roll_deg=30.0),
    )
    assert isinstance(traj, Trajectory)
    assert traj.metadata["attitude"] == "lof_offset:TNW;roll=30.0,pitch=0.0,yaw=0.0"
