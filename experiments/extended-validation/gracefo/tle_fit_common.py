"""Part 3 arc geometry, the 13 configurations, the r/s gate, and the fade harness.

Everything `run_tle_window.py` and `summarize_tle.py` share, in one place so the
gate cannot be defined twice. Build plan Chunk 14; the contract's "The design --
TLE fitting tests".

**THE ARC GEOMETRY.** Every scored arc ENDS at the same instant ``T = t0 + 6 d``
and they differ only in how far back they reach. Left-aligning them would leave
each method forecasting from a different epoch and the part would measure
arc-end epoch rather than method (contract). The forecast is ``[T, T + 7 d]``,
read at day 1, day 3 and day 7 past T -- each the RMS over that single day, the
per-day rule :func:`drag_common.day_bounds` defines once for the whole study.

**T IS A TRUTH-GRID INDEX, NOT A UTC INSTANT.** GNV1B days start at GPS
midnight, which is UTC midnight - 18 s, so ``epochs[K_T]`` lands 18 s before the
UTC day boundary that the catalogue pull used and that Orekit's daily-Ap
NRLMSISE-00 steps a storm on. Index ``K_T`` is nonetheless the truth sample
NEAREST that boundary (18 s before, against 42 s after for ``K_T + 1``), and it
falls on the pre-onset side -- which is the side `storm_2026_01`'s mandated
fit-right-before-onset case needs. Every driver prints T in both scales with the
offset named; nothing is interpolated, because every residual in this study
aligns to truth by array index.

**THE FADE HARNESS IMPORTS FITTER PRIVATES.** This is the one module in the
study that does (``_run_estimation``, ``_MEASUREMENT_CAP``, ``_SIGMA_POSITION_M``,
``_SIGMA_VELOCITY_MS``, ``_ProgressReporter``) -- documented unsupported usage,
framed exactly as ``tle-fit-strategy/probe2_epoch_and_weights.py`` framed it, and
the reason age weighting is testable with no API change. The ``tau = None``
no-op check in the driver is what proves the private path has not drifted from
the public one.

**`drag_common.py` IS IMPORTED, NEVER EDITED.** It is on the ``--verify`` path
for twenty committed Part 2 results files, so this part brings its own
propagation helper rather than growing a flag on that module's.

Imports ``propygator`` (JVM-free at import) but starts no JVM at import time.
Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
_FROZEN = _STUDY.parent / "real-world-validation"
for _p in (str(_HERE), str(_STUDY), str(_FROZEN), str(_FROZEN / "gracefo")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import ric_components  # noqa: E402
from common import rms as _rms  # noqa: E402
from drag_common import SAMPLES_PER_DAY, day_bounds  # noqa: E402
from gracefo_ext_common import (  # noqa: E402
    NORAD_IDS,
    SUBSAMPLE_S,
    box_spacecraft,
    box_table,
    force_config,
    sphere_spacecraft,
    sphere_table,
)

from propygator import (  # noqa: E402
    TLE,
    Frame,
    InPlaneTracking,
    IntegratorConfig,
    SpacecraftConfig,
    State,
    Trajectory,
    propagate_numerical,
)

SAT = "C"  # Part 3 is GRACE-FO C only (contract: "no Swarms")
NORAD_ID = NORAD_IDS[SAT]
SAT_NAME = "GRACE-FO 1"

# --- arc geometry -------------------------------------------------------------
# NAME COLLISION WITH PART 2, deliberate and contained: gracefo_ext_common
# carries ARC_DAYS = 7.0 / LOAD_DAYS = 8 / READ_DAYS = (1, 3, 7) for the drag
# runs. run_tle_window.py imports its arc and loading constants ONLY from this
# module -- never add any of these three names to its gracefo_ext_common import
# list, or Part 3 would silently fit over Part 2's arc.
ARC_END_DAY = 6.0  # T = t0 + 6 d, the common arc end
FORECAST_DAYS = 7.0  # [T, T + 7 d], window days 6-13
READ_DAYS = (1, 3, 7)  # days PAST T; day N is [N-1 d, N d] alone
LOAD_DAYS = 14  # the last forecast sample sits in the 14th daily file

# Truth index of T on the t0 + k*60 s grid. The forecast reads index K_T + k.
K_T = int(ARC_END_DAY * SAMPLES_PER_DAY)  # 8640
N_FORECAST = int(FORECAST_DAYS * SAMPLES_PER_DAY)  # 10080 steps, 10081 samples

# The staging fits. `fit2` IS the scored `naive_2d` row -- one fit, two uses.
STAGING_SPAN_2_D = 2.0
STAGING_SPAN_3_D = 3.0

# --- the frozen gate ----------------------------------------------------------
# CARRIED VERBATIM FROM docs/tle-fitting-playbook.md:61 AS PRE-REGISTERED
# PREDICTIONS. Re-fitting these to this study's data and then reporting that
# they classify correctly is circular and is forbidden (contract). If they
# misclassify, the misclassification IS the finding; any recalibration is a
# separate, post-hoc result and is labelled as one in Chunk 18.
R_THRESHOLD = 0.05
S_THRESHOLD = 0.1

FADE_TAUS = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


@dataclass(frozen=True)
class Config:
    """One scored row. The 13 configurations are DATA, so drivers loop."""

    id: str
    label: str
    kind: str  # "truth_fit" | "catalog" | "state"
    arc_days: float | None  # None for the catalogue row, which fits nothing
    bstar: str  # "free" | "held_fit2" | "zero" | "catalog"
    tau_days: float | None = None
    geometry: str | None = None  # "sphere" | "box", the state rows only


CONFIGS: tuple[Config, ...] = (
    Config("naive_2d", "naive 2 d (shipped default)", "truth_fit", 2.0, "free"),
    Config("arm_transplant", "arm: transplant fit2 B*", "truth_fit", 1.0, "held_fit2"),
    Config("arm_zero", "arm: fresh 1 d, B* = 0", "truth_fit", 1.0, "zero"),
    Config("arm_fresh", "arm: freshest 1 d, B* free", "truth_fit", 1.0, "free"),
    Config("catalog", "catalogue (Space-Track)", "catalog", None, "catalog"),
    Config("state_sphere", "state path, sphere table", "state", 2.0, "free",
           geometry="sphere"),
    Config("state_box", "state path, box table (IPT)", "state", 2.0, "free",
           geometry="box"),
) + tuple(
    Config(
        f"fade_tau_{tau:g}".replace(".", "p"),
        f"fade tau = {tau:g} d",
        "truth_fit",
        6.0,
        "free",
        tau_days=tau,
    )
    for tau in FADE_TAUS
)

CONFIG_IDS = tuple(c.id for c in CONFIGS)
CONFIGS_BY_ID = {c.id: c for c in CONFIGS}

# The three gated arms, in mapping order -- what [bench-2] scores the gate against.
ARM_IDS = ("arm_transplant", "arm_zero", "arm_fresh")


# --- the per-day slice, forecast-relative -------------------------------------
def forecast_day_bounds(day: int) -> tuple[int, int, int, int]:
    """Inclusive index bounds of forecast day ``day``, in both bases.

    Returns ``(truth_i0, truth_i1, fc_i0, fc_i1)``. DEFINED AS AN OFFSET OF
    :func:`drag_common.day_bounds` rather than as a second slice rule, so Parts 2
    and 3 cannot drift apart on the one definition that matters -- what "day N"
    means. Day 1 past T is truth ``[K_T, K_T + 1440]`` and forecast
    ``[0, 1440]``.
    """
    i0, i1 = day_bounds(day)
    return i0 + K_T, i1 + K_T, i0, i1


def forecast_ric_rms(
    diff: np.ndarray, eph, day: int
) -> tuple[float, float, float, float]:
    """Radial / along / cross / 3D RMS of a forecast residual over one day.

    Earth-fixed RIC, the frozen study's convention -- the same computation
    :func:`drag_common.ric_rms` performs, carrying the ONE difference this part
    needs: ``diff`` is indexed from the forecast start while the truth arrays
    are indexed from t0, so the two slices come from
    :func:`forecast_day_bounds` rather than from a single index pair.
    """
    t0i, t1i, f0i, f1i = forecast_day_bounds(day)
    sl_t, sl_f = slice(t0i, t1i + 1), slice(f0i, f1i + 1)
    ric = ric_components(
        diff[sl_f], eph.positions_m[sl_t], eph.velocities_ms[sl_t], earth_fixed=True
    )
    return (
        _rms(ric[:, 0]),
        _rms(ric[:, 1]),
        _rms(ric[:, 2]),
        _rms(np.linalg.norm(diff[sl_f], axis=1)),
    )


# --- the gate -----------------------------------------------------------------
def parse_bstar(line1: str) -> float:
    """B* from line 1 columns 54-61 (the playbook's own read)."""
    field = line1[53:61]
    sign = -1.0 if field[0] == "-" else 1.0
    return sign * (int(field[1:6]) / 1.0e5) * 10.0 ** int(field[6:8])


def bstar_sigma(fit) -> float | None:
    """Raw formal sigma of B* from a ``FitResult``, or ``None`` if unavailable.

    ``FitResult.sigmas`` is the RAW ``sqrt(diag(covariance))``; the playbook's
    ``r`` multiplies it by ``sigma0`` exactly once, which :func:`compute_rs`
    does. Multiplying here as well would double-count.
    """
    if fit.covariance is None or "BSTAR" not in fit.parameter_names:
        return None
    sigmas = fit.sigmas
    if sigmas is None:
        return None
    return float(sigmas[fit.parameter_names.index("BSTAR")])


def compute_rs(
    sigma0: float,
    sigma_bstar: float | None,
    bstar2: float,
    bstar3: float,
) -> tuple[float, float]:
    """The playbook's two gate numbers, as a pure function of scalars.

    ``r = sigma0 * sigma(B*) / |B*|`` off the 2 d staging fit -- in-arc B*
    observability. ``s = |B*(fit3) - B*(fit2)| / |B*(fit2)|`` -- cross-span
    drift, i.e. nonstationarity.

    DEGENERATE CASES ARE PRE-REGISTERED, not decided after seeing a window: an
    absent covariance (singular normal equations) or a B* of exactly zero makes
    the ratio undefined, and both are returned as ``inf``. An infinite ``r``
    fails ``r < R_THRESHOLD``, so :func:`select_arm` routes to ``arm_zero`` --
    the arm for "B* unobservable", which is exactly the condition that produced
    the degeneracy. ``s`` is only ever consulted when ``r`` is finite and
    nonzero, so the two cannot disagree.

    Pure arithmetic and JVM-free, so Chunk 23's gate pin can call it on
    literals.
    """
    inf = float("inf")
    r = inf if (sigma_bstar is None or bstar2 == 0.0) else sigma0 * sigma_bstar / abs(bstar2)
    s = inf if bstar2 == 0.0 else abs(bstar3 - bstar2) / abs(bstar2)
    return float(r), float(s)


def select_arm(r: float, s: float) -> str:
    """The playbook's gate -> arm mapping (playbook step 3), carried verbatim.

    | r < 0.05 | s < 0.1 | arm             |
    |----------|---------|-----------------|
    | yes      | yes     | arm_transplant  |
    | no       | --      | arm_zero        |
    | yes      | no      | arm_fresh       |

    The third row reads "freshest 1 d fit" in the playbook, ambiguous between
    free and held B*. It is ``arm_fresh`` (free) on the contract's own
    arithmetic -- three DISTINCT playbook fits, and held-zero is already
    ``arm_zero``. Both configurations are measured in every window regardless,
    and ``summarize_tle.py`` prints the substituted mapping as a labelled
    sensitivity line.

    WHAT "VERBATIM" DROPS, AND WHY IT MATTERS AT DAY 7. This mapping is
    horizon-independent by build-plan construction, but two of the playbook's
    rows are not: row 2 scopes ``B* = 0`` to "~3 d horizons" and directs a held
    catalog/known B* at ">= 4 d", and row 3 scopes the fresh fit to "horizon
    <= 1 d, expect km-class regardless". Part 3 reads day 1, day 3 AND day 7,
    so a quiet window's ``arm_zero`` and a storm window's ``arm_fresh`` are
    both scored past the horizon their own source claims for them, and a poor
    day-7 result there is the playbook behaving as documented rather than the
    gate mispredicting. Chunk 18 must read day-3/day-7 gate scoring with that
    stated; the data to separate the two exists, since ``arm_transplant``
    (held B*) runs in every window regardless of what the gate selects. No
    threshold is re-fitted here -- that is forbidden (contract).
    """
    if not (r < R_THRESHOLD):
        return "arm_zero"
    return "arm_transplant" if s < S_THRESHOLD else "arm_fresh"


# --- truth slicing ------------------------------------------------------------
def arc_trajectory(eph, arc_days: float) -> Trajectory:
    """The ITRF truth arc ``[T - arc_days, T]``, inclusive of both ends.

    ``fit_tle_detailed`` clips a Trajectory reference to its LEADING
    ``fitting_span``, so an arc built to exactly these bounds makes the clip a
    no-op and pins the fitted epoch at the arc start (features.md sec 1.2's
    epoch-at-reference-start rule).
    """
    k0 = K_T - int(round(arc_days * SAMPLES_PER_DAY))
    if k0 < 0:
        raise SystemExit(f"arc of {arc_days} d reaches before t0 (index {k0})")
    return Trajectory.from_arrays(
        list(eph.epochs[k0 : K_T + 1]),
        eph.positions_m[k0 : K_T + 1],
        eph.velocities_ms[k0 : K_T + 1],
        Frame.ITRF,
    )


def truth_state(eph, index: int, frame: Frame = Frame.EME2000) -> State:
    """One truth sample as a ``State``, converted out of ITRF."""
    return State(
        eph.epochs[index],
        eph.positions_m[index],
        eph.velocities_ms[index],
        Frame.ITRF,
    ).to_frame(frame)


# --- the state-path references ------------------------------------------------
def state_reference(
    eph, geometry: str, mass_kg: float, arc_days: float
) -> tuple[Trajectory, np.ndarray]:
    """Numerical reference over ``[T - arc_days, T]`` for a state-path row.

    Returns ``(trajectory, itrf_positions)`` -- the trajectory is what gets
    fitted, the positions are what the ``[state]`` block measures drift with.
    The box is flown ``InPlaneTracking(velocity_reference="ecef")`` through the
    external propagate-then-fit route, which ``results_fit_state_path.txt``
    measured as equivalent to the native State path (rows 4 vs 5, deltas
    <= 1.9 m) and which is the only route that can express that attitude. The
    sphere needs no attitude: a sphere's drag and SRP are attitude-independent.

    A guard trip is caught here so the failure names its cause rather than
    surfacing as a shape error inside a fit.
    """
    k0 = K_T - int(round(arc_days * SAMPLES_PER_DAY))
    state0 = truth_state(eph, k0)
    if geometry == "sphere":
        spacecraft: SpacecraftConfig = sphere_spacecraft(sphere_table(), mass_kg=mass_kg)
        attitude = None
    elif geometry == "box":
        spacecraft = box_spacecraft(box_table(), mass_kg=mass_kg)
        attitude = InPlaneTracking(velocity_reference="ecef")
    else:
        raise ValueError(f"geometry must be 'sphere' or 'box', got {geometry!r}")

    traj = propagate_numerical(
        state0,
        arc_days * 86400.0,
        output_step=SUBSAMPLE_S,
        force_models=force_config(drag=True),
        spacecraft=spacecraft,
        attitude=attitude,
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    if traj.metadata.get("terminated"):
        raise SystemExit(
            f"state reference ({geometry}) terminated early: "
            f"{traj.metadata.get('termination_reason')} at "
            f"{traj.metadata.get('termination_epoch')} -- the arc is short of "
            f"{arc_days:.1f} d, so the fit below would not span its own arc"
        )
    return traj, traj.to_frame(Frame.ITRF).positions


# --- the age-weighted (fading-memory) harness ---------------------------------
# Lifted from tle-fit-strategy/probe2_epoch_and_weights.py, with ONE deliberate
# change: the seed is built at the arc START, not the arc end. That is the
# shipped sec 1.2 rule, it is what makes the tau = None no-op check meaningful,
# and probe 2 measured epoch-at-end as a < 2 m no-op anyway. Consequence, stated
# rather than hidden: a 6 d fade arc yields a TLE epoched 6 d before T, so SGP4
# runs 13 d from epoch to the day-7 read.
from propygator.core.progress import _ProgressReporter  # noqa: E402
from propygator.tle.fitter import (  # noqa: E402
    _MEASUREMENT_CAP,
    _SIGMA_POSITION_M,
    _SIGMA_VELOCITY_MS,
    _run_estimation,
)


@dataclass(frozen=True)
class WeightedFit:
    """What the private path returns, reduced to what the driver reports."""

    tle: TLE
    iterations: int
    evaluations: int
    rms_m: float
    bstar: float
    sigma0: float
    sigma_bstar: float | None


def measurement_indices(n: int) -> np.ndarray:
    """The estimator's own even-subsample index set over ``n`` samples.

    Replicates ``fitter._build_measurements`` exactly (verified against that
    function, 2026-08-22). ``run_tle_window.py --emit-fixture`` emits truth at
    these indices so Chunk 23's pin re-subsamples 300 -> 300 and therefore fits
    the IDENTICAL measurement set, off the identical seed sample.
    """
    return np.unique(
        np.round(np.linspace(0, n - 1, min(_MEASUREMENT_CAP, n))).astype(int)
    )


def _build_seed(ref_teme: Trajectory) -> TLE:
    """Fixed-point-refined seed at the reference START, mirroring ``_build_seed``.

    Same mechanism as the public path with no ``initial_guess``: a
    ``from_state_unfitted`` template (B* = 0) at the first sample, refined by
    ``FixedPointTleGenerationAlgorithm``. Reproduced rather than imported
    because the public one is not exposed and the tau = None check has to
    compare against it.
    """
    from org.orekit.orbits import CartesianOrbit
    from org.orekit.propagation import SpacecraftState
    from org.orekit.propagation.analytical.tle import TLEConstants
    from org.orekit.propagation.analytical.tle.generation import (
        FixedPointTleGenerationAlgorithm,
    )

    first = ref_teme[0]
    template = TLE.from_state_unfitted(first, norad_id=NORAD_ID)
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


def _build_measurements(ref_teme: Trajectory, tau_days: float | None) -> list:
    """PV measurements with ``sigma(age) = base * exp(age_days / tau)``.

    ``tau_days = None`` reproduces the public path's uniform sigmas exactly --
    the no-op leg. Age is measured back from the arc END, so the freshest
    samples keep the base sigma and older ones are progressively down-weighted.
    """
    from org.orekit.estimation.measurements import PV, ObservableSatellite

    satellite = ObservableSatellite(0)
    end_epoch = ref_teme.end_epoch
    measurements = []
    for i in measurement_indices(len(ref_teme)):
        sample = ref_teme[int(i)]
        pv = sample._orekit_pv()
        if tau_days is None:
            inflate = 1.0
        else:
            age_d = end_epoch.seconds_since(sample.epoch) / 86400.0
            inflate = float(np.exp(age_d / tau_days))
        measurements.append(
            PV(
                sample.epoch.to_orekit(),
                pv.getPosition(),
                pv.getVelocity(),
                _SIGMA_POSITION_M * inflate,
                _SIGMA_VELOCITY_MS * inflate,
                1.0,
                satellite,
            )
        )
    return measurements


def run_weighted_fit(
    ref: Trajectory, tau_days: float | None, label: str, *, max_iterations: int = 100
) -> WeightedFit:
    """One age-weighted fit through the fitter internals.

    ``ref`` is taken in any frame and converted to TEME here, mirroring
    ``_normalize_reference``, so a caller can hand this the same ITRF arc it
    hands the public verb.

    THE WEIGHTED DIAGNOSTICS NEVER FEED THE GATE. Age weighting turns
    ``sigma0`` and the covariance into weighted quantities and the playbook's
    thresholds do not carry over, so these are printed and never compared
    against R_THRESHOLD / S_THRESHOLD (contract build caveat;
    ``tle-fit-strategy-findings.md`` sec 3, the conservative default).
    """
    ref_teme = ref.to_frame(Frame.TEME)
    seed = _build_seed(ref_teme)
    measurements = _build_measurements(ref_teme, tau_days)
    reporter = _ProgressReporter(f"tle_fit:{label}", False)
    try:
        (
            fitted_j,
            iterations,
            evaluations,
            rms_m,
            _res,
            _vres,
            _ric,
            covariance,
            names,
            sigma0,
        ) = _run_estimation(seed, measurements, max_iterations, True, reporter, False)
    finally:
        reporter.close()
    tle = TLE.from_strings(
        str(fitted_j.getLine1()), str(fitted_j.getLine2()), name=SAT_NAME
    )
    sigma_bstar = None
    if covariance is not None and "BSTAR" in names:
        k = names.index("BSTAR")
        sigma_bstar = float(np.sqrt(covariance[k, k]))
    return WeightedFit(
        tle=tle,
        iterations=int(iterations),
        evaluations=int(evaluations),
        rms_m=float(rms_m),
        bstar=parse_bstar(tle.line1),
        sigma0=float(sigma0),
        sigma_bstar=sigma_bstar,
    )
