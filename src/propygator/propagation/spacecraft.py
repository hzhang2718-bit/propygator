"""``SpacecraftConfig`` / ``SpacecraftGeometry`` and the variable-Cd tables.

The spacecraft's physical description — mass plus an external geometry carrying its
surface-interaction coefficients — and the Tier A ``VariableCd`` lookup table
machinery (features.md §1.1). Everything here is **pure-Python and safe before
init** (architecture §10): construction and validation never touch Orekit or start
the JVM. The custom ``DragSensitive`` that *consumes* a :class:`VariableCd` at
runtime is built inside ``propagate_numerical`` (build-plan chunk 8), never at
geometry construction — that keeps this factory on the safe-before-init surface.

**Why coefficients live on the geometry.** Orekit parameterizes *drag* with a
single Cd for both supported geometries, but parameterizes *radiation* differently
per surface model: the sphere takes one reflectivity coefficient Cr; the box
(``BoxAndSolarArraySpacecraft``) takes an absorption and a specular coefficient,
each in [0, 1] (diffuse is the remainder). A single ``Cr`` field could not drive
the box, so each geometry's coefficients live on its own factory (features.md §1.1).

**Variable Cd (Tier A).** :class:`VariableCd` is a 2-D ``(geocentric radius, total
density)`` table keying on quantities Orekit hands the drag force at runtime — so
it sidesteps re-querying the atmosphere per substep (features.md "Drag-coefficient
modeling"). It applies to **both** sphere and box (one scalar Cd, uniform across
faces). :class:`BoxFaceCd` (Tier B — adds a body-frame face-flow-incidence axis) is a
per-face, incidence-resolved free-molecular table for a **convex box** (general
upgrades 1, "Tier B Drag"): one universal ``(geocentric radius, total density,
face-flow angle θ)`` table whose value is a single face's Cd referenced to its full
area, summed over the box's six faces at runtime. It is accepted only by
:meth:`SpacecraftGeometry.box_and_panels` with ``solar_array_area_m2 == 0`` (a convex
bus, no arrays); the per-face acceleration sum is built inside ``propagate_numerical``.

**Metadata.** :func:`_serialize_spacecraft` builds the deterministic ``spacecraft``
metadata string (features.md §1.1), mirroring the facts-driven serializer pattern of
:mod:`propygator.propagation.force_models`. A table records ``Cd=table:<name-or-hash>``
— the content hash folds in the table's axis set so a 2-D and an incidence table
for the same geometry do not collide.
"""

from __future__ import annotations

import hashlib
import math
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

# --- shared table helpers --------------------------------------------------


def _as_readonly(arr: NDArray[np.float64]) -> NDArray[np.float64]:
    """Return a contiguous float64 *copy* of ``arr`` with the write flag cleared.

    Tables defensively copy their inputs and freeze them, matching the array-backed
    value-type idiom in ``core/`` (``State`` / ``Orientation``): callers cannot
    mutate a constructed table through the array they passed in.
    """
    out = np.array(arr, dtype=np.float64)
    out.setflags(write=False)
    return out


def _validate_axis(name: str, axis: NDArray[np.float64]) -> NDArray[np.float64]:
    """Validate and freeze a 1-D, finite, strictly increasing table axis.

    Takes a single owned float64 copy of ``axis`` up front, so callers pass their raw
    input directly (no second copy) and cannot mutate the frozen result through the
    array they handed in.
    """
    arr = np.array(axis, dtype=np.float64)  # one owned copy; validate and freeze it
    if arr.ndim != 1 or arr.size < 2:
        raise ValueError(
            f"{name} must be a 1-D array with >= 2 entries, got shape {arr.shape}"
        )
    if not np.all(np.isfinite(arr)):
        raise ValueError(f"{name} must be finite")
    if not np.all(np.diff(arr) > 0.0):
        raise ValueError(f"{name} must be strictly increasing")
    arr.setflags(write=False)
    return arr


def _content_hash(kind: str, arrays: tuple[NDArray[np.float64], ...]) -> str:
    """Stable short content hash over a table's kind tag and all its arrays.

    The ``kind`` tag ("cd2d" / "cd_boxface") is folded in so a 2-D table and a
    per-face incidence table built from the same grid do not collide (features.md
    §1.1). Used for the ``Cd=table:<hash>`` token and ``__hash__`` / ``__eq__``.
    """
    digest = hashlib.sha256()
    digest.update(kind.encode("utf-8"))
    for arr in arrays:
        # Shape + raw bytes: distinguishes same-bytes-different-shape grids. Force a
        # little-endian float64 layout ("<f8") so the token is identical across
        # platforms — native byte order would otherwise leak into the hash on a
        # big-endian machine and break cross-platform reproducibility comparisons.
        digest.update(str(arr.shape).encode("utf-8"))
        digest.update(np.ascontiguousarray(arr, dtype="<f8").tobytes())
    return digest.hexdigest()[:16]


def _clamp_to_axis(value: float, axis: NDArray[np.float64]) -> tuple[float, bool]:
    """Clamp ``value`` into ``[axis[0], axis[-1]]``; report whether it was clamped."""
    lo = float(axis[0])
    hi = float(axis[-1])
    if value < lo:
        return lo, True
    if value > hi:
        return hi, True
    return value, False


