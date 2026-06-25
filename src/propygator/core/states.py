"""``State`` — the canonical "where is this object, when, in what frame."

A :class:`State` is an immutable Cartesian position+velocity at an :class:`Epoch`
in an explicit :class:`Frame`. Construction and validation are pure-Python and
safe before JVM init (architecture §10); the conversion methods
(:meth:`State.to_frame`, :meth:`State.to_keplerian`, :meth:`State.to_orekit`)
cross into Orekit and start the JVM lazily on first use (Feature 1.1).
"""

from __future__ import annotations

import importlib.metadata
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Required, TypedDict

import numpy as np

from .frames import Frame, _require_pseudo_inertial, to_geodetic
from .time import Epoch, TimeScale, _abs_date, _count_from_wallclock

if TYPE_CHECKING:
    # Type-only. The org.* namespaces are runtime JPype stubs; pandas is imported
    # lazily inside to_dataframe so importing the package stays cheap.
    import org.hipparchus.geometry.euclidean.threed  # noqa: F401
    import org.orekit.propagation  # noqa: F401
    import org.orekit.propagation.analytical  # noqa: F401
    import org.orekit.utils  # noqa: F401
    import pandas as pd  # noqa: F401

    from .elements import KeplerianElements  # noqa: F401


def _vector3d_to_array(
    v: "org.hipparchus.geometry.euclidean.threed.Vector3D",
) -> np.ndarray:
    """Extract a Hipparchus/Orekit ``Vector3D`` into a fresh ``(3,) float64`` array.

    The JVM-boundary idiom (architecture §10): pull the Java ``Vector3D`` getters
    into NumPy. The returned array is owned by the caller; :class:`State` copies it
    again on construction, so the read-only-array invariant is preserved.
    """
    return np.array([v.getX(), v.getY(), v.getZ()], dtype=np.float64)


def _pv(position: np.ndarray, velocity: np.ndarray) -> "org.orekit.utils.PVCoordinates":
    """Build Orekit ``PVCoordinates`` from a ``(3,)`` position and ``(3,)`` velocity.

    The JVM-boundary idiom in one place: cast a NumPy ``(p, v)`` pair into the
    Hipparchus ``Vector3D`` pair Orekit wants. The caller must have started the
    JVM (each call site runs ``_ensure_started()`` first). Shared by
    :meth:`State._orekit_pv` and the :meth:`Trajectory.to_frame` per-sample loop so
    the float-cast convention lives in a single spot.
    """
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.utils import PVCoordinates

    return PVCoordinates(
        Vector3D(float(position[0]), float(position[1]), float(position[2])),
        Vector3D(float(velocity[0]), float(velocity[1]), float(velocity[2])),
    )


