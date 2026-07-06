"""``propagate_numerical`` — the numerical orbit propagator (Feature 1.1).

The full propagator (build-plan chunks 7-9): integrator selection + tolerances, the
gravity force, the full perturbation set (Sun/Moon third body plus an optional lumped
seven-planet third body, drag with a fixed or :class:`VariableCd` coefficient,
conical-shadow SRP, solid/ocean tides, relativity)
acting on either the **sphere** or the **box** (``BoxAndSolarArraySpacecraft``)
geometry, the full seven-mode attitude family, output-step ephemeris sampling, the
``Trajectory`` + metadata assembly, input validation, and ``NumericalPropagationError``.

**Geometry + attitude (chunk 9).** A ``box_and_panels`` geometry builds one
``BoxAndSolarArraySpacecraft`` driving both drag and SRP; a box :class:`VariableCd`
is routed through a custom ``DragSensitive`` that delegates the attitude-driven
projected-area computation to the box and overrides only the scalar Cd (via the
box's "global drag factor"). The :data:`AttitudeConfig` is lowered to a native
Orekit provider (:func:`~propygator.propagation.attitude._to_provider`). A sphere is
orientation-independent, so a non-default attitude on a sphere triggers a one-time
consistency warning and falls back to ``LofAligned`` (features.md §1.1). A box
:class:`BoxFaceCd` (Tier B per-face drag) instead drives a per-face free-molecular
drag sum — each face's flow angle resolved and its Cd looked up, summed over the full
face areas — through that same custom ``DragSensitive`` (general-upgrades-1 "Tier B
Drag").

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
from ..core.sampling import _output_offsets, _validate_sampling
from ..core.states import Trajectory, _propygator_version
from .attitude import LofAligned, _serialize_attitude, _to_provider
from .force_models import ForceModelConfig, _serialize_force_models
from .guards import _DETECTOR_THRESHOLD_S
from .integrators import IntegratorConfig
from .spacecraft import (
    BoxFaceCd,
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
    from .guards import AltitudeLimits

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

# A run "terminated early" (a guard's Action.STOP fired) iff the planned end is more
# than this many seconds past the achieved ephemeris span. A normal propagate(end)
# lands getMaxDate() == end (durationFrom == 0), so this is the common-path test for
# "did a backstop stop the run"; comfortably above any sub-ns float noise and below
# any meaningful early stop (addendum §6.6). Must stay >= guards._DETECTOR_THRESHOLD_S
# (the detector root-finds each crossing only to within that time tolerance) so this
# early-stop test never mistakes the root-finder's own slack for a full-span run — the
# assert enforces that cross-module invariant at import rather than trusting this
# comment, so loosening the detector tolerance later fails fast here.
_TERMINATION_TIME_TOL_S = 1.0e-3
assert _TERMINATION_TIME_TOL_S >= _DETECTOR_THRESHOLD_S


def _realized_sample_count(
    max_offset: float, output_step: float, planned_count: int
) -> int:
    """Output-sample count clamped to the achieved ephemeris span (addendum §6.3).

    A terminal guard (impact, escape, or — Chunk 8 — a re-entry min-step catch) stops
    the propagation early, so the generated ephemeris spans only ``max_offset``
    seconds from the start rather than the planned ``(planned_count - 1) *
    output_step``. Return the number of on-grid samples at or before ``max_offset`` —
    ``floor(max_offset / output_step) + 1`` with **no** round-off slack, so the last
    offset never overshoots ``getMaxDate()`` and the ephemeris query cannot raise —
    capped at ``planned_count`` and floored at 1. A full run returns ``planned_count``
    unchanged. One clamp serves impact, escape, and the re-entry catch alike.
    """
    if max_offset >= (planned_count - 1) * output_step:
        return planned_count
    count = int(math.floor(max_offset / output_step)) + 1
    return max(1, min(count, planned_count))


def _recover_ephemeris(
    generator: "org.orekit.propagation.EphemerisGenerator",
) -> "org.orekit.propagation.BoundedPropagator | None":
    """Return the ephemeris generated up to a propagation failure, or ``None``.

    After a ``JException`` from ``propagate()``, the generator usually still holds the
    good steps recorded before the failure — a usable partial ephemeris (addendum §6.6,
    verified on a real drag decay). But on a failure with *no* good steps (an integrator
    config so unmeetable the very first step is rejected), ``getGeneratedEphemeris()``
    *itself* raises; that edge returns ``None`` so the caller re-raises cleanly with no
    partial attached.
    """
    import jpype

    try:
        return generator.getGeneratedEphemeris()
    except jpype.JException:  # type: ignore[attr-defined]
        return None


def _radial_velocity_m_s(state: "org.orekit.propagation.SpacecraftState") -> float:
    """Radial velocity of ``state`` in m/s (``r·v / |r|``); < 0 while descending."""
    pv = state.getPVCoordinates()
    p = pv.getPosition()
    return float(p.dotProduct(pv.getVelocity())) / float(p.getNorm())


def _osculating_perigee_radius_m(
    state: "org.orekit.propagation.SpacecraftState",
) -> float:
    """Osculating perigee radius of ``state`` in m — ``a(1 - e)`` from its orbit.

    Uses the orbit's own ``getA()`` / ``getE()`` (which carry the propagation mu), so it
    is correct for any orbit type; for a bound orbit ``a(1 - e)`` is the perigee radius.
    """
    orbit = state.getOrbit()
    return float(orbit.getA()) * (1.0 - float(orbit.getE()))


def _validate_inputs(
    initial: State,
    duration: float,
    output_step: float,
    integrator: IntegratorConfig,
    force_models: ForceModelConfig,
) -> int:
    """Validate everything checkable before integration and return the sample count.

    Pure-Python (no JVM): the inertial-frame rule, the positive/ordered duration
    and output step, the integrator type name (+ the ``ClassicalRK4`` fixed-step
    coupling), and the gravity-field name. Each raises ``ValueError`` with an
    actionable message; the ``State`` itself already guarantees finite p/v
    (architecture §6). Returns the planned output-sample count from the shared
    :func:`_validate_sampling` (so the caller need not recompute it).
    """
    # Inertial-frame rule: Newtonian integration is only well-posed in an inertial
    # frame, and EME2000 (alias J2000) is the only inertial frame in the v1 set.
    if initial.frame is not Frame.EME2000:
        raise ValueError(
            f"propagate_numerical requires an inertial initial frame (EME2000 / "
            f"J2000), got {initial.frame.name}; convert first with "
            "initial.to_frame(Frame.EME2000). The output Trajectory is EME2000."
        )
    # Positive/ordered duration & output_step plus the sample-count cap — the
    # propagator-agnostic sampling pre-flight, shared with propagate_tle.
    n_samples = _validate_sampling(duration, output_step)
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
    return n_samples


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
    planets_third_body: bool
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


def _constant_cd(value: float) -> "Callable[[float, float], float]":
    """A fixed-Cd lookup matching the ``VariableCd(radius_m, density) -> Cd`` shape.

    Lets a plain float Cd flow through the same proxy as a :class:`VariableCd`, so every
    drag path shares the per-substep Kn-floor hook (addendum §6.2).
    """
    return lambda radius_m, density: value


def _build_drag_sensitive(
    cd_lookup: "Callable[[float, float], float]",
    accel: "Callable[..., object]",
    kn_floor: "tuple[float, str] | None",
) -> "org.orekit.forces.drag.DragSensitive":
    """A custom ``DragSensitive`` carrying the scalar-Cd lookup + the Kn-floor warning.

    Implements the ``DragSensitive`` interface from Python via ``@JImplements`` (Java
    classes can't be subclassed; CLAUDE.md) — **one** proxy serving every drag path
    (sphere and box, fixed Cd and :class:`VariableCd`), which differ only in how the
    per-substep scalar Cd becomes an acceleration. ``cd_lookup(radius_m, density) ->
    Cd`` is a :class:`VariableCd` (its call does the table lookup **and** the
    edge-aware clamp warning) or a fixed-Cd constant (:func:`_constant_cd`);
    ``accel(state, density, relative_velocity, cd)`` turns that scalar into an
    acceleration — the **sphere** assembles the ``IsotropicDrag`` formula, the **box**
    delegates to ``BoxAndSolarArraySpacecraft.dragAcceleration`` (attitude-driven
    projected area) with the value as the box's single "global drag factor".

    ``kn_floor`` is ``(floor_radius_m, message)`` or ``None``: when the geocentric
    radius first drops below ``floor_radius_m`` the loud free-molecular-floor warning
    is emitted **once** (addendum §6.2/§6.3).

    **Deliberate trade (chunk 9).** Routing *every* drag path through this one proxy —
    including a fixed-Cd sphere, which previously used Orekit's native ``IsotropicDrag``
    — buys a single shared warn-once hook and one code path, at the cost of crossing the
    Java->Python boundary for the whole drag formula on every integration substep
    instead of staying in Java for the fixed-Cd case. That per-substep cost is marginal
    next to the per-substep atmosphere-density query under the default ``NRLMSISE-00``,
    but is a larger share under a cheaper atmosphere (e.g. ``Harris-Priester``); the
    uniformity was judged worth it for v1. If a profile later shows it matters, restore
    native ``IsotropicDrag`` for the fixed-Cd sphere and move the floor check off the
    per-substep path (a setup-time perigee check or a non-terminal radius detector).
    See architecture §13 ("Coefficient of drag modeling") for the contract-level note.

    Only the double-precision ``dragAcceleration`` is implemented — the Field overload
    is never invoked by a double-precision ``NumericalPropagator``;
    ``getDragParametersDrivers`` returns no tunable parameters (the Cd comes from
    ``cd_lookup``, not a driver). Geocentric radius is ``|position|`` in the propagation
    frame (no transform).
    """
    import jpype
    from java.util import ArrayList
    from org.orekit.forces.drag import DragSensitive

    kn_floor_warned = [False]  # one-element mutable box: floor warn-once state

    @jpype.JImplements(DragSensitive)  # type: ignore[attr-defined]
    class _DragSensitive:
        @jpype.JOverride  # type: ignore[attr-defined]
        def getDragParametersDrivers(self):  # noqa: ANN001, ANN202 - Java signature
            return ArrayList()  # no tunable parameters: Cd comes from cd_lookup

        @jpype.JOverride  # type: ignore[attr-defined]
        def dependsOnAttitudeRate(self):  # noqa: ANN001, ANN202
            return False

        @jpype.JOverride  # type: ignore[attr-defined]
        def dragAcceleration(self, state, density, relative_velocity, parameters):  # noqa: ANN001, ANN202
            radius_m = float(state.getPosition().getNorm())
            if (
                kn_floor is not None
                and radius_m < kn_floor[0]
                and not kn_floor_warned[0]
            ):
                kn_floor_warned[0] = True
                warnings.warn(kn_floor[1], stacklevel=2)
            cd = cd_lookup(radius_m, float(density))
            return accel(state, density, relative_velocity, float(cd))

    # Implements DragSensitive only at the JPype runtime level (mypy can't see it).
    return _DragSensitive()  # type: ignore[return-value]


def _build_box_spacecraft(
    geometry: SpacecraftGeometry,
    sun: "org.orekit.utils.ExtendedPositionProvider",
) -> "org.orekit.forces.BoxAndSolarArraySpacecraft":
    """Build the ``BoxAndSolarArraySpacecraft`` for a **box** ``geometry`` (chunk 9).

    One object drives **both** drag and SRP (it implements ``DragSensitive`` and
    ``RadiationSensitive``), so the caller builds it once and shares it. The 10-arg
    ctor is ``(x, y, z, sun, arrayArea, arrayAxis, dragCoeff, liftRatio, absorption,
    specular)``; lift ratio is ``0.0`` (v1 models no aerodynamic lift). The base drag
    coefficient is **always ``1.0``**: the fixed-Cd and :class:`VariableCd` drag paths
    route through the custom box ``DragSensitive``, which applies the per-substep scalar
    Cd as the box's single "global drag factor" (drag is exactly linear in that factor —
    verified), so the Kn-floor warn-once hook is shared by both (addendum §6.2). A
    :class:`BoxFaceCd` box is still built here, but only to drive SRP — its drag takes
    the dedicated per-face path (:func:`_build_box_face_drag_force`), not this object's
    ``dragAcceleration``. The array axis is
    already a validated unit vector. Box field invariants hold (validated at
    construction).
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.forces import BoxAndSolarArraySpacecraft

    base_cd = 1.0
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
    """Build the drag ``ForceModel`` (chunk 8 sphere; chunk 9 box + Kn floor).

    Every fixed-Cd / :class:`VariableCd` drag path routes through
    :func:`_build_drag_sensitive` (the shared custom ``DragSensitive``), so they share
    both the scalar-Cd lookup shape and the §6.2 free-molecular-floor warn-once hook.
    ``cd_lookup`` is the :class:`VariableCd` (its call does the lookup + the edge-aware
    clamp warning) or a fixed-Cd constant (:func:`_constant_cd`); ``accel`` is the
    **sphere** ``IsotropicDrag`` formula or the **box** delegation to
    ``BoxAndSolarArraySpacecraft.dragAcceleration`` (the box is built at base
    dragCoeff=1.0 and the Cd is applied as its global drag factor). A box
    :class:`BoxFaceCd` (Tier B per-face table) takes the dedicated per-face path
    (:func:`_build_box_face_drag_force`) — the **same** shared proxy, but the six face
    lookups and ``CdA`` sum live in the accel closure. ``box`` is the shared object also
    used by SRP (``None`` for a sphere, and unused by drag for a ``BoxFaceCd``). The Kn
    floor for this body (addendum §6.2/§6.3) is computed once here.
    """
    import jpype
    from org.orekit.forces.drag import DragForce

    from .guards import _kn_floor_setup

    cd = geometry.drag_coefficient
    # The body's free-molecular validity floor: (floor_radius_m, warning) or None when
    # it falls outside the captured band. Computed once at setup; checked per-substep
    # inside the proxy so the loud regime warning fires once on the first dip below it.
    kn_floor = _kn_floor_setup(geometry)

    if isinstance(cd, BoxFaceCd):
        # Tier B per-face convex-box drag: the six face lookups + CdA assembly need the
        # SpacecraftState attitude, so they live in a dedicated accel closure (not the
        # 2-arg cd_lookup shape) that reuses the same shared proxy + Kn-floor hook.
        return _build_box_face_drag_force(geometry, atmosphere, cd, kn_floor)

    # A VariableCd does its own table lookup + edge-aware clamp warning; a fixed Cd is a
    # constant. Both flow through the same proxy.
    cd_lookup = cd if isinstance(cd, VariableCd) else _constant_cd(float(cd))
    if isinstance(cd, VariableCd):
        # Give the table-edge warnings the same once-per-run scope as the Kn-floor hook
        # below: clear the warn-once state now, so a VariableCd reused across several
        # propagations re-warns each run instead of staying silent after the first.
        cd._reset_edge_warnings()

    if geometry.kind == "sphere":
        assert geometry.area_m2 is not None  # sphere always carries an area
        area = float(geometry.area_m2)

        # IsotropicDrag formula with the looked-up Cd. Orekit hands the relative
        # velocity as v_atmosphere - v_spacecraft, so the matching deceleration is the
        # +1/2 (Cd*A/m) rho |relVel| relVel form (features.md §1.1 sign note; mass from
        # the state, verified against the stock IsotropicDrag to ~1e-21 m/s²).
        def _sphere_accel(state, density, relative_velocity, scalar_cd):  # noqa: ANN001, ANN202
            factor = (
                0.5
                * scalar_cd
                * area
                / state.getMass()
                * density
                * relative_velocity.getNorm()
            )
            return relative_velocity.scalarMultiply(float(factor))

        return DragForce(
            atmosphere, _build_drag_sensitive(cd_lookup, _sphere_accel, kn_floor)
        )

    assert box is not None  # built by the caller whenever geometry is a box

    # Delegate the attitude-driven projected-area bookkeeping to the box and apply the
    # looked-up Cd as its single "global drag factor": the box was built at base
    # dragCoeff=1.0, so the effective Cd equals the lookup value (drag is exactly
    # linear).
    def _box_accel(state, density, relative_velocity, scalar_cd):  # noqa: ANN001, ANN202
        return box.dragAcceleration(
            state,
            density,
            relative_velocity,
            jpype.JArray(jpype.JDouble)([float(scalar_cd)]),
        )

    return DragForce(atmosphere, _build_drag_sensitive(cd_lookup, _box_accel, kn_floor))