def _bilinear(
    grid: NDArray[np.float64],
    radius_axis: NDArray[np.float64],
    density_axis: NDArray[np.float64],
    radius: float,
    density: float,
) -> float:
    """Bilinear interpolation of ``grid[radius, density]`` at an in-range point.

    ``radius`` / ``density`` must already be clamped into the axis spans. Linear in
    the raw physical axis coordinates as supplied — this stays a general grid
    interpolator and does not special-case the axis spacing.

    Note the shipped ``sphere_default`` table samples density on a *log*-spaced axis
    and was regridded by its generator in log10(density), whereas this consumer
    interpolates linearly in raw density between nodes. Across one ~1.86x-wide density
    cell the two schemes differ by only ~0.1-0.3% of Cd — far below thermospheric
    density uncertainty — so the simpler raw-linear interpolation is kept. If that
    error ever needs tightening, interpolate the density fraction in log space to match
    the generator (an opt-in worth adding to :meth:`VariableCd.from_table`).
    """
    i = int(np.searchsorted(radius_axis, radius)) - 1
    j = int(np.searchsorted(density_axis, density)) - 1
    i = min(max(i, 0), radius_axis.size - 2)
    j = min(max(j, 0), density_axis.size - 2)

    r0, r1 = float(radius_axis[i]), float(radius_axis[i + 1])
    d0, d1 = float(density_axis[j]), float(density_axis[j + 1])
    tr = 0.0 if r1 == r0 else (radius - r0) / (r1 - r0)
    td = 0.0 if d1 == d0 else (density - d0) / (d1 - d0)

    c00 = float(grid[i, j])
    c01 = float(grid[i, j + 1])
    c10 = float(grid[i + 1, j])
    c11 = float(grid[i + 1, j + 1])
    return (
        c00 * (1.0 - tr) * (1.0 - td)
        + c10 * tr * (1.0 - td)
        + c01 * (1.0 - tr) * td
        + c11 * tr * td
    )


def _trilinear(
    grid: NDArray[np.float64],
    radius_axis: NDArray[np.float64],
    density_axis: NDArray[np.float64],
    incidence_axis: NDArray[np.float64],
    radius: float,
    density: float,
    theta: float,
) -> float:
    """Trilinear interpolation of ``grid[radius, density, incidence]`` (8 corners).

    The per-face twin of :func:`_bilinear` for :class:`BoxFaceCd`. ``radius`` /
    ``density`` must already be clamped into their axis spans (the caller clamps them
    with the edge-aware warn-once). ``theta`` is **not** clamped: it is a bounded
    face-flow angle in ``[0, π]`` — the full span of ``incidence_axis`` — so a real
    incidence always lands in range, and there is no incidence seam to warn about
    (general upgrades 1, "Tier B Drag"). Linear in the raw physical axis coordinates,
    matching :func:`_bilinear` (the same raw-vs-log density-cell note applies).
    """
    i = int(np.searchsorted(radius_axis, radius)) - 1
    j = int(np.searchsorted(density_axis, density)) - 1
    k = int(np.searchsorted(incidence_axis, theta)) - 1
    i = min(max(i, 0), radius_axis.size - 2)
    j = min(max(j, 0), density_axis.size - 2)
    k = min(max(k, 0), incidence_axis.size - 2)

    r0, r1 = float(radius_axis[i]), float(radius_axis[i + 1])
    d0, d1 = float(density_axis[j]), float(density_axis[j + 1])
    t0, t1 = float(incidence_axis[k]), float(incidence_axis[k + 1])
    tr = 0.0 if r1 == r0 else (radius - r0) / (r1 - r0)
    td = 0.0 if d1 == d0 else (density - d0) / (d1 - d0)
    tt = 0.0 if t1 == t0 else (theta - t0) / (t1 - t0)

    c000, c001 = float(grid[i, j, k]), float(grid[i, j, k + 1])
    c010, c011 = float(grid[i, j + 1, k]), float(grid[i, j + 1, k + 1])
    c100, c101 = float(grid[i + 1, j, k]), float(grid[i + 1, j, k + 1])
    c110, c111 = float(grid[i + 1, j + 1, k]), float(grid[i + 1, j + 1, k + 1])
    return (
        c000 * (1.0 - tr) * (1.0 - td) * (1.0 - tt)
        + c100 * tr * (1.0 - td) * (1.0 - tt)
        + c010 * (1.0 - tr) * td * (1.0 - tt)
        + c110 * tr * td * (1.0 - tt)
        + c001 * (1.0 - tr) * (1.0 - td) * tt
        + c101 * tr * (1.0 - td) * tt
        + c011 * (1.0 - tr) * td * tt
        + c111 * tr * td * tt
    )


# Edge-aware clamp warnings (addendum §6.2). Out-of-grid inputs still clamp to the
# nearest edge per axis (features.md §1.1); the message is tailored to the boundary,
# because the two altitude edges are physically asymmetric — below the table's lower
# edge the drag model is invalid and the force is large (loud), while above the upper
# edge drag is negligible (soft). A density-only clamp is a data-range edge, not an
# altitude regime (neutral). Keyed by the boundary names used in `_warn_edge_once`.
_CLAMP_EDGE_MESSAGES = {
    "radius_low": (
        "Cd-table geocentric radius below the drag-table grid (lower altitude edge): "
        "Cd is clamped to the edge value and is unreliable below the validated "
        "drag-table floor. This warning is emitted once."
    ),
    "radius_high": (
        "Cd-table geocentric radius above the drag-table grid (upper altitude edge): "
        "drag is negligible at this altitude, so the clamped Cd has minimal effect. "
        "This warning is emitted once."
    ),
    "density": (
        "Cd-table total density outside the table grid: clamping to the nearest "
        "edge. This warning is emitted once."
    ),
}


# --- Tier A: VariableCd -----------------------------------------------------


