"""``fit_tle`` / ``fit_tle_detailed`` — the TLE least-squares fitter (Feature 1.2).

The repo's first *estimation* feature: an iterative batch-least-squares fit of
SGP4 mean elements (+ optionally B*) against a reference trajectory, riding
Orekit's ``TLEPropagatorBuilder`` + ``BatchLSEstimator`` (Levenberg-Marquardt)
over evenly subsampled PV measurements. ``fit_tle_detailed`` is the engine and
returns the full :class:`FitResult` diagnostics; ``fit_tle`` is the thin
``.tle`` wrapper (one implementation, no drift). Binding contract:
features.md §1.2 (amended 2026-07-10 at Checkpoint A; covariance / ``sigma0``
fields added 2026-07-18 — the real-world-validation Chunk 6 follow-on).

The defining caveat (stated loudly on the verbs): the fit is **inherently
lossy** — SGP4 is a simplified model, so a full-force numerical orbit can never
be reproduced exactly. The Chunk-0 probe (``experiments/tle-fitting/``) measured
~495 m RMS over a 2-day LEO ``leo_default`` reference, and *exact* recovery on
the SGP4 self-fit (the known-exact-answer case).

**Architecture invariants** (CLAUDE.md / architecture §4, §10): no Orekit type
on the public surface; ``jpype`` / ``org.orekit.*`` imported lazily inside the
JVM sections; the pure-Python pre-flight rows raise before the JVM starts; SI
units throughout. The ``State`` reference path calls
``propagation.numerical.propagate_numerical`` — the one sanctioned
``tle → propagation`` call edge (architecture §7 dependency rule; the
``export_all`` lazy-import idiom), contract-bound by the §1.2 signature's
``force_models`` / ``spacecraft`` parameters.
"""

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

import numpy as np

from ..core.exceptions import TLEFitError
from ..core.frames import Frame
from ..core.progress import _ProgressReporter
from ..core.states import State, Trajectory
from ..core.time import Epoch
from ..core.tle import TLE

if TYPE_CHECKING:
    from ..core.progress import ProgressCallback
    from ..propagation.force_models import ForceModelConfig
    from ..propagation.spacecraft import SpacecraftConfig

    # _run_estimation outputs: (fitted Orekit TLE, iterations, evaluations,
    # rms_m, residuals_m, covariance, parameter_names, sigma0).
    _EstimationOutputs = tuple[
        Any, int, int, float, np.ndarray, np.ndarray | None, tuple[str, ...], float
    ]

logger = logging.getLogger(__name__)

# --- internal knobs (tunable placeholders, not contract — features §1.2) --------

# State-path internal reference grid: propagate_numerical output targeting this
# many evenly spaced samples across the fitting span (contract: ~300, tunable).
_INTERNAL_GRID_SAMPLES = 300

# Estimator internals, pre-tuned by the Chunk-0 probe (experiments/tle-fitting/:
# the positionScale 1-1000 m and threshold 1e-2-1e-4 sweeps were flat, so the
# baselines stand). The sigmas only weight a noise-free reference uniformly.
_MEASUREMENT_CAP = 300  # even-subsample cap over the reference samples
_SIGMA_POSITION_M = 1.0  # PV measurement position sigma
_SIGMA_VELOCITY_MS = 1.0e-3  # PV measurement velocity sigma
_MEASUREMENT_WEIGHT = 1.0  # PV base weight
_POSITION_SCALE_M = 1.0  # TLEPropagatorBuilder parameter normalization scale
_CONVERGENCE_THRESHOLD = 1.0e-3  # BatchLSEstimator parameters convergence threshold
# Decomposition cutoff for getPhysicalCovariances at convergence (the Step-0
# probe value, 2026-07-18; even a ~1-revolution arc inverts cleanly at it).
_COVARIANCE_SINGULARITY_THRESHOLD = 1.0e-10


def _format_rms(rms_m: float) -> str:
    """Format a position RMS for the progress lines (contract: km examples).

    km above a metre (the contract's ``rms 0.42 km`` shape), plain metres below
    it — a converged self-fit sits at ~1e-6 m, where a km rendering would be
    unreadable noise.
    """
    if rms_m < 1.0:
        return f"{rms_m:.3g} m"
    return f"{rms_m / 1000.0:.3g} km"


# --- FitResult -------------------------------------------------------------------