@dataclass(frozen=True)
class State:
    """An object's Cartesian position+velocity at an epoch, in an explicit frame.

    Immutable, with the frame mandatory (no defaults). No Orekit types appear in
    the field annotations. ``position``/``velocity`` are SI (meters, m/s), shape
    ``(3,)``, ``float64`` — enforced in :meth:`__post_init__` so a buggy path
    producing shape ``(1, 3)``, ``float32``, or a non-finite value fails at the
    construction site rather than surfacing later as an opaque Orekit failure.

    Immutability is real, not just frozen bindings: ``__post_init__`` defensively
    copies the input arrays and marks them read-only, so a ``State`` never aliases
    caller memory and its contents cannot change. This makes value-based ``==``
    and ``hash()`` well-defined (two ``State``s with equal fields compare equal and
    hash equal).
    """

    epoch: Epoch
    position: np.ndarray
    velocity: np.ndarray
    frame: Frame

    def __post_init__(self) -> None:
        # Type annotations don't enforce ndarray-ness; a non-array would fail on
        # .shape with an opaque AttributeError, so check it first for a clean error.
        if not isinstance(self.position, np.ndarray) or not isinstance(
            self.velocity, np.ndarray
        ):
            raise TypeError(
                "position and velocity must be numpy.ndarray, got "
                f"{type(self.position).__name__} and {type(self.velocity).__name__}"
            )
        if self.position.shape != (3,) or self.velocity.shape != (3,):
            raise ValueError(
                f"position and velocity must have shape (3,), "
                f"got {self.position.shape} and {self.velocity.shape}"
            )
        if self.position.dtype != np.float64 or self.velocity.dtype != np.float64:
            raise ValueError("position and velocity must be float64")
        # np.isfinite is False for both NaN and inf.
        if not (
            np.all(np.isfinite(self.position)) and np.all(np.isfinite(self.velocity))
        ):
            raise ValueError("position and velocity must be finite (no NaN or inf)")

        # Immutable value type (architecture §6): defensively copy so the State
        # does not alias the caller's arrays, then make the contents read-only.
        # Copying severs aliasing; the read-only flag keeps __eq__/__hash__ sound
        # (a hash must not change under the caller's feet). Frozen-dataclass
        # fields are rebound via object.__setattr__.
        pos = np.array(self.position, dtype=np.float64, copy=True)
        vel = np.array(self.velocity, dtype=np.float64, copy=True)
        pos.setflags(write=False)
        vel.setflags(write=False)
        object.__setattr__(self, "position", pos)
        object.__setattr__(self, "velocity", vel)

    def __eq__(self, other: object) -> bool:
        # The dataclass-generated __eq__ would compare the ndarray fields with
        # ``==`` and then call bool() on the result, raising "truth value ...
        # ambiguous". Compare by value instead. Exact array comparison is the
        # right semantics for a value type; cross-construction float noise makes
        # two "equivalent" states unequal, same as any float-bearing value type.
        if not isinstance(other, State):
            return NotImplemented
        return (
            self.epoch == other.epoch
            and self.frame is other.frame
            and np.array_equal(self.position, other.position)
            and np.array_equal(self.velocity, other.velocity)
        )

    def __hash__(self) -> int:
        # ndarrays are unhashable; hash their bytes. Sound because the arrays are
        # read-only (see __post_init__) so the hash is stable for the lifetime.
        return hash(
            (self.epoch, self.frame, self.position.tobytes(), self.velocity.tobytes())
        )

    def to_frame(self, target_frame: Frame) -> "State":
        """Return this state expressed in ``target_frame``.

        Crosses into Orekit: resolves both frames via :meth:`Frame.to_orekit` and
        applies the Orekit ``Transform`` between them at ``self.epoch`` to the
        position+velocity. The transform carries the frames' relative rotation
        rate, so the velocity gets the correct transport-theorem correction — e.g.
        the Earth-rotation term on an ``EME2000`` → ``ITRF`` conversion. Returns a
        new :class:`State` with freshly allocated, read-only arrays (no aliasing of
        this state's memory). ``target_frame is self.frame`` short-circuits to a
        fresh copy without starting the JVM.
        """
        if target_frame is self.frame:
            return State(self.epoch, self.position, self.velocity, target_frame)

        from .._orekit_init import _ensure_started

        _ensure_started()

        transform = self.frame.to_orekit().getTransformTo(
            target_frame.to_orekit(), self.epoch.to_orekit()
        )
        pv = transform.transformPVCoordinates(self._orekit_pv())
        return State(
            self.epoch,
            _vector3d_to_array(pv.getPosition()),
            _vector3d_to_array(pv.getVelocity()),
            target_frame,
        )

    def to_keplerian(self) -> "KeplerianElements":
        """Return the osculating classical elements in this state's own frame.

        Builds an Orekit ``KeplerianOrbit`` from the position+velocity in
        ``self.frame`` using Earth's WGS84 µ (:func:`core.bodies._earth_mu`) and
        reads back the six classical elements with the **true anomaly** as the
        canonical angle (architecture §6). No implicit frame conversion — the
        elements are computed in ``self.frame``, which must be pseudo-inertial for
        classical elements to be well-defined (a rotating frame such as ``ITRF``
        raises ``ValueError``; convert with :meth:`to_frame` first). ω, Ω, and ν
        are individually ill-conditioned as e→0 / i→0
        (finite but erratic for the near-circular LEO orbits this library targets;
        the argument of latitude is the stable combination — architecture §6).

        Near-parabolic states (osculating e→1) are unsupported: classical elements
        have no finite semi-major axis there, so :class:`KeplerianElements` rejects
        e == 1 and the read-back surfaces that as a clean ``ValueError`` (not a Java
        trace). Such orbits are outside this library's LEO target domain.
        """
        from .._orekit_init import _ensure_started

        _ensure_started()
        from org.orekit.orbits import KeplerianOrbit

        from .bodies import _earth_mu
        from .elements import KeplerianElements

        ok_frame = _require_pseudo_inertial(
            self.frame,
            "to_keplerian",
            "Convert first with state.to_frame(Frame.EME2000).",
        )

        orbit = KeplerianOrbit(
            self._orekit_pv(),
            ok_frame,
            self.epoch.to_orekit(),
            _earth_mu(),
        )
        return KeplerianElements(
            float(orbit.getA()),
            float(orbit.getE()),
            float(orbit.getI()),
            float(orbit.getRightAscensionOfAscendingNode()),
            float(orbit.getPerigeeArgument()),
            float(orbit.getTrueAnomaly()),
        )

    def _orekit_pv(self) -> "org.orekit.utils.PVCoordinates":
        """Orekit ``PVCoordinates`` for this state's position+velocity (JVM-crossing).

        Shared by :meth:`to_orekit`, :meth:`to_frame`, and :meth:`to_keplerian`;
        the caller must have started the JVM (each calls ``_ensure_started()``
        first). Frame-agnostic — the frame/epoch are attached by the caller.
        """
        return _pv(self.position, self.velocity)

    if TYPE_CHECKING:

        def to_orekit(self) -> "org.orekit.propagation.SpacecraftState": ...

    else:

        def to_orekit(self):
            """Build the Orekit ``SpacecraftState`` for this state.

            The JVM-crossing conversion: starts the JVM on first call via
            ``_ensure_started()`` (lazy-JVM contract, architecture §10). The
            state is wrapped as ``AbsolutePVCoordinates`` -> ``SpacecraftState`` —
            a frame-agnostic position+velocity snapshot at ``self.epoch`` in
            ``self.frame``. Position/velocity round-trip exactly through the
            Orekit getters regardless of frame (``isOrbitDefined()`` is ``False``).

            No gravitational parameter (mu) is attached here, by design. A
            numerical propagation's mu is the one carried by its configured
            gravity field (the ``propagation`` layer, later in Feature 1.1), so
            baking a fixed mu into this conversion would be redundant and could
            silently disagree with the field actually integrated. ``to_keplerian``
            supplies its own mu where osculating elements genuinely require one.
            """
            from .._orekit_init import _ensure_started

            _ensure_started()
            from org.orekit.propagation import SpacecraftState
            from org.orekit.utils import AbsolutePVCoordinates

            abs_pv = AbsolutePVCoordinates(
                self.frame.to_orekit(),
                self.epoch.to_orekit(),
                self._orekit_pv(),
            )
            return SpacecraftState(abs_pv)


# ---------------------------------------------------------------------------
# Trajectory metadata
# ---------------------------------------------------------------------------


class TrajectoryMetadata(TypedDict, total=False):
    """Reproducibility metadata carried on every :class:`Trajectory` (architecture §6).

    The three ``Required[...]`` keys must be present; the rest are optional and
    populated when applicable, and user code may add arbitrary extra keys.

    Runtime caveat: because this module uses ``from __future__ import
    annotations``, the field annotations are strings at runtime, so the typing
    machinery does not populate ``__required_keys__`` (it comes back empty). That
    is harmless here — static type checkers read the source and honor
    ``Required[...]``, while :meth:`Trajectory.__post_init__` enforces the
    required keys at runtime from the hard-coded ``_REQUIRED_METADATA_KEYS`` set
    rather than from ``__required_keys__``.
    """

    # Required for reproducibility (checker-enforced; runtime-validated in
    # Trajectory.__post_init__). "user" tags a hand-assembled trajectory.
    propygator_version: Required[str]
    orekit_version: Required[str]
    propagator: Required[str]  # "numerical" | "sgp4" | "user"

    # Optional — populated when applicable.
    force_models: list[str]
    integrator: str
    integrator_tolerances: dict
    output_step_s: float
    created_at: str
    spacecraft: str
    attitude: str
    name: str
    tle_line1: str
    tle_line2: str
    norad_id: (
        int  # catalog number; mirrors TLE.norad_id (architecture §6, features.md §1.3)
    )
    tle_epoch: str
    start: str

    # Termination reporting (addendum §6.6) — written ONLY when a guard stops the
    # run early (impact, escape, re-entry, or a reasonable user-limit crossing), so a
    # normal completed run's metadata (and its export_csv header) are byte-identical
    # to today. NOT added to _REQUIRED_METADATA_KEYS — these stay optional.
    terminated: bool
    termination_reason: str  # "reentry" | "impact" | "escape" | "user_min" | "user_max"
    termination_epoch: str  # ISO 8601 UTC of the crossing