class VariableCd:
    """A density-varying scalar drag coefficient (Tier A; sphere and box).

    A 2-D ``(geocentric radius [m], total density [kg/m^3])`` lookup, or a callable
    of the same two arguments. Construct via the factories — :meth:`from_table`,
    :meth:`from_callable`, or the shipped :meth:`sphere_default` — never directly.

    Pure-Python and safe to construct before init. The custom ``DragSensitive`` that
    evaluates it per integration substep is built inside ``propagate_numerical``
    (build-plan chunk 8); this object just supplies the scalar Cd via
    :meth:`__call__`. A sphere has no incidence dependence, so ``(radius, density)``
    fully determines its Cd; a box keeps Orekit's attitude-driven projected-area
    bookkeeping and only the scalar Cd it applies is replaced by the table value
    (per-face incidence is Tier B — :class:`BoxFaceCd`).

    Out-of-grid inputs **clamp to the nearest edge per axis with a one-time
    warning** (features.md §1.1): raising would crash a long propagation mid-run, and
    extrapolating would fabricate Cd values.
    """

    __slots__ = (
        "_grid",
        "_radius_axis",
        "_density_axis",
        "_callable",
        "_name",
        "_content_hash",
        "_clamp_warned_edges",
    )

    def __init__(
        self,
        *,
        grid: NDArray[np.float64] | None,
        radius_axis: NDArray[np.float64] | None,
        density_axis: NDArray[np.float64] | None,
        callable_: Callable[[float, float], float] | None,
        name: str | None,
        content_hash: str,
    ) -> None:
        # Private constructor: the public factories enforce the two valid backings
        # (a frozen grid+axes, or a callable). Stored read-only; value identity is
        # the content hash (see __eq__ / __hash__).
        self._grid = grid
        self._radius_axis = radius_axis
        self._density_axis = density_axis
        self._callable = callable_
        self._name = name
        self._content_hash = content_hash
        self._clamp_warned_edges: set[str] = set()  # warn-once-per-boundary state

    @classmethod
    def from_table(
        cls,
        grid: NDArray[np.float64],
        *,
        radius_axis: NDArray[np.float64],
        density_axis: NDArray[np.float64],
        name: str | None = None,
    ) -> "VariableCd":
        """Build a table from a ``(radius, density)`` grid and its two axes.

        ``grid`` has shape ``(len(radius_axis), len(density_axis))``; both axes are
        SI (radius in meters, density in kg/m^3), strictly increasing and finite.
        ``name`` overrides the content hash in metadata (the shipped table uses
        ``"sphere_default"``); leave it ``None`` for a user table.
        """
        radius = _validate_axis("radius_axis", radius_axis)
        density = _validate_axis("density_axis", density_axis)
        grid_arr = np.asarray(grid, dtype=np.float64)
        if grid_arr.shape != (radius.size, density.size):
            raise ValueError(
                f"grid shape {grid_arr.shape} must equal "
                f"(len(radius_axis), len(density_axis)) = {(radius.size, density.size)}"
            )
        if not np.all(np.isfinite(grid_arr)):
            raise ValueError("grid must be finite (no NaN/inf)")
        grid_arr = _as_readonly(grid_arr)
        return cls(
            grid=grid_arr,
            radius_axis=radius,
            density_axis=density,
            callable_=None,
            name=name,
            content_hash=_content_hash("cd2d", (grid_arr, radius, density)),
        )

    @classmethod
    def from_callable(cls, fn: Callable[[float, float], float]) -> "VariableCd":
        """Wrap ``fn(radius_m, density_kgm3) -> Cd`` as a variable Cd.

        The escape hatch for an analytic Cd. **Not byte-reproducible**: the metadata
        records the callable's name, not its contents (the same gap noted for
        ``CustomAttitude``), so two different callables sharing a name collide in
        metadata. Prefer :meth:`from_table` for a reproducible run.
        """
        if not callable(fn):
            raise ValueError(f"fn must be callable, got {type(fn).__name__}")
        name = getattr(fn, "__name__", None) or repr(fn)
        return cls(
            grid=None,
            radius_axis=None,
            density_axis=None,
            callable_=fn,
            name=name,
            # A callable has no inspectable content; identify it by name only.
            content_hash=hashlib.sha256(
                ("callable:" + name).encode("utf-8")
            ).hexdigest()[:16],
        )

    @classmethod
    def sphere_default(cls) -> "VariableCd":
        """Load the shipped sphere Cd table from ``data/`` (generated offline).

        The committed asset is produced by
        ``scripts/generate_sphere_cd_table.py`` (a maintainer step) and loaded here;
        end users compute nothing. Metadata records ``Cd=table:sphere_default``.
        """
        path = _data_dir() / _SPHERE_DEFAULT_FILENAME
        if not path.is_file():
            raise FileNotFoundError(
                f"sphere_default Cd table not found at {path}. It is a committed "
                f"asset under data/; regenerate it with "
                f"`python scripts/generate_sphere_cd_table.py` if missing."
            )
        with np.load(path) as npz:
            grid = npz["grid"]
            radius_axis = npz["radius_axis"]
            density_axis = npz["density_axis"]
        return cls.from_table(
            grid,
            radius_axis=radius_axis,
            density_axis=density_axis,
            name="sphere_default",
        )

    def __call__(self, radius_m: float, density_kgm3: float) -> float:
        """Scalar Cd at a geocentric radius [m] and total density [kg/m^3].

        Table backing interpolates bilinearly and clamps out-of-grid inputs to the
        nearest edge per axis, warning once *per boundary* with an edge-tailored
        message (addendum §6.2). Callable backing forwards, then validates the
        returned Cd. A non-finite ``radius_m`` / ``density_kgm3`` raises
        ``ValueError``: NaN slips past the clamp's ``<`` / ``>`` comparisons
        unflagged and would otherwise poison the drag acceleration with a silent NaN.
        """
        r_in = float(radius_m)
        d_in = float(density_kgm3)
        if not (math.isfinite(r_in) and math.isfinite(d_in)):
            raise ValueError(
                "VariableCd requires finite (radius_m, density_kgm3); got "
                f"({radius_m!r}, {density_kgm3!r})."
            )
        if self._callable is not None:
            cd = float(self._callable(r_in, d_in))
            if not math.isfinite(cd) or cd < 0.0:
                raise ValueError(
                    f"VariableCd callable {self._name!r} returned an invalid Cd "
                    f"{cd!r} at (radius_m={r_in!r}, density_kgm3={d_in!r}); the drag "
                    "coefficient must be finite and >= 0."
                )
            return cd
        assert self._grid is not None  # narrow for type-checkers: table backing
        assert self._radius_axis is not None
        assert self._density_axis is not None
        r, _ = _clamp_to_axis(r_in, self._radius_axis)
        d, d_clamped = _clamp_to_axis(d_in, self._density_axis)
        # Edge-aware drag-regime warnings (addendum §6.2): which boundary was crossed
        # decides the message (radius low = loud invalid-floor; radius high = soft
        # negligible-drag; density = neutral data-range edge). Warn once per boundary.
        if r_in < self._radius_axis[0]:
            self._warn_edge_once("radius_low")
        elif r_in > self._radius_axis[-1]:
            self._warn_edge_once("radius_high")
        if d_clamped:
            self._warn_edge_once("density")
        return _bilinear(self._grid, self._radius_axis, self._density_axis, r, d)

    def _reset_edge_warnings(self) -> None:
        """Clear the warn-once-per-boundary state so the next propagation re-warns.

        ``propagate_numerical`` calls this once when it wires the drag force, giving the
        table-edge warnings the same **once-per-run** scope as the Kn-floor warn-once
        hook (``numerical._build_drag_sensitive``). Without it, a ``VariableCd`` reused
        across several propagations would stay silent after the first run, even though
        each run re-enters the same out-of-grid regime.
        """
        self._clamp_warned_edges.clear()

    def _warn_edge_once(self, edge: str) -> None:
        """Emit the edge-tailored clamp warning for ``edge`` once per boundary per run.

        ``propagate_numerical`` resets the per-boundary state each run via
        :meth:`_reset_edge_warnings`, so "once" is once-per-propagation (matching the
        Kn-floor warn-once hook), not once for the object's whole lifetime.
        """
        if edge in self._clamp_warned_edges:
            return
        self._clamp_warned_edges.add(edge)
        warnings.warn(
            _CLAMP_EDGE_MESSAGES[edge],
            # stacklevel=2 points at the __call__ site (the Cd lookup). During a
            # propagation __call__ is invoked from inside Orekit's integration loop
            # via JPype, so there is no stable Python caller frame to surface; a
            # higher stacklevel would just report an arbitrary internal location.
            stacklevel=2,
        )

    def _metadata_id(self) -> str:
        """The ``<name-or-hash>`` written as ``Cd=table:<...>`` in metadata."""
        return self._name if self._name is not None else self._content_hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VariableCd):
            return NotImplemented
        return self._content_hash == other._content_hash and self._name == other._name

    def __hash__(self) -> int:
        return hash((self._content_hash, self._name))

    def __repr__(self) -> str:
        return f"VariableCd(id={self._metadata_id()!r})"