@dataclass(frozen=True)
class FitResult:
    """Outcome of a **converged** TLE fit (features.md §1.2, Checkpoint A addition).

    Returned by :func:`fit_tle_detailed`; :func:`fit_tle` returns just
    :attr:`tle`. There is deliberately no ``converged`` flag: non-convergence
    raises :class:`~propygator.core.exceptions.TLEFitError` with no partial
    result, so a ``FitResult`` only exists for converged fits.

    ``rms_m`` is the observed-vs-estimated position RMS over the N fit
    measurements at convergence — the same quantity the final progress line
    quotes (there in km). It is *not* the propagate-back residual over a full
    reference grid; that is one ``propagate_tle`` call away::

        back = propagate_tle(result.tle, span, output_step=step, start=start)

    The 2026-07-18 §1.2 amendment (the real-world-validation Chunk 6
    follow-on) adds the estimator's **raw** physical parameter covariance and
    the a-posteriori variance factor ``sigma0``. The parameter basis is the
    one Orekit's ``TLEPropagatorBuilder`` estimates in — **Cartesian TEME
    position / velocity at the fitted epoch** (``Px Py Pz`` in m, ``Vx Vy Vz``
    in m/s) plus ``BSTAR`` (TLE units, 1/earth-radii) iff ``fit_bstar`` —
    labelled row-for-row by :attr:`parameter_names`. Raw means ``(J^T J)^-1``
    under the internal 1 m / 1 mm/s measurement sigmas: **conditioning
    indicators**, not absolute uncertainty. The documented bridge to the
    standard residual-scaled form is ``sigmas * sigma0`` — applied by the user
    knowingly, never silently — and the honest B* read is **comparative**:
    judge sigma(B*) against a physically plausible B* (e.g. the catalog's) or
    across fit configurations. There is deliberately no self-contained
    "B* unconstrained" flag — on weak-drag arcs the fitted B* inflates in
    step with its sigma, so no single-fit ratio discriminates (the Chunk 6
    probe finding that also dropped the elected correlation property).
    ``covariance`` is ``None`` — with a ``UserWarning`` at fit time — in the
    exactly-singular corner the probes never reached.

    Immutable and pure-Python (constructible + validating before JVM init, the
    architecture §10 "safe before init" surface). ``residuals_m`` and
    ``covariance`` follow the array-backed value-type invariant
    (:class:`~propygator.core.states.State` pattern): defensively copied,
    contents read-only, value-based ``__eq__`` / ``__hash__``.
    """

    tle: TLE
    iterations: int  # LS iterations consumed
    evaluations: int  # LS evaluations (>= iterations; LM may re-evaluate within one)
    rms_m: float  # final position RMS over the fit measurements, meters
    residuals_m: np.ndarray  # per-measurement position residual norms, meters, (N,)
    measurement_epochs: tuple[Epoch, ...]  # the N measurement epochs, aligned
    covariance: np.ndarray | None  # raw physical parameter covariance, (n, n)
    parameter_names: tuple[str, ...]  # covariance row/column labels, estimator order
    sigma0: float  # a-posteriori variance factor sqrt(cost^2 / (m - n))

    def __post_init__(self) -> None:
        if not isinstance(self.tle, TLE):
            raise TypeError(
                f"tle must be a propygator TLE, got {type(self.tle).__name__}"
            )
        for label, value in (
            ("iterations", self.iterations),
            ("evaluations", self.evaluations),
        ):
            # bool is an int subclass; reject it explicitly (True is not a count).
            if not isinstance(value, int) or isinstance(value, bool):
                raise TypeError(f"{label} must be int, got {type(value).__name__}")
        if self.iterations < 0:
            raise ValueError(f"iterations must be >= 0, got {self.iterations}")
        if self.evaluations < max(self.iterations, 1):
            raise ValueError(
                "evaluations must be >= 1 and >= iterations, got "
                f"evaluations={self.evaluations} with iterations={self.iterations}"
            )
        if isinstance(self.rms_m, bool) or not isinstance(self.rms_m, (int, float)):
            raise TypeError(f"rms_m must be a float, got {type(self.rms_m).__name__}")
        if not math.isfinite(self.rms_m) or self.rms_m < 0.0:
            raise ValueError(f"rms_m must be finite and >= 0, got {self.rms_m!r}")
        object.__setattr__(self, "rms_m", float(self.rms_m))

        if not isinstance(self.residuals_m, np.ndarray):
            raise TypeError(
                "residuals_m must be numpy.ndarray, got "
                f"{type(self.residuals_m).__name__}"
            )
        if self.residuals_m.ndim != 1:
            raise ValueError(
                f"residuals_m must be 1-D, got shape {self.residuals_m.shape}"
            )
        if self.residuals_m.dtype != np.float64:
            raise ValueError(
                f"residuals_m must be float64, got {self.residuals_m.dtype}"
            )
        if not np.all(np.isfinite(self.residuals_m)) or np.any(self.residuals_m < 0):
            raise ValueError("residuals_m must be finite and >= 0")
        # Immutable value type (architecture §6): defensively copy, freeze contents
        # (the State/Orientation pattern) so __eq__/__hash__ stay sound.
        residuals = np.array(self.residuals_m, dtype=np.float64, copy=True)
        residuals.setflags(write=False)
        object.__setattr__(self, "residuals_m", residuals)

        epochs = tuple(self.measurement_epochs)
        for e in epochs:
            if not isinstance(e, Epoch):
                raise TypeError(
                    f"measurement_epochs entries must be Epoch, got {type(e).__name__}"
                )
        if len(epochs) != residuals.shape[0]:
            raise ValueError(
                f"measurement_epochs length ({len(epochs)}) must match "
                f"residuals_m length ({residuals.shape[0]})"
            )
        object.__setattr__(self, "measurement_epochs", epochs)

        names = tuple(self.parameter_names)
        if not names:
            raise ValueError(
                "parameter_names must be non-empty (a converged fit always "
                "estimates at least the six orbital parameters)"
            )
        for name in names:
            if not isinstance(name, str):
                raise TypeError(
                    f"parameter_names entries must be str, got {type(name).__name__}"
                )
        object.__setattr__(self, "parameter_names", names)

        if isinstance(self.sigma0, bool) or not isinstance(self.sigma0, (int, float)):
            raise TypeError(f"sigma0 must be a float, got {type(self.sigma0).__name__}")
        if not math.isfinite(self.sigma0) or self.sigma0 < 0.0:
            raise ValueError(f"sigma0 must be finite and >= 0, got {self.sigma0!r}")
        object.__setattr__(self, "sigma0", float(self.sigma0))

        if self.covariance is not None:
            if not isinstance(self.covariance, np.ndarray):
                raise TypeError(
                    "covariance must be numpy.ndarray or None, got "
                    f"{type(self.covariance).__name__}"
                )
            if (
                self.covariance.ndim != 2
                or self.covariance.shape[0] != self.covariance.shape[1]
            ):
                raise ValueError(
                    f"covariance must be square 2-D, got shape {self.covariance.shape}"
                )
            if self.covariance.dtype != np.float64:
                raise ValueError(
                    f"covariance must be float64, got {self.covariance.dtype}"
                )
            if not np.all(np.isfinite(self.covariance)):
                raise ValueError("covariance must be finite")
            if self.covariance.shape[0] != len(names):
                raise ValueError(
                    f"covariance shape {self.covariance.shape} must match "
                    f"parameter_names length ({len(names)})"
                )
            # atol=0: entries span ~30 orders of magnitude (position m^2 vs
            # B*^2), so only a relative symmetry test is meaningful.
            if not np.allclose(self.covariance, self.covariance.T, rtol=1e-8, atol=0.0):
                raise ValueError("covariance must be symmetric")
            if np.any(np.diag(self.covariance) < 0.0):
                raise ValueError("covariance diagonal (variances) must be >= 0")
            cov = np.array(self.covariance, dtype=np.float64, copy=True)
            cov.setflags(write=False)
            object.__setattr__(self, "covariance", cov)

    @property
    def sigmas(self) -> np.ndarray | None:
        """Raw per-parameter formal sigmas, ``sqrt(diag(covariance))``.

        Derived on demand from the stored :attr:`covariance` — not a second
        stored array, so the object cannot carry an inconsistent copy and
        equality/hash stay covariance-based. Labelled by
        :attr:`parameter_names`, same units as the parameters (m, m/s, B* in
        1/earth-radii). Raw conditioning indicators — multiply by
        :attr:`sigma0` for the residual-scaled form (class docstring).
        ``None`` when :attr:`covariance` is. Each call returns a fresh
        writable array.
        """
        if self.covariance is None:
            return None
        return np.sqrt(np.diag(self.covariance))

    def __eq__(self, other: object) -> bool:
        # The dataclass-generated __eq__ would call bool() on the ndarray
        # comparison and raise; compare by value instead (the State idiom).
        if not isinstance(other, FitResult):
            return NotImplemented
        if (self.covariance is None) != (other.covariance is None):
            return False
        covariance_equal = (
            self.covariance is None
            or other.covariance is None  # unreachable (XOR above); narrows the type
            or np.array_equal(self.covariance, other.covariance)
        )
        return (
            self.tle == other.tle
            and self.iterations == other.iterations
            and self.evaluations == other.evaluations
            and self.rms_m == other.rms_m
            and np.array_equal(self.residuals_m, other.residuals_m)
            and self.measurement_epochs == other.measurement_epochs
            and covariance_equal
            and self.parameter_names == other.parameter_names
            and self.sigma0 == other.sigma0
        )

    def __hash__(self) -> int:
        # residuals_m / covariance are read-only (see __post_init__), so
        # hashing their bytes is stable for the object's lifetime.
        return hash(
            (
                self.tle,
                self.iterations,
                self.evaluations,
                self.rms_m,
                self.residuals_m.tobytes(),
                self.measurement_epochs,
                self.covariance.tobytes() if self.covariance is not None else None,
                self.parameter_names,
                self.sigma0,
            )
        )