# Required metadata keys, enforced at runtime in Trajectory.__post_init__ (see the
# TrajectoryMetadata runtime caveat for why __required_keys__ isn't used).
_REQUIRED_METADATA_KEYS = frozenset(
    {"propygator_version", "orekit_version", "propagator"}
)


def _propygator_version() -> str:
    """Installed propygator version, or ``"unknown"`` if not resolvable.

    Pure-Python (``importlib.metadata``) — no JVM, safe before init.
    """
    try:
        return importlib.metadata.version("propygator")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _default_metadata(propagator: str = "user") -> "TrajectoryMetadata":
    """Minimal required-key metadata for a user-assembled trajectory.

    ``orekit_version`` is ``"unknown"`` because resolving the real Orekit version
    needs the JVM, and the constructors that call this are on the safe-before-init
    surface (architecture §10); a real propagation (Feature 1) fills it in.
    """
    return {
        "propygator_version": _propygator_version(),
        "orekit_version": "unknown",
        "propagator": propagator,
    }


# ---------------------------------------------------------------------------
# Trajectory
# ---------------------------------------------------------------------------

# Orekit Ephemeris interpolation order for Trajectory.at. Samples are stored as
# raw Cartesian (p, v); the Ephemeris runs cubic Hermite on position AND velocity
# (see _ephemeris for the USE_PV filter choice that makes this so): exact at the
# sample nodes, and sub-meter between them at a 60 s LEO cadence, falling
# ~quadratically as the step shrinks. Two points is deliberate and optimal here —
# a higher order over Cartesian samples oscillates (Runge) and *worsens* accuracy,
# the interpolated velocity worst of all (verified). Users who need finer
# interpolation re-propagate with a smaller output_step.
_AT_INTERPOLATION_POINTS = 2


def _epoch_arrays_from_list(
    epochs: "list[Epoch]",
) -> "tuple[np.ndarray, np.ndarray, TimeScale]":
    """Two-double epoch arrays + shared scale from a list of Epochs.

    The per-epoch ``scale`` must be uniform across the list (architecture §6
    Epoch-input contract); preserves full femtosecond-class precision.
    """
    epoch_list = list(epochs)
    if not epoch_list:
        raise ValueError(
            "from_arrays needs at least one Epoch; pass a datetime64[ns] ndarray "
            "with epoch_scale to build an empty trajectory."
        )
    scale = epoch_list[0].scale
    for e in epoch_list:
        if not isinstance(e, Epoch):
            raise TypeError(
                f"epochs list must contain Epoch instances, got {type(e).__name__}"
            )
        if e.scale is not scale:
            raise ValueError(
                f"all epochs must share one TimeScale; got {scale} and {e.scale}"
            )
    n = len(epoch_list)
    epochs_int = np.fromiter(
        (e._int_seconds for e in epoch_list), dtype=np.int64, count=n
    )
    epochs_frac = np.fromiter(
        (e._frac_seconds for e in epoch_list), dtype=np.float64, count=n
    )
    return epochs_int, epochs_frac, scale


def _epoch_arrays_from_datetime64(
    epochs: np.ndarray, epoch_scale: TimeScale
) -> "tuple[np.ndarray, np.ndarray, TimeScale]":
    """Two-double epoch arrays from a 1-D datetime64[ns] wall-clock in ``epoch_scale``.

    The array is interpreted as wall-clock time in ``epoch_scale`` (architecture
    §6); nanosecond precision is sufficient for observational data.
    """
    if epochs.dtype != np.dtype("datetime64[ns]"):
        raise ValueError(
            f"epochs ndarray must be dtype datetime64[ns], got {epochs.dtype}"
        )
    if epochs.ndim != 1:
        raise ValueError(f"epochs ndarray must be 1-D, got shape {epochs.shape}")
    if bool(np.isnat(epochs).any()):
        raise ValueError("epochs ndarray must not contain NaT")
    vals_ns = epochs.astype("int64")  # nanoseconds since 1970-01-01 (wall-clock)
    n = vals_ns.shape[0]
    epochs_int = np.empty(n, dtype=np.int64)
    epochs_frac = np.empty(n, dtype=np.float64)
    origin = datetime(1970, 1, 1)
    # TODO(1.1): this per-sample Python loop is fine for the moderate-N skeleton
    # but is the hotspot for the ~1e5-sample bulk path (stack-compat part (c));
    # vectorize the leap-second lookup (np.searchsorted on the thresholds) then.
    for k in range(n):
        whole_s, rem_ns = divmod(int(vals_ns[k]), 1_000_000_000)
        whole_dt = origin + timedelta(seconds=whole_s)
        i_s, fr = _count_from_wallclock(whole_dt, rem_ns * 1e-9, epoch_scale)
        epochs_int[k] = i_s
        epochs_frac[k] = fr
    return epochs_int, epochs_frac, epoch_scale


