"""``AttitudeConfig`` — how the spacecraft is oriented over a propagation.

The seven v1 attitude modes (features.md §1.1) plus the internal lowering that
turns each one into a native Orekit ``AttitudeProvider``. The **dataclasses and
their validation/metadata are pure-Python and safe before init** (architecture
§10): constructing and validating an :class:`Inertial`, :class:`SunPointing`, …
never touches Orekit. Only :func:`_to_provider` (and the ``CustomAttitude``
``law``-backed provider it builds) crosses into the JVM, behind
``_ensure_started()`` with lazy ``org.orekit.*`` imports.

Attitude is meaningful only for non-spherical geometry — a sphere's cross-section
is orientation-independent, so the propagator warns and ignores a non-default
attitude on a sphere (features.md §1.1; enforced in ``propagate_numerical``, not
here).

**Native providers vs the escape hatch.** Six of the seven modes lower to a stock
Orekit provider (``LofOffset(TNW)``, ``FrameAlignedProvider``,
``CelestialBodyPointed`` / ``AlignedAndConstrained``), so they add no per-substep
Python. :class:`CustomAttitude` is the only non-native mode: its ``law`` (a
``Callable[[State], Orientation]``) is invoked from inside the integration loop via
a ``@JImplements`` provider that converts the returned :class:`Orientation` with
``Orientation.to_orekit()`` — prefer the declarative modes (features.md performance
caveat).

**Rotation direction (verified).** Orekit's ``Attitude`` rotation is
reference(inertial)→spacecraft(body) in the frame-transform sense, which lines up
with how :meth:`Orientation.to_orekit` builds its Hipparchus ``Rotation`` — so the
law's :class:`Orientation` is used directly with no conjugate/inverse. Pinned by
``test_custom_attitude_provider_body_to_inertial`` (a body axis lands at the
hand-checked inertial direction), the first real consumer of
``Orientation.to_orekit`` that the Chunk-3 characterization test left to this chunk.

**Metadata.** :func:`_serialize_attitude` builds the deterministic ``attitude``
metadata string (features.md §1.1), mirroring the facts-driven serializers in
:mod:`~propygator.propagation.force_models` and
:mod:`~propygator.propagation.spacecraft`.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.frames import Frame

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.attitudes  # noqa: F401

    from ..core.states import Orientation, State  # noqa: F401


# --- shared helpers --------------------------------------------------------


def _validate_finite_angles(**angles: float) -> None:
    """Raise ``ValueError`` if any named angle is non-finite (NaN / inf)."""
    for name, value in angles.items():
        if not math.isfinite(value):
            raise ValueError(f"{name} must be finite, got {value!r}")


def _normalized_axis(name: str, axis: tuple[float, float, float]) -> np.ndarray:
    """Validate a length-3, finite, nonzero body axis and return its unit vector.

    Axes are normalized silently (features.md §1.1): a caller-supplied direction
    need not be unit-length.
    """
    vec = np.asarray(axis, dtype=np.float64)
    if vec.shape != (3,):
        raise ValueError(f"{name} must be a length-3 vector, got {axis!r}")
    if not np.all(np.isfinite(vec)):
        raise ValueError(f"{name} must be finite, got {axis!r}")
    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        raise ValueError(f"{name} must be nonzero")
    return vec / norm


def _fmt_axis_component(value: float) -> str:
    """Render an axis component compactly: ``0.0`` -> ``0``, ``1.0`` -> ``1``.

    The twin of :func:`propygator.propagation.spacecraft._fmt_axis_component`;
    duplicated to keep each config module's metadata serializer self-contained
    (the established force_models / spacecraft pattern). Whole values drop the
    trailing ``.0`` to match the features.md ``point=(0,0,1)`` form; non-whole
    (normalized) components fall back to ``repr`` for round-tripping.
    """
    if math.isfinite(value) and value == int(value):
        return str(int(value))
    return repr(value)


def _fmt_axis(axis: tuple[float, float, float]) -> str:
    """Render a body axis as the ``(a,b,c)`` metadata token."""
    return "(" + ",".join(_fmt_axis_component(c) for c in axis) + ")"


# --- the seven attitude modes ----------------------------------------------

_VALID_PHASING_REFERENCES = ("orbit_normal", "velocity", "inertial_z")
_VALID_VELOCITY_REFERENCES = ("inertial", "ecef")


@dataclass(frozen=True)
class LofAligned:
    """Body axes follow the TNW local orbital frame: body-X along velocity,
    body-Z along orbital momentum, body-Y completing the right-handed set.

    The v1 default. TNW is fixed in v1; no parameters (features.md §1.1)."""

    def _metadata_string(self) -> str:
        return "lof_aligned:TNW"


@dataclass(frozen=True)
class LofOffset:
    """``LofAligned`` (TNW) rotated by fixed body-frame angles.

    Use for an arbitrary fixed offset from the velocity-aligned frame — e.g. a
    flat plate rolled about the velocity axis (``roll_deg``). Non-finite angles
    raise ``ValueError``. The angles are applied as ``RotationOrder.XYZ`` Euler
    angles (roll about body-X, the velocity axis in TNW)."""

    roll_deg: float = 0.0  # about body-X (the velocity axis in TNW)
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        _validate_finite_angles(
            roll_deg=self.roll_deg, pitch_deg=self.pitch_deg, yaw_deg=self.yaw_deg
        )

    def _metadata_string(self) -> str:
        return (
            f"lof_offset:TNW;roll={float(self.roll_deg)!r},"
            f"pitch={float(self.pitch_deg)!r},yaw={float(self.yaw_deg)!r}"
        )


@dataclass(frozen=True)
class Inertial:
    """Fixed orientation in inertial space — the spacecraft does not rotate
    relative to ``reference_frame``.

    Optional fixed offset via the angles. ``reference_frame`` must be inertial
    (``EME2000`` / ``J2000``, the same member); ``ITRF`` / ``TEME`` raise
    ``ValueError`` (features.md §1.1)."""

    reference_frame: Frame = Frame.EME2000
    roll_deg: float = 0.0
    pitch_deg: float = 0.0
    yaw_deg: float = 0.0

    def __post_init__(self) -> None:
        # Member-identity check (no JVM): EME2000 is the only inertial frame in
        # the v1 set, and J2000 is the same enum member, so this accepts both
        # names while rejecting ITRF / TEME.
        if self.reference_frame is not Frame.EME2000:
            raise ValueError(
                f"Inertial.reference_frame must be inertial (EME2000 / J2000), got "
                f"{self.reference_frame.name}; ITRF / TEME are not inertial."
            )
        _validate_finite_angles(
            roll_deg=self.roll_deg, pitch_deg=self.pitch_deg, yaw_deg=self.yaw_deg
        )

    def _metadata_string(self) -> str:
        return (
            f"inertial:{self.reference_frame.name};roll={float(self.roll_deg)!r},"
            f"pitch={float(self.pitch_deg)!r},yaw={float(self.yaw_deg)!r}"
        )


@dataclass(frozen=True)
class SunPointing:
    """``pointing_axis`` (body) is held exactly on the Sun; ``phasing_axis``
    (body) fixes the remaining roll about the Sun line by tracking
    ``phasing_reference``.

    Axes normalized silently; ``pointing_axis`` parallel to ``phasing_axis``
    raises ``ValueError``. ``phasing_reference`` is one of ``orbit_normal`` |
    ``velocity`` | ``inertial_z`` (features.md §1.1)."""

    pointing_axis: tuple[float, float, float] = (0.0, 0.0, 1.0)  # body -> Sun
    phasing_axis: tuple[float, float, float] = (1.0, 0.0, 0.0)  # body, 2nd DOF
    phasing_reference: str = "orbit_normal"

    def __post_init__(self) -> None:
        if self.phasing_reference not in _VALID_PHASING_REFERENCES:
            raise ValueError(
                f"SunPointing.phasing_reference must be one of "
                f"{_VALID_PHASING_REFERENCES}, got {self.phasing_reference!r}"
            )
        point = _normalized_axis("pointing_axis", self.pointing_axis)
        phase = _normalized_axis("phasing_axis", self.phasing_axis)
        # |unit x unit| = |sin(angle)|; ~0 means (anti)parallel, leaving the roll
        # about the Sun line undefined.
        if float(np.linalg.norm(np.cross(point, phase))) < 1e-9:
            raise ValueError(
                "SunPointing.pointing_axis must not be parallel to phasing_axis "
                "(the roll about the Sun line would be undefined)."
            )
        # Frozen dataclass: store the silently-normalized axes.
        object.__setattr__(
            self, "pointing_axis", (point[0].item(), point[1].item(), point[2].item())
        )
        object.__setattr__(
            self, "phasing_axis", (phase[0].item(), phase[1].item(), phase[2].item())
        )

    def _metadata_string(self) -> str:
        return (
            f"sun_pointing:point={_fmt_axis(self.pointing_axis)},"
            f"phase={_fmt_axis(self.phasing_axis)}:{self.phasing_reference}"
        )


@dataclass(frozen=True)
class NadirPointing:
    """Body -Z held on (geodetic) nadir; body +Y steered toward the velocity
    vector. Earth-pointing with velocity yaw.

    Exact when the flight-path angle is zero (circular orbits, apsides);
    off-apsis on eccentric orbits, nadir is held exactly and velocity is
    best-effort. ``velocity_reference`` is ``inertial`` (ECI) | ``ecef``
    (Earth-relative); ``ecef`` is **deferred** (a validated skeleton — it
    constructs and serializes, but lowering it raises ``NotImplementedError``;
    architecture §13)."""

    velocity_reference: str = "inertial"  # "inertial" (ECI) | "ecef"

    def __post_init__(self) -> None:
        if self.velocity_reference not in _VALID_VELOCITY_REFERENCES:
            raise ValueError(
                f"NadirPointing.velocity_reference must be one of "
                f"{_VALID_VELOCITY_REFERENCES}, got {self.velocity_reference!r}"
            )

    def _metadata_string(self) -> str:
        return f"nadir_pointing:vel={self.velocity_reference}"


@dataclass(frozen=True)
class InPlaneTracking:
    """Body +Z on the orbit normal; body +Y on the velocity vector.

    Exact for all orbits, since the orbit normal is always perpendicular to
    velocity. No parameters (features.md §1.1)."""

    def _metadata_string(self) -> str:
        return "in_plane_tracking"


@dataclass(frozen=True)
class CustomAttitude:
    """Fully user-defined law mapping a ``State`` to a body orientation.

    ``law`` returns a propygator :class:`Orientation` (a boundary value type —
    NOT an Orekit / Hipparchus object), converted internally. The escape hatch
    for laws not expressible above. ``law`` must be callable, else ``ValueError``.
    The law is invoked from inside the integration loop on every substep
    (features.md performance caveat)."""

    law: Callable[[State], Orientation]

    def __post_init__(self) -> None:
        if not callable(self.law):
            raise ValueError(
                f"CustomAttitude.law must be callable, got {type(self.law).__name__}"
            )

    def _metadata_string(self) -> str:
        # The law is arbitrary Python and cannot be fully serialized; record its
        # name where available (a documented reproducibility gap, features.md §1.1).
        name = getattr(self.law, "__name__", None) or repr(self.law)
        return f"custom:{name}"


# The accepted attitude configuration: any one of the seven modes (features.md §1.1).
AttitudeConfig = (
    LofAligned
    | LofOffset
    | Inertial
    | SunPointing
    | NadirPointing
    | InPlaneTracking
    | CustomAttitude
)


# --- metadata serializer ----------------------------------------------------


def _serialize_attitude(config: AttitudeConfig) -> str:
    """The deterministic ``attitude`` metadata string for ``config``.

    A single named entry point (mirroring ``force_models`` / ``spacecraft``) that
    dispatches to each mode's own ``_metadata_string``. ``propagate_numerical``
    (chunk 9) calls this with the attitude it actually wired into the propagator.
    """
    return config._metadata_string()


# --- provider lowering (JVM-crossing) --------------------------------------

_ECEF_DEFERRED_MESSAGE = (
    "NadirPointing(velocity_reference='ecef') is not yet implemented. "
    "Earth-relative (ECEF) velocity yaw-steering needs a custom Orekit target "
    "provider that subtracts Earth rotation; only 'inertial' (ECI) velocity is "
    "wired in v1. Use NadirPointing(velocity_reference='inertial'). "
    "Deferred — architecture §13."
)


def _to_provider(
    config: AttitudeConfig, *, inertial_frame: Frame = Frame.EME2000
) -> "org.orekit.attitudes.AttitudeProvider":
    """Lower an :data:`AttitudeConfig` to a native Orekit ``AttitudeProvider``.

    JVM-crossing: starts the JVM via ``_ensure_started()`` then resolves the
    provider with lazy ``org.orekit.*`` imports. ``inertial_frame`` is the
    propagation frame (EME2000 in v1) the providers and the ``CustomAttitude`` law
    are referenced against. Six modes map to stock Orekit providers (constructor
    spellings verified against the installed 13.1.x API); ``CustomAttitude`` builds
    a law-backed provider. ``NadirPointing(velocity_reference='ecef')`` raises
    ``NotImplementedError`` (deferred — see :data:`_ECEF_DEFERRED_MESSAGE`).
    """
    from .._orekit_init import _ensure_started

    _ensure_started()

    from org.hipparchus.geometry.euclidean.threed import (
        Rotation,
        RotationConvention,
        RotationOrder,
        Vector3D,
    )
    from org.orekit.attitudes import (
        AlignedAndConstrained,
        CelestialBodyPointed,
        FrameAlignedProvider,
        PredefinedTarget,
    )
    from org.orekit.attitudes import LofOffset as _OkLofOffset
    from org.orekit.frames import LOFType

    from ..core.bodies import _earth, _sun

    inertial = inertial_frame.to_orekit()

    if isinstance(config, LofAligned):
        return _OkLofOffset(inertial, LOFType.TNW)

    if isinstance(config, LofOffset):
        return _OkLofOffset(
            inertial,
            LOFType.TNW,
            RotationOrder.XYZ,
            math.radians(config.roll_deg),
            math.radians(config.pitch_deg),
            math.radians(config.yaw_deg),
        )

    if isinstance(config, Inertial):
        # FRAME_TRANSFORM (reference->body): the same sense Orekit's Attitude rotation
        # and LofOffset use for their Euler angles, so a given roll/pitch/yaw is the
        # same physical offset across Inertial, LofOffset, and CustomAttitude
        # (Orientation.to_orekit). VECTOR_OPERATOR here would invert the offset sign,
        # leaving Inertial opposite-handed to every other mode.
        offset = Rotation(
            RotationOrder.XYZ,
            RotationConvention.FRAME_TRANSFORM,
            math.radians(config.roll_deg),
            math.radians(config.pitch_deg),
            math.radians(config.yaw_deg),
        )
        return FrameAlignedProvider(offset, inertial)

    if isinstance(config, SunPointing):
        point = Vector3D(*config.pointing_axis)
        phase = Vector3D(*config.phasing_axis)
        if config.phasing_reference == "inertial_z":
            # Fixed inertial phasing direction: CelestialBodyPointed holds
            # `point` on the Sun and aligns `phase` with inertial +Z.
            return CelestialBodyPointed(
                inertial, _sun(), Vector3D(0.0, 0.0, 1.0), point, phase
            )
        # Orbit-relative phasing varies with the state -> AlignedAndConstrained,
        # primary `point` on the Sun (exact), secondary `phase` best-effort.
        secondary = (
            PredefinedTarget.MOMENTUM
            if config.phasing_reference == "orbit_normal"
            else PredefinedTarget.VELOCITY
        )
        return AlignedAndConstrained(
            point, PredefinedTarget.SUN, phase, secondary, _sun(), _earth()
        )

    if isinstance(config, NadirPointing):
        if config.velocity_reference == "ecef":
            raise NotImplementedError(_ECEF_DEFERRED_MESSAGE)
        # Primary -Z on nadir (exact), secondary +Y best-effort on inertial velocity.
        return AlignedAndConstrained(
            Vector3D(0.0, 0.0, -1.0),
            PredefinedTarget.NADIR,
            Vector3D(0.0, 1.0, 0.0),
            PredefinedTarget.VELOCITY,
            _sun(),
            _earth(),
        )

    if isinstance(config, InPlaneTracking):
        # +Y on velocity, +Z on orbital momentum; velocity _|_ momentum so both hold.
        return AlignedAndConstrained(
            Vector3D(0.0, 1.0, 0.0),
            PredefinedTarget.VELOCITY,
            Vector3D(0.0, 0.0, 1.0),
            PredefinedTarget.MOMENTUM,
            _sun(),
            _earth(),
        )

    if isinstance(config, CustomAttitude):
        return _build_law_backed_provider(config.law, inertial_frame)

    # Unreachable: every AttitudeConfig member is handled above (fail loud).
    raise TypeError(f"unknown AttitudeConfig type {type(config).__name__!r}")


def _build_law_backed_provider(
    law: "Callable[[State], Orientation]", inertial_frame: Frame
) -> "org.orekit.attitudes.AttitudeProvider":
    """Build a ``CustomAttitude`` ``law``-backed Orekit ``AttitudeProvider``.

    Implements the ``AttitudeProvider`` interface from Python via ``@JImplements``
    (Java classes can't be subclassed; CLAUDE.md). The double-precision ``getAttitude``
    carries the law (the Field/generic overload is never invoked by a double-precision
    ``NumericalPropagator``); ``getEventDetectors`` is also implemented because
    ``propagate()`` queries it and JPype cannot dispatch that inherited interface
    *default* method on a Python proxy. Each ``getAttitude`` call reconstructs a
    propygator :class:`State` from the Orekit PV provider, runs the user ``law``, and
    wraps the returned :class:`Orientation` as an Orekit ``Attitude`` (zero
    rate/acceleration — attitude rates are out of scope for v1).
    """
    from .._orekit_init import _ensure_started

    _ensure_started()

    import jpype
    from java.util import ArrayList
    from java.util.stream import Stream
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.attitudes import Attitude, AttitudeProvider

    from ..core.states import State, _vector3d_to_array
    from ..core.time import _epoch_from_orekit

    @jpype.JImplements(AttitudeProvider)  # type: ignore[attr-defined]
    class _LawBackedAttitudeProvider:
        @jpype.JOverride  # type: ignore[attr-defined]
        def getAttitude(self, pv_provider, date, frame):
            # `frame` is the propagation frame (== inertial_frame in v1, the only
            # frame numerical propagation runs in); the law's Orientation is
            # referenced against it, so the Attitude reference frame is `frame`.
            pv = pv_provider.getPVCoordinates(date, frame)
            p = pv.getPosition()
            v = pv.getVelocity()
            state = State(
                position=_vector3d_to_array(p),
                velocity=_vector3d_to_array(v),
                epoch=_epoch_from_orekit(date),
                frame=inertial_frame,
            )
            # Orekit's Attitude rotation is reference(inertial)->body in the
            # frame-transform sense, matching Orientation.to_orekit (verified — see
            # the module docstring), so the law's Orientation is used directly.
            rotation = law(state).to_orekit()
            return Attitude(date, frame, rotation, Vector3D.ZERO, Vector3D.ZERO)

        @jpype.JOverride  # type: ignore[attr-defined]
        def getAttitudeRotation(self, *args):  # noqa: ANN002, ANN202 - Java overloads
            # NumericalPropagator's state mapper queries getAttitudeRotation; like
            # getEventDetectors these are interface *default* methods JPype cannot
            # dispatch on a Python proxy, so both AttitudeProvider overloads are
            # implemented here, each mirroring its default body via our getAttitude:
            #   (PVCoordinatesProvider, AbsoluteDate, Frame) — the state mapper's call
            #   (SpacecraftState, double[])                  — the parameterized form;
            #     a SpacecraftState is itself a PVCoordinatesProvider, so reuse the
            #     3-arg path at the state's own date/frame.
            if len(args) == 3:
                pv_provider, date, frame = args
                return self.getAttitude(pv_provider, date, frame).getRotation()
            state = args[0]
            return self.getAttitude(
                state, state.getDate(), state.getFrame()
            ).getRotation()

        @jpype.JOverride  # type: ignore[attr-defined]
        def getParametersDrivers(self):  # noqa: ANN001, ANN202 - Java signature
            # AttitudeProvider extends ParameterDriversProvider; the propagator may
            # collect parameter drivers from every provider during setup. JPype cannot
            # dispatch this interface *default* on a Python proxy, so implement it: the
            # law exposes no tunable parameters -> an empty list (the default's body).
            return ArrayList()

        @jpype.JOverride  # type: ignore[attr-defined]
        def getEventDetectors(self, *args):  # noqa: ANN002, ANN202 - Java overloads
            # AttitudeProvider extends EventDetectorsProvider; NumericalPropagator
            # queries getEventDetectors() during propagate(). JPype cannot dispatch
            # this interface *default* method on a Python proxy (it fails with
            # "no such method ... getEventDetectors()Stream/invokeSpecial"), so we
            # implement it explicitly. The law registers no events -> an empty Stream.
            # `*args` also covers the getEventDetectors(List) overload.
            return Stream.empty()

    # The class implements AttitudeProvider only at the JPype runtime level (via
    # @JImplements), which mypy cannot see — hence the cast through the ignore.
    return _LawBackedAttitudeProvider()  # type: ignore[return-value]