# --- identity resolution (pure-Python) --------------------------------------------


@dataclass(frozen=True)
class _FittedIdentity:
    """The catalog-bookkeeping fields of the fitted TLE, resolved pre-fit.

    Resolution order per field: explicit kwarg -> inherited from
    ``initial_guess`` -> placeholder (features.md §1.2 Fitted-TLE field policy;
    the ``from_state_unfitted`` placeholder conventions). Element-set and
    revolution numbers inherit **verbatim** — no auto-increment (we are not a
    catalog operator), and the revolution number is documented as stale when
    the fitted epoch differs from the guess's. Mean-motion derivatives are not
    identity — they are always zeroed at assembly, never inherited.
    """

    norad_id: int
    name: str | None
    classification: str
    launch_year: int  # 4-digit (windowed from the TLE's 2-digit field); 0 = blank
    launch_number: int
    launch_piece: str
    elset_number: int
    rev_number: int


def _int_field(field: str) -> int:
    """Parse a fixed-column integer TLE field; all-blank reads as 0."""
    stripped = field.strip()
    return int(stripped) if stripped else 0


def _resolve_identity(
    initial_guess: TLE | None, norad_id: int | None, name: str | None
) -> _FittedIdentity:
    """Resolve the fitted TLE's identity fields (kwarg -> guess -> placeholder).

    Pure-Python fixed-column parsing (the ``core/tle.py`` layout: classification
    col 8; international designator cols 10-17 as year/number/piece; element-set
    number cols 65-68 on line 1; revolution number cols 64-68 on line 2). The
    2-digit launch year is windowed with the same 57-pivot as ``TLE.epoch``.
    """
    if initial_guess is None:
        return _FittedIdentity(
            norad_id=norad_id if norad_id is not None else 0,
            name=name,
            classification="U",
            launch_year=0,
            launch_number=0,
            launch_piece="",
            elset_number=0,
            rev_number=0,
        )

    line1 = initial_guess.line1
    line2 = initial_guess.line2
    year_2digit = _int_field(line1[9:11])
    if line1[9:11].strip():
        launch_year = (1900 if year_2digit >= 57 else 2000) + year_2digit
    else:
        launch_year = 0
    return _FittedIdentity(
        norad_id=norad_id if norad_id is not None else initial_guess.norad_id,
        name=name if name is not None else initial_guess.name,
        classification=line1[7],
        launch_year=launch_year,
        launch_number=_int_field(line1[11:14]),
        launch_piece=line1[14:17].strip(),
        elset_number=_int_field(line1[64:68]),
        rev_number=_int_field(line2[63:68]),
    )


# --- reference normalization -------------------------------------------------------


def _clip_leading(reference: Trajectory, fitting_span: float) -> Trajectory:
    """Clip a ``Trajectory`` reference to the leading ``fitting_span`` seconds.

    Pure-Python (no JVM): offsets are computed from the trajectory's two-part
    epoch arrays (in-package use of the private backing fields, the
    ``core/sampling.py`` precedent). Samples at exactly ``start + fitting_span``
    are included. Raises ``ValueError`` when fewer than 2 samples fall inside
    the span (features.md §1.2 Failure modes).
    """
    d_int = reference._epochs_int - reference._epochs_int[0]
    offsets = d_int.astype(np.float64) + (
        reference._epochs_frac - reference._epochs_frac[0]
    )
    n = int(np.searchsorted(offsets, fitting_span, side="right"))
    if n < 2:
        raise ValueError(
            f"Trajectory reference has {n} sample(s) inside the "
            f"{fitting_span:g} s fitting span; at least 2 are required to fit. "
            "Provide a denser/longer trajectory or a shorter fitting_span."
        )
    if n == len(reference):
        return reference
    epochs = [reference._epoch_at(i) for i in range(n)]
    return Trajectory.from_arrays(
        epochs,
        reference.positions[:n],
        reference.velocities[:n],
        reference.frame,
    )