@dataclass(eq=False)
class Trajectory:
    """A propagation output: column-oriented (p, v) samples over time (architecture §6).

    Backed by NumPy arrays for memory locality. Intentionally *not* a frozen
    dataclass — the ``at()`` ephemeris is cached on first call (Feature 1) — but
    the backing arrays' *contents* are made read-only in :meth:`__post_init__`;
    rebinding the attributes (e.g. ``traj.frame = ...``) is unsupported and will
    corrupt invariants. Construct via :meth:`from_states` or :meth:`from_arrays`;
    the raw ``__init__`` exists for propagator internals and must be handed a full
    required-key ``metadata`` dict.

    Equality is by identity (``eq=False``): value-comparing two large array-backed
    trajectories is expensive and unneeded, and the dataclass-generated ``__eq__``
    would raise on the ndarray fields ("truth value ... ambiguous").
    """

    _epochs_int: np.ndarray  # int64, shape (N,), TAI seconds since J2000
    _epochs_frac: np.ndarray  # float64, shape (N,), sub-second fraction
    epoch_scale: TimeScale
    positions: np.ndarray  # float64, shape (N, 3), meters
    velocities: np.ndarray  # float64, shape (N, 3), m/s
    frame: Frame
    metadata: "TrajectoryMetadata"

    def __post_init__(self) -> None:
        # UT1 epochs need EOP data (deferred — see Epoch / architecture §6); reject
        # early rather than failing later when a State is materialized.
        if self.epoch_scale is TimeScale.UT1:
            raise NotImplementedError(
                "Trajectory epoch_scale=UT1 is deferred (UT1 needs EOP data); "
                "see Epoch and architecture §6."
            )

        # 1. Metadata: required keys present (hard-coded; see TrajectoryMetadata).
        missing = _REQUIRED_METADATA_KEYS - self.metadata.keys()
        if missing:
            raise ValueError(
                f"Trajectory metadata missing required keys: {sorted(missing)}"
            )

        # 2. Backing-array types, dtypes, shapes, finiteness, consistent N.
        named = {
            "_epochs_int": self._epochs_int,
            "_epochs_frac": self._epochs_frac,
            "positions": self.positions,
            "velocities": self.velocities,
        }
        for name, arr in named.items():
            if not isinstance(arr, np.ndarray):
                raise TypeError(
                    f"{name} must be numpy.ndarray, got {type(arr).__name__}"
                )

        if self._epochs_int.dtype != np.int64:
            raise ValueError(f"_epochs_int must be int64, got {self._epochs_int.dtype}")
        for name in ("_epochs_frac", "positions", "velocities"):
            if named[name].dtype != np.float64:
                raise ValueError(f"{name} must be float64, got {named[name].dtype}")

        if self._epochs_int.ndim != 1:
            raise ValueError(
                f"_epochs_int must be 1-D, got shape {self._epochs_int.shape}"
            )
        n = self._epochs_int.shape[0]
        if self._epochs_frac.shape != (n,):
            raise ValueError(
                f"epoch arrays must share shape ({n},), got "
                f"{self._epochs_int.shape} and {self._epochs_frac.shape}"
            )
        if self.positions.shape != (n, 3) or self.velocities.shape != (n, 3):
            raise ValueError(
                f"positions and velocities must have shape ({n}, 3), got "
                f"{self.positions.shape} and {self.velocities.shape}"
            )

        for name in ("_epochs_frac", "positions", "velocities"):
            if not np.all(np.isfinite(named[name])):
                raise ValueError(f"{name} must be finite (no NaN or inf)")

        # 3. Epochs strictly increasing in time. Trajectory.at() takes the first
        #    and last samples as the span endpoints, and the Orekit Ephemeris that
        #    backs it assumes chronologically ordered, distinct samples — so an
        #    unsorted or duplicate-epoch trajectory would silently mis-bound queries
        #    or break interpolation. Enforce the invariant once here so every later
        #    path can rely on it; the two-part TAI count compares lexicographically
        #    since _epochs_frac ∈ [0, 1). n < 2 is trivially ordered.
        if n >= 2:
            d_int = np.diff(self._epochs_int)
            d_frac = np.diff(self._epochs_frac)
            if not np.all((d_int > 0) | ((d_int == 0) & (d_frac > 0))):
                raise ValueError(
                    "Trajectory epochs must be strictly increasing in time; got "
                    "out-of-order or duplicate samples."
                )

        # 4. Freeze backing-array contents (architecture §6); the attribute
        #    bindings are not enforced-immutable (see the class docstring).
        for arr in (
            self._epochs_int,
            self._epochs_frac,
            self.positions,
            self.velocities,
        ):
            arr.setflags(write=False)

    # --- sequence protocol -------------------------------------------------

    def __len__(self) -> int:
        return int(self._epochs_int.shape[0])

    def _epoch_at(self, i: int) -> Epoch:
        """Materialize the :class:`Epoch` for sample ``i`` (supports negative i)."""
        return Epoch(
            int(self._epochs_int[i]), float(self._epochs_frac[i]), self.epoch_scale
        )

    @property
    def start_epoch(self) -> Epoch:
        """The first sample's :class:`Epoch` — the start of the realized span.

        Pure-Python (no JVM). This is the lower bound :meth:`at` bounds-checks
        against; together with :attr:`end_epoch` it is the single source of truth for
        the realized span (e.g. Feature 1.4's live engine clamps ``buffer.at(...)`` to
        ``end_epoch`` rather than re-deriving the sample grid).
        """
        return self._epoch_at(0)

    @property
    def end_epoch(self) -> Epoch:
        """The last sample's :class:`Epoch` — the end of the realized span.

        Pure-Python (no JVM). The upper bound :meth:`at` bounds-checks against; see
        :attr:`start_epoch`.
        """
        return self._epoch_at(-1)

    def __getitem__(self, index: int) -> State:
        """Materialize sample ``index`` as a :class:`State` with its own arrays."""
        if isinstance(index, slice):
            raise TypeError(
                "Trajectory does not support slice indexing; iterate or build a "
                "list comprehension of States instead."
            )
        if not isinstance(index, (int, np.integer)):
            raise TypeError(
                f"Trajectory indices must be integers, got {type(index).__name__}"
            )
        return State(
            self._epoch_at(index),
            self.positions[index].copy(),
            self.velocities[index].copy(),
            self.frame,
        )

    def __iter__(self) -> "Iterator[State]":
        for i in range(len(self)):
            yield self[i]

    # --- constructors ------------------------------------------------------

    @classmethod
    def from_states(cls, states: list[State]) -> "Trajectory":
        """Build from a list of :class:`State` sharing one frame and epoch scale.

        Ergonomic for small N; for large N prefer :meth:`from_arrays`. Metadata is
        the minimal user default (architecture §6). Raises ``ValueError`` on an
        empty list or on a mixed frame / epoch scale.
        """
        if not states:
            raise ValueError("from_states requires at least one State")
        frame = states[0].frame
        scale = states[0].epoch.scale
        for s in states:
            if s.frame is not frame:
                raise ValueError(
                    f"all states must share one frame; got {frame} and {s.frame}"
                )
            if s.epoch.scale is not scale:
                raise ValueError(
                    f"all states must share one epoch scale; got {scale} and "
                    f"{s.epoch.scale}"
                )
        n = len(states)
        epochs_int = np.fromiter(
            (s.epoch._int_seconds for s in states), dtype=np.int64, count=n
        )
        epochs_frac = np.fromiter(
            (s.epoch._frac_seconds for s in states), dtype=np.float64, count=n
        )
        positions = np.array([s.position for s in states], dtype=np.float64)
        velocities = np.array([s.velocity for s in states], dtype=np.float64)
        return cls(
            epochs_int,
            epochs_frac,
            scale,
            positions,
            velocities,
            frame,
            _default_metadata(),
        )

    @classmethod
    def from_arrays(
        cls,
        epochs: "list[Epoch] | np.ndarray",
        positions: np.ndarray,
        velocities: np.ndarray,
        frame: Frame,
        epoch_scale: TimeScale = TimeScale.UTC,
        metadata: "TrajectoryMetadata | None" = None,
    ) -> "Trajectory":
        """Build from raw arrays (architecture §6 Epoch-input contract).

        ``epochs`` is either a ``list[Epoch]`` (full precision; the per-epoch
        ``scale`` must be uniform and ``epoch_scale`` is ignored) or a 1-D
        ``datetime64[ns]`` ndarray (wall-clock in ``epoch_scale``, nanosecond
        precision). ``positions`` / ``velocities`` are defensively copied so the
        caller's arrays are not frozen; they must be ``(N, 3)`` ``float64``.
        ``metadata=None`` populates the minimal required-key user default; a
        supplied ``metadata`` dict is shallow-copied so later caller mutation
        cannot alter the trajectory's record.
        """
        if isinstance(epochs, np.ndarray):
            epochs_int, epochs_frac, scale = _epoch_arrays_from_datetime64(
                epochs, epoch_scale
            )
        else:
            epochs_int, epochs_frac, scale = _epoch_arrays_from_list(epochs)

        pos = np.array(positions, copy=True)
        vel = np.array(velocities, copy=True)
        # Defensively copy caller-supplied metadata (like positions/velocities) so
        # later mutation of the caller's dict can't corrupt the trajectory's
        # reproducibility record (architecture §10). Shallow copy is enough — the
        # required keys are scalars.
        meta = _default_metadata() if metadata is None else metadata.copy()
        return cls(epochs_int, epochs_frac, scale, pos, vel, frame, meta)

    # --- interpolation / conversion (Orekit-crossing) ---------------------

    def at(self, epoch: Epoch) -> State:
        """Return the interpolated state at ``epoch`` (in this trajectory's frame).

        Builds an Orekit ``Ephemeris`` over the samples with Hermite interpolation
        (which keeps position+velocity consistent by construction), **cached on the
        trajectory on first call** and reused thereafter. The result is in this
        trajectory's frame — call :meth:`State.to_frame` on it to convert.

        Raises ``ValueError`` if ``epoch`` lies outside the trajectory's time span:
        there is no extrapolation (architecture §13). A query that needs denser
        coverage should re-propagate with a smaller ``output_step``. Needs at least
        two samples to interpolate.
        """
        n = len(self)
        if n < 2:
            raise ValueError(
                f"Trajectory.at needs at least 2 samples to interpolate, got {n}."
            )

        # Bounds check in Python on the two-part TAI count (scale-independent, so
        # the query Epoch's scale need not match the trajectory's) so an out-of-span
        # query raises a clean ValueError instead of an opaque Orekit
        # TimeStampedCacheException. (int, frac) compares as the real instant since
        # frac is in [0, 1). Samples run chronologically (a propagation output), so
        # the span endpoints are the first and last samples.
        query = (epoch._int_seconds, epoch._frac_seconds)
        first = (int(self._epochs_int[0]), float(self._epochs_frac[0]))
        last = (int(self._epochs_int[-1]), float(self._epochs_frac[-1]))
        if query < first or query > last:
            raise ValueError(
                f"epoch {epoch.to_iso()} is outside the trajectory span "
                f"[{self._epoch_at(0).to_iso()}, {self._epoch_at(-1).to_iso()}]; "
                "Trajectory.at does not extrapolate (re-propagate with a smaller "
                "output_step for denser coverage)."
            )

        ephemeris, interp_frame = self._ephemeris()
        ss = ephemeris.propagate(epoch.to_orekit())
        state = State(
            epoch,
            _vector3d_to_array(ss.getPosition()),
            _vector3d_to_array(ss.getVelocity()),
            interp_frame,
        )
        # The ephemeris is built in this trajectory's frame when that frame is
        # pseudo-inertial, else in EME2000 (Orekit's SpacecraftStateInterpolator
        # rejects a non-inertial output frame — see _ephemeris). Transform the
        # sampled state back so at() always returns a State in self.frame.
        if interp_frame is not self.frame:
            state = state.to_frame(self.frame)
        return state

    def _ephemeris(
        self,
    ) -> "tuple[org.orekit.propagation.analytical.Ephemeris, Frame]":
        """Lazily build + cache the Orekit ``Ephemeris`` backing :meth:`at`.

        Returns the ephemeris together with the propygator :class:`Frame` it is
        expressed in. The interpolation frame is this trajectory's own frame when
        that frame is pseudo-inertial (``EME2000`` / ``TEME``), but **EME2000 when
        it is not** (``ITRF``): Orekit's ``SpacecraftStateInterpolator`` requires a
        pseudo-inertial output/attitude-reference frame and raises
        ``OrekitIllegalArgumentException`` otherwise, so an Earth-fixed trajectory is
        interpolated in EME2000 and :meth:`at` transforms each sampled state back to
        ``self.frame``. A private cached Orekit reference is an allowed
        implementation detail (architecture §10) — it never appears on a public
        signature. Building it materializes one ``SpacecraftState`` per sample, so it
        is deferred to the first :meth:`at` call and reused for every subsequent query.
        """
        cached = getattr(self, "_ephemeris_cache", None)
        if cached is not None:
            return cached

        from .._orekit_init import _ensure_started

        _ensure_started()
        from java.util import ArrayList
        from org.orekit.propagation import SpacecraftState, SpacecraftStateInterpolator
        from org.orekit.propagation.analytical import Ephemeris
        from org.orekit.time import AbstractTimeInterpolator
        from org.orekit.utils import (
            AbsolutePVCoordinates,
            AngularDerivativesFilter,
            CartesianDerivativesFilter,
        )

        # SpacecraftStateInterpolator requires a pseudo-inertial output frame, so a
        # non-inertial (Earth-fixed) trajectory is interpolated in EME2000 and at()
        # transforms the result back. A pseudo-inertial frame (EME2000/TEME) is used
        # as-is, so those paths are unchanged.
        if self.frame.to_orekit().isPseudoInertial():
            interp_frame = self.frame
            source = self
        else:
            interp_frame = Frame.EME2000
            source = self.to_frame(Frame.EME2000)
        output_frame = interp_frame.to_orekit()
        # ArrayList is generic in the Java stubs, so mypy wants an element type; the
        # elements are untyped Orekit SpacecraftStates, so the annotation adds nothing.
        states = ArrayList()  # type: ignore[var-annotated]
        # Build each SpacecraftState straight from the backing arrays rather than via
        # source[i].to_orekit(): the rows are already validated and read-only
        # (__post_init__), so the State round-trip would only re-copy and re-validate
        # them per sample. output_frame and _abs_date(...) supply the frame/epoch.
        for i in range(len(source)):
            abs_pv = AbsolutePVCoordinates(
                output_frame,
                _abs_date(int(source._epochs_int[i]), float(source._epochs_frac[i])),
                _pv(source.positions[i], source.velocities[i]),
            )
            states.add(SpacecraftState(abs_pv))
        # USE_PV, not the constructor default USE_PVA: the samples carry only
        # position+velocity, while the AbsolutePVCoordinates behind each
        # SpacecraftState default their acceleration to zero. USE_PVA would treat
        # that fabricated a=0 as a real node constraint, forcing the interpolant flat
        # in acceleration where the true orbit is ~-9 m/s² — a ~900 m midpoint error
        # at a 60 s LEO cadence. USE_PV does cubic Hermite on the (p, v) actually
        # present: exact at nodes, sub-meter between them. USE_R likewise ignores the
        # absent attitude rates. The explicit extrapolation threshold and the
        # output_frame reused as the attitude-reference frame reproduce the
        # short-constructor defaults.
        interpolator = SpacecraftStateInterpolator(
            _AT_INTERPOLATION_POINTS,
            AbstractTimeInterpolator.DEFAULT_EXTRAPOLATION_THRESHOLD_SEC,
            output_frame,
            output_frame,
            CartesianDerivativesFilter.USE_PV,
            AngularDerivativesFilter.USE_R,
        )
        ephemeris = Ephemeris(states, interpolator)
        self._ephemeris_cache = (ephemeris, interp_frame)
        return self._ephemeris_cache

    def to_frame(self, frame: Frame) -> "Trajectory":
        """Return this trajectory expressed in ``frame``.

        Applies a per-sample Orekit ``Transform`` — the EME2000↔ITRF relation is
        epoch-dependent, so each sample is transformed at its own epoch and the
        velocity picks up the transport-theorem correction (e.g. the Earth-rotation
        term on EME2000 → ITRF). Returns a new :class:`Trajectory` with freshly
        allocated, read-only ``positions``/``velocities`` arrays (no view aliasing
        of this trajectory's memory); the read-only epoch arrays are shared and
        ``metadata`` is shallow-copied, since neither is frame-dependent
        (architecture §6 ``to_frame`` allocation contract). ``frame is self.frame``
        short-circuits to a fresh copy without starting the JVM.
        """
        if frame is self.frame:
            return Trajectory(
                self._epochs_int,
                self._epochs_frac,
                self.epoch_scale,
                self.positions.copy(),
                self.velocities.copy(),
                frame,
                self.metadata.copy(),
            )

        from .._orekit_init import _ensure_started

        _ensure_started()

        src = self.frame.to_orekit()
        dst = frame.to_orekit()

        n = len(self)
        new_pos = np.empty((n, 3), dtype=np.float64)
        new_vel = np.empty((n, 3), dtype=np.float64)
        # Per-sample loop: the EME2000<->ITRF transform changes with epoch, so there
        # is no single batch transform. This is the bulk-path hotspot at ~1e5 samples
        # (stack-compat part (c)), so it avoids per-sample allocations: src/dst are
        # hoisted, the date is built straight from the two-part count via _abs_date
        # (no throwaway Epoch), and the transformed getters are written directly into
        # the preallocated rows (no throwaway (3,) arrays). The rest is inherently
        # per-sample.
        for i in range(n):
            transform = src.getTransformTo(
                dst, _abs_date(int(self._epochs_int[i]), float(self._epochs_frac[i]))
            )
            pv = transform.transformPVCoordinates(
                _pv(self.positions[i], self.velocities[i])
            )
            p = pv.getPosition()
            v = pv.getVelocity()
            new_pos[i, 0], new_pos[i, 1], new_pos[i, 2] = p.getX(), p.getY(), p.getZ()
            new_vel[i, 0], new_vel[i, 1], new_vel[i, 2] = v.getX(), v.getY(), v.getZ()

        return Trajectory(
            self._epochs_int,
            self._epochs_frac,
            self.epoch_scale,
            new_pos,
            new_vel,
            frame,
            self.metadata.copy(),
        )

    def _geodetic_track(
        self,
    ) -> "tuple[Trajectory, np.ndarray, np.ndarray, np.ndarray]":
        """Return this trajectory in ITRF plus per-sample geodetic lat/lon/alt.

        Backs the module-level :func:`~propygator.core.frames.geodetic_track` that CSV
        export and the ground-track / altitude plots share. Converts to ITRF once and
        projects every sample (:func:`~propygator.core.frames.to_geodetic`), returning
        ``(itrf, latitude_deg, longitude_deg, altitude_m)`` with the three lat/lon/alt
        arrays read-only. The result is cached on the instance the same lazy
        cache-on-first-call way as the :meth:`at` ephemeris (architecture §10; the
        backing data is immutable, so the cache never goes stale). Repeated consumers
        (``plot_summary`` panels, a full ``export_all``) reuse one ITRF conversion plus
        projection instead of recomputing it 2-3x.
        """
        cached = getattr(self, "_geodetic_cache", None)
        if cached is not None:
            return cached

        itrf = self.to_frame(Frame.ITRF)
        n = len(itrf)
        lat = np.empty(n, dtype=np.float64)
        lon = np.empty(n, dtype=np.float64)
        alt = np.empty(n, dtype=np.float64)
        for i, state in enumerate(itrf):
            geo = to_geodetic(state)
            lat[i] = geo.latitude_deg
            lon[i] = geo.longitude_deg
            alt[i] = geo.altitude_m
        for arr in (lat, lon, alt):
            arr.setflags(write=False)  # shared cached arrays; guard against mutation
        self._geodetic_cache = (itrf, lat, lon, alt)
        return self._geodetic_cache

    # --- export ------------------------------------------------------------

    def to_dataframe(self) -> "pd.DataFrame":
        """Return a pandas view of the samples in the trajectory's own frame.

        Columns: ``epoch_utc`` (tz-aware UTC, dtype ``datetime64[ns, UTC]``; the
        values carry microsecond resolution since they come from ``Epoch
        .to_datetime()``), ``x_m`` / ``y_m`` / ``z_m``, ``vx_mps`` / ``vy_mps`` /
        ``vz_mps``. ``frame``, ``epoch_scale``, and a copy of ``metadata`` are
        carried in ``df.attrs``. Pure-Python — this lightweight in-frame view is
        distinct from the richer 16-column ``export_csv`` (with derived
        ITRF/geodetic columns), which lands in ``io.exports`` with Feature 1.
        """
        import pandas as pd

        n = len(self)
        # Pin the column unit to ns so the dtype is deterministic: pandas would
        # otherwise infer [us] from the microsecond-resolution datetimes (and [s]
        # for an empty trajectory), which surprises dtype-sensitive callers.
        # TODO(1.1): the per-sample Epoch.to_datetime() list comp is the bulk-path
        # hotspot exercised by stack-compat part (c) at ~1e5 samples; vectorize the
        # count->datetime conversion when that test lands.
        epoch_utc = pd.to_datetime(
            [self._epoch_at(i).to_datetime() for i in range(n)], utc=True
        ).as_unit("ns")
        df = pd.DataFrame(
            {
                "epoch_utc": epoch_utc,
                "x_m": self.positions[:, 0],
                "y_m": self.positions[:, 1],
                "z_m": self.positions[:, 2],
                "vx_mps": self.velocities[:, 0],
                "vy_mps": self.velocities[:, 1],
                "vz_mps": self.velocities[:, 2],
            }
        )
        df.attrs["frame"] = self.frame.value
        df.attrs["epoch_scale"] = self.epoch_scale.value
        df.attrs["metadata"] = dict(self.metadata)
        return df


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------