# --- Tier B: BoxFaceCd (per-face incidence table, convex box) ---------------


class BoxFaceCd:
    """Per-face incidence-resolved free-molecular drag coefficient (Tier B; convex box).

    A 3-D ``(geocentric radius [m], total density [kg/m^3], face-flow angle θ [rad])``
    lookup, or a callable of the same three arguments. The value is **one face's** Cd
    referenced to that face's **full** area, as a function of the angle θ between the
    face's outward normal and the incoming flow over the full ``θ ∈ [0, π]`` (0 head-on,
    π/2 edge-on, π fully leeward). The incidence projection is already baked in: the
    normal-pressure part falls off as ``cos θ``, but the tangential-shear part floors at
    ~0.07 edge-on and tapers to ~0 by θ ≈ 110°, so the table spans the leeward half and
    every face is a direct lookup (general upgrades 1, "Tier B Drag").

    Construct via the factories — :meth:`default`, :meth:`from_table`, or
    :meth:`from_callable` — never directly. Pure-Python and safe to construct before
    init. Because the coefficient is per-unit-area and geometry-independent, **one**
    table serves every convex box and plate; the per-face acceleration sum
    ``CdA = Σ Cd_i · A_i`` over the box's six faces is built inside
    ``propagate_numerical``. It is accepted only by
    :meth:`SpacecraftGeometry.box_and_panels` with ``solar_array_area_m2 == 0`` (a
    convex bus); a paneled box or a sphere is rejected at construction.

    Out-of-grid ``(radius, density)`` inputs **clamp to the nearest edge per axis with a
    one-time warning** (the same edge-aware policy as :class:`VariableCd`). The θ axis
    spans the full ``[0, π]``, so a real face-flow angle never falls outside it — there
    is no incidence clamp, wrap, or seam.

    **When it matters (scenario-dependent, honest).** The per-face correction is
    attitude-correlated, so its orbit-level benefit depends on how the body flies.
    For **face-on / nadir-held / tumbling / Sun-pointing** flight a best-fit
    *physical* constant Cd (or :class:`VariableCd`) absorbs almost all of it
    (< 1 % along-track over a multi-day LEO run), and ``BoxFaceCd`` is not worth its
    per-substep cost. Its load-bearing case is **grazing / edge-on flight of a
    high-area-to-mass flat plate** (a solar / drag sail), where the tangential shear
    dominates: a physical constant Cd *under*-predicts along-track by a factor of ~2
    that a recalibrated scalar cannot absorb (~1400-1640 km / 5 d at 400 km, solar
    max; best-fit Cd ~= 4.7 still leaves a ~100 km residual). That non-absorbable
    regime is why it ships. The ~2x is measured with :class:`InPlaneTracking`, which
    tracks *inertial* velocity only, so an "edge-on" body sits a few degrees off the
    true Earth-relative flow — the idealized perfectly-edge-on benefit is larger
    (~9x); this uses the honest shipped figure.
    """

    __slots__ = (
        "_grid",
        "_radius_axis",
        "_density_axis",
        "_incidence_axis",
        "_callable",
        "_name",
        "_content_hash",
        "_clamp_warned_edges",
    )

    def __init__(
        self,
        *,
        grid: NDArray[np.float64] | None,
        radius_axis: NDArray[np.float64] | None,
        density_axis: NDArray[np.float64] | None,
        incidence_axis: NDArray[np.float64] | None,
        callable_: Callable[[float, float, float], float] | None,
        name: str | None,
        content_hash: str,
    ) -> None:
        # Private constructor: the public factories enforce the two valid backings
        # (a frozen grid+axes, or a callable). Stored read-only; value identity is
        # the content hash (see __eq__ / __hash__).
        self._grid = grid
        self._radius_axis = radius_axis
        self._density_axis = density_axis
        self._incidence_axis = incidence_axis
        self._callable = callable_
        self._name = name
        self._content_hash = content_hash
        self._clamp_warned_edges: set[str] = set()  # warn-once-per-boundary state

    @classmethod
    def from_table(
        cls,
        grid: NDArray[np.float64],
        *,
        radius_axis: NDArray[np.float64],
        density_axis: NDArray[np.float64],
        incidence_axis: NDArray[np.float64],
        name: str | None = None,
    ) -> "BoxFaceCd":
        """Build a per-face table from a ``(radius, density, incidence)`` grid + axes.

        ``grid`` has shape ``(len(radius_axis), len(density_axis),
        len(incidence_axis))``; all axes are SI (radius in meters, density in kg/m^3,
        ``incidence`` the face-flow angle θ in radians), strictly increasing and finite.
        ``incidence_axis`` must lie within ``[0, π]``. ``name`` overrides the content
        hash in metadata (the shipped table uses ``"box_face_default"``); leave it
        ``None`` for a user table.
        """
        radius = _validate_axis("radius_axis", radius_axis)
        density = _validate_axis("density_axis", density_axis)
        incidence = _validate_axis("incidence_axis", incidence_axis)
        # The one rule _validate_axis does not cover: θ is a face-flow angle, so the
        # axis must stay within [0, π] (0 head-on, π/2 edge-on, π fully leeward).
        if incidence[0] < 0.0 or incidence[-1] > math.pi:
            raise ValueError(
                f"incidence_axis must lie within [0, pi]; got "
                f"[{float(incidence[0])!r}, {float(incidence[-1])!r}]"
            )
        grid_arr = np.asarray(grid, dtype=np.float64)
        if grid_arr.shape != (radius.size, density.size, incidence.size):
            raise ValueError(
                f"grid shape {grid_arr.shape} must equal (len(radius_axis), "
                f"len(density_axis), len(incidence_axis)) = "
                f"{(radius.size, density.size, incidence.size)}"
            )
        if not np.all(np.isfinite(grid_arr)):
            raise ValueError("grid must be finite (no NaN/inf)")
        grid_arr = _as_readonly(grid_arr)
        return cls(
            grid=grid_arr,
            radius_axis=radius,
            density_axis=density,
            incidence_axis=incidence,
            callable_=None,
            name=name,
            content_hash=_content_hash(
                "cd_boxface", (grid_arr, radius, density, incidence)
            ),
        )

    @classmethod
    def from_callable(
        cls,
        fn: Callable[[float, float, float], float],
        *,
        name: str | None = None,
    ) -> "BoxFaceCd":
        """Wrap ``fn(radius_m, density_kgm3, theta_rad) -> Cd`` as a per-face table.

        ``theta_rad`` is the face-flow angle θ in ``[0, π]`` and the returned Cd is
        referenced to the **full** face area. The escape hatch for an analytic per-face
        coefficient. **Not byte-reproducible**: the metadata records ``name`` (or the
        callable's ``__name__``), not its contents (the same gap noted for
        ``CustomAttitude``). Prefer :meth:`from_table` for a reproducible run.
        """
        if not callable(fn):
            raise ValueError(f"fn must be callable, got {type(fn).__name__}")
        resolved = name or getattr(fn, "__name__", None) or repr(fn)
        return cls(
            grid=None,
            radius_axis=None,
            density_axis=None,
            incidence_axis=None,
            callable_=fn,
            name=resolved,
            # A callable has no inspectable content; identify it by name only. The
            # "boxface-callable:" prefix keeps it distinct from a VariableCd callable
            # hash of the same name.
            content_hash=hashlib.sha256(
                ("boxface-callable:" + resolved).encode("utf-8")
            ).hexdigest()[:16],
        )

    @classmethod
    def default(cls) -> "BoxFaceCd":
        """Load the shipped per-face box Cd table from ``data/`` (generated offline).

        The committed asset is produced by
        ``scripts/generate_box_face_cd_table.py`` (a maintainer step) and loaded here;
        end users compute nothing. It carries the project's shared gas-surface
        assumptions (SESAM accommodation anchored at α = 0.90 / 400 km solar-max,
        diffuse re-emission, 300 K wall), exactly as the Tier A sphere default. A
        spacecraft with markedly different surface physics should supply its own table
        via :meth:`from_table` / :meth:`from_callable`. Metadata records
        ``Cd=table:box_face_default``.
        """
        path = _data_dir() / _BOX_FACE_DEFAULT_FILENAME
        if not path.is_file():
            raise FileNotFoundError(
                f"box_face_default Cd table not found at {path}. It is a committed "
                f"asset under data/; regenerate it with "
                f"`python scripts/generate_box_face_cd_table.py` if missing."
            )
        with np.load(path) as npz:
            grid = npz["grid"]
            radius_axis = npz["radius_axis"]
            density_axis = npz["density_axis"]
            incidence_axis = npz["incidence_axis"]
        return cls.from_table(
            grid,
            radius_axis=radius_axis,
            density_axis=density_axis,
            incidence_axis=incidence_axis,
            name="box_face_default",
        )

    def __call__(self, radius_m: float, density_kgm3: float, theta_rad: float) -> float:
        """A single face's Cd at a (radius, density, face-flow angle θ) point.

        Table backing interpolates trilinearly and clamps out-of-grid ``(radius,
        density)`` to the nearest edge per axis, warning once *per boundary* with an
        edge-tailored message; θ is never clamped (it is a bounded ``[0, π]`` angle
        spanning the full axis). Callable backing forwards, then validates the returned
        Cd. A non-finite input raises ``ValueError``: NaN slips past the clamp's
        ``<`` / ``>`` comparisons unflagged and would otherwise poison the drag
        acceleration with a silent NaN.
        """
        r_in = float(radius_m)
        d_in = float(density_kgm3)
        th_in = float(theta_rad)
        if not (math.isfinite(r_in) and math.isfinite(d_in) and math.isfinite(th_in)):
            raise ValueError(
                "BoxFaceCd requires finite (radius_m, density_kgm3, theta_rad); got "
                f"({radius_m!r}, {density_kgm3!r}, {theta_rad!r})."
            )
        if self._callable is not None:
            cd = float(self._callable(r_in, d_in, th_in))
            if not math.isfinite(cd) or cd < 0.0:
                raise ValueError(
                    f"BoxFaceCd callable {self._name!r} returned an invalid Cd {cd!r} "
                    f"(radius_m={r_in!r}, density_kgm3={d_in!r}, theta_rad={th_in!r}); "
                    "the drag coefficient must be finite and >= 0."
                )
            return cd
        assert self._grid is not None  # narrow for type-checkers: table backing
        assert self._radius_axis is not None
        assert self._density_axis is not None
        assert self._incidence_axis is not None
        r, _ = _clamp_to_axis(r_in, self._radius_axis)
        d, d_clamped = _clamp_to_axis(d_in, self._density_axis)
        # Edge-aware drag-regime warnings (addendum §6.2), shared with VariableCd: the
        # boundary crossed decides the message (radius low = loud invalid-floor; radius
        # high = soft negligible-drag; density = neutral data-range). θ never clamps.
        if r_in < self._radius_axis[0]:
            self._warn_edge_once("radius_low")
        elif r_in > self._radius_axis[-1]:
            self._warn_edge_once("radius_high")
        if d_clamped:
            self._warn_edge_once("density")
        return _trilinear(
            self._grid,
            self._radius_axis,
            self._density_axis,
            self._incidence_axis,
            r,
            d,
            th_in,
        )

    def _reset_edge_warnings(self) -> None:
        """Clear the warn-once-per-boundary state so the next propagation re-warns.

        ``propagate_numerical`` calls this once when it wires the drag force, giving the
        table-edge warnings the same **once-per-run** scope as the Kn-floor warn-once
        hook. Mirrors :meth:`VariableCd._reset_edge_warnings`.
        """
        self._clamp_warned_edges.clear()

    def _warn_edge_once(self, edge: str) -> None:
        """Emit the edge-tailored clamp warning for ``edge`` once per boundary per run.

        Mirrors :meth:`VariableCd._warn_edge_once` and reuses the shared
        :data:`_CLAMP_EDGE_MESSAGES`. ``propagate_numerical`` resets the per-boundary
        state each run via :meth:`_reset_edge_warnings`, so "once" is once-per-run.
        """
        if edge in self._clamp_warned_edges:
            return
        self._clamp_warned_edges.add(edge)
        # stacklevel=2 points at the __call__ site; during a propagation __call__ is
        # invoked from inside Orekit's integration loop via JPype, so there is no stable
        # Python caller frame to surface (same rationale as VariableCd).
        warnings.warn(_CLAMP_EDGE_MESSAGES[edge], stacklevel=2)

    def _metadata_id(self) -> str:
        """The ``<name-or-hash>`` written as ``Cd=table:<...>`` in metadata."""
        return self._name if self._name is not None else self._content_hash

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BoxFaceCd):
            return NotImplemented
        return self._content_hash == other._content_hash and self._name == other._name

    def __hash__(self) -> int:
        return hash((self._content_hash, self._name))

    def __repr__(self) -> str:
        return f"BoxFaceCd(id={self._metadata_id()!r})"