def _normalize_reference(
    reference: State | Trajectory,
    fitting_span: float,
    force_models: "ForceModelConfig | None",
    spacecraft: "SpacecraftConfig | None",
) -> Trajectory:
    """Normalize either reference shape to a TEME trajectory over the span.

    ``State`` path: an internal ``propagate_numerical`` run over ``fitting_span``
    with ``force_models`` (default ``leo_default()``), ``spacecraft`` (default
    ``SpacecraftConfig()``), the default ``LofAligned`` attitude, and
    ``IntegratorConfig.high_precision()`` — the §1.1 preset designed for fit
    references — on a ~300-sample grid with ``progress=False`` (contract:
    Reference-input paths; ``fit_tle`` owns the reporting). A propagation
    failure raises ``NumericalPropagationError`` unchanged.

    ``Trajectory`` path: frame conversion only — the caller has **already
    clipped** the leading portion via :func:`_clip_leading` (kept pure-Python
    and ahead of the JVM rows so the too-few-samples ``ValueError`` raises
    before the JVM starts).

    Both paths end in TEME — the ``TLEPropagatorBuilder`` propagation frame, so
    the Chunk-2 PV measurements must live there (an internal conversion on a
    non-frame-carrying output, sanctioned by architecture §10).

    The ``propagation`` import is lazy, in-body: the one sanctioned
    ``tle → propagation`` call edge (architecture §7; the ``export_all`` idiom)
    — ``tle/``'s static module graph stays ``core``-only.
    """
    if isinstance(reference, State):
        from ..propagation.force_models import ForceModelConfig
        from ..propagation.integrators import IntegratorConfig
        from ..propagation.numerical import propagate_numerical
        from ..propagation.spacecraft import SpacecraftConfig

        resolved_force_models = (
            force_models if force_models is not None else ForceModelConfig.leo_default()
        )
        resolved_spacecraft = (
            spacecraft if spacecraft is not None else SpacecraftConfig()
        )
        # Evenly spaced grid targeting the internal sample count:
        # floor(span/step) + 1 == _INTERNAL_GRID_SAMPLES for this step.
        output_step = fitting_span / (_INTERNAL_GRID_SAMPLES - 1)
        logger.info(
            "fit_tle: building reference trajectory — %.1f h, %d samples",
            fitting_span / 3600.0,
            _INTERNAL_GRID_SAMPLES,
        )
        ref = propagate_numerical(
            reference,
            fitting_span,
            output_step=output_step,
            force_models=resolved_force_models,
            spacecraft=resolved_spacecraft,
            integrator=IntegratorConfig.high_precision(),
            progress=False,
        )
        # The guard system stops-and-reports rather than raising (features §1.1):
        # a re-entry/impact/limits termination returns a PARTIAL trajectory with
        # `terminated` metadata. Fitting it silently would cover less span than
        # requested — warn and fit the realized arc; with fewer than 2 samples
        # there is no arc to fit, so raise the same clean ValueError the
        # Trajectory path's span clip uses.
        if ref.metadata.get("terminated"):
            reason = ref.metadata.get("termination_reason") or "terminated"
            if len(ref) < 2:
                raise ValueError(
                    "fit_tle's internal reference propagation terminated "
                    f"immediately ({reason}); no reference arc to fit. The "
                    "reference orbit decays/exits inside the first output step "
                    "— fit_tle needs an orbit that survives at least a short "
                    "arc."
                )
            realized_h = ref.end_epoch.seconds_since(ref.start_epoch) / 3600.0
            warnings.warn(
                "fit_tle: the internal reference propagation terminated early "
                f"({reason}); fitting the realized {realized_h:.1f} h arc "
                f"instead of the requested {fitting_span / 3600.0:.1f} h "
                "fitting_span.",
                UserWarning,
                # warn -> _normalize_reference -> fit_tle_detailed -> caller.
                stacklevel=3,
            )
    else:
        ref = reference

    return ref if ref.frame is Frame.TEME else ref.to_frame(Frame.TEME)


def _check_bound_orbit(first: State) -> None:
    """Pre-flight: the reference must start on a bound orbit (SGP4 can't else).

    Evaluates the first sample's osculating elements in TEME (JVM-touching;
    ``to_keplerian`` needs a pseudo-inertial frame, and TEME is where the fit
    lives anyway). An exactly-parabolic state (e == 1) already raises a clean
    ``ValueError`` inside ``to_keplerian``; the explicit check below catches the
    hyperbolic case, which classical elements *can* represent but SGP4 cannot
    (features.md §1.2 Failure modes: e >= 1 or a <= 0, pre-flight).
    """
    el = first.to_frame(Frame.TEME).to_keplerian()
    if el.eccentricity >= 1.0 or el.semi_major_axis_m <= 0.0:
        raise ValueError(
            "fit_tle requires a bound reference orbit: the first sample has "
            f"osculating e={el.eccentricity:.6f}, a={el.semi_major_axis_m:.1f} m "
            "(e >= 1 / a <= 0 is not representable by SGP4)."
        )


def _warn_if_subrevolution(ref_teme: Trajectory) -> None:
    """Warn once when the realized fitting arc covers < 1 orbital revolution.

    Weak-observability notice, then proceed (features.md §1.2 Failure modes).
    The message is deliberately constant so Python's default once-per-location
    warning dedup makes this warn-once per session — the exact inverse of the
    stale-TLE warning's embedded-age trick (``tle/propagator.py``).
    """
    from ..core.bodies import _earth_mu

    el = ref_teme[0].to_keplerian()
    period_s = 2.0 * math.pi * math.sqrt(el.semi_major_axis_m**3 / _earth_mu())
    realized_span_s = ref_teme.end_epoch.seconds_since(ref_teme.start_epoch)
    if realized_span_s < period_s:
        warnings.warn(
            "fit_tle: the fitting span covers less than one orbital revolution; "
            "the TLE mean elements (mean motion and B* especially) are weakly "
            "observable over a sub-revolution arc. Proceeding, but consider a "
            "longer fitting_span or a longer reference trajectory.",
            UserWarning,
            # warn -> _warn_if_subrevolution -> fit_tle_detailed -> caller.
            stacklevel=3,
        )


# --- seed --------------------------------------------------------------------------


def _build_seed(
    ref_teme: Trajectory, initial_guess: TLE | None, resolved_norad_id: int
) -> TLE:
    """Build the estimator's template TLE at the reference start (JVM-touching).

    The Chunk-0-resolved mechanism (features.md §1.2 Fit mechanism step 1): the
    **fixed-point refinement** — Orekit's ``FixedPointTleGenerationAlgorithm``
    applied to the first reference sample with ``initial_guess`` (else
    ``TLE.from_state_unfitted``) as the template — iterates the mean elements
    until the TLE's own SGP4 osculating output reproduces the first sample: a
    local osculating→mean inversion at the start epoch (probe: ~7 km initial
    fit residual vs ~1100 km unrefined; roughly half the LS iterations).

    ``generate`` requires an **orbit-defined** ``SpacecraftState``, so the first
    sample is wrapped as a ``CartesianOrbit`` in TEME with ``TLEConstants.MU``
    (the TLE world's WGS-72 GM, in SI — ``Constants`` has no ``WGS72_EARTH_MU``
    in Orekit 13.1.x, and ``State.to_orekit()``'s ``AbsolutePVCoordinates`` form
    defines no orbit). The template supplies B* (held by ``fit_bstar=False``)
    while the refinement re-derives the six elements at the start epoch, so an
    ``initial_guess`` at any epoch is legal.

    If the fixed-point iteration itself fails, the fallback seed is the raw
    ``from_state_unfitted`` template at the reference start, carrying the
    guess's B* if any — the probe's unrefined-seed legs prove the fit converges
    from there.
    """
    first = ref_teme[0]

    from .._orekit_init import _ensure_started

    _ensure_started()
    import jpype
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.propagation import SpacecraftState
    from org.orekit.propagation.analytical.tle import TLEConstants
    from org.orekit.propagation.analytical.tle.generation import (
        FixedPointTleGenerationAlgorithm,
    )

    if initial_guess is not None:
        guess_bstar = float(initial_guess.to_orekit().getBStar())
        template = initial_guess
    else:
        guess_bstar = 0.0
        template = TLE.from_state_unfitted(first, norad_id=resolved_norad_id)

    try:
        orbit = CartesianOrbit(
            first._orekit_pv(),
            Frame.TEME.to_orekit(),
            first.epoch.to_orekit(),
            float(TLEConstants.MU),
        )
        refined = FixedPointTleGenerationAlgorithm().generate(
            SpacecraftState(orbit), template.to_orekit()
        )
        return TLE.from_strings(str(refined.getLine1()), str(refined.getLine2()))
    except jpype.JException as exc:  # type: ignore[attr-defined]
        # The fixed-point iteration can fail to converge on unusual orbits; the
        # raw template is a proven (slower) seed, so degrade rather than raise.
        # Re-anchor a user guess at the reference start via from_state_unfitted,
        # carrying its B* (the epoch contract: fitted epoch = reference start).
        logger.info(
            "fit_tle: fixed-point seed refinement failed (%s); "
            "falling back to the unrefined template",
            exc.getMessage(),
        )
        if initial_guess is not None:
            return TLE.from_state_unfitted(
                first, norad_id=resolved_norad_id, bstar=guess_bstar
            )
        return template