# Below this magnitude a quaternion component is treated as "zero" when picking
# the canonical sign (a unit quaternion always has a larger component to anchor
# the choice). Well above float round-off, well below any meaningful component.
_QUAT_SIGN_TOL = 1e-9


def _canonicalize_quaternion_sign(q: np.ndarray) -> None:
    """Flip ``q`` in place so one representative stands for the rotation.

    A unit quaternion and its negation denote the same rotation. Picking ``w >=
    0`` is ambiguous for 180-degree rotations where ``w`` is ~0 (and its sign is
    pure round-off), which would store ``q`` and ``-q`` with opposite signs. Anchor
    on the first significantly-nonzero component of ``(w, x, y, z)`` instead, so an
    exact ``q`` / ``-q`` pair always canonicalizes to the same array.
    """
    for comp in q:
        if comp > _QUAT_SIGN_TOL:
            break
        if comp < -_QUAT_SIGN_TOL:
            q *= -1.0
            break
    # Normalize signed zeros to +0.0. The flip turns 0.0 into -0.0, which compares
    # equal under np.array_equal but has a different byte pattern — so without this
    # q and -q would hash differently despite comparing equal. (x + 0.0 leaves
    # every value unchanged except -0.0, which becomes +0.0.)
    q += 0.0


@dataclass(frozen=True)
class Orientation:
    """A propygator-native body→inertial rotation (architecture §6).

    Stored canonically as a unit quaternion ``(w, x, y, z)``, sign-normalized so
    that ``q`` and ``-q`` (which denote the same rotation) store identically and
    therefore ``==``/``hash`` equal. The sign is anchored on the first
    significantly-nonzero component (``w >= 0`` alone is ambiguous for 180-degree
    rotations where ``w`` is ~0). Construct via
    :meth:`from_quaternion`, :meth:`from_axis_angle`, or :meth:`from_matrix`,
    which normalize and validate. Only :meth:`to_orekit` (the Hipparchus
    ``Rotation``) touches the JVM and is deferred to Feature 1. Attitude rates are
    out of scope for v1 — orientation only.
    """

    # (4,) float64, unit-norm, (w, x, y, z); sign-canonicalized so the first
    # significantly-nonzero component is >= 0 (not simply w >= 0 — see the class
    # docstring and _canonicalize_quaternion_sign).
    _quaternion: np.ndarray

    def __post_init__(self) -> None:
        q = self._quaternion
        if not isinstance(q, np.ndarray):
            raise TypeError(
                f"_quaternion must be numpy.ndarray, got {type(q).__name__}"
            )
        if q.shape != (4,):
            raise ValueError(f"_quaternion must have shape (4,), got {q.shape}")
        if q.dtype != np.float64:
            raise ValueError(f"_quaternion must be float64, got {q.dtype}")
        if not np.all(np.isfinite(q)):
            raise ValueError("_quaternion must be finite (no NaN or inf)")
        norm = float(np.linalg.norm(q))
        if not math.isclose(norm, 1.0, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(
                f"_quaternion must be unit-norm, got {norm!r}; construct via "
                "from_quaternion / from_axis_angle / from_matrix."
            )
        q.setflags(write=False)

    def __eq__(self, other: object) -> bool:
        # The dataclass-generated __eq__ would call bool() on an array comparison
        # ("truth value ... ambiguous"). Compare the canonical quaternions by
        # value; canonicalization (see _canonicalize_quaternion_sign) guarantees
        # an exact q / -q pair stores identical arrays, so this honors the
        # documented "q and -q compare equal" contract.
        if not isinstance(other, Orientation):
            return NotImplemented
        return np.array_equal(self._quaternion, other._quaternion)

    def __hash__(self) -> int:
        # ndarrays are unhashable; hash the bytes of the read-only quaternion.
        return hash(self._quaternion.tobytes())

    @classmethod
    def from_quaternion(cls, w: float, x: float, y: float, z: float) -> "Orientation":
        """Build from quaternion components (normalized; sign-canonicalized so the
        first significantly-nonzero component of (w, x, y, z) is >= 0)."""
        q = np.array([w, x, y, z], dtype=np.float64)
        if not np.all(np.isfinite(q)):
            raise ValueError("quaternion components must be finite")
        norm = float(np.linalg.norm(q))
        if norm < 1e-12:
            raise ValueError(f"quaternion must be non-zero, got norm {norm!r}")
        q = q / norm
        _canonicalize_quaternion_sign(q)
        return cls(np.ascontiguousarray(q, dtype=np.float64))

    @classmethod
    def from_axis_angle(
        cls, axis: "tuple[float, float, float] | np.ndarray", angle_rad: float
    ) -> "Orientation":
        """Build from a rotation ``axis`` and ``angle_rad`` (right-handed, radians)."""
        a = np.asarray(axis, dtype=np.float64)
        if a.shape != (3,):
            raise ValueError(f"axis must have shape (3,), got {a.shape}")
        if not np.all(np.isfinite(a)) or not math.isfinite(angle_rad):
            raise ValueError("axis and angle_rad must be finite")
        norm = float(np.linalg.norm(a))
        if norm < 1e-12:
            raise ValueError(f"axis must be non-zero, got norm {norm!r}")
        u = a / norm
        half = 0.5 * float(angle_rad)
        s = math.sin(half)
        return cls.from_quaternion(math.cos(half), s * u[0], s * u[1], s * u[2])

    @classmethod
    def from_matrix(cls, matrix: np.ndarray) -> "Orientation":
        """Build from a 3x3 proper rotation matrix (orthonormal, det = +1)."""
        m = np.asarray(matrix, dtype=np.float64)
        if m.shape != (3, 3):
            raise ValueError(f"matrix must have shape (3, 3), got {m.shape}")
        if not np.all(np.isfinite(m)):
            raise ValueError("matrix must be finite (no NaN or inf)")
        if not np.allclose(m @ m.T, np.eye(3), rtol=0.0, atol=1e-6):
            raise ValueError("matrix must be orthonormal (R @ R.T == I)")
        det = float(np.linalg.det(m))
        if not math.isclose(det, 1.0, rel_tol=0.0, abs_tol=1e-6):
            raise ValueError(
                f"matrix must be a proper rotation (det == +1), got {det!r}"
            )
        # Trace ("Shepperd") method, picking the largest divisor for stability.
        t = m[0, 0] + m[1, 1] + m[2, 2]
        if t > 0.0:
            s = math.sqrt(t + 1.0) * 2.0
            w = 0.25 * s
            x = (m[2, 1] - m[1, 2]) / s
            y = (m[0, 2] - m[2, 0]) / s
            z = (m[1, 0] - m[0, 1]) / s
        elif m[0, 0] > m[1, 1] and m[0, 0] > m[2, 2]:
            s = math.sqrt(1.0 + m[0, 0] - m[1, 1] - m[2, 2]) * 2.0
            w = (m[2, 1] - m[1, 2]) / s
            x = 0.25 * s
            y = (m[0, 1] + m[1, 0]) / s
            z = (m[0, 2] + m[2, 0]) / s
        elif m[1, 1] > m[2, 2]:
            s = math.sqrt(1.0 + m[1, 1] - m[0, 0] - m[2, 2]) * 2.0
            w = (m[0, 2] - m[2, 0]) / s
            x = (m[0, 1] + m[1, 0]) / s
            y = 0.25 * s
            z = (m[1, 2] + m[2, 1]) / s
        else:
            s = math.sqrt(1.0 + m[2, 2] - m[0, 0] - m[1, 1]) * 2.0
            w = (m[1, 0] - m[0, 1]) / s
            x = (m[0, 2] + m[2, 0]) / s
            y = (m[1, 2] + m[2, 1]) / s
            z = 0.25 * s
        return cls.from_quaternion(w, x, y, z)

    def as_quaternion(self) -> np.ndarray:
        """Return a writable copy of the unit quaternion ``(w, x, y, z)`` (sign-
        canonicalized: first significantly-nonzero component >= 0)."""
        return self._quaternion.copy()

    if TYPE_CHECKING:

        def to_orekit(
            self,
        ) -> "org.hipparchus.geometry.euclidean.threed.Rotation": ...

    else:

        def to_orekit(self):
            """Build the Hipparchus ``Rotation`` for this orientation (JVM-crossing).

            Starts the JVM on first call via ``_ensure_started()`` (lazy-JVM
            contract, architecture §10), then constructs the rotation from the
            stored unit quaternion ``(w, x, y, z)`` — Hipparchus'
            ``Rotation(q0, q1, q2, q3, needsNormalization)`` takes ``q0`` as the
            scalar part. The quaternion is already unit-norm and sign-canonicalized,
            so the ``needsNormalization`` pass is a no-op safeguard; ``q`` and
            ``-q`` denote the same rotation, so the result is independent of the
            stored sign convention.
            """
            from .._orekit_init import _ensure_started

            _ensure_started()
            from org.hipparchus.geometry.euclidean.threed import Rotation

            q = self._quaternion
            return Rotation(float(q[0]), float(q[1]), float(q[2]), float(q[3]), True)
