"""``propagate_numerical`` — the numerical orbit propagator (Feature 1.1).

The full propagator (build-plan chunks 7-9): integrator selection + tolerances, the
gravity force, the full perturbation set (Sun/Moon third body, drag with a fixed or
:class:`VariableCd` coefficient, conical-shadow SRP, solid/ocean tides, relativity)
acting on either the **sphere** or the **box** (``BoxAndSolarArraySpacecraft``)
geometry, the full seven-mode attitude family, output-step ephemeris sampling, the
``Trajectory`` + metadata assembly, input validation, and ``PropagationError``.

**Geometry + attitude (chunk 9).** A ``box_and_panels`` geometry builds one
``BoxAndSolarArraySpacecraft`` driving both drag and SRP; a box :class:`VariableCd`
is routed through a custom ``DragSensitive`` that delegates the attitude-driven
projected-area computation to the box and overrides only the scalar Cd (via the
box's "global drag factor"). The :data:`AttitudeConfig` is lowered to a native
Orekit provider (:func:`~propygator.propagation.attitude._to_provider`). A sphere is
orientation-independent, so a non-default attitude on a sphere triggers a one-time
consistency warning and falls back to ``LofAligned`` (features.md §1.1). An
``IncidenceVariableCd`` (Tier B) on a box raises ``NotImplementedError`` when drag is
wired.

**Force scope.** Each ``ForceModelConfig`` toggle maps to its Orekit force model
and is wired only when enabled. The ``force_models`` metadata is driven by *what
was actually wired* (:class:`_WiredForces`), never by the config booleans, so the
recorded metadata never claims a force that is not acting (features.md §1.1) — the
``keplerian`` preset records just the point-mass gravity token. The ``spacecraft``
metadata key is emitted only when a surface force that consumes it (drag or SRP)
was wired, and the ``attitude`` key only when geometry is a box *and* a surface
force was wired — the same "reflect what's acting" rule (so ``keplerian`` omits
both, and a sphere never records ``attitude``).

**Architecture invariants** (CLAUDE.md / architecture §10): no Orekit type appears
on the public signature (``initial`` and the return ``Trajectory`` are propygator
types); ``jpype`` / ``org.orekit.*`` are imported lazily *inside* functions behind
``_ensure_started()``; SI units throughout; the input frame must be inertial
(EME2000) and the output ``Trajectory`` is EME2000 (no auto-conversion).
"""

from __future__ import annotations

import logging
import math
import time
import warnings
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np