# --- estimator core -----------------------------------------------------------------


def _build_measurements(
    ref_teme: Trajectory,
) -> "tuple[list[Any], tuple[Epoch, ...]]":
    """PV measurements from the normalized reference (JVM-touching).

    Even subsampling to :data:`_MEASUREMENT_CAP` (all samples when the reference
    is smaller), chronological — so the estimator's measurement order matches
    the returned epochs tuple, which becomes ``FitResult.measurement_epochs``.
    The reference is already TEME (the ``TLEPropagator`` propagation frame — PV
    measurements are compared against the propagator state in that frame).
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.estimation.measurements import PV, ObservableSatellite

    n = len(ref_teme)
    indices = np.unique(
        np.round(np.linspace(0, n - 1, min(_MEASUREMENT_CAP, n))).astype(int)
    )
    satellite = ObservableSatellite(0)
    measurements: list[Any] = []
    epochs: list[Epoch] = []
    for i in indices:
        sample = ref_teme[int(i)]
        pv = sample._orekit_pv()
        measurements.append(
            PV(
                sample.epoch.to_orekit(),
                pv.getPosition(),
                pv.getVelocity(),
                _SIGMA_POSITION_M,
                _SIGMA_VELOCITY_MS,
                _MEASUREMENT_WEIGHT,
                satellite,
            )
        )
        epochs.append(sample.epoch)
    return measurements, tuple(epochs)


def _build_fit_observer(
    on_iteration: "Callable[[int, float], None] | None" = None,
) -> "Any":
    """The ``BatchLSObserver`` proxy capturing per-evaluation fit diagnostics.

    The one new ``@JImplements`` proxy of Feature 1.2 (Java classes can't be
    subclassed; CLAUDE.md). Reflection + the Chunk-0 probe confirmed the
    interface has a **single abstract method and no defaults**, so the JPype
    default-method trap does not apply. Orekit fires it per *evaluation* (LM may
    re-evaluate within an iteration), and the last callback belongs to the
    accepted final estimate — its physical residuals feed ``FitResult``, and
    on a non-converged exit its RMS is the "last RMS" the ``TLEFitError``
    message carries.

    ``on_iteration(iteration, pos_rms_m)`` is the progress hook (contract:
    Progress reporting): invoked once per **new** iteration count — deduped
    against the per-evaluation firing, so exactly one ``iter N | rms …`` line
    prints per iteration.
    """
    import jpype

    @jpype.JImplements(  # type: ignore[attr-defined]
        "org.orekit.estimation.leastsquares.BatchLSObserver"
    )
    class _FitObserver:
        def __init__(self) -> None:
            self.iterations = 0
            self.evaluations = 0
            self.last_pos_rms_m: float | None = None
            self.last_residuals_m: np.ndarray | None = None
            self.last_cost: float | None = None
            self.last_residual_dim: int | None = None
            self._last_reported_iteration: int | None = None

        @jpype.JOverride  # type: ignore[attr-defined]
        def evaluationPerformed(  # noqa: N802 - Java signature
            self,
            iterations_count,  # noqa: ANN001
            evaluations_count,  # noqa: ANN001
            orbits,  # noqa: ANN001
            estimated_orbital_parameters,  # noqa: ANN001
            estimated_propagator_parameters,  # noqa: ANN001
            estimated_measurements_parameters,  # noqa: ANN001
            evaluations_provider,  # noqa: ANN001
            ls_evaluation,  # noqa: ANN001
        ):  # noqa: ANN202
            # Physical position residual norms, observed vs estimated, from the
            # per-measurement data the provider hands over for free (the
            # residuals-are-free Chunk-0 finding behind FitResult).
            n = int(evaluations_provider.getNumber())
            residuals = np.empty(n, dtype=np.float64)
            for i in range(n):
                estimated = evaluations_provider.getEstimatedMeasurement(i)
                observed = estimated.getObservedValue()
                theoretical = estimated.getEstimatedValue()
                dx = float(observed[0]) - float(theoretical[0])
                dy = float(observed[1]) - float(theoretical[1])
                dz = float(observed[2]) - float(theoretical[2])
                residuals[i] = math.sqrt(dx * dx + dy * dy + dz * dz)
            self.iterations = int(iterations_count)
            self.evaluations = int(evaluations_count)
            self.last_residuals_m = residuals
            self.last_pos_rms_m = float(np.sqrt(np.mean(residuals**2)))
            # sigma0 inputs (2026-07-18 amendment): the weighted LS cost and
            # the residual-vector dimension m (6 scalar components per PV) at
            # the accepted final evaluation.
            self.last_cost = float(ls_evaluation.getCost())
            self.last_residual_dim = int(ls_evaluation.getResiduals().getDimension())
            if (
                on_iteration is not None
                and self.iterations != self._last_reported_iteration
            ):
                self._last_reported_iteration = self.iterations
                on_iteration(self.iterations, self.last_pos_rms_m)

    return _FitObserver()


def _run_estimation(
    seed: TLE,
    measurements: "list[Any]",
    max_iterations: int,
    fit_bstar: bool,
    reporter: _ProgressReporter,
    deliver_fraction: bool,
) -> "_EstimationOutputs":
    """The batch least squares itself (features.md §1.2 Fit mechanism).

    ``TLEPropagatorBuilder`` (MEAN position angle, Chunk-0 ``positionScale``,
    fixed-point generation algorithm) + ``BatchLSEstimator`` with a
    Levenberg-Marquardt optimizer; ``max_iterations`` bounds iterations **and**
    evaluations (contract). The six orbital drivers are selected by default;
    the ``BSTAR`` propagation driver (default-unselected, Chunk 0) is selected
    iff ``fit_bstar``.

    Progress (contract: Progress reporting): the observer hook drives
    ``reporter.step("iter N | rms …")`` once per iteration (deduped against the
    per-evaluation firing), and — when ``deliver_fraction`` (the caller got a
    callable) — ``reporter.update(min(iteration / max_iterations, 1.0))``, the
    *iteration-budget* fraction. ``update`` is gated on the callable mode
    because in print mode it would interleave percent lines with the ``iter``
    lines; the reporter's own throttle governs the callable's cadence.

    Returns ``(fitted Orekit TLE, iterations, evaluations, rms_m,
    residuals_m, covariance, parameter_names, sigma0)`` — the last three the
    2026-07-18 amendment's capture: the raw physical covariance from
    ``getPhysicalCovariances`` (``None``, with a ``UserWarning``, if the
    normal equations are exactly singular — the stop-and-report spirit; a
    converged fit is not discarded over an absent diagnostic), the estimated
    parameter labels in covariance row order, and
    ``sigma0 = sqrt(cost^2 / (m - n))`` from the final evaluation's weighted
    cost. Non-convergence — Hipparchus' too-many-iterations /
    too-many-evaluations, or a diverged LS — emits the honest
    ``failed at iter N | not converged | last rms …`` final line, delivers the
    exhausted budget fraction (1.0 only when a budget was actually hit), and
    surfaces as :class:`~propygator.core.exceptions.TLEFitError` carrying the
    iteration count and the last RMS; the Java failure is reduced to its
    message string (architecture §3), and **no partial result** escapes.
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    import jpype
    from org.hipparchus.optim.nonlinear.vector.leastsquares import (
        LevenbergMarquardtOptimizer,
    )
    from org.orekit.estimation.leastsquares import BatchLSEstimator
    from org.orekit.orbits import PositionAngleType
    from org.orekit.propagation.analytical.tle.generation import (
        FixedPointTleGenerationAlgorithm,
    )
    from org.orekit.propagation.conversion import TLEPropagatorBuilder

    builder = TLEPropagatorBuilder(
        seed.to_orekit(),
        PositionAngleType.MEAN,
        _POSITION_SCALE_M,
        FixedPointTleGenerationAlgorithm(),
    )
    for driver in builder.getPropagationParametersDrivers().getDrivers():
        if str(driver.getName()) == "BSTAR":
            driver.setSelected(bool(fit_bstar))

    # The estimated-parameter labels, in the estimator's covariance row order:
    # orbital drivers first, then selected propagation drivers (the Step-0
    # probe, 2026-07-18: Px Py Pz Vx Vy Vz [BSTAR] — TLEPropagatorBuilder
    # estimates in Cartesian TEME at epoch; no mean-element basis exists).
    parameter_names = tuple(
        str(driver.getName())
        for drivers in (
            builder.getOrbitalParametersDrivers().getDrivers(),
            builder.getPropagationParametersDrivers().getDrivers(),
        )
        for driver in drivers
        if driver.isSelected()
    )

    estimator = BatchLSEstimator(LevenbergMarquardtOptimizer(), builder)
    estimator.setParametersConvergenceThreshold(_CONVERGENCE_THRESHOLD)
    estimator.setMaxIterations(max_iterations)
    estimator.setMaxEvaluations(max_iterations)

    def _on_iteration(iteration: int, pos_rms_m: float) -> None:
        reporter.step(f"iter {iteration} | rms {_format_rms(pos_rms_m)}")
        if deliver_fraction:
            reporter.update(min(iteration / max_iterations, 1.0))

    observer = _build_fit_observer(_on_iteration)
    estimator.setObserver(observer)
    for measurement in measurements:
        estimator.addMeasurement(measurement)

    try:
        propagators = estimator.estimate()
    except jpype.JException as exc:  # type: ignore[attr-defined]
        iterations = int(estimator.getIterationsCount())
        evaluations = int(estimator.getEvaluationsCount())
        last_rms = (
            _format_rms(observer.last_pos_rms_m)
            if observer.last_pos_rms_m is not None
            else "unavailable"
        )
        if deliver_fraction:
            # 1.0 only when a budget (iterations or evaluations — both bounded
            # by max_iterations) was genuinely exhausted; a diverged LS below
            # budget reports the honest partial fraction.
            budget_hit = iterations >= max_iterations or evaluations >= max_iterations
            reporter.update(
                1.0 if budget_hit else min(iterations / max_iterations, 1.0)
            )
        reporter.finish(
            f"failed at iter {iterations} | not converged | last rms {last_rms}"
        )
        raise TLEFitError(
            f"TLE fit did not converge: stopped after {iterations} iteration(s) "
            f"(max_iterations={max_iterations}); last position RMS {last_rms}. "
            f"Orekit: {exc.getMessage()}"
        ) from None

    if (
        observer.last_residuals_m is None
        or observer.last_pos_rms_m is None
        or observer.last_cost is None
        or observer.last_residual_dim is None
    ):
        # estimate() always evaluates at least once, so this is unreachable in
        # practice; fail honestly rather than assemble a result with no data.
        raise TLEFitError(
            "TLE fit produced no evaluations; cannot assemble a FitResult."
        )

    # sigma0^2 = cost^2 / (m - n): the weighted residual sum of squares over
    # the degrees of freedom. m - n >= 5 always (the 2-sample reference
    # minimum gives m >= 12; n <= 7), so the division is safe.
    sigma0 = math.sqrt(
        observer.last_cost**2 / (observer.last_residual_dim - len(parameter_names))
    )
    covariance: np.ndarray | None
    try:
        cov_j = estimator.getPhysicalCovariances(_COVARIANCE_SINGULARITY_THRESHOLD)
    except jpype.JException as exc:  # type: ignore[attr-defined]
        # Converged fit, singular normal equations: stop-and-report rather
        # than raise (the guard-system spirit) — the fit stands, the
        # diagnostic is honestly absent. Unreached in the Step-0 probes (even
        # a ~1-revolution arc inverted cleanly); kept for the exactly-singular
        # corner.
        warnings.warn(
            "fit_tle: the fit converged but the parameter covariance could "
            f"not be extracted (singular normal equations: {exc.getMessage()})"
            ". FitResult.covariance/sigmas are None; B* is likely fully "
            "unobservable in this arc — consider fit_bstar=False.",
            UserWarning,
            # warn -> _run_estimation -> fit_tle_detailed -> caller.
            stacklevel=3,
        )
        covariance = None
    else:
        dim = int(cov_j.getRowDimension())
        covariance = np.array(
            [[float(cov_j.getEntry(i, j)) for j in range(dim)] for i in range(dim)],
            dtype=np.float64,
        )
    return (
        # The stub type is the Propagator base; the runtime type for a
        # TLEPropagatorBuilder is always TLEPropagator, which carries getTLE().
        propagators[0].getTLE(),  # type: ignore[attr-defined]
        int(estimator.getIterationsCount()),
        int(estimator.getEvaluationsCount()),
        observer.last_pos_rms_m,
        observer.last_residuals_m,
        covariance,
        parameter_names,
        sigma0,
    )