def _build_box_face_drag_force(
    geometry: SpacecraftGeometry,
    atmosphere: "org.orekit.models.earth.atmosphere.Atmosphere",
    table: BoxFaceCd,
    kn_floor: "tuple[float, str] | None",
) -> "org.orekit.forces.ForceModel":
    """Per-face drag ``ForceModel`` for a convex box with a :class:`BoxFaceCd` (Tier B).

    A convex body never self-shadows in free-molecular flow, so its drag is the exact
    **independent sum of its six per-face contributions** — which a single uniform Cd
    cannot represent, so this does **not** route through
    ``BoxAndSolarArraySpacecraft.dragAcceleration`` (the box object is still built, but
    only to drive SRP). Each substep the accel closure rotates the incoming-flow
    direction into the body frame, forms every face's flow angle θ, looks up that
    face's Cd, and assembles ``CdA = Σ Cd_i · A_i`` over the **full** face areas — the
    incidence projection (the ``cos θ`` pressure falloff *and* the tangential-shear
    floor) is already baked into ``Cd_i``, so the areas are **not** re-projected. The
    acceleration is the sphere-style ``½ (CdA/m) ρ |relVel| relVel`` form (Orekit's
    ``+½`` sign). **All six faces** are evaluated (windward and leeward), so the leeward
    shear tail is not dropped and there is no face-on attitude discontinuity
    (general-upgrades-1 "Tier B Drag").

    The closure reuses the **same** shared :func:`_build_drag_sensitive` proxy as every
    other drag path (so the Kn-floor warn-once hook is shared and no new Java interface
    is introduced); its ``cd_lookup`` is a no-op because the per-face path owns its own
    lookups. The table's edge-aware clamp warnings are given once-per-run scope here,
    exactly as a :class:`VariableCd`.
    """
    from org.orekit.forces.drag import DragForce

    assert geometry.x_length_m is not None  # a box always carries its edge lengths
    assert geometry.y_length_m is not None
    assert geometry.z_length_m is not None

    # Give the table's edge-clamp warnings the same once-per-run scope as the Kn floor.
    table._reset_edge_warnings()
    # Full face areas: the ±X faces span y*z, the ±Y faces x*z, the ±Z faces x*y.
    area_x = geometry.y_length_m * geometry.z_length_m
    area_y = geometry.x_length_m * geometry.z_length_m
    area_z = geometry.x_length_m * geometry.y_length_m

    def _box_face_accel(state, density, relative_velocity, _scalar_cd):  # noqa: ANN001, ANN202
        radius_m = float(state.getPosition().getNorm())
        rho = float(density)
        # Incoming-flow direction the body sees: -relVel/|relVel|, rotated into the
        # body frame via applyTo (verified to machine precision against Orekit's box
        # drag; applyInverseTo is wrong by ~9% — see the ecef-nadir convention work).
        flow_inertial = relative_velocity.normalize().negate()
        flow_body = state.getAttitude().getRotation().applyTo(flow_inertial)
        cd_area = 0.0
        for component, area in (
            (flow_body.getX(), area_x),
            (flow_body.getY(), area_y),
            (flow_body.getZ(), area_z),
        ):
            # The two opposite faces on each axis see +component and -component. The
            # clip is mandatory: at exact head-on/leeward a finite-precision dot can
            # land just past +/-1, where an unclamped arccos returns NaN and poisons
            # the drag acceleration with a silent NaN.
            for cosine in (component, -component):
                theta = math.acos(max(-1.0, min(1.0, cosine)))
                cd_area += table(radius_m, rho, theta) * area
        factor = 0.5 * cd_area / state.getMass() * density * relative_velocity.getNorm()
        return relative_velocity.scalarMultiply(float(factor))

    return DragForce(
        atmosphere, _build_drag_sensitive(_constant_cd(0.0), _box_face_accel, kn_floor)
    )


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
    metadata-token order (third body — Sun, Moon, then the lumped planets — drag,
    SRP, tides, relativity) and the wired facts returned so the metadata reflects
    exactly what acts. The celestial bodies and Earth come from ``core/bodies.py``
    (the canonical WGS84 ellipsoid + Orekit body singletons).
    A **box** geometry drives both drag and SRP from one shared
    ``BoxAndSolarArraySpacecraft``, built once here when a surface force will use it.
    """
    from org.orekit.forces.gravity import Relativity, ThirdBodyAttraction

    from ..core.bodies import (
        _earth,
        _jupiter,
        _mars,
        _mercury,
        _moon,
        _neptune,
        _saturn,
        _sun,
        _uranus,
        _venus,
    )

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
    if fm.planets_third_body:
        # The pinned seven-planet set in heliocentric order (general-upgrades-1.md
        # "Planetary Third-Body & Earth Radiation Pressure"): one lumped toggle, one
        # lumped metadata token.
        for planet in (
            _mercury(),
            _venus(),
            _mars(),
            _jupiter(),
            _saturn(),
            _uranus(),
            _neptune(),
        ):
            propagator.addForceModel(ThirdBodyAttraction(planet))
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
        planets_third_body=fm.planets_third_body,
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
    limits: AltitudeLimits | None = None,
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
    ``ForceModelConfig`` toggle adds its Orekit force — Sun/Moon third body (and,
    lumped behind one toggle, the seven other planets — a tiny completeness term), drag
    (every path — sphere or box, fixed Cd or a :class:`VariableCd` table — routes
    through one custom ``DragSensitive`` so the §6.2 free-molecular-floor warn-once
    hook is shared), conical-shadow SRP, solid/ocean tides, relativity. The
    ``force_models`` metadata lists only the forces actually wired, and ``spacecraft``
    is recorded only when drag or SRP (which consume it) is wired. Because all drag
    flows through that one proxy it exposes no drag ``ParameterDriver``: that is
    invisible to forward/backward-in-time propagation and to TLE fitting (which reads
    only the propagated *states* and estimates the TLE's own elements + B*), and would
    matter only for numerical orbit determination — estimating the propagator's own Cd
    — which is out of scope for v1.

    **Geometry + attitude.** A ``sphere`` geometry uses the custom drag
    ``DragSensitive`` (an ``IsotropicDrag``-equivalent formula) and
    ``IsotropicRadiationSingleCoefficient`` for SRP; a ``box_and_panels`` geometry
    builds one ``BoxAndSolarArraySpacecraft`` driving both drag and SRP, with drag
    routed through that same custom ``DragSensitive`` (a box ``BoxFaceCd`` instead
    drives a per-face free-molecular drag sum through that proxy — the box object then
    feeds SRP only). The
    ``attitude`` argument is lowered to a native Orekit provider and wired into the
    propagator; a non-default attitude on a sphere has no dynamical effect, so it
    emits a one-time consistency warning and falls back to ``LofAligned``. The
    ``attitude`` metadata key is recorded only for a box with a wired surface force.

    **Termination (addendum §6).** Two always-on geocentric-radius backstops stop the
    run and report: Earth impact (``r < R⊕``) and lunar-gravity-parity escape
    (``r > ~327,000 km``). An optional ``limits`` (:class:`AltitudeLimits`) adds user
    terminal altitude bounds that **nest inside** those backstops — a supplied
    ``min_altitude_km`` / ``max_altitude_km`` is lowered once to a geocentric-radius
    threshold and can only *tighten* termination (a limit outside the backstops is
    rejected at ``AltitudeLimits`` construction, so it never reaches here). A
    **drag-driven decay** that stiffens into a propagation failure is caught and, when
    its osculating perigee is already below the drag-table floor (~150 km) while
    descending, also stops & reports (``"reentry"``) rather than raising. On any stop
    the returned ``Trajectory`` holds the samples up to the crossing and its metadata
    gains ``terminated=True``, ``termination_reason`` (``"impact"`` / ``"escape"`` /
    ``"user_min"`` / ``"user_max"`` / ``"reentry"``), and ``termination_epoch``
    (ISO-8601 UTC of the crossing — for ``"reentry"`` this is the last successfully
    integrated step, just before the min-step failure, since nothing past it can be
    sampled). A normal completed run carries none of these keys.

    Parameters mirror features.md §1.1 exactly. ``None`` config arguments are
    substituted with their defaults inside the body (``force_models`` ->
    ``leo_default()``, ``spacecraft`` -> ``SpacecraftConfig()``, ``attitude`` ->
    ``LofAligned()``, ``integrator`` -> ``IntegratorConfig.default()``); ``limits``
    left ``None`` means the system backstops only; ``name``, if given, is recorded in
    the trajectory metadata.

    Raises ``ValueError`` for invalid inputs (non-inertial frame, non-positive or
    mis-ordered ``duration`` / ``output_step``, unknown ``integrator.type``,
    ``gravity_field``, or ``atmosphere_model``, ``ClassicalRK4`` without
    ``fixed_step_s``); and
    :class:`~propygator.core.exceptions.NumericalPropagationError` if the integrator
    fails and the failure is **not** a drag-driven re-entry (a too-tight tolerance, a
    bad setup, or any non-low-altitude stiffness) — carrying the Orekit message only
    (no Java trace). Any recoverable partial trajectory is attached as
    ``err.partial_trajectory`` (``None`` when no usable steps were generated).

    Spacecraft-model limitations (v1):
      * Solar radiation pressure uses uniform optical coefficients across the
        whole spacecraft. Per-face optical properties are not modeled.
      * Drag acts on the projected cross-section but produces no torque, and
        aerodynamic lift is not modeled; attitude is not perturbed by drag.
      * The drag coefficient is a fixed value, a (geocentric radius, density)
        table value (``VariableCd``, sphere or box), or — for a convex box with no
        solar arrays — a per-face free-molecular incidence table (``BoxFaceCd``,
        Sentman/Schaaf-Chambre) that resolves how each face meets the flow.
        Solar-array shadowing (non-convex bodies), aerodynamic lift, and
        higher-fidelity gas-surface physics (multiple reflection, per-facet
        material/temperature, transitional/continuum flow) are not modeled.
      * Drag modeling is valid only within an altitude band — free-molecular flow
        above a body-size-dependent floor (~110 km for a small CubeSat rising to
        ~220 km for a large bus/station) up to the Cd-table ceiling (~1400 km).
        Below the floor the run continues with a warning but drag is unreliable;
        a decaying orbit ends gracefully at re-entry, while impact and escape
        terminate the run, and user altitude limits may tighten these bounds.
    """
    # Resolve None sentinels to default instances (features.md default-arg rule).
    force_models = (
        force_models if force_models is not None else ForceModelConfig.leo_default()
    )
    spacecraft = spacecraft if spacecraft is not None else SpacecraftConfig()
    integrator = integrator if integrator is not None else IntegratorConfig.default()

    # All pre-integration validation up front (pure-Python); also yields the
    # planned output-sample count (shared cap helper) so it isn't recomputed.
    n_samples = _validate_inputs(
        initial, duration, output_step, integrator, force_models
    )

    # Resolve the attitude actually wired (pure-Python): None -> LofAligned, and a
    # non-default attitude on a sphere emits the one-time consistency warning + falls
    # back to LofAligned. Done before the JVM section so the warning fires up front.
    attitude_config = _resolve_attitude(attitude, spacecraft.geometry)

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

    from ..core.exceptions import NumericalPropagationError
    from ..core.time import _epoch_from_orekit
    from .guards import (
        _altitude_km_to_radius_m,
        _classify_termination,
        _escape_radius_m,
        _impact_radius_m,
        _is_reentry_failure,
        _make_radius_stop_detector,
        _reentry_floor_radius_m,
    )

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

    # Terminal radius backstops (addendum §6.1/§6.3): stop & report at Earth impact
    # and at lunar-gravity-parity escape. Both always active, independent of the force
    # config. `termination_specs` (radius -> reason) also drives reason classification
    # after the run. The system backstops stay FIRST in the list so the
    # nearest-threshold classifier resolves a degenerate exact tie with a user limit in
    # favor of the system reason (min_altitude_km == 0 -> "impact"; max_altitude_km at
    # the escape-parity altitude -> "escape").
    termination_specs = [
        (_impact_radius_m(), "impact"),
        (_escape_radius_m(), "escape"),
    ]
    # Optional user altitude limits (addendum §6.4/§6.6): lower each supplied bound
    # once to a geocentric radius via the *same* altitude->radius reference the escape
    # backstop uses, and register it as another terminal stop. A reasonable limit is
    # guaranteed (by AltitudeLimits.__post_init__) to nest inside the backstops, so it
    # can only tighten termination — on a descent the inner user_min radius is reached
    # before R⊕, on a climb the user_max radius before escape, so the first crossing
    # wins with no explicit tightest-of arithmetic. An unreasonable limit raised a
    # ValueError at construction, so none reaches here. (features.md §1.1 failure-modes
    # table gains that construction-time ValueError row in the Chunk-11 reconciliation.)
    if limits is not None:
        if limits.min_altitude_km is not None:
            termination_specs.append(
                (_altitude_km_to_radius_m(limits.min_altitude_km), "user_min")
            )
        if limits.max_altitude_km is not None:
            termination_specs.append(
                (_altitude_km_to_radius_m(limits.max_altitude_km), "user_max")
            )
    for threshold_radius, _ in termination_specs:
        propagator.addEventDetector(_make_radius_stop_detector(threshold_radius))

    last_offset = float((n_samples - 1) * output_step)
    end_date = start_date.shiftedBy(last_offset)

    t0 = time.perf_counter()
    generator = propagator.getEphemerisGenerator()
    # A propagation failure (a JException) is no longer always fatal (addendum §6.6). A
    # drag-driven decay stiffens until it fails — the adaptive step saturates min_step_s
    # or, with looser tolerances, the atmosphere model rejects the sub-surface query
    # ("point is inside ellipsoid"). Both surface as a JException; we catch it, recover
    # the ephemeris built so far, and CLASSIFY by physical state (drag + descending +
    # osculating perigee), not by the message. The impact detector registered above is
    # the drag-OFF counterpart: with no atmosphere query it stops cleanly at R⊕ as
    # "impact" (addendum §8), so a drag-on decay routes here as "reentry" instead.
    failure_msg: str | None = None
    try:
        propagator.propagate(end_date)
    except jpype.JException as exc:  # type: ignore[attr-defined]
        # Capture the Java *message* only (no raw stack trace; architecture §3) and
        # leave the except block before recovering, so a recovery failure cannot chain.
        failure_msg = str(exc.getMessage())

    if failure_msg is not None:
        ephemeris = _recover_ephemeris(generator)
        if ephemeris is None:
            # No usable steps recovered (edge a): fail loudly with no partial attached.
            raise NumericalPropagationError(
                f"numerical propagation failed: {failure_msg}"
            ) from None
    else:
        ephemeris = generator.getGeneratedEphemeris()

    # A terminal detector firing — or a recovered partial — shortens the realized span
    # below the planned end, so clamp the sampling grid to the achieved span (addendum
    # §6.3): sampling past getMaxDate() would raise. A normal run achieves the full span
    # (realized == n_samples), so the common path is unchanged.
    max_date = ephemeris.getMaxDate()
    max_offset = float(max_date.durationFrom(start_date))
    realized = _realized_sample_count(max_offset, output_step, n_samples)

    # Sample the (possibly partial) ephemeris at exactly output_step. The Orekit lookup
    # date and the propygator Epoch share the same offset, so they denote one instant.
    offsets = _output_offsets(realized, output_step)
    # A terminal stop inside the first output_step clamps to one on-grid sample
    # (the start). Append the achieved-span endpoint so the partial Trajectory keeps
    # the >= 2 samples every downstream verb (at/plot/export) needs — the floor a
    # normal run gets from output_step <= duration. The endpoint is exactly
    # getMaxDate(), so the lookup stays inside the ephemeris.
    if len(offsets) < 2 and max_offset > 0.0:
        offsets.append(max_offset)
    positions = np.empty((len(offsets), 3), dtype=np.float64)
    velocities = np.empty((len(offsets), 3), dtype=np.float64)
    epochs = []
    for k, offset in enumerate(offsets):
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

    # Termination decision (addendum §6.6). Three outcomes feed the single metadata +
    # Trajectory build below:
    #   * propagation failure -> classify: a drag-driven re-entry stops & reports
    #     "reentry"; anything else is a genuine error to re-raise (with the partial).
    #   * a terminal detector fired -> classify the reason by nearest threshold radius.
    #   * normal completion -> no termination keys (byte-identical to a pre-guard run).
    terminated = False
    termination_reason: str | None = None
    termination_epoch: str | None = None
    reraise = False
    if failure_msg is not None:
        last_state = ephemeris.propagate(max_date)
        if _is_reentry_failure(
            drag_enabled=wired.drag,
            radial_velocity_m_s=_radial_velocity_m_s(last_state),
            perigee_radius_m=_osculating_perigee_radius_m(last_state),
            floor_radius_m=_reentry_floor_radius_m(),
        ):
            terminated = True
            termination_reason = "reentry"
        else:
            # Not a re-entry (drag off, climbing, or perigee still above the floor): a
            # genuine numeric/config failure -> re-raise (invariant: prefer a false
            # re-raise over a false reentry). The partial built below is attached to it.
            reraise = True
    else:
        terminated = float(end_date.durationFrom(max_date)) > _TERMINATION_TIME_TOL_S
        if terminated:
            r_final = float(ephemeris.propagate(max_date).getPosition().getNorm())
            termination_reason = _classify_termination(r_final, termination_specs)
            # A clean impact-detector stop with drag ON is a drag-driven re-entry, not a
            # geometric impact: the impact detector can fire at R⊕ before the atmosphere
            # model throws (the usual "reentry" route via the min-step catch), and §8
            # reserves "impact" for a drag-OFF sub-surface orbit. Relabel here so the
            # reported reason is robust to that integrator-vs-atmosphere race.
            if termination_reason == "impact" and wired.drag:
                termination_reason = "reentry"
    # The crossing instant is the same in either branch, so format the ISO-8601 UTC
    # termination_epoch once here — keeping the "+ Z" UTC-suffix convention in a single
    # place (Epoch.to_iso() deliberately emits no zone suffix).
    if terminated:
        termination_epoch = _epoch_from_orekit(max_date).to_iso() + "Z"

    metadata = _build_metadata(
        force_models,
        wired,
        integrator,
        output_step,
        spacecraft,
        attitude_config,
        name,
        terminated=terminated,
        termination_reason=termination_reason,
        termination_epoch=termination_epoch,
    )
    traj = Trajectory.from_arrays(
        epochs,
        positions,
        velocities,
        Frame.EME2000,
        metadata=metadata,
    )
    if reraise:
        # Fail loudly, but carry the samples computed before the failure for advanced
        # recovery (addendum §6.6) — a non-terminated partial (no termination keys).
        err = NumericalPropagationError(f"numerical propagation failed: {failure_msg}")
        err.partial_trajectory = traj
        raise err from None
    logger.info(
        "propagate_numerical: done — %d samples in %.3fs wall%s",
        len(epochs),
        time.perf_counter() - t0,
        f" (terminated: {termination_reason})" if terminated else "",
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
    *,
    terminated: bool = False,
    termination_reason: str | None = None,
    termination_epoch: str | None = None,
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

    The optional ``terminated`` / ``termination_reason`` / ``termination_epoch`` keys
    (addendum §6.6) are written only when a guard stopped the run early; a normal
    completed run omits all three, keeping its metadata byte-identical to before the
    guard system landed.
    """
    force_tokens = _serialize_force_models(
        gravity_field=force_models.gravity_field,
        gravity_degree=force_models.gravity_degree,
        gravity_order=force_models.gravity_order,
        sun_third_body=wired.sun_third_body,
        moon_third_body=wired.moon_third_body,
        planets_third_body=wired.planets_third_body,
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
    # Termination reporting (addendum §6.6): written ONLY when a guard stopped the run
    # early, so a normal completed run's metadata (and its export_csv header) are
    # byte-identical to today.
    if terminated:
        assert termination_reason is not None  # set together by the caller
        assert termination_epoch is not None
        metadata["terminated"] = True
        metadata["termination_reason"] = termination_reason
        metadata["termination_epoch"] = termination_epoch
    return metadata