from .._orekit_init import _ensure_started, _orekit_version
from ..core.frames import Frame
from ..core.states import Trajectory, _propygator_version
from .attitude import LofAligned, _serialize_attitude, _to_provider
from .force_models import ForceModelConfig, _serialize_force_models
from .integrators import IntegratorConfig
from .spacecraft import (
    IncidenceVariableCd,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    # Type-only; the org.* namespaces are runtime JPype stubs (mypy treats them as
    # untyped via ignore_missing_imports).
    import org.hipparchus.ode  # noqa: F401
    import org.orekit.forces  # noqa: F401
    import org.orekit.forces.drag  # noqa: F401
    import org.orekit.models.earth.atmosphere  # noqa: F401
    import org.orekit.propagation.numerical  # noqa: F401
    import org.orekit.time  # noqa: F401
    from org.orekit.forces.gravity.potential import (  # noqa: F401
        NormalizedSphericalHarmonicsProvider,
    )

    from ..core.states import State, TrajectoryMetadata
    from .attitude import AttitudeConfig

logger = logging.getLogger(__name__)

# Known integrator type names (features.md §1.1). The type-name check is
# pure-Python and runs at the top of propagate_numerical; the actual integrator
# object is built later, once the orbit exists (tolerances need it).
_KNOWN_INTEGRATOR_TYPES = ("ClassicalRK4", "DOP853", "DormandPrince54")

# Gravity-field names that resolve against the shipped orekit-data. v1 ships only
# EIGEN-6S (``Potential/eigen-6s.gfc``), which is also Orekit's default field, so
# the default ``getNormalizedProvider`` loads it without registering a scoped
# reader. Additional fields (e.g. EGM2008) need their coefficient file added to
# orekit-data and a scoped reader; deferred until a second field ships.
_KNOWN_GRAVITY_FIELDS = ("EIGEN-6S",)

# Atmosphere-model names accepted for drag (features.md §1.1). Harris-Priester needs
# only Sun + Earth; NRLMSISE-00 and DTM-2000 additionally read CSSI space-weather
# data shipped in orekit-data. The name is checked pure-Python at the top of
# propagate_numerical (gated on drag being enabled); the model is built later in the
# JVM section, where a data-load failure is surfaced as a ValueError.
_KNOWN_ATMOSPHERE_MODELS = ("NRLMSISE-00", "Harris-Priester", "DTM-2000")

# Ocean-tide field truncation. Ocean tides are off in every preset and a rarely-used
# toggle; a conservative 4x4 (well within the shipped fes2004 model) keeps the
# perturbation cheap and deterministic. Solid tides take no degree/order. Bump only
# if a use case needs finer ocean-tide structure.
_OCEAN_TIDE_DEGREE = 4
_OCEAN_TIDE_ORDER = 4

# Sample-count round-off tolerance (features.md §1.1): absorbs float error so a
# duration that is an exact multiple of output_step yields the deterministic count.
_SAMPLE_COUNT_TOL = 1e-9

# Upper bound on the output-sample count. With no cap, a tiny output_step against a
# long duration (e.g. 1 ms over a year -> ~3e10 samples) would pre-allocate multi-GB
# position/velocity arrays plus that many per-sample ephemeris queries and exhaust
# memory before any useful work. 1e7 covers ~19 years at a 60 s step; beyond it,
# raise and tell the caller to coarsen output_step.
_MAX_OUTPUT_SAMPLES = 10_000_000


def _sample_count(duration: float, output_step: float) -> int:
    """Number of output samples: ``floor(duration/output_step + tol) + 1``.

    First sample at ``initial.epoch``, last at ``initial.epoch + (n-1)*output_step``
    (features.md §1.1). The small relative ``tol`` makes divisible cases
    deterministic. ``output_step <= duration`` (validated upstream) guarantees
    ``n >= 2``.
    """
    return int(math.floor(duration / output_step + _SAMPLE_COUNT_TOL)) + 1


def _validate_inputs(
    initial: State,
    duration: float,
    output_step: float,
    integrator: IntegratorConfig,
    force_models: ForceModelConfig,
) -> None:
    """Validate everything checkable before integration (features.md §1.1).

    Pure-Python (no JVM): the inertial-frame rule, the positive/ordered duration
    and output step, the integrator type name (+ the ``ClassicalRK4`` fixed-step
    coupling), and the gravity-field name. Each raises ``ValueError`` with an
    actionable message; the ``State`` itself already guarantees finite p/v
    (architecture §6).
    """
    # Inertial-frame rule: Newtonian integration is only well-posed in an inertial
    # frame, and EME2000 (alias J2000) is the only inertial frame in the v1 set.
    if initial.frame is not Frame.EME2000:
        raise ValueError(
            f"propagate_numerical requires an inertial initial frame (EME2000 / "
            f"J2000), got {initial.frame.name}; convert first with "
            "initial.to_frame(Frame.EME2000). The output Trajectory is EME2000."
        )
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError(f"duration must be finite and > 0 seconds, got {duration!r}")
    if not math.isfinite(output_step) or output_step <= 0.0:
        raise ValueError(
            f"output_step must be finite and > 0 seconds, got {output_step!r}"
        )
    if output_step > duration:
        raise ValueError(
            f"output_step must be <= duration; got output_step={output_step!r} > "
            f"duration={duration!r}"
        )
    if integrator.type not in _KNOWN_INTEGRATOR_TYPES:
        raise ValueError(
            f"unknown integrator type {integrator.type!r}; known types: "
            f"{list(_KNOWN_INTEGRATOR_TYPES)}"
        )
    # Type-dependent coupling validated here (not at IntegratorConfig construction,
    # which stays type-agnostic): ClassicalRK4 is fixed-step and needs fixed_step_s.
    if integrator.type == "ClassicalRK4" and integrator.fixed_step_s is None:
        raise ValueError(
            "IntegratorConfig.type='ClassicalRK4' requires fixed_step_s (it is a "
            "fixed-step integrator); set IntegratorConfig(type='ClassicalRK4', "
            "fixed_step_s=...)."
        )
    if force_models.gravity_field not in _KNOWN_GRAVITY_FIELDS:
        raise ValueError(
            f"unknown gravity_field {force_models.gravity_field!r}; known fields: "
            f"{list(_KNOWN_GRAVITY_FIELDS)}. Additional fields require adding their "
            "coefficient file to orekit-data."
        )
    # atmosphere_model is only consumed when drag is enabled; validate the name only
    # then (a drag-off config carries the default name harmlessly). The actual model
    # build can still fail later on missing space-weather data -> ValueError there.
    if (
        force_models.drag
        and force_models.atmosphere_model not in _KNOWN_ATMOSPHERE_MODELS
    ):
        raise ValueError(
            f"unknown atmosphere_model {force_models.atmosphere_model!r}; known "
            f"models: {list(_KNOWN_ATMOSPHERE_MODELS)}"
        )
    # Guard against an accidental enormous sample count (tiny output_step over a long
    # duration) that would exhaust memory before any integration runs.
    n_samples = _sample_count(duration, output_step)
    if n_samples > _MAX_OUTPUT_SAMPLES:
        raise ValueError(
            f"duration/output_step requests {n_samples} output samples, exceeding the "
            f"{_MAX_OUTPUT_SAMPLES} cap; increase output_step or shorten duration "
            "(each sample allocates a position+velocity row and an ephemeris query, "
            "so a much larger count would exhaust memory)."
        )


def _resolve_gravity_provider(
    gravity_field: str, degree: int, order: int
) -> "NormalizedSphericalHarmonicsProvider":
    """Return the normalized spherical-harmonics provider for ``gravity_field``.

    The name is already validated against :data:`_KNOWN_GRAVITY_FIELDS` upstream.
    v1's only field (EIGEN-6S) is Orekit's default, so the default reader chain
    loads ``Potential/eigen-6s.gfc`` directly. A load failure (e.g. a Potential
    file missing from a misconfigured orekit-data) is surfaced as a ``ValueError``
    pointing at the data, not a raw Java trace — consistent with the
    "gravity_field doesn't resolve -> ValueError" contract (features.md §1.1).
    """
    import jpype
    from org.orekit.forces.gravity.potential import GravityFieldFactory

    try:
        return GravityFieldFactory.getNormalizedProvider(degree, order)
    except jpype.JException as exc:  # type: ignore[attr-defined]  # pragma: no cover
        # pragma: needs a broken orekit-data install to hit (the named field's file
        # absent); surfaced as ValueError per the gravity-resolution contract.
        raise ValueError(
            f"gravity_field {gravity_field!r} could not be loaded from orekit-data "
            f"(degree={degree}, order={order}): {exc.getMessage()}"
        ) from None


def _build_gravity_force(
    provider: "NormalizedSphericalHarmonicsProvider",
    degree: int,
    order: int,
) -> "org.orekit.forces.ForceModel":
    """Build the gravity ``ForceModel`` for ``provider`` at ``degree`` x ``order``.

    Point mass (``0 x 0``, the ``keplerian`` preset) maps to ``NewtonianAttraction``
    on the provider's central mu; any non-trivial field maps to
    ``HolmesFeatherstoneAttractionModel`` in Earth's body-fixed frame (ITRF).
    """
    if degree == 0 and order == 0:
        from org.orekit.forces.gravity import NewtonianAttraction

        return NewtonianAttraction(provider.getMu())
    from org.orekit.forces.gravity import HolmesFeatherstoneAttractionModel

    return HolmesFeatherstoneAttractionModel(Frame.ITRF.to_orekit(), provider)


@dataclass(frozen=True)
class _WiredForces:
    """Which perturbations were *actually added* to the propagator (chunk 8).

    Drives the ``force_models`` metadata and the conditional ``spacecraft`` key, so
    both reflect the real force model rather than the config booleans (features.md
    §1.1). Gravity is always wired and is not tracked here. In chunk 8 (sphere only)
    every enabled toggle maps one-to-one to a wired force, so these mirror the config;
    they are recorded as explicit facts to keep the metadata honest as later chunks
    add geometry-dependent wiring.
    """

    sun_third_body: bool
    moon_third_body: bool
    drag: bool
    srp: bool
    solid_tides: bool
    ocean_tides: bool
    relativity: bool


def _resolve_atmosphere(
    model: str,
    sun: "org.orekit.utils.ExtendedPositionProvider",
    earth: "org.orekit.bodies.OneAxisEllipsoid",
) -> "org.orekit.models.earth.atmosphere.Atmosphere":
    """Build the atmosphere model named ``model`` (already validated upstream).

    ``Harris-Priester`` needs only Sun + Earth; ``NRLMSISE-00`` / ``DTM-2000`` read
    CSSI space-weather data (``SpaceWeather-All-*.txt`` in orekit-data) via
    ``CssiSpaceWeatherData`` keyed on its default supported-names regex. A data-load
    failure surfaces as ``ValueError`` (no raw Java trace), consistent with the
    gravity / "doesn't resolve" contract (features.md §1.1).
    """
    import jpype

    try:
        if model == "Harris-Priester":
            from org.orekit.models.earth.atmosphere import HarrisPriester

            return HarrisPriester(sun, earth)
        from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

        cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
        if model == "NRLMSISE-00":
            from org.orekit.models.earth.atmosphere import NRLMSISE00

            return NRLMSISE00(cssi, sun, earth)
        from org.orekit.models.earth.atmosphere import DTM2000

        return DTM2000(cssi, sun, earth)
    except jpype.JException as exc:  # type: ignore[attr-defined]  # pragma: no cover
        # pragma: needs a broken/missing space-weather install to hit.
        raise ValueError(
            f"atmosphere_model {model!r} could not be built from orekit-data "
            f"(space-weather data missing or unreadable): {exc.getMessage()}"
        ) from None


def _build_variable_cd_drag_sensitive(
    variable_cd: VariableCd,
    accel: "Callable[..., object]",
) -> "org.orekit.forces.drag.DragSensitive":
    """A custom ``DragSensitive`` applying a :class:`VariableCd` scalar Cd (Tier A).

    Implements the ``DragSensitive`` interface from Python via ``@JImplements`` (Java
    classes can't be subclassed; CLAUDE.md) — **one** proxy serving both the sphere
    and box paths, which differ only in how the per-substep scalar Cd becomes an
    acceleration. ``accel(state, density, relative_velocity, cd)`` supplies that step:
    the **sphere** assembles the ``IsotropicDrag`` formula directly; the **box**
    delegates to ``BoxAndSolarArraySpacecraft.dragAcceleration`` (attitude-driven
    projected area) with the table value as the box's single "global drag factor".
    Keeping the interface boilerplate (drivers, attitude-rate flag, the radius +
    table-lookup preamble) in one place means a future Java default method JPype needs
    is added once, not twice.

    Only the double-precision ``dragAcceleration`` is implemented — the Field overload
    is never invoked by a double-precision ``NumericalPropagator``;
    ``getDragParametersDrivers`` returns no tunable parameters (the Cd comes from the
    table, not a driver). Geocentric radius is ``|position|`` in the propagation frame
    (no transform); calling ``variable_cd`` does the table lookup and the one-time
    out-of-grid clamp warning.
    """
    import jpype
    from java.util import ArrayList
    from org.orekit.forces.drag import DragSensitive

    @jpype.JImplements(DragSensitive)  # type: ignore[attr-defined]
    class _VariableCdDragSensitive:
        @jpype.JOverride  # type: ignore[attr-defined]
        def getDragParametersDrivers(self):  # noqa: ANN001, ANN202 - Java signature
            return ArrayList()  # no tunable parameters: Cd is table-driven

        @jpype.JOverride  # type: ignore[attr-defined]
        def dependsOnAttitudeRate(self):  # noqa: ANN001, ANN202
            return False

        @jpype.JOverride  # type: ignore[attr-defined]
        def dragAcceleration(self, state, density, relative_velocity, parameters):  # noqa: ANN001, ANN202
            cd = variable_cd(float(state.getPosition().getNorm()), float(density))
            return accel(state, density, relative_velocity, float(cd))

    # Implements DragSensitive only at the JPype runtime level (mypy can't see it).
    return _VariableCdDragSensitive()  # type: ignore[return-value]


def _build_box_spacecraft(
    geometry: SpacecraftGeometry,
    sun: "org.orekit.utils.ExtendedPositionProvider",
) -> "org.orekit.forces.BoxAndSolarArraySpacecraft":
    """Build the ``BoxAndSolarArraySpacecraft`` for a **box** ``geometry`` (chunk 9).

    One object drives **both** drag and SRP (it implements ``DragSensitive`` and
    ``RadiationSensitive``), so the caller builds it once and shares it. The 10-arg
    ctor is ``(x, y, z, sun, arrayArea, arrayAxis, dragCoeff, liftRatio, absorption,
    specular)``; lift ratio is ``0.0`` (v1 models no aerodynamic lift). The base drag
    coefficient is the fixed Cd for a plain float; for a Cd *table* (:class:`VariableCd`
    / :class:`IncidenceVariableCd`) it is ``1.0`` and the per-substep scalar Cd is
    applied as the box's single "global drag factor" by the custom box ``DragSensitive``
    (drag is exactly linear in that factor — verified). The array axis is already a
    validated unit vector. Box field invariants hold (validated at construction).
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.forces import BoxAndSolarArraySpacecraft

    cd = geometry.drag_coefficient
    base_cd = 1.0 if isinstance(cd, (VariableCd, IncidenceVariableCd)) else float(cd)
    assert geometry.x_length_m is not None
    assert geometry.y_length_m is not None
    assert geometry.z_length_m is not None
    assert geometry.solar_array_area_m2 is not None
    assert geometry.solar_array_axis is not None
    assert geometry.absorption_coefficient is not None
    assert geometry.specular_reflection_coefficient is not None
    return BoxAndSolarArraySpacecraft(
        float(geometry.x_length_m),
        float(geometry.y_length_m),
        float(geometry.z_length_m),
        sun,
        float(geometry.solar_array_area_m2),
        Vector3D(*geometry.solar_array_axis),
        base_cd,
        0.0,  # drag lift ratio — v1 models no aerodynamic lift
        float(geometry.absorption_coefficient),
        float(geometry.specular_reflection_coefficient),
    )


def _build_drag_force(
    geometry: SpacecraftGeometry,
    atmosphere: "org.orekit.models.earth.atmosphere.Atmosphere",
    box: "org.orekit.forces.BoxAndSolarArraySpacecraft | None",
) -> "org.orekit.forces.ForceModel":
    """Build the drag ``ForceModel`` (chunk 8 sphere; chunk 9 box).

    **Sphere:** a fixed Cd uses the stock ``IsotropicDrag(area, Cd)``; a
    :class:`VariableCd` uses :func:`_build_variable_cd_drag_sensitive` with the
    isotropic-acceleration strategy. **Box:** a fixed Cd uses ``box`` directly (it
    implements ``DragSensitive`` and was built with that Cd); a :class:`VariableCd`
    uses the same shared proxy with a strategy that delegates the projected-area
    bookkeeping to ``box``; an :class:`IncidenceVariableCd` (Tier B) raises
    ``NotImplementedError`` — its runtime lookup is deferred (architecture §13).
    ``box`` is the shared object also used by SRP (``None`` for a sphere).
    """
    import jpype
    from org.orekit.forces.drag import DragForce, IsotropicDrag

    cd = geometry.drag_coefficient
    if geometry.kind == "sphere":
        assert geometry.area_m2 is not None  # sphere always carries an area
        area = float(geometry.area_m2)
        if isinstance(cd, VariableCd):
            # IsotropicDrag formula with the table Cd. Orekit hands the relative
            # velocity as v_atmosphere - v_spacecraft, so the matching deceleration is
            # the +1/2 (Cd*A/m) rho |relVel| relVel form (features.md §1.1 sign note;
            # mass from the state, verified against IsotropicDrag to ~1e-21 m/s²).
            def _sphere_accel(state, density, relative_velocity, table_cd):  # noqa: ANN001, ANN202
                factor = (
                    0.5
                    * table_cd
                    * area
                    / state.getMass()
                    * density
                    * relative_velocity.getNorm()
                )
                return relative_velocity.scalarMultiply(float(factor))

            sensitive = _build_variable_cd_drag_sensitive(cd, _sphere_accel)
        else:
            sensitive = IsotropicDrag(area, float(cd))  # type: ignore[arg-type]
        return DragForce(atmosphere, sensitive)

    assert box is not None  # built by the caller whenever geometry is a box
    if isinstance(cd, IncidenceVariableCd):
        raise NotImplementedError(
            "IncidenceVariableCd (Tier B, incidence-keyed box drag) is a validated "
            "skeleton in v1: its runtime Cd lookup is deferred (architecture §13). Use "
            "a fixed Cd or a VariableCd on box_and_panels for now."
        )
    if isinstance(cd, VariableCd):
        # Delegate the attitude-driven projected-area bookkeeping to the box and
        # override only the scalar Cd: the box was built with base dragCoeff=1.0, so
        # forwarding the table value as its single "global drag factor" makes the
        # effective Cd equal the table value (drag is exactly linear in it).
        def _box_accel(state, density, relative_velocity, table_cd):  # noqa: ANN001, ANN202
            return box.dragAcceleration(
                state,
                density,
                relative_velocity,
                jpype.JArray(jpype.JDouble)([float(table_cd)]),
            )

        return DragForce(atmosphere, _build_variable_cd_drag_sensitive(cd, _box_accel))
    return DragForce(atmosphere, box)  # fixed Cd: box built with that Cd


def _build_srp_force(
    geometry: SpacecraftGeometry,
    sun: "org.orekit.utils.ExtendedPositionProvider",
    earth: "org.orekit.bodies.OneAxisEllipsoid",
    box: "org.orekit.forces.BoxAndSolarArraySpacecraft | None",
) -> "org.orekit.forces.ForceModel":
    """Build the SRP ``ForceModel`` (chunk 8 sphere; chunk 9 box).

    **Sphere:** the single ``Cr`` maps to ``IsotropicRadiationSingleCoefficient(area,
    Cr)`` — *not* ``IsotropicRadiationClassicalConvention`` (which takes absorption +
    specular and can't represent a single Cr); the doc naming was misleading, see the
    features.md §1.1 sphere note. **Box:** the shared ``box`` (absorption + specular
    optics) drives SRP directly (it implements ``RadiationSensitive``). The 3-arg
    ``SolarRadiationPressure`` uses the conical Earth shadow on the WGS84 ellipsoid.
    ``box`` is ``None`` for a sphere.
    """
    from org.orekit.forces.radiation import (
        IsotropicRadiationSingleCoefficient,
        SolarRadiationPressure,
    )

    if geometry.kind == "sphere":
        assert geometry.area_m2 is not None
        assert geometry.reflectivity_coefficient is not None
        radiation = IsotropicRadiationSingleCoefficient(
            float(geometry.area_m2), float(geometry.reflectivity_coefficient)
        )
        return SolarRadiationPressure(sun, earth, radiation)

    assert box is not None  # built by the caller whenever geometry is a box
    return SolarRadiationPressure(sun, earth, box)


def _ut1() -> "org.orekit.time.UT1Scale":
    """Orekit's EOP-backed UT1 scale (IERS 2010), for the tide models.

    This is Orekit's *internal* UT1 (resolved from the Earth-Orientation-Parameters
    in orekit-data) and is unrelated to propygator's deferred public UT1 ``TimeScale``
    in ``core/time.py`` — wiring tides through it does not violate that deferral.
    """
    from org.orekit.time import TimeScalesFactory
    from org.orekit.utils import IERSConventions

    return TimeScalesFactory.getUT1(IERSConventions.IERS_2010, False)


def _build_solid_tides(
    provider: "NormalizedSphericalHarmonicsProvider",
    sun: "org.orekit.bodies.CelestialBody",
    moon: "org.orekit.bodies.CelestialBody",
) -> "org.orekit.forces.ForceModel":
    """Build the solid-Earth-tide ``ForceModel`` (Sun + Moon tide-raising bodies).

    Reuses the gravity provider's ``ae`` / ``mu`` / tide system so the tide model is
    consistent with the field it perturbs, in Earth's body-fixed frame (ITRF) with
    IERS-2010 conventions and Orekit's EOP-backed UT1 (:func:`_ut1`).
    """
    import jpype
    from org.orekit.bodies import CelestialBody
    from org.orekit.forces.gravity import SolidTides
    from org.orekit.utils import IERSConventions

    bodies = jpype.JArray(CelestialBody)([sun, moon])  # type: ignore[attr-defined]
    return SolidTides(
        Frame.ITRF.to_orekit(),
        provider.getAe(),
        provider.getMu(),
        provider.getTideSystem(),
        IERSConventions.IERS_2010,
        _ut1(),
        bodies,
    )


def _build_ocean_tides(
    provider: "NormalizedSphericalHarmonicsProvider",
) -> "org.orekit.forces.ForceModel":
    """Build the ocean-tide ``ForceModel`` at the conservative 4x4 truncation.

    Reuses the gravity provider's ``ae`` / ``mu`` in ITRF with IERS-2010 conventions
    and Orekit's EOP-backed UT1 (:func:`_ut1`). See :data:`_OCEAN_TIDE_DEGREE`.
    """
    from org.orekit.forces.gravity import OceanTides
    from org.orekit.utils import IERSConventions

    return OceanTides(
        Frame.ITRF.to_orekit(),
        provider.getAe(),
        provider.getMu(),
        _OCEAN_TIDE_DEGREE,
        _OCEAN_TIDE_ORDER,
        IERSConventions.IERS_2010,
        _ut1(),
    )


def _add_perturbation_forces(
    propagator: "org.orekit.propagation.numerical.NumericalPropagator",
    force_models: ForceModelConfig,
    spacecraft: SpacecraftConfig,
    provider: "NormalizedSphericalHarmonicsProvider",
) -> _WiredForces:
    """Add the enabled perturbation forces to ``propagator`` (chunks 8-9).

    Gravity is already wired by the caller. Forces are added in the ``force_models``
    metadata-token order (third body, drag, SRP, tides, relativity) and the wired
    facts returned so the metadata reflects exactly what acts. Sun/Moon/Earth come
    from ``core/bodies.py`` (the canonical WGS84 ellipsoid + Orekit body singletons).
    A **box** geometry drives both drag and SRP from one shared
    ``BoxAndSolarArraySpacecraft``, built once here when a surface force will use it.
    """
    from org.orekit.forces.gravity import Relativity, ThirdBodyAttraction

    from ..core.bodies import _earth, _moon, _sun

    fm = force_models
    geometry = spacecraft.geometry
    # One box drives both drag and SRP; build it once when a surface force needs it.
    # A sphere uses no shared object (box stays None and each builder handles its own).
    box = (
        _build_box_spacecraft(geometry, _sun())
        if geometry.kind == "box" and (fm.drag or fm.srp)
        else None
    )

    if fm.sun_third_body:
        propagator.addForceModel(ThirdBodyAttraction(_sun()))
    if fm.moon_third_body:
        propagator.addForceModel(ThirdBodyAttraction(_moon()))
    if fm.drag:
        atmosphere = _resolve_atmosphere(fm.atmosphere_model, _sun(), _earth())
        propagator.addForceModel(_build_drag_force(geometry, atmosphere, box))
    if fm.srp:
        propagator.addForceModel(_build_srp_force(geometry, _sun(), _earth(), box))
    if fm.solid_tides:
        propagator.addForceModel(_build_solid_tides(provider, _sun(), _moon()))
    if fm.ocean_tides:
        propagator.addForceModel(_build_ocean_tides(provider))
    if fm.relativity:
        propagator.addForceModel(Relativity(float(provider.getMu())))

    return _WiredForces(
        sun_third_body=fm.sun_third_body,
        moon_third_body=fm.moon_third_body,
        drag=fm.drag,
        srp=fm.srp,
        solid_tides=fm.solid_tides,
        ocean_tides=fm.ocean_tides,
        relativity=fm.relativity,
    )


def _build_integrator(
    config: IntegratorConfig, orbit: "org.orekit.orbits.Orbit"
) -> "org.hipparchus.ode.ODEIntegrator":
    """Build the Hipparchus integrator for ``config`` against ``orbit``.

    The absolute tolerance vector comes from Orekit's ``OrbitType.CARTESIAN``
    tolerance computation seeded with ``abs_tolerance_m`` (meters of position); the
    relative tolerance vector is filled uniformly with ``rel_tolerance`` — so the
    ``[abs, rel]`` arrays are built from the config's two scalars (features.md
    §1.1). The type name is already validated upstream; ``ClassicalRK4`` (fixed
    step) ignores the adaptive tolerances and uses ``fixed_step_s``.
    """
    import jpype
    from org.orekit.orbits import OrbitType
    from org.orekit.propagation.numerical import NumericalPropagator

    if config.type == "ClassicalRK4":
        from org.hipparchus.ode.nonstiff import ClassicalRungeKuttaIntegrator

        # fixed_step_s presence is guaranteed by _validate_inputs.
        assert config.fixed_step_s is not None
        return ClassicalRungeKuttaIntegrator(float(config.fixed_step_s))

    tolerances = NumericalPropagator.tolerances(
        config.abs_tolerance_m, orbit, OrbitType.CARTESIAN
    )
    abs_tol = tolerances[0]
    rel_tol = jpype.JArray(jpype.JDouble)(  # type: ignore[attr-defined]
        [config.rel_tolerance] * len(tolerances[1])
    )

    if config.type == "DOP853":
        from org.hipparchus.ode.nonstiff import DormandPrince853Integrator

        return DormandPrince853Integrator(
            config.min_step_s, config.max_step_s, abs_tol, rel_tol
        )
    from org.hipparchus.ode.nonstiff import DormandPrince54Integrator

    return DormandPrince54Integrator(
        config.min_step_s, config.max_step_s, abs_tol, rel_tol
    )


def _resolve_attitude(
    attitude: "AttitudeConfig | None", geometry: SpacecraftGeometry
) -> "AttitudeConfig":
    """Resolve the attitude config actually wired into the propagator (chunk 9).

    ``None`` -> the default :class:`~propygator.propagation.attitude.LofAligned` (TNW).
    A sphere's cross-section is orientation-invariant, so a non-default attitude on a
    sphere has no dynamical effect: emit the one-time **attitude/geometry consistency
    warning** (features.md §1.1) and fall back to ``LofAligned``. A box keeps the
    supplied attitude — it shapes the drag/SRP cross-section over the orbit. Pure
    Python (no JVM); the returned config is lowered to an Orekit provider by the
    caller and recorded in metadata (for a box with a surface force).
    """
    config = attitude if attitude is not None else LofAligned()
    if geometry.kind == "sphere" and not isinstance(config, LofAligned):
        warnings.warn(
            "attitude has no effect on orientation-independent geometry; ignoring it "
            "and using the default LofAligned. Use box_and_panels geometry for the "
            "attitude to affect the drag/SRP cross-section.",
            # warn -> _resolve_attitude -> propagate_numerical -> user: stacklevel 3
            # surfaces the warning at the caller's propagate_numerical(...) line, not
            # this internal frame (_resolve_attitude has a single fixed-depth caller).
            stacklevel=3,
        )
        return LofAligned()
    return config


def propagate_numerical(
    initial: State,
    duration: float,
    *,
    output_step: float,
    force_models: ForceModelConfig | None = None,
    spacecraft: SpacecraftConfig | None = None,
    attitude: AttitudeConfig | None = None,
    integrator: IntegratorConfig | None = None,
    name: str | None = None,
) -> Trajectory:
    """Numerically propagate ``initial`` forward by ``duration`` seconds.

    Returns a :class:`~propygator.core.states.Trajectory` in ``Frame.EME2000``
    sampled every ``output_step`` seconds (``floor(duration/output_step) + 1``
    samples, first at ``initial.epoch``). ``initial.frame`` must be inertial
    (``EME2000`` / ``J2000``); a rotating frame raises ``ValueError``. Backward
    propagation is unsupported (``duration`` must be ``> 0``).

    **Force model.** Gravity is always wired (point-mass for the ``keplerian`` preset
    ``0 x 0``, a Holmes-Featherstone field otherwise); each enabled
    ``ForceModelConfig`` toggle adds its Orekit force — Sun/Moon third body, drag
    (fixed Cd via ``IsotropicDrag`` / the box, or a :class:`VariableCd` via a custom
    ``DragSensitive``), conical-shadow SRP, solid/ocean tides, relativity. The
    ``force_models`` metadata lists only the forces actually wired, and ``spacecraft``
    is recorded only when drag or SRP (which consume it) is wired.

    **Geometry + attitude.** A ``sphere`` geometry uses ``IsotropicDrag`` /
    ``IsotropicRadiationSingleCoefficient``; a ``box_and_panels`` geometry builds one
    ``BoxAndSolarArraySpacecraft`` driving both drag and SRP (a box
    :class:`VariableCd` is routed through a delegating custom ``DragSensitive``; a box
    ``IncidenceVariableCd`` raises ``NotImplementedError`` when drag is wired). The
    ``attitude`` argument is lowered to a native Orekit provider and wired into the
    propagator; a non-default attitude on a sphere has no dynamical effect, so it
    emits a one-time consistency warning and falls back to ``LofAligned``. The
    ``attitude`` metadata key is recorded only for a box with a wired surface force.

    Parameters mirror features.md §1.1 exactly. ``None`` config arguments are
    substituted with their defaults inside the body (``force_models`` ->
    ``leo_default()``, ``spacecraft`` -> ``SpacecraftConfig()``, ``attitude`` ->
    ``LofAligned()``, ``integrator`` -> ``IntegratorConfig.default()``); ``name``, if
    given, is recorded in the trajectory metadata.

    Raises ``ValueError`` for invalid inputs (non-inertial frame, non-positive or
    mis-ordered ``duration`` / ``output_step``, unknown ``integrator.type``,
    ``gravity_field``, or ``atmosphere_model``, ``ClassicalRK4`` without
    ``fixed_step_s``); ``NotImplementedError`` for a box ``IncidenceVariableCd`` under
    drag (Tier B deferred); and
    :class:`~propygator.core.exceptions.PropagationError` if the integrator fails to
    converge (carrying the Orekit message, no Java trace).
    """
    # Resolve None sentinels to default instances (features.md default-arg rule).
    force_models = (
        force_models if force_models is not None else ForceModelConfig.leo_default()
    )
    spacecraft = spacecraft if spacecraft is not None else SpacecraftConfig()
    integrator = integrator if integrator is not None else IntegratorConfig.default()

    # All pre-integration validation up front (pure-Python).
    _validate_inputs(initial, duration, output_step, integrator, force_models)

    # Resolve the attitude actually wired (pure-Python): None -> LofAligned, and a
    # non-default attitude on a sphere emits the one-time consistency warning + falls
    # back to LofAligned. Done before the JVM section so the warning fires up front.
    attitude_config = _resolve_attitude(attitude, spacecraft.geometry)

    n_samples = _sample_count(duration, output_step)
    degree = force_models.gravity_degree
    order = force_models.gravity_order
    logger.info(
        "propagate_numerical: integrator=%s gravity=%s:%dx%d duration=%.1fs "
        "output_step=%.1fs samples=%d",
        integrator.type,
        force_models.gravity_field,
        degree,
        order,
        duration,
        output_step,
        n_samples,
    )

    _ensure_started()
    import jpype
    from org.orekit.orbits import CartesianOrbit, OrbitType
    from org.orekit.propagation import SpacecraftState
    from org.orekit.propagation.numerical import NumericalPropagator

    from ..core.exceptions import PropagationError

    eme2000 = Frame.EME2000.to_orekit()
    start_date = initial.epoch.to_orekit()

    # Gravity provider + force (also the source of the central mu the orbit uses,
    # so the orbit and the gravity force share one consistent mu).
    provider = _resolve_gravity_provider(force_models.gravity_field, degree, order)
    mu = float(provider.getMu())
    gravity = _build_gravity_force(provider, degree, order)

    orbit = CartesianOrbit(
        initial.to_orekit().getPVCoordinates(), eme2000, start_date, mu
    )

    integrator_obj = _build_integrator(integrator, orbit)
    propagator = NumericalPropagator(integrator_obj)
    propagator.setOrbitType(OrbitType.CARTESIAN)
    propagator.addForceModel(gravity)
    # Enabled perturbations (third body, drag, SRP, tides, relativity) on the sphere
    # or box geometry; `wired` records exactly what was added, for honest metadata.
    wired = _add_perturbation_forces(propagator, force_models, spacecraft, provider)
    # Attitude provider (resolved above): the supplied mode for a box, LofAligned for
    # a sphere. For a sphere the cross-section is orientation-invariant, so this has no
    # effect on the dynamics; for a box it drives the drag/SRP projected area.
    propagator.setAttitudeProvider(_to_provider(attitude_config))
    # Mass drives drag/SRP per-unit-mass acceleration (gravity is mass-independent).
    propagator.setInitialState(SpacecraftState(orbit, float(spacecraft.mass_kg)))

    last_offset = float((n_samples - 1) * output_step)
    end_date = start_date.shiftedBy(last_offset)

    t0 = time.perf_counter()
    generator = propagator.getEphemerisGenerator()
    try:
        propagator.propagate(end_date)
    except jpype.JException as exc:  # type: ignore[attr-defined]
        # Convergence / unknown Orekit failures surface as PropagationError with the
        # Java message only (no raw stack trace), per the failure table (features.md).
        raise PropagationError(
            f"numerical propagation failed: {exc.getMessage()}"
        ) from None
    ephemeris = generator.getGeneratedEphemeris()

    # Sample the generated ephemeris at exactly output_step. The Orekit lookup date
    # and the propygator Epoch share the same offset, so they denote one instant.
    positions = np.empty((n_samples, 3), dtype=np.float64)
    velocities = np.empty((n_samples, 3), dtype=np.float64)
    epochs = []
    for k in range(n_samples):
        offset = float(k * output_step)
        pv = ephemeris.propagate(start_date.shiftedBy(offset)).getPVCoordinates()
        p = pv.getPosition()
        v = pv.getVelocity()
        positions[k, 0], positions[k, 1], positions[k, 2] = p.getX(), p.getY(), p.getZ()
        velocities[k, 0], velocities[k, 1], velocities[k, 2] = (
            v.getX(),
            v.getY(),
            v.getZ(),
        )
        epochs.append(initial.epoch.shifted_by(offset))

    metadata = _build_metadata(
        force_models, wired, integrator, output_step, spacecraft, attitude_config, name
    )
    traj = Trajectory.from_arrays(
        epochs,
        positions,
        velocities,
        Frame.EME2000,
        metadata=metadata,
    )
    logger.info(
        "propagate_numerical: done — %d samples in %.3fs wall",
        n_samples,
        time.perf_counter() - t0,
    )
    return traj


def _build_metadata(
    force_models: ForceModelConfig,
    wired: _WiredForces,
    integrator: IntegratorConfig,
    output_step: float,
    spacecraft: SpacecraftConfig,
    attitude: "AttitudeConfig",
    name: str | None,
) -> "TrajectoryMetadata":
    """Assemble the trajectory metadata for this run (features.md §1.1).

    The ``force_models`` list is driven by ``wired`` — the perturbations *actually
    added* to the propagator — not by the config booleans, so it never claims a force
    that is not acting (gravity is always present; the ``keplerian`` preset yields
    just the point-mass token). The ``spacecraft`` key is emitted only when a surface
    force that consumes it (drag or SRP) was wired, the same "reflect what's acting"
    rule — a ``keplerian`` run, whose result is independent of the spacecraft, omits
    it. The ``attitude`` key follows the same gate, restricted to a **box**: attitude
    affects the result only through a non-spherical cross-section under a surface
    force, so it is recorded exactly when geometry is a box *and* drag or SRP was wired
    (a sphere, or a force-free box, leaves it dynamically inert and omits the key).
    """
    force_tokens = _serialize_force_models(
        gravity_field=force_models.gravity_field,
        gravity_degree=force_models.gravity_degree,
        gravity_order=force_models.gravity_order,
        sun_third_body=wired.sun_third_body,
        moon_third_body=wired.moon_third_body,
        drag=wired.drag,
        atmosphere_model=force_models.atmosphere_model,
        srp=wired.srp,
        solid_tides=wired.solid_tides,
        ocean_tides=wired.ocean_tides,
        relativity=wired.relativity,
    )
    # ClassicalRK4 is fixed-step: the adaptive abs/rel/min/max tolerances never act,
    # so recording them would misrepresent the run and omit the one control that did
    # shape it (fixed_step_s). Emit the fixed-step parameter instead, keeping the
    # metadata an honest, reproducible record of what actually drove the integrator.
    if integrator.type == "ClassicalRK4":
        assert integrator.fixed_step_s is not None  # guaranteed by _validate_inputs
        integrator_tolerances: dict = {"fixed_step_s": float(integrator.fixed_step_s)}
    else:
        integrator_tolerances = {
            "abs_m": integrator.abs_tolerance_m,
            "rel": integrator.rel_tolerance,
            "min_step_s": integrator.min_step_s,
            "max_step_s": integrator.max_step_s,
        }
    metadata: TrajectoryMetadata = {
        "propygator_version": _propygator_version(),
        "orekit_version": _orekit_version(),
        "propagator": "numerical",
        "force_models": force_tokens,
        "integrator": integrator.type,
        "integrator_tolerances": integrator_tolerances,
        "output_step_s": float(output_step),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    # Spacecraft (mass + geometry coefficients) only influences the result through
    # drag/SRP; record it exactly when one of those was wired.
    if wired.drag or wired.srp:
        metadata["spacecraft"] = spacecraft._metadata_string()
    # Attitude only shapes the result through a non-spherical cross-section under a
    # surface force; record it exactly for a box with drag or SRP wired (same gate as
    # spacecraft, restricted to box geometry). A sphere / force-free box omits it.
    if spacecraft.geometry.kind == "box" and (wired.drag or wired.srp):
        metadata["attitude"] = _serialize_attitude(attitude)
    if name is not None:
        metadata["name"] = name
    return metadata