def _assemble_fitted_tle(fitted_j: "Any", identity: _FittedIdentity) -> TLE:
    """The final TLE under the field policy (features.md §1.2 Fitted-TLE table).

    Physics comes from the estimator's converged TLE (epoch, the six mean
    elements, B*); identity comes from :func:`_resolve_identity` (kwargs win,
    then the guess, then placeholders); the mean-motion derivatives are
    **always zeroed, never inherited** — SGP4 ignores them, and a guess's
    values described *its* fit, not ours. Orekit's ``TLE`` constructor formats
    the fixed columns + both checksums, and ``from_strings`` re-validates (the
    ``from_state_unfitted`` pattern), so the return value is always a
    well-formed propygator :class:`TLE`.
    """
    from .._orekit_init import _ensure_started

    _ensure_started()
    from org.orekit.propagation.analytical.tle import TLE as OrekitTLE

    final = OrekitTLE(
        identity.norad_id,
        identity.classification,
        identity.launch_year,
        identity.launch_number,
        identity.launch_piece,
        0,  # ephemeris type (field policy: always 0)
        identity.elset_number,
        fitted_j.getDate(),
        fitted_j.getMeanMotion(),
        0.0,  # mean-motion 1st derivative — always zeroed, never inherited
        0.0,  # mean-motion 2nd derivative — "
        fitted_j.getE(),
        fitted_j.getI(),
        fitted_j.getPerigeeArgument(),
        fitted_j.getRaan(),
        fitted_j.getMeanAnomaly(),
        identity.rev_number,
        fitted_j.getBStar(),
    )
    return TLE.from_strings(
        str(final.getLine1()), str(final.getLine2()), name=identity.name
    )


