"""Altitude / regime guard system — pure-Python foundations (addendum §6).

This module is the home for the propagator's geocentric-radius guard family
(impact + escape backstops, drag-regime warnings, the min-step re-entry catch,
optional user altitude limits) introduced by the drag-validity & altitude-guards
addendum. Two layers live here:

* The **pure-Python, safe-before-init** surface (architecture §10): the
  :class:`AltitudeLimits` config dataclass and the escape-parity policy constant.
  Unit-testable with **no JVM**.
* The **terminal radius event detectors** (impact + escape; addendum §6.1/§6.3) and
  their threshold helpers, which cross into Orekit. As with the rest of the package
  these import ``jpype`` / ``org.orekit.*`` **lazily inside functions** — the module
  top stays JVM-free, and there must never be a top-level Orekit import.

**Detector mechanism (why ``FunctionalDetector``, not a raw ``EventDetector``
proxy).** The addendum §6.3 build note suggested a ``@JImplements(EventDetector)``
proxy with every interface method overridden. The installed Orekit 13.1
``EventDetector`` interface declares ten methods, most of them ``default``
(``getMaxCheckInterval``, ``getDetectionSettings``, ``getThreshold``,
``getMaxIterationCount``, ``dependsOnTimeOnly``, ``init``, ``reset``, ``finish``),
and JPype proxies do **not** inherit Java interface ``default`` methods — the trap
already recorded for ``CustomAttitude`` (CLAUDE.md). So instead of a raw proxy, the
detectors are built from Orekit's own ``FunctionalDetector`` (a concrete
``AbstractDetector`` whose defaults all work natively) driven by a single-method
``java.util.function.ToDoubleFunction`` switching function (no defaults → no trap)
and the native ``StopOnEvent`` handler (``Action.STOP``; no handler proxy needed).
See :func:`_make_radius_stop_detector`.

**Escape-parity policy constant.** The escape backstop fires when the geocentric
radius exceeds the Earth-Moon gravity-parity radius (≈ 327,000 km; addendum §6.3).
It is a deliberately fuzzy, hard-coded *policy* fence — not derived from Orekit
``Constants`` (the Earth-Moon distance is not a ``Constants`` member, and nothing
in the dynamics consumes it). It is stored here as a geodetic **altitude** bound so
the :class:`AltitudeLimits` ``max`` reasonableness check stays a pure
altitude-vs-altitude comparison with no ``R⊕`` and no JVM; the Chunk-6 escape
detector lowers this *same* altitude back to a geocentric radius by adding the
Orekit equatorial radius (the identical altitude→radius lowering used for user
limits), recovering ≈ 327,000 km. One source of truth for both.
"""

from __future__ import annotations