# Any accepted ``drag_coefficient`` value: a fixed scalar or one of the tables.
DragCoefficient = float | VariableCd | BoxFaceCd


# --- SpacecraftGeometry -----------------------------------------------------

_SOFT_CD_LIMIT = 5.0  # fixed Cd above this warns (improbable but allowed)
_SOFT_CR_LIMIT = 3.0  # sphere Cr above this warns


@dataclass(frozen=True)
class SpacecraftGeometry:
    """External shape plus its surface-interaction coefficients (features.md §1.1).

    Construct via :meth:`sphere` or :meth:`box_and_panels`, never directly — the
    factories give the clean per-shape signatures and the discriminant ``kind`` is an
    implementation detail. Frozen and pure-Python; the full validation table runs in
    :meth:`__post_init__` with no Orekit calls. Coefficients live here (not on
    :class:`SpacecraftConfig`) because the geometry fixes which Orekit surface model
    is used and how its coefficients are parameterized.
    """

    kind: str  # "sphere" | "box"
    drag_coefficient: DragCoefficient = 2.2
    # sphere-only
    area_m2: float | None = None
    reflectivity_coefficient: float | None = None
    # box-only
    x_length_m: float | None = None
    y_length_m: float | None = None
    z_length_m: float | None = None
    solar_array_area_m2: float | None = None
    solar_array_axis: tuple[float, float, float] | None = None
    absorption_coefficient: float | None = None
    specular_reflection_coefficient: float | None = None

    def __post_init__(self) -> None:
        if self.kind == "sphere":
            self._validate_sphere()
        elif self.kind == "box":
            self._validate_box()
        else:
            raise ValueError(f"unknown geometry kind {self.kind!r} (use the factories)")

    # -- factories --

    @classmethod
    def sphere(
        cls,
        area_m2: float,
        *,
        drag_coefficient: float | VariableCd = 2.2,
        reflectivity_coefficient: float = 1.5,
    ) -> "SpacecraftGeometry":
        """An isotropic sphere — one cross-sectional area, attitude-independent.

        Maps to Orekit's ``IsotropicDrag`` / ``IsotropicRadiationSingleCoefficient``.
        ``Cd`` defaults to the 2.2 free-molecular convention. ``Cr`` is a single
        reflection coefficient — **1.0 = fully absorbing, 2.0 = perfectly specular**
        (not a [0, 1] reflectivity fraction). A sphere has no incidence dependence, so
        it accepts a fixed Cd or a :class:`VariableCd`, but **not** a
        :class:`BoxFaceCd`.
        """
        return cls(
            kind="sphere",
            area_m2=area_m2,
            drag_coefficient=drag_coefficient,
            reflectivity_coefficient=reflectivity_coefficient,
        )

    @classmethod
    def box_and_panels(
        cls,
        *,
        x_length_m: float,
        y_length_m: float,
        z_length_m: float,
        solar_array_area_m2: float = 0.0,
        solar_array_axis: tuple[float, float, float] = (0.0, 1.0, 0.0),
        drag_coefficient: DragCoefficient = 2.2,
        absorption_coefficient: float = 0.3,
        specular_reflection_coefficient: float = 0.6,
    ) -> "SpacecraftGeometry":
        """A rectangular bus with optional Sun-tracking solar arrays.

        Maps to Orekit's ``BoxAndSolarArraySpacecraft``: the box is centered on the
        body origin with faces normal to body X/Y/Z, and the arrays (total area,
        treated as one equivalent panel) auto-rotate about ``solar_array_axis`` to
        track the Sun. SRP optics are an absorption + specular pair, each in [0, 1]
        (diffuse is the remainder). Accepts a fixed Cd, a :class:`VariableCd`, or — for
        a convex bus (``solar_array_area_m2 == 0``) — a :class:`BoxFaceCd`.
        """
        return cls(
            kind="box",
            x_length_m=x_length_m,
            y_length_m=y_length_m,
            z_length_m=z_length_m,
            solar_array_area_m2=solar_array_area_m2,
            solar_array_axis=solar_array_axis,
            drag_coefficient=drag_coefficient,
            absorption_coefficient=absorption_coefficient,
            specular_reflection_coefficient=specular_reflection_coefficient,
        )

    # -- validation --

    def _validate_drag_coefficient(self) -> None:
        cd = self.drag_coefficient
        if isinstance(cd, (VariableCd, BoxFaceCd)):
            return  # table value range is the table's responsibility
        if not isinstance(cd, (int, float)) or isinstance(cd, bool):
            raise ValueError(
                f"drag_coefficient must be a number or a Cd table, got {cd!r}"
            )
        if not math.isfinite(cd) or cd < 0.0:
            raise ValueError(f"drag_coefficient must be finite and >= 0, got {cd!r}")
        if cd > _SOFT_CD_LIMIT:
            warnings.warn(
                f"drag_coefficient {cd} exceeds {_SOFT_CD_LIMIT} (physically "
                "improbable; allowed for sensitivity studies).",
                stacklevel=3,
            )

    def _validate_sphere(self) -> None:
        if (
            self.area_m2 is None
            or not math.isfinite(self.area_m2)
            or self.area_m2 <= 0.0
        ):
            raise ValueError(
                f"sphere area_m2 must be finite and > 0, got {self.area_m2!r}"
            )
        if isinstance(self.drag_coefficient, BoxFaceCd):
            raise ValueError(
                "a sphere has no flow incidence; use a fixed Cd or VariableCd "
                "(BoxFaceCd is a per-face convex-box table)."
            )
        self._validate_drag_coefficient()
        cr = self.reflectivity_coefficient
        if cr is None or not math.isfinite(cr) or cr < 0.0:
            raise ValueError(
                f"reflectivity_coefficient must be finite and >= 0, got {cr!r}"
            )
        if cr > _SOFT_CR_LIMIT:
            warnings.warn(
                f"reflectivity_coefficient {cr} exceeds {_SOFT_CR_LIMIT} (physically "
                "improbable; allowed for sensitivity studies).",
                stacklevel=3,
            )

    def _validate_box(self) -> None:
        for name in ("x_length_m", "y_length_m", "z_length_m"):
            val = getattr(self, name)
            if val is None or not math.isfinite(val) or val <= 0.0:
                raise ValueError(f"box {name} must be finite and > 0, got {val!r}")
        area = self.solar_array_area_m2
        if area is None or not math.isfinite(area) or area < 0.0:
            raise ValueError(
                f"solar_array_area_m2 must be finite and >= 0, got {area!r}"
            )
        if isinstance(self.drag_coefficient, BoxFaceCd) and area > 0.0:
            raise ValueError(
                "BoxFaceCd models a convex box only and cannot represent solar-array "
                "shadowing; set solar_array_area_m2=0, or use a fixed Cd / VariableCd."
            )
        self._normalize_array_axis()
        self._validate_drag_coefficient()
        absn = self.absorption_coefficient
        spec = self.specular_reflection_coefficient
        for name, val in (
            ("absorption_coefficient", absn),
            ("specular_reflection_coefficient", spec),
        ):
            if val is None or not math.isfinite(val) or not (0.0 <= val <= 1.0):
                raise ValueError(f"{name} must be finite and in [0, 1], got {val!r}")
        assert absn is not None and spec is not None  # narrowed by the loop above
        if absn + spec > 1.0:
            raise ValueError(
                f"absorption_coefficient + specular_reflection_coefficient must be "
                f"<= 1 (the remainder is diffuse); got {absn} + {spec} = {absn + spec}"
            )

    def _normalize_array_axis(self) -> None:
        """Validate the solar-array axis is finite/nonzero and normalize it in place."""
        axis = self.solar_array_axis
        if axis is None or len(axis) != 3:
            raise ValueError(
                f"solar_array_axis must be a length-3 vector, got {axis!r}"
            )
        vec = np.asarray(axis, dtype=np.float64)
        if not np.all(np.isfinite(vec)):
            raise ValueError(f"solar_array_axis must be finite, got {axis!r}")
        norm = float(np.linalg.norm(vec))
        if norm == 0.0:
            raise ValueError("solar_array_axis must be nonzero")
        unit = vec / norm
        # Frozen dataclass: set the normalized tuple via object.__setattr__.
        object.__setattr__(
            self, "solar_array_axis", (float(unit[0]), float(unit[1]), float(unit[2]))
        )