# --- public verbs ------------------------------------------------------------------


def fit_tle_detailed(
    reference: State | Trajectory,
    *,
    fitting_span: float = 86400.0 * 2,
    force_models: "ForceModelConfig | None" = None,
    spacecraft: "SpacecraftConfig | None" = None,
    initial_guess: TLE | None = None,
    max_iterations: int = 100,
    fit_bstar: bool = True,
    norad_id: int | None = None,
    name: str | None = None,
    progress: "bool | ProgressCallback" = True,
) -> FitResult:
    """Fit a TLE to ``reference`` by batch least squares; return full diagnostics.

    The engine behind :func:`fit_tle` (features.md §1.2 "``FitResult`` and
    ``fit_tle_detailed``"): identical parameters, one implementation; use this
    form when you want the fit diagnostics (iterations, RMS, per-measurement
    residuals, the raw parameter covariance + ``sigma0``) alongside the
    fitted TLE.

    See :func:`fit_tle` for the full parameter and behavior contract.

    Returns a :class:`FitResult`; non-convergence raises
    :class:`~propygator.core.exceptions.TLEFitError` with **no partial result**.
    """
    # --- pre-flight, pure-Python rows first (before any JVM; architecture §10) ---
    if not isinstance(reference, (State, Trajectory)):
        raise TypeError(
            "reference must be a propygator State or Trajectory, got "
            f"{type(reference).__name__}"
        )
    if not math.isfinite(fitting_span) or fitting_span <= 0.0:
        raise ValueError(
            f"fitting_span must be a positive, finite number of seconds, "
            f"got {fitting_span!r}"
        )
    if max_iterations < 1:
        raise ValueError(f"max_iterations must be >= 1, got {max_iterations}")
    if isinstance(reference, State) and reference.frame is not Frame.EME2000:
        # The State path feeds propagate_numerical and inherits its inertial-input
        # rule (features.md §1.2); checked here pre-flight so it fails before the
        # JVM starts, with propagate_numerical's framing.
        raise ValueError(
            "fit_tle requires an inertial State reference (EME2000 / J2000), "
            f"got {reference.frame}. Convert first with "
            "reference.to_frame(Frame.EME2000)."
        )
    if isinstance(reference, Trajectory) and (
        force_models is not None or spacecraft is not None
    ):
        warnings.warn(
            "fit_tle: force_models/spacecraft configure the internal reference "
            "propagation of a State reference and are ignored for a Trajectory "
            "reference (features.md §1.2; architecture §13).",
            UserWarning,
            # warn -> fit_tle_detailed -> caller (direct calls; via the fit_tle
            # wrapper the warning is attributed to the wrapper's line — accepted).
            stacklevel=2,
        )

    # The reporter validates the progress argument itself (shared TypeError) —
    # constructed with the pure rows, before any JVM work (architecture §10).
    reporter = _ProgressReporter("fit_tle", progress)
    # bool is not callable, so this cleanly separates the callable mode from
    # True/False; update() is driven only in callable mode (see _run_estimation).
    deliver_fraction = callable(progress)

    identity = _resolve_identity(initial_guess, norad_id, name)

    # Leading-portion clip for the Trajectory path — pure-Python, kept ahead of
    # the JVM rows so the too-few-samples ValueError raises before the JVM
    # starts (architecture §10).
    normalized_input: State | Trajectory
    if isinstance(reference, Trajectory):
        normalized_input = _clip_leading(reference, fitting_span)
        first = normalized_input[0]
    else:
        normalized_input = reference
        first = reference

    logger.info(
        "fit_tle: reference=%s fitting_span=%.1fs max_iterations=%d fit_bstar=%s",
        type(reference).__name__,
        fitting_span,
        max_iterations,
        fit_bstar,
    )

    # The start line prints before the JVM boots (contract: Progress reporting);
    # the wide try/finally from here through TLE assembly guarantees an honest
    # final line on every exit path — finish() on the classified paths
    # (converged / not converged), close()'s shared "failed at NN%" fallback on
    # anything unclassified (the §1.1 pattern).
    span_h = fitting_span / 3600.0
    reporter.start(f"fitting span {span_h:.1f} h | max {max_iterations} iterations")
    try:
        # --- JVM rows: bound-orbit pre-flight, then normalization ---------------
        # Fail the unbound case fast, before the (possibly minutes-long)
        # State-path internal propagation.
        _check_bound_orbit(first)

        if isinstance(reference, State):
            # The contract's phase line: the internal reference propagation is
            # the one long silent stretch of the State path.
            reporter.step(f"building reference trajectory | {span_h:.1f} h")
        ref_teme = _normalize_reference(
            normalized_input, fitting_span, force_models, spacecraft
        )
        _warn_if_subrevolution(ref_teme)

        seed = _build_seed(ref_teme, initial_guess, identity.norad_id)
        logger.info("fit_tle: seed TLE at reference start — %s", seed.line1)

        # --- the fit -------------------------------------------------------------
        measurements, measurement_epochs = _build_measurements(ref_teme)
        logger.info("fit_tle: %d PV measurements", len(measurements))
        (
            fitted_j,
            iterations,
            evaluations,
            rms_m,
            residuals_m,
            covariance,
            parameter_names,
            sigma0,
        ) = _run_estimation(
            seed, measurements, max_iterations, fit_bstar, reporter, deliver_fraction
        )
        fitted = _assemble_fitted_tle(fitted_j, identity)
        result = FitResult(
            tle=fitted,
            iterations=iterations,
            evaluations=evaluations,
            rms_m=rms_m,
            residuals_m=residuals_m,
            measurement_epochs=measurement_epochs,
            covariance=covariance,
            parameter_names=parameter_names,
            sigma0=sigma0,
        )
        reporter.finish(
            f"done | converged in {iterations} iterations | rms {_format_rms(rms_m)}"
        )
        return result
    finally:
        reporter.close()


