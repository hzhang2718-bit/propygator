"""``State`` — the canonical "where is this object, when, in what frame."

A :class:`State` is an immutable Cartesian position+velocity at an :class:`Epoch`
in an explicit :class:`Frame`. Construction and validation are pure-Python and
safe before JVM init (architecture §10); only the deferred conversion methods
(:meth:`State.to_frame`, :meth:`State.to_keplerian`, :meth:`State.to_orekit`)
touch Orekit, and they land with Feature 1.
"""

from __future__ import annotations

import importlib.metadata
import math
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Required, TypedDict

import numpy as np

from .frames import Frame
from .time import Epoch, TimeScale, _count_from_wallclock

if TYPE_CHECKING:
    # Type-only. The org.* namespaces are runtime JPype stubs; pandas is imported
    # lazily inside to_dataframe so importing the package stays cheap.
    import org.hipparchus.geometry.euclidean.threed  # noqa: F401
    import org.orekit.propagation  # noqa: F401
    import pandas as pd  # noqa: F401

    from .elements import KeplerianElements  # noqa: F401


_FEATURE1_NOTE = (
    "{name} is deferred to Feature 1 (numerical propagator). It performs an "
    "Orekit-backed conversion, so it is not part of the pure-Python, "
    "safe-before-init surface (architecture §10)."
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
        """Return this state expressed in ``target_frame`` (deferred to Feature 1)."""
        raise NotImplementedError(_FEATURE1_NOTE.format(name="State.to_frame"))

    def to_keplerian(self) -> "KeplerianElements":
        """Return the osculating classical elements (deferred to Feature 1)."""
        raise NotImplementedError(_FEATURE1_NOTE.format(name="State.to_keplerian"))

    if TYPE_CHECKING:

        def to_orekit(self) -> "org.orekit.propagation.SpacecraftState": ...

    else:

        def to_orekit(self):
            """Build the Orekit ``SpacecraftState`` (deferred to Feature 1)."""
            raise NotImplementedError(_FEATURE1_NOTE.format(name="State.to_orekit"))


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
    norad_id: str  # architecture §6 types this str (features.md 1.3 shows an int)
    tle_epoch: str
    start: str


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

        # 3. Freeze backing-array contents (architecture §6); the attribute
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

    # --- deferred to Feature 1 --------------------------------------------

    def at(self, epoch: Epoch) -> State:
        """Interpolated state lookup (deferred to Feature 1)."""
        raise NotImplementedError(_FEATURE1_NOTE.format(name="Trajectory.at"))

    def to_frame(self, frame: Frame) -> "Trajectory":
        """Return this trajectory expressed in ``frame`` (deferred to Feature 1)."""
        raise NotImplementedError(_FEATURE1_NOTE.format(name="Trajectory.to_frame"))

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

    _quaternion: np.ndarray  # (4,) float64, unit-norm, w >= 0; (w, x, y, z)

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
        """Build from quaternion components (normalized; sign-canonicalized to w>=0)."""
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
        """Return a writable copy of the unit quaternion ``(w, x, y, z)`` (w >= 0)."""
        return self._quaternion.copy()

    if TYPE_CHECKING:

        def to_orekit(
            self,
        ) -> "org.hipparchus.geometry.euclidean.threed.Rotation": ...

    else:

        def to_orekit(self):
            """Build the Hipparchus ``Rotation`` (deferred to Feature 1)."""
            raise NotImplementedError(
                _FEATURE1_NOTE.format(name="Orientation.to_orekit")
            )