# --- SpacecraftConfig -------------------------------------------------------

_DEFAULT_GEOMETRY = SpacecraftGeometry.sphere(area_m2=1.0)


@dataclass(frozen=True)
class SpacecraftConfig:
    """Physical properties: mass plus a coefficient-bearing :class:`SpacecraftGeometry`.

    Mass is the only shape-independent property; the surface-interaction coefficients
    live on the geometry. The default is a generic 1000 kg, 1 m^2 sphere with
    conventional coefficients — a placeholder. **For accurate drag and SRP modeling,
    override the mass, geometry, and coefficients to match your spacecraft.** Frozen
    and safe before init (the default geometry is a frozen, Orekit-free constant).
    """

    mass_kg: float = 1000.0
    geometry: SpacecraftGeometry = _DEFAULT_GEOMETRY

    def __post_init__(self) -> None:
        if not math.isfinite(self.mass_kg) or self.mass_kg <= 0.0:
            raise ValueError(f"mass_kg must be finite and > 0, got {self.mass_kg!r}")

    def _metadata_string(self) -> str:
        """This config's deterministic ``spacecraft`` metadata string."""
        return _serialize_spacecraft(mass_kg=self.mass_kg, geometry=self.geometry)


# --- spacecraft metadata serializer ----------------------------------------