def fit_tle(
    reference: State | Trajectory,
    *,
    fitting_span: float = 86400.0 * 2,
    force_models: "ForceModelConfig | None" = None,
    spacecraft: "SpacecraftConfig | None" = None,
    initial_guess: TLE | None = None,
    max_iterations: int = 100,
    fit_bstar: bool = True,
    norad_id: int | None = None,
    name: str | None = None,
    progress: "bool | ProgressCallback" = True,
) -> TLE:
    """Fit a TLE to a reference orbit by least squares (features.md §1.2).

    Re-expresses a reference orbit — a prior numerical propagation, a
    user-assembled trajectory, or another TLE's propagation — as a shareable
    TLE under SGP4/SDP4, via Orekit's batch least squares over the TLE
    parameterization. The faithful sibling of
    :meth:`TLE.from_state_unfitted`: this one actually round-trips.

    **The fit is inherently lossy.** SGP4 is a simplified model (J2/J3/J4
    zonals + a single B* drag term for the near-Earth branch), so a full-force
    numerical orbit can never be reproduced exactly — expect a few hundred
    meters RMS over a 2-day LEO span (the Chunk-0 probe measured ~495 m RMS /
    ~1.1 km max against a ``leo_default`` reference). An SGP4-generated
    reference (path (c)) is recovered essentially exactly.

    ``reference`` shapes (architecture §8):

    - **State** — a reference trajectory is first generated internally over
      ``fitting_span`` via ``propagate_numerical`` with ``force_models``
      (default ``leo_default()``), ``spacecraft`` (default
      ``SpacecraftConfig()``), the default ``LofAligned`` attitude and
      ``IntegratorConfig.high_precision()``. Must be EME2000/J2000 (the
      propagate_numerical inertial rule). Supply your real ``spacecraft`` —
      with drag/SRP on, the reference physics are wrong without your
      mass/area/Cd.
    - **Trajectory** — used directly, any frame (a TLE carries no frame; the
      conversion to TEME is internal). ``force_models`` / ``spacecraft`` are
      ignored with a warning. ``fitting_span`` is clipped to the leading
      ``min(fitting_span, trajectory span)``.

    The fitted TLE's **epoch is the reference start** (first sample in the
    fitting span). ``fit_bstar=True`` (default) estimates B* in the least
    squares — right for LEO, where the default 2-day span makes drag
    observable; the fitted B* is a *fit residual*, not a physical ballistic
    coefficient. Pass ``False`` where B* is unobservable (short spans,
    drag-free regimes like GEO — the estimate would wander, absorbing
    along-track error) to hold the seed's value (``0.0`` without an
    ``initial_guess``). ``initial_guess`` seeds the fit and donates identity;
    ``norad_id`` / ``name`` override identity explicitly (kwarg → guess →
    placeholder). Identity inherits, physics is fitted-or-zeroed — the
    mean-motion derivatives are always ``0.0`` (SGP4 ignores them; a guess's
    values described *its* fit, not ours).

    ``progress`` (features.md §1.2 Progress reporting, indeterminate mode):
    ``True`` streams ``iter N | rms …`` stderr lines plus an honest final line;
    ``False`` is silent; a callable receives ``min(iteration / max_iterations,
    1.0)`` — the fraction of the iteration *budget* consumed, not of work.

    Raises ``ValueError`` pre-flight for a non-positive ``fitting_span`` /
    ``max_iterations < 1`` / a Trajectory with fewer than 2 samples in span /
    a non-inertial ``State`` / an unbound (e >= 1) first sample; propagates
    :class:`~propygator.core.exceptions.NumericalPropagationError` unchanged
    if the internal reference propagation fails; and raises
    :class:`~propygator.core.exceptions.TLEFitError` — with the iteration count
    and last RMS in the message, and **no partial TLE** — when the least
    squares does not converge within ``max_iterations``. A sub-revolution
    fitting arc warns once (weak observability) and proceeds.

    Returns the fitted :class:`TLE`. For the fit diagnostics (iterations,
    RMS, per-measurement residuals, the raw parameter covariance + ``sigma0``
    — the B*-observability instrument) use :func:`fit_tle_detailed`, whose
    parameters are identical and of which this is a thin ``.tle`` wrapper.
    """
    return fit_tle_detailed(
        reference,
        fitting_span=fitting_span,
        force_models=force_models,
        spacecraft=spacecraft,
        initial_guess=initial_guess,
        max_iterations=max_iterations,
        fit_bstar=fit_bstar,
        norad_id=norad_id,
        name=name,
        progress=progress,
    ).tle