import bisect
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Type-only; the org.orekit.* namespace is a runtime JPype stub (mypy treats it
    # as untyped via ignore_missing_imports).
    import org.orekit.propagation.events  # noqa: F401

    from .spacecraft import SpacecraftGeometry

# --- escape-parity policy constant (addendum §6.3) -------------------------

# Earth-Moon equigravisphere along the Earth-Moon line, where lunar gravity equals
# Earth's:
#     r = D * sqrt(k) / (1 + sqrt(k)),   k = mu_earth / mu_moon ≈ 81.3  ->  r ≈ 0.90 * D
# evaluated at the Moon's *perigee* distance D ≈ 363,300 km — the conservative
# minimum-parity choice (it guarantees termination *before* parity regardless of
# where the Moon actually is; addendum §6.3) -> r ≈ 327,000 km. A hard-coded policy
# fence, NOT derived from Orekit Constants.
_ESCAPE_PARITY_RADIUS_KM = 327_000.0

# WGS84 equatorial radius in km (== Constants.WGS84_EARTH_EQUATORIAL_RADIUS / 1000,
# = 6,378,137 m). Hard-coded as a literal so the reasonableness check below stays
# JVM-free; the Chunk-6 escape detector adds back the *Orekit* equatorial radius (the
# same value), so the altitude->radius round-trip recovers _ESCAPE_PARITY_RADIUS_KM
# exactly.
_WGS84_EQUATORIAL_RADIUS_KM = 6_378.137

# The escape-parity bound stored as a geodetic ALTITUDE (radius minus the equatorial
# radius) so AltitudeLimits.max is a pure altitude comparison — no R⊕, no JVM. The
# ~21 km latitude spread of the geodetic->geocentric approximation is within a
# guard's tolerance (addendum §6.4). ≈ 320,621.863 km (the build plan's "≈ 320,650 km").
_ESCAPE_PARITY_ALTITUDE_KM = _ESCAPE_PARITY_RADIUS_KM - _WGS84_EQUATORIAL_RADIUS_KM


# --- user-settable altitude limits (addendum §6.4) -------------------------


@dataclass(frozen=True)
class AltitudeLimits:
    """Optional user terminal altitude bounds for a propagation.

    Altitudes are geodetic km above the WGS84 ellipsoid; each is converted ONCE
    at setup to a geocentric-radius threshold (reference: equatorial radius — a
    documented, slightly conservative approximation consistent with the no-
    per-substep-geodetic-conversion rule; the ~21 km latitude spread is within a
    guard's tolerance). ``None`` = no user limit on that side (the system backstops
    still apply). Crossing a *reasonable* user limit at runtime **stops & reports**:
    it returns the partial :class:`~propygator.core.states.Trajectory` with
    ``termination_reason="user_min"`` / ``"user_max"``, exactly like the system
    backstops it nests inside (addendum §6.6).

    An *unreasonable* limit — one outside the system backstops, which could never
    bind — is rejected at **construction** with a plain ``ValueError`` (like every
    other config dataclass): ``min_altitude_km < 0`` (below the surface; the impact
    backstop fires first) or ``max_altitude_km`` above the escape-parity altitude
    (≈ 320,621 km; the escape backstop fires first). Plus the usual sanity checks:
    each finite if given, and ``min < max``. All are pure altitude comparisons
    against fixed policy bounds — no JVM, safe before init (architecture §10).
    """

    min_altitude_km: float | None = None
    max_altitude_km: float | None = None

    def __post_init__(self) -> None:
        # Finiteness first (rejects NaN / ±inf); None means "no limit on that side".
        for name, val in (
            ("min_altitude_km", self.min_altitude_km),
            ("max_altitude_km", self.max_altitude_km),
        ):
            if val is not None and not math.isfinite(val):
                raise ValueError(f"{name}, when given, must be finite, got {val!r}")

        # Floor: a limit below the surface can never bind (impact fires first).
        if self.min_altitude_km is not None and self.min_altitude_km < 0.0:
            raise ValueError(
                "min_altitude_km must be >= 0 (a limit below the surface can never "
                f"bind — the impact backstop fires first), got {self.min_altitude_km!r}"
            )

        # Ceiling: a limit above the escape-parity altitude can never bind (escape
        # fires first). Strictly above is unreasonable (addendum §6.6).
        if (
            self.max_altitude_km is not None
            and self.max_altitude_km > _ESCAPE_PARITY_ALTITUDE_KM
        ):
            raise ValueError(
                f"max_altitude_km must be <= ~{_ESCAPE_PARITY_ALTITUDE_KM:.0f} km, the "
                "escape-parity altitude (a limit above it can never bind — the escape "
                f"backstop fires first), got {self.max_altitude_km!r}"
            )

        # Ordering: a min at or above the max could never admit a valid band.
        if (
            self.min_altitude_km is not None
            and self.max_altitude_km is not None
            and self.min_altitude_km >= self.max_altitude_km
        ):
            raise ValueError(
                "min_altitude_km must be < max_altitude_km, got "
                f"min={self.min_altitude_km!r} max={self.max_altitude_km!r}"
            )


# --- terminal radius event detectors (addendum §6.1, §6.3) -----------------

# Tuning for the terminal radius detectors. The switching function r - r_threshold
# is smooth and effectively monotonic near impact (radius falling) and escape
# (radius rising), so a 60 s check interval reliably brackets the single crossing;
# the root-finder then refines it to _DETECTOR_THRESHOLD_S, which at orbital speeds
# (~km/s) pins the stop radius to well under a metre (verified). A terminal stop is
# cheap — the bracket search runs once and each evaluation is a vector norm.
_DETECTOR_MAX_CHECK_S = 60.0
_DETECTOR_THRESHOLD_S = 1.0e-3


def _altitude_km_to_radius_m(altitude_km: float) -> float:
    """Lower a geodetic altitude (km) to a geocentric-radius threshold (m).

    The single altitude->radius conversion shared by the escape backstop
    (:func:`_escape_radius_m`) and the Chunk-7 user limits: add the WGS84 equatorial
    radius — the documented, slightly conservative reference of addendum §6.4 (no
    per-substep geodetic conversion; the ~21 km latitude spread is within a guard's
    tolerance). JVM-crossing: reads ``Constants.WGS84_EARTH_EQUATORIAL_RADIUS`` (the
    caller is already past ``_ensure_started()``).
    """
    from org.orekit.utils import Constants

    return altitude_km * 1000.0 + float(Constants.WGS84_EARTH_EQUATORIAL_RADIUS)


def _impact_radius_m() -> float:
    """Geocentric radius of the impact backstop = the WGS84 equatorial radius (m).

    ``Constants.WGS84_EARTH_EQUATORIAL_RADIUS`` (6,378,137 m), not a literal — the
    same constant ``core/bodies.py`` builds the Earth ellipsoid on. The exact value
    is non-critical (addendum §6.3): by ``R⊕`` the orbit is long destroyed and the
    low-altitude warnings have fired.
    """
    from org.orekit.utils import Constants

    return float(Constants.WGS84_EARTH_EQUATORIAL_RADIUS)


def _escape_radius_m() -> float:
    """Geocentric radius of the escape backstop (≈ 327,000 km), in metres.

    The Chunk-5 escape-parity *altitude* lowered to a radius via the same
    :func:`_altitude_km_to_radius_m` used for user limits. Because that altitude was
    stored as ``_ESCAPE_PARITY_RADIUS_KM - _WGS84_EQUATORIAL_RADIUS_KM`` (Chunk 5),
    adding the equatorial radius back recovers ≈ 327,000 km exactly — one source of
    truth for the §6.4 reasonableness check and this §6.3 detector.
    """
    return _altitude_km_to_radius_m(_ESCAPE_PARITY_ALTITUDE_KM)


def _make_radius_stop_detector(
    threshold_radius_m: float,
) -> "org.orekit.propagation.events.EventDetector":
    """Build a terminal geocentric-radius detector that stops at its crossing.

    Returns an Orekit ``FunctionalDetector`` whose switching function is
    ``g(state) = |position| - threshold_radius_m`` (geocentric radius in the
    propagation frame — one norm, no geodetic conversion; architecture §10) and
    whose handler is the native ``StopOnEvent`` (``Action.STOP``). Module-internal:
    the Orekit type never reaches a public signature (same allowance as
    ``core/bodies.py``).

    The only Python object is the single-method ``ToDoubleFunction`` switching
    function — see the module docstring for why this avoids the JPype
    interface-``default`` trap that a raw ``@JImplements(EventDetector)`` proxy would
    hit. ``StopOnEvent`` halts on the first crossing in either direction, which is
    what a terminal backstop wants; the realized span then shortens, so the caller
    must clamp its ephemeris sampling to ``getMaxDate()`` (``numerical.py``).
    """
    import jpype
    from java.util.function import ToDoubleFunction
    from org.orekit.propagation.events import FunctionalDetector
    from org.orekit.propagation.events.handlers import StopOnEvent

    @jpype.JImplements(ToDoubleFunction)  # type: ignore[attr-defined]
    class _RadiusSwitch:
        @jpype.JOverride  # type: ignore[attr-defined]
        def applyAsDouble(self, state):  # noqa: ANN001, ANN202 - Java signature
            return float(state.getPosition().getNorm()) - threshold_radius_m

    return (
        FunctionalDetector()
        .withMaxCheck(_DETECTOR_MAX_CHECK_S)
        .withThreshold(_DETECTOR_THRESHOLD_S)
        # _RadiusSwitch implements ToDoubleFunction only at the JPype runtime level
        # (via @JImplements), which mypy cannot see — hence the arg-type ignore.
        .withFunction(_RadiusSwitch())  # type: ignore[arg-type]
        .withHandler(StopOnEvent())
    )


def _classify_termination(r_final_m: float, specs: list[tuple[float, str]]) -> str:
    """Return the termination reason whose threshold radius is nearest ``r_final_m``.

    A fired ``Action.STOP`` detector leaves the final state *at* its threshold radius
    (sub-metre, from the root-find), and the registered thresholds (impact ≈ 6,378
    km, escape ≈ 327,000 km, plus any Chunk-7 user limits) are far apart, so
    nearest-threshold matching identifies which guard stopped the run without an
    event-recording handler — which would reintroduce the ``EventHandler``
    interface-``default`` burden. Pure-Python.

    **Caller invariant — keep the system backstops first in ``specs``.** A user limit
    may land *exactly* on a system threshold (``min_altitude_km == 0`` coincides with
    impact; ``max_altitude_km`` at the escape-parity altitude coincides with escape).
    On that degenerate tie ``min`` returns the first-listed spec, so listing the system
    backstops (impact, escape) before any user limits resolves the tie to the system
    reason. Re-ordering or sorting ``specs`` would silently mislabel a system stop as a
    user stop — the call site (``numerical.py``) builds the list in that order on
    purpose.
    """
    return min(specs, key=lambda spec: abs(r_final_m - spec[0]))[1]


# --- min-step re-entry classification (addendum §6.6) ----------------------

# A drag-driven decay stiffens until the propagation fails — either the adaptive step
# saturates ``min_step_s`` or, with looser tolerances, the atmosphere model rejects the
# sub-surface query ("point is inside ellipsoid"). Either surfaces as a JException; the
# catch is classified as a *physical re-entry* iff the osculating perigee at the failure
# is already below this floor — the validated drag-table lower edge (~150 km; addendum
# §9). Judged on the osculating *perigee*, not the instantaneous altitude, since a
# healthy low pass is descending for half of every orbit (addendum §6.6).
_REENTRY_PERIGEE_FLOOR_ALTITUDE_KM = 150.0


def _reentry_floor_radius_m() -> float:
    """Geocentric radius of the re-entry perigee floor (≈ R⊕ + 150 km), in metres.

    The ~150 km drag-table lower edge lowered to a radius via the *same*
    :func:`_altitude_km_to_radius_m` used for the escape backstop and user limits — one
    altitude→radius reference for every guard threshold. JVM-crossing (reads
    ``Constants`` via that helper); the caller is already past ``_ensure_started()``.
    """
    return _altitude_km_to_radius_m(_REENTRY_PERIGEE_FLOOR_ALTITUDE_KM)


def _is_reentry_failure(
    *,
    drag_enabled: bool,
    radial_velocity_m_s: float,
    perigee_radius_m: float,
    floor_radius_m: float,
) -> bool:
    """Classify a propagation failure as a drag-driven re-entry (addendum §6.6).

    Re-entry iff **drag was enabled**, the orbit is **descending** (radial velocity
    < 0), and its **osculating perigee is already below** ``floor_radius_m`` (the
    drag-table lower edge). Anything else — drag off, climbing, or a perigee still above
    the floor — is a genuine numeric/config failure, and the caller re-raises.

    **Invariant: prefer a false re-raise over a false ``reentry``.** A missed re-entry
    surfaces as a loud, fixable ``NumericalPropagationError``; a false ``reentry``
    would return a silently-truncated wrong trajectory. So every condition must hold to
    claim re-entry; when in doubt the caller re-raises. Pure-Python (no JVM), so
    unit-testable.
    """
    return (
        drag_enabled and radial_velocity_m_s < 0.0 and perigee_radius_m < floor_radius_m
    )


# --- free-molecular (Knudsen) validity floor (addendum §6.2/§6.3) ----------
#
# Below a body-size-dependent altitude a meter-scale body leaves free-molecular flow
# (Knudsen number Kn = λ/L < 10) and the Sentman/DRIA drag coefficient over-predicts
# — the model-validity floor the collapse experiment is *blind* to (addendum §2). The
# runtime re-implements the experiment's §3.4 method a third time here (the experiment
# `experiments/.../kn_floor.py` + the generator being the other two; subject to the §5
# equivalence check). The mean free path needs **per-species number densities**, which
# NRLMSISE-00 supplies but Orekit's public API does not expose (only total density) and
# pymsis is not a runtime dependency — so the conservative-profile composition is
# captured offline (`scripts/generate_kn_floor_composition.py`) and embedded below. The
# floor is then a pure-Python, deterministic function of the body's characteristic
# length L; only lowering it to a geocentric radius touches Orekit (`Constants`).

# Composition-weighted hard-sphere mean free path:
#     λ = 1 / (√2 · Σ_i n_i · σ_i),   σ_i = π · d_i²
# over the major NRLMSISE-00 species. Kinetic / collision diameters d_i [m] from
# standard kinetic-theory tables (molecular N2/O2/Ar: gas-kinetic diameters, e.g.
# Breck 1974; He/H: same family; atomic O/N: aeronomy values ~3.0e-10 m, Bird 1994 —
# more uncertain, but the floor band is N2/O2/O-dominated where the values are best
# known, and a larger σ only shortens λ and *raises* the floor, i.e. errs
# conservative). This σ/diameter table is hand-duplicated in THREE files that MUST stay
# byte-identical (the §5 equivalence obligation): here, `experiments/.../kn_floor.py`,
# and `scripts/generate_kn_floor_composition.py`. If you change a diameter, edit all
# three AND regenerate the embedded composition below — a `src/` module cannot import
# the throwaway-venv experiment or the maintainer script. This (runtime) copy is pinned
# by `tests/propagation/test_guards.py::test_sigma_table_pinned` (a drift fails there
# with a self-explaining message) and further constrained by
# `test_runtime_floor_matches_experiment_curve`; the other two copies are only checked
# when re-run offline, so a future curve mismatch is not mysterious — start here.
_KINETIC_DIAMETER_M = {
    "N2": 3.64e-10,
    "O2": 3.46e-10,
    "O": 3.00e-10,
    "HE": 2.18e-10,
    "H": 2.40e-10,
    "AR": 3.40e-10,
    "N": 3.00e-10,
}
_SIGMA_M2 = {sp: math.pi * d * d for sp, d in _KINETIC_DIAMETER_M.items()}
_SQRT2 = math.sqrt(2.0)

# Free-molecular Knudsen threshold (addendum §3.4): 0.1 < Kn < 10 is the transitional
# regime where DRIA over-predicts; Kn = 100 would be over-conservative.
_KN_FREE_MOLECULAR = 10.0

# ==== captured composition (generated; addendum §5/§6.3) =====================
# Conservative high-activity NRLMSISE-00 per-species NUMBER densities [1/m^3] vs
# geodetic altitude [km], captured offline by
# scripts/generate_kn_floor_composition.py at the fixed conservative profile
# (F10.7=250, Ap=45, equatorial dayside, 2002-07-01T12:00 — deterministic, NOT the
# run's space weather; addendum §6.3/§9). Densities fall ~exponentially, so the floor
# scan interpolates each species in log-density between nodes.
#
# RECORDED §5 cross-check: the generator's committed stdout
# experiments/drag-coefficient-verification/kn_floor_runtime_crosscheck.txt shows its
# continuous-MSIS floor_altitude(L) reproduces the experiment's kn_floor_results.txt
# (110.5/128.4/177.2/222.5 km), and this runtime grid+bisection method matches it to
# < 0.3 km. test_runtime_floor_matches_experiment_curve re-asserts it in-suite.
# fmt: off
_KN_FLOOR_ALTITUDE_KM: tuple[float, ...] = (80.0, 90.0, 100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0, 200.0, 210.0, 220.0, 230.0, 240.0, 250.0, 260.0, 270.0, 280.0, 290.0, 300.0, 310.0, 320.0, 330.0, 340.0, 350.0, 360.0, 370.0, 380.0, 390.0, 400.0, 410.0, 420.0, 430.0, 440.0, 450.0)  # noqa: E501
_KN_FLOOR_NUMBER_DENSITY_M3: dict[str, tuple[float, ...]] = {
    "N2": (2.995348e+20, 5.329309e+19, 8.193238e+18, 1.496339e+18, 3.228655e+17, 1.106591e+17, 5.344589e+16, 3.047161e+16, 1.915198e+16, 1.282044e+16, 8.969197e+15, 6.476475e+15, 4.788180e+15, 3.604410e+15, 2.751682e+15, 2.124167e+15, 1.654423e+15, 1.297895e+15, 1.024236e+15, 8.122354e+14, 6.467460e+14, 5.167432e+14, 4.140753e+14, 3.326341e+14, 2.677870e+14, 2.159871e+14, 1.744955e+14, 1.411817e+14, 1.143788e+14, 9.277502e+13, 7.533390e+13, 6.123315e+13, 4.981839e+13, 4.056701e+13, 3.306106e+13, 2.696512e+13, 2.200978e+13, 1.797807e+13),  # noqa: E501
    "O2": (7.212987e+19, 1.155235e+19, 1.456793e+18, 1.953631e+17, 2.992008e+16, 7.514641e+15, 2.738768e+15, 1.218594e+15, 6.215939e+14, 3.508078e+14, 2.135804e+14, 1.376695e+14, 9.266121e+13, 6.446561e+13, 4.601040e+13, 3.349883e+13, 2.477371e+13, 1.854902e+13, 1.402883e+13, 1.069146e+13, 8.200327e+12, 6.322520e+12, 4.895657e+12, 3.804331e+12, 2.965124e+12, 2.316902e+12, 1.814329e+12, 1.423456e+12, 1.118644e+12, 8.803997e+11, 6.938150e+11, 5.474336e+11, 4.324156e+11, 3.419153e+11, 2.706176e+11, 2.143830e+11, 1.699820e+11, 1.348891e+11),  # noqa: E501
    "O": (3.702332e+15, 2.763780e+17, 4.705313e+17, 2.430127e+17, 9.506818e+16, 4.653501e+16, 2.904605e+16, 2.037139e+16, 1.523405e+16, 1.184449e+16, 9.459557e+15, 7.710185e+15, 6.386279e+15, 5.358268e+15, 4.542458e+15, 3.883040e+15, 3.341748e+15, 2.891671e+15, 2.513416e+15, 2.192688e+15, 1.918727e+15, 1.683273e+15, 1.479875e+15, 1.303035e+15, 1.149510e+15, 1.015417e+15, 8.979988e+14, 7.949605e+14, 7.043736e+14, 6.246078e+14, 5.542730e+14, 4.921803e+14, 4.373060e+14, 3.887655e+14, 3.457923e+14, 3.077193e+14, 2.739647e+14, 2.440199e+14),  # noqa: E501
    "HE": (2.064819e+15, 4.108903e+14, 1.012337e+14, 4.736206e+13, 2.798515e+13, 1.953894e+13, 1.563059e+13, 1.331817e+13, 1.177452e+13, 1.066099e+13, 9.812152e+12, 9.137593e+12, 8.583697e+12, 8.107352e+12, 7.707362e+12, 7.355912e+12, 7.042396e+12, 6.759108e+12, 6.500333e+12, 6.261760e+12, 6.040083e+12, 5.832743e+12, 5.637723e+12, 5.453428e+12, 5.278577e+12, 5.112127e+12, 4.953233e+12, 4.801194e+12, 4.655422e+12, 4.515427e+12, 4.380791e+12, 4.251154e+12, 4.126206e+12, 4.005674e+12, 3.889319e+12, 3.776924e+12, 3.668300e+12, 3.563271e+12),  # noqa: E501
    "H": (2.240761e+13, 5.064640e+13, 1.270787e+13, 4.980905e+12, 1.914483e+12, 7.776565e+11, 3.615851e+11, 1.905272e+11, 1.144852e+11, 7.787142e+10, 5.880639e+10, 4.815718e+10, 4.184163e+10, 3.790018e+10, 3.532698e+10, 3.357507e+10, 3.233245e+10, 3.141441e+10, 3.070822e+10, 3.014344e+10, 2.967512e+10, 2.927408e+10, 2.892210e+10, 2.860354e+10, 2.831006e+10, 2.802081e+10, 2.777069e+10, 2.753061e+10, 2.729910e+10, 2.707496e+10, 2.685720e+10, 2.664502e+10, 2.643777e+10, 2.623489e+10, 2.603593e+10, 2.584052e+10, 2.564836e+10, 2.545918e+10),  # noqa: E501
    "AR": (3.557995e+18, 6.144473e+17, 8.203027e+16, 1.045561e+16, 1.402664e+15, 3.302260e+14, 1.223414e+14, 5.695390e+13, 3.023202e+13, 1.744373e+13, 1.065727e+13, 6.785106e+12, 4.454774e+12, 2.994441e+12, 2.050117e+12, 1.424161e+12, 1.000947e+12, 7.105059e+11, 5.080187e+11, 3.655946e+11, 2.645257e+11, 1.922723e+11, 1.402979e+11, 1.027152e+11, 7.541795e+10, 5.551545e+10, 4.095671e+10, 3.027633e+10, 2.242137e+10, 1.663153e+10, 1.235531e+10, 9.191342e+09, 6.846488e+09, 5.106061e+09, 3.812478e+09, 2.849753e+09, 2.132390e+09, 1.597233e+09),  # noqa: E501
    "N": (1.184162e+11, 2.561843e+11, 5.085321e+11, 1.253572e+12, 2.986849e+12, 7.428584e+12, 1.768930e+13, 3.558862e+13, 5.957230e+13, 8.462886e+13, 1.052192e+14, 1.181145e+14, 1.230012e+14, 1.214341e+14, 1.155474e+14, 1.072535e+14, 9.795548e+13, 8.855422e+13, 7.956558e+13, 7.124616e+13, 6.369333e+13, 5.691381e+13, 5.086651e+13, 4.549109e+13, 4.071829e+13, 3.648073e+13, 3.271582e+13, 2.936714e+13, 2.638484e+13, 2.372520e+13, 2.135013e+13, 1.922643e+13, 1.732526e+13, 1.562140e+13, 1.409288e+13, 1.272040e+13, 1.148678e+13, 1.037767e+13),  # noqa: E501
}
# fmt: on
# =============================================================================

# Floor-scan bracket [km]: the captured-composition altitude span. The Kn = 10 crossing
# of every physical spacecraft (L ~ 0.1 m CubeSat → ~30 m station ⇒ floor ~110-223 km;
# addendum §3.4/§9) sits well inside it; a body whose floor falls outside the bracket
# yields no floor (`None` → no warning) — only for an unphysically tiny/huge L.
_KN_FLOOR_SCAN_LO_KM = _KN_FLOOR_ALTITUDE_KM[0]
_KN_FLOOR_SCAN_HI_KM = _KN_FLOOR_ALTITUDE_KM[-1]


def _interp_log(x: float, xs: tuple[float, ...], ys: tuple[float, ...]) -> float:
    """Linear interpolation of ``log(ys)`` in ``x`` (``xs`` strictly ascending).

    Number densities are ~exponential in altitude, so interpolating in log space
    between the captured nodes is far more accurate than raw-linear. ``x`` is clamped
    into ``[xs[0], xs[-1]]`` before interpolating, so an out-of-bracket query returns
    the nearest edge value rather than extrapolating (the floor scan only ever queries
    inside the bracket, but this keeps the helper safe for any future caller).
    """
    # Clamp into the bracket so t stays in [0, 1] (no extrapolation past the edges).
    x = min(max(x, xs[0]), xs[-1])
    if x <= xs[0]:
        i = 0
    elif x >= xs[-1]:
        i = len(xs) - 2
    else:
        i = bisect.bisect_right(xs, x) - 1
    x0, x1 = xs[i], xs[i + 1]
    t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
    # Floor each node at a tiny positive value before the log, matching the generator's
    # ``np.clip(d, 1e-300, None)``: a zero or underflowed density node would otherwise
    # raise ``ValueError: math domain error`` from inside the per-substep drag path. The
    # shipped composition is all-positive, so this only guards a future regeneration.
    ly0 = math.log(ys[i] if ys[i] > 0.0 else 1e-300)
    ly1 = math.log(ys[i + 1] if ys[i + 1] > 0.0 else 1e-300)
    return math.exp(ly0 + t * (ly1 - ly0))


def _mean_free_path_m(altitude_km: float) -> float:
    """Composition-weighted mean free path λ [m] at a geodetic altitude (§3.4).

    ``λ = 1 / (√2 · Σ_i n_i σ_i)`` with ``n_i`` the per-species number density
    interpolated from the captured conservative-profile composition and ``σ_i`` the
    runtime σ table — the genuine re-coding of the §3.4 method (not a stored λ curve),
    so the σ table from Chunk 2 is exercised at runtime.
    """
    total = 0.0
    for sp, densities in _KN_FLOOR_NUMBER_DENSITY_M3.items():
        n = _interp_log(altitude_km, _KN_FLOOR_ALTITUDE_KM, densities)
        if math.isfinite(n) and n > 0.0:
            total += n * _SIGMA_M2[sp]
    return math.inf if total <= 0.0 else 1.0 / (_SQRT2 * total)


def _characteristic_length_m(geometry: "SpacecraftGeometry") -> float:
    """Body characteristic length ``L`` [m] for the Knudsen number (addendum §6.3).

    Sphere → diameter ``2√(A/π)``; box → the **max edge length** (the conservative
    choice — the largest dimension gives the smallest Kn and hence the highest, safest
    floor). Pure-Python; reads only the validated geometry fields.
    """
    if geometry.kind == "sphere":
        assert geometry.area_m2 is not None  # a sphere always carries an area
        return 2.0 * math.sqrt(geometry.area_m2 / math.pi)
    assert geometry.x_length_m is not None  # a box always carries its three edges
    assert geometry.y_length_m is not None
    assert geometry.z_length_m is not None
    return max(geometry.x_length_m, geometry.y_length_m, geometry.z_length_m)


def _floor_altitude_km(length_m: float) -> float | None:
    """Free-molecular floor altitude [km] for a body of length ``L`` — or ``None``.

    The altitude where ``Kn(alt) = λ(alt) / L = 10``. ``λ`` rises monotonically with
    altitude (density falls), so ``f(alt) = Kn(alt) − 10`` has a single crossing, found
    by bisection over the captured bracket to a 1e-3 km tolerance (no scipy — a runtime
    dependency-free re-coding of the experiment's ``brentq`` scan). Returns ``None`` if
    the crossing falls outside the captured band (an unphysically tiny/huge body), in
    which case no Kn-floor warning is emitted. Pure-Python / JVM-free.
    """

    def f(alt_km: float) -> float:
        return _mean_free_path_m(alt_km) / length_m - _KN_FREE_MOLECULAR

    lo, hi = _KN_FLOOR_SCAN_LO_KM, _KN_FLOOR_SCAN_HI_KM
    f_lo, f_hi = f(lo), f(hi)
    if not (math.isfinite(f_lo) and math.isfinite(f_hi)) or f_lo > 0.0 or f_hi < 0.0:
        return None  # crossing not bracketed -> no floor in the captured band
    for _ in range(200):  # bisection: >> enough iterations to reach the 1e-3 km xtol
        mid = 0.5 * (lo + hi)
        if f(mid) < 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1.0e-3:
            break
    return 0.5 * (lo + hi)


def _kn_floor_warning_message(floor_altitude_km: float, length_m: float) -> str:
    """The loud low-edge drag-regime warning (addendum §6.2 low edge, §8 example)."""
    return (
        f"below the free-molecular flow floor (~{floor_altitude_km:.0f} km for this "
        f"{length_m:.1f} m body): drag modeling is invalid below it and results may be "
        "wildly off. This warning is emitted once."
    )


def _kn_floor_setup(
    geometry: "SpacecraftGeometry",
) -> tuple[float, str] | None:
    """Resolve the Kn floor: ``(floor_radius_m, message)`` or ``None``.

    Computes the body's characteristic length, scans for the ``Kn = 10`` floor altitude
    (pure-Python), then lowers it to a geocentric radius via the *same*
    :func:`_altitude_km_to_radius_m` reference used for the escape backstop and user
    limits. ``None`` when the floor falls outside the captured band (no warning). The
    radius lowering reads ``Constants`` (JVM); the caller is past ``_ensure_started()``.
    """
    length_m = _characteristic_length_m(geometry)
    floor_km = _floor_altitude_km(length_m)
    if floor_km is None:
        return None
    return _altitude_km_to_radius_m(floor_km), _kn_floor_warning_message(
        floor_km, length_m
    )