def _fmt_axis_component(value: float) -> str:
    """Render an axis component compactly: ``0.0`` -> ``0``, ``1.0`` -> ``1``.

    Whole values drop the trailing ``.0`` to match the features.md ``axis=(0,1,0)``
    form; non-whole (normalized) components fall back to ``repr`` for round-tripping.
    """
    if math.isfinite(value) and value == int(value):
        return str(int(value))
    return repr(value)


def _fmt_num(value: float) -> str:
    """Render a numeric metadata field with a stable float ``repr``.

    Coerces to ``float`` first so an int-valued input (e.g. ``drag_coefficient=2`` or
    ``mass_kg=1000``) serializes with its decimal point (``2.0`` / ``1000.0``). Two
    physically-identical configs that differ only in int-vs-float input then yield
    byte-identical metadata, preserving the deterministic grammar (features.md §1.1).
    """
    return repr(float(value))


def _format_cd(cd: DragCoefficient) -> str:
    """Render a Cd field: ``2.2`` or ``table:<name-or-hash>``."""
    if isinstance(cd, (VariableCd, BoxFaceCd)):
        return f"table:{cd._metadata_id()}"
    return _fmt_num(cd)


def _serialize_spacecraft(*, mass_kg: float, geometry: SpacecraftGeometry) -> str:
    """Build the deterministic ``spacecraft`` metadata string (features.md §1.1).

    A standalone function (mirroring :func:`force_models._serialize_force_models`) so
    ``propagate_numerical`` can serialize the mass + geometry it actually used.
    Numbers use ``repr`` for exact round-tripping; a semicolon separates geometry from
    mass/coefficients. Examples::

        sphere:A=1.0;m=1000.0,Cd=2.2,Cr=1.5
        sphere:A=1.0;m=1000.0,Cd=table:sphere_default,Cr=1.5
        box:x=2.0,y=1.5,z=1.0,arrays=10.0,axis=(0,1,0);m=420.0,Cd=2.2,abs=0.3,spec=0.6
    """
    g = geometry
    cd = _format_cd(g.drag_coefficient)
    if g.kind == "sphere":
        # Validated invariants: a sphere always carries area + reflectivity.
        assert g.area_m2 is not None and g.reflectivity_coefficient is not None
        return (
            f"sphere:A={_fmt_num(g.area_m2)};"
            f"m={_fmt_num(mass_kg)},Cd={cd},Cr={_fmt_num(g.reflectivity_coefficient)}"
        )
    # Validated invariants: a box always carries its dims, array, axis, and optics.
    assert (
        g.x_length_m is not None
        and g.y_length_m is not None
        and g.z_length_m is not None
        and g.solar_array_area_m2 is not None
        and g.solar_array_axis is not None
        and g.absorption_coefficient is not None
        and g.specular_reflection_coefficient is not None
    )
    axis = "(" + ",".join(_fmt_axis_component(c) for c in g.solar_array_axis) + ")"
    return (
        f"box:x={_fmt_num(g.x_length_m)},y={_fmt_num(g.y_length_m)},"
        f"z={_fmt_num(g.z_length_m)},"
        f"arrays={_fmt_num(g.solar_array_area_m2)},axis={axis};"
        f"m={_fmt_num(mass_kg)},Cd={cd},"
        f"abs={_fmt_num(g.absorption_coefficient)},"
        f"spec={_fmt_num(g.specular_reflection_coefficient)}"
    )


# --- bundled-asset resolution ----------------------------------------------

_SPHERE_DEFAULT_FILENAME = "sphere_cd_default.npz"
_BOX_FACE_DEFAULT_FILENAME = "box_face_cd_default.npz"


def _data_dir() -> Path:
    """Locate the repo-root ``data/`` directory holding bundled assets.

    **Single point of asset-path resolution** (architecture §5: ``data/`` lives at the
    repo root, outside the importable package). This resolves relative to the source
    tree, which works for an editable install (``pip install -e .``) and a source
    checkout — propygator's only distribution mode (project_meta: GitHub-only). A
    built *wheel* would not contain repo-root ``data/``; if that ever ships, move the
    asset into ``src/propygator/`` and switch this one helper to
    ``importlib.resources`` — no caller changes.
    """
    return Path(__file__).resolve().parents[3] / "data"
