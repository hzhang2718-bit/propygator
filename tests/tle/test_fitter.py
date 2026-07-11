"""Feature 1.2 fitter tests (features.md §1.2).

Chunk-1 surface: the pre-flight ``ValueError`` table, the ``FitResult`` value
type, the Trajectory-path warn-and-ignore, leading-span clipping, TEME
normalization, the internal-propagation failure passthrough, and the
fixed-point seed. Chunk-2 surface: the estimator core — the self-fit gate
(path (c), the known-exact-answer case), the fitted-TLE field-policy table,
``fit_bstar`` hold, the wrapper/engine agreement + ``FitResult`` invariants,
and the ``TLEFitError`` non-convergence path.

The pure-Python rows run fixture-free (they must raise before the JVM starts —
the architecture §10 "safe before init" discipline); JVM rows acquire the
session ``orekit`` fixture (directly or via the module-scoped reference
fixtures), which is how the conftest ordering hook schedules them after the
no-JVM guards.
"""

from __future__ import annotations

import inspect
import math
import warnings
from datetime import datetime, timezone

import numpy as np
import pytest

from propygator import (
    TLE,
    Epoch,
    ForceModelConfig,
    Frame,
    IntegratorConfig,
    NumericalPropagationError,
    SpacecraftConfig,
    State,
    TimeScale,
    Trajectory,
    propagate_numerical,
    propagate_tle,
)
from propygator.tle.fitter import (
    FitResult,
    _build_seed,
    _clip_leading,
    _normalize_reference,
    _resolve_identity,
    _warn_if_subrevolution,
    fit_tle,
    fit_tle_detailed,
)

# The suite's ISS fixture (tests/core/test_tle.py) — epoch 2026-06-20.
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


def _epoch(offset_s: float = 0.0) -> Epoch:
    base = Epoch.from_datetime(
        datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc), TimeScale.UTC
    )
    return base.shifted_by(offset_s)


def _leo_state(frame: Frame = Frame.EME2000) -> State:
    """A plausible bound LEO state (pure-Python construction)."""
    return State(
        _epoch(),
        np.array([6778.0e3, 0.0, 0.0]),
        np.array([0.0, 7.67e3, 0.0]),
        frame,
    )


def _toy_trajectory(n: int = 3, step_s: float = 100.0) -> Trajectory:
    """A tiny JVM-free trajectory; contents are arbitrary (pre-flight rows only)."""
    states = [
        State(
            _epoch(k * step_s),
            np.array([6778.0e3 + 1000.0 * k, 0.0, 0.0]),
            np.array([0.0, 7.67e3, 0.0]),
            Frame.TEME,
        )
        for k in range(n)
    ]
    return Trajectory.from_states(states)


def _iss_tle() -> TLE:
    return TLE.from_strings(ISS_LINE1, ISS_LINE2, name="ISS (ZARYA)")


def _valid_fit_result(**overrides: object) -> FitResult:
    kwargs: dict = {
        "tle": _iss_tle(),
        "iterations": 7,
        "evaluations": 8,
        "rms_m": 0.5,
        "residuals_m": np.array([0.4, 0.5, 0.6]),
        "measurement_epochs": (_epoch(0.0), _epoch(60.0), _epoch(120.0)),
    }
    kwargs.update(overrides)
    return FitResult(**kwargs)


# ---------------------------------------------------------------------------
# Pre-flight ValueError table — pure-Python rows (no JVM, no fixture)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad_span", [0.0, -1.0, float("nan"), float("inf")])
def test_fitting_span_must_be_positive_finite(bad_span: float) -> None:
    with pytest.raises(ValueError, match="fitting_span"):
        fit_tle(_leo_state(), fitting_span=bad_span)


@pytest.mark.parametrize("bad_iter", [0, -5])
def test_max_iterations_below_one_raises(bad_iter: int) -> None:
    with pytest.raises(ValueError, match="max_iterations"):
        fit_tle(_leo_state(), max_iterations=bad_iter)


def test_reference_wrong_type_raises() -> None:
    with pytest.raises(TypeError, match="State or Trajectory"):
        fit_tle([1.0, 2.0, 3.0])  # type: ignore[arg-type]


@pytest.mark.parametrize("frame", [Frame.TEME, Frame.ITRF])
def test_state_reference_must_be_eme2000(frame: Frame) -> None:
    with pytest.raises(ValueError, match="EME2000"):
        fit_tle(_leo_state(frame=frame))


def test_trajectory_too_few_samples_in_span_raises() -> None:
    # Samples at 0/100/200 s; a 50 s span keeps only the first -> < 2 samples.
    with pytest.raises(ValueError, match="at least 2"):
        fit_tle(_toy_trajectory(), fitting_span=50.0)


def test_single_sample_trajectory_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        fit_tle(_toy_trajectory(n=1))


@pytest.mark.parametrize(
    "physics_kwargs",
    [
        {"force_models": ForceModelConfig.keplerian()},
        {"spacecraft": SpacecraftConfig()},
        {
            "force_models": ForceModelConfig.keplerian(),
            "spacecraft": SpacecraftConfig(),
        },
    ],
)
def test_trajectory_reference_warns_and_ignores_physics_configs(
    physics_kwargs: dict,
) -> None:
    # The warning must precede the (deliberately triggered, still pure-Python)
    # too-few-samples ValueError, proving warn-then-proceed ordering.
    with pytest.warns(UserWarning, match="ignored"):
        with pytest.raises(ValueError, match="at least 2"):
            fit_tle(_toy_trajectory(), fitting_span=50.0, **physics_kwargs)


def test_state_reference_does_not_warn_for_physics_configs() -> None:
    # Same kwargs on the State path are meaningful — no warning; the call then
    # fails on the (pure-Python) non-inertial row we arrange deliberately.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        with pytest.raises(ValueError, match="EME2000"):
            fit_tle(
                _leo_state(frame=Frame.TEME),
                force_models=ForceModelConfig.keplerian(),
            )


def test_wrapper_and_engine_signatures_identical() -> None:
    # Contract: fit_tle_detailed has the identical parameter list, row for row.
    params_wrapper = inspect.signature(fit_tle).parameters
    params_engine = inspect.signature(fit_tle_detailed).parameters
    assert list(params_wrapper) == list(params_engine)
    for name in params_wrapper:
        assert params_wrapper[name].default == params_engine[name].default
        assert params_wrapper[name].kind == params_engine[name].kind


# ---------------------------------------------------------------------------
# _resolve_identity — pure-Python
# ---------------------------------------------------------------------------


def test_identity_placeholders_without_guess() -> None:
    identity = _resolve_identity(None, None, None)
    assert identity.norad_id == 0
    assert identity.name is None
    assert identity.classification == "U"
    assert identity.launch_year == 0
    assert identity.launch_number == 0
    assert identity.launch_piece == ""
    assert identity.elset_number == 0
    assert identity.rev_number == 0


def test_identity_kwargs_without_guess() -> None:
    identity = _resolve_identity(None, 42, "SAILCRAFT")
    assert identity.norad_id == 42
    assert identity.name == "SAILCRAFT"


def test_identity_inherited_from_guess() -> None:
    identity = _resolve_identity(_iss_tle(), None, None)
    assert identity.norad_id == 25544
    assert identity.name == "ISS (ZARYA)"
    assert identity.classification == "U"
    assert identity.launch_year == 1998
    assert identity.launch_number == 67
    assert identity.launch_piece == "A"
    assert identity.elset_number == 999
    assert identity.rev_number == 57225


def test_identity_kwargs_win_over_guess() -> None:
    identity = _resolve_identity(_iss_tle(), 99999, "OVERRIDE")
    assert identity.norad_id == 99999
    assert identity.name == "OVERRIDE"
    # Non-overridable fields still inherit.
    assert identity.launch_year == 1998


# ---------------------------------------------------------------------------
# FitResult — pure-Python value type
# ---------------------------------------------------------------------------


def test_fit_result_valid_construction() -> None:
    result = _valid_fit_result()
    assert result.tle == _iss_tle()
    assert result.iterations == 7
    assert result.evaluations == 8
    assert result.rms_m == 0.5
    assert result.residuals_m.shape == (3,)
    assert isinstance(result.measurement_epochs, tuple)
    assert len(result.measurement_epochs) == 3


def test_fit_result_residuals_defensively_copied_and_read_only() -> None:
    source = np.array([0.4, 0.5, 0.6])
    result = _valid_fit_result(residuals_m=source)
    source[0] = 999.0  # caller mutation must not reach the value type
    assert result.residuals_m[0] == 0.4
    with pytest.raises(ValueError):
        result.residuals_m[0] = 1.0  # read-only contents


def test_fit_result_epochs_list_coerced_to_tuple() -> None:
    result = _valid_fit_result(
        measurement_epochs=[_epoch(0.0), _epoch(60.0), _epoch(120.0)]
    )
    assert isinstance(result.measurement_epochs, tuple)


def test_fit_result_value_equality_and_hash() -> None:
    a = _valid_fit_result()
    b = _valid_fit_result()
    assert a == b
    assert hash(a) == hash(b)
    c = _valid_fit_result(rms_m=0.7)
    assert a != c
    d = _valid_fit_result(residuals_m=np.array([0.4, 0.5, 0.7]))
    assert a != d


@pytest.mark.parametrize(
    ("overrides", "exc"),
    [
        ({"tle": "not a tle"}, TypeError),
        ({"iterations": -1}, ValueError),
        ({"iterations": True}, TypeError),
        ({"iterations": 2.0}, TypeError),
        ({"evaluations": 0}, ValueError),
        ({"iterations": 9, "evaluations": 8}, ValueError),
        ({"rms_m": float("nan")}, ValueError),
        ({"rms_m": -0.1}, ValueError),
        ({"rms_m": "0.5"}, TypeError),
        ({"residuals_m": [0.4, 0.5, 0.6]}, TypeError),
        ({"residuals_m": np.array([[0.4, 0.5, 0.6]])}, ValueError),
        ({"residuals_m": np.array([0.4, 0.5, 0.6], dtype=np.float32)}, ValueError),
        ({"residuals_m": np.array([0.4, -0.5, 0.6])}, ValueError),
        ({"residuals_m": np.array([0.4, np.nan, 0.6])}, ValueError),
        ({"measurement_epochs": (_epoch(0.0), _epoch(60.0))}, ValueError),
        ({"measurement_epochs": (_epoch(0.0), _epoch(60.0), "x")}, TypeError),
    ],
)
def test_fit_result_validation_rows(overrides: dict, exc: type[Exception]) -> None:
    with pytest.raises(exc):
        _valid_fit_result(**overrides)


# ---------------------------------------------------------------------------
# JVM rows — reference normalization, bound-orbit pre-flight, the seed
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def iss_ref_teme(orekit: None) -> Trajectory:
    """A 2 h @ 60 s SGP4 reference for the ISS fixture (121 TEME samples)."""
    return propagate_tle(_iss_tle(), 7200.0, output_step=60.0)


@pytest.mark.usefixtures("orekit")
def test_unbound_reference_raises_pre_flight() -> None:
    # ~12 km/s tangential at LEO radius is well above escape -> osculating e > 1.
    hyperbolic = State(
        _epoch(),
        np.array([6778.0e3, 0.0, 0.0]),
        np.array([0.0, 12.0e3, 0.0]),
        Frame.EME2000,
    )
    with pytest.raises(ValueError, match="bound"):
        fit_tle(hyperbolic)


def test_clip_leading_keeps_span_inclusive(iss_ref_teme: Trajectory) -> None:
    clipped = _clip_leading(iss_ref_teme, 3600.0)
    # 0..3600 s inclusive at 60 s -> 61 samples, leading portion, start unchanged.
    assert len(clipped) == 61
    assert clipped.start_epoch == iss_ref_teme.start_epoch
    assert clipped.end_epoch.seconds_since(clipped.start_epoch) == pytest.approx(
        3600.0, abs=1e-9
    )


def test_clip_leading_full_span_returns_same_object(iss_ref_teme: Trajectory) -> None:
    assert _clip_leading(iss_ref_teme, 7200.0) is iss_ref_teme


def test_normalize_reference_converts_any_frame_to_teme(
    iss_ref_teme: Trajectory,
) -> None:
    # The contract accepts a Trajectory in any frame; normalization must land in
    # TEME and preserve the samples (round-trip against the native TEME clip).
    clipped_teme = _clip_leading(iss_ref_teme, 3600.0)
    eme = clipped_teme.to_frame(Frame.EME2000)
    normalized = _normalize_reference(eme, 3600.0, None, None)
    assert normalized.frame is Frame.TEME
    assert len(normalized) == 61
    np.testing.assert_allclose(normalized.positions, clipped_teme.positions, atol=1e-3)


def test_normalize_reference_teme_passthrough_is_no_copy(
    iss_ref_teme: Trajectory,
) -> None:
    assert _normalize_reference(iss_ref_teme, 7200.0, None, None) is iss_ref_teme


@pytest.mark.usefixtures("orekit")
def test_state_path_internal_grid(iss_ref_teme: Trajectory) -> None:
    # A short keplerian-force internal propagation exercises the State-path
    # normalization end-to-end: ~300-sample grid, TEME output, span honored.
    state = iss_ref_teme[0].to_frame(Frame.EME2000)
    normalized = _normalize_reference(
        state, 600.0, ForceModelConfig.keplerian(), SpacecraftConfig()
    )
    assert normalized.frame is Frame.TEME
    assert len(normalized) == 300
    assert normalized.start_epoch == state.epoch
    assert normalized.end_epoch.seconds_since(normalized.start_epoch) == pytest.approx(
        600.0, abs=1e-6
    )


def test_subrevolution_span_warns(iss_ref_teme: Trajectory) -> None:
    short = _normalize_reference(
        _clip_leading(iss_ref_teme, 1800.0), 1800.0, None, None
    )
    with pytest.warns(UserWarning, match="revolution"):
        _warn_if_subrevolution(short)


def test_full_revolution_span_does_not_warn(iss_ref_teme: Trajectory) -> None:
    # 2 h > the ~93 min ISS period: no observability warning.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        _warn_if_subrevolution(iss_ref_teme)


@pytest.mark.usefixtures("orekit")
def test_internal_propagation_failure_passes_through(
    iss_ref_teme: Trajectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Contract: a failed State-path internal propagation propagates the
    # NumericalPropagationError unchanged. The fitter's lazy in-body import
    # resolves propagate_numerical at call time, so patching the propagation
    # module attribute intercepts exactly the internal call site.
    sentinel = NumericalPropagationError("synthetic reference-propagation failure")

    def _boom(*args: object, **kwargs: object) -> None:
        raise sentinel

    monkeypatch.setattr("propygator.propagation.numerical.propagate_numerical", _boom)
    state = iss_ref_teme[0].to_frame(Frame.EME2000)
    with pytest.raises(NumericalPropagationError) as excinfo:
        fit_tle(state)
    assert excinfo.value is sentinel


@pytest.mark.usefixtures("orekit")
def test_state_path_terminated_partial_reference_warns(
    iss_ref_teme: Trajectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The guard system stops-and-reports (features §1.1): a re-entry returns a
    # PARTIAL trajectory with `terminated` metadata instead of raising. The
    # fitter must not silently fit a shorter arc than requested — it warns and
    # proceeds on the realized arc.
    partial = _clip_leading(iss_ref_teme, 7200.0)
    partial.metadata["terminated"] = True
    partial.metadata["termination_reason"] = "reentry"
    monkeypatch.setattr(
        "propygator.propagation.numerical.propagate_numerical",
        lambda *args, **kwargs: partial,
    )
    state = iss_ref_teme[0].to_frame(Frame.EME2000)
    with pytest.warns(UserWarning, match="terminated early"):
        result = fit_tle_detailed(state, fitting_span=86400.0, norad_id=25544)
    # The fit covers the realized 2 h arc, not the requested 24 h.
    assert result.measurement_epochs[-1] == partial.end_epoch


@pytest.mark.usefixtures("orekit")
def test_state_path_immediately_terminated_reference_raises(
    iss_ref_teme: Trajectory, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A termination inside the first output step leaves a 1-sample partial —
    # no arc to fit; a clean ValueError beats an opaque singular-LM failure.
    stub = Trajectory.from_states([iss_ref_teme[0]])
    stub.metadata["terminated"] = True
    stub.metadata["termination_reason"] = "reentry"
    monkeypatch.setattr(
        "propygator.propagation.numerical.propagate_numerical",
        lambda *args, **kwargs: stub,
    )
    state = iss_ref_teme[0].to_frame(Frame.EME2000)
    with pytest.raises(ValueError, match="terminated immediately"):
        fit_tle(state)


# --- the seed ---------------------------------------------------------------


def test_seed_fixed_point_refines_first_sample(iss_ref_teme: Trajectory) -> None:
    from propygator.tle.propagator import _tle_state_at

    first = iss_ref_teme[0]
    seed = _build_seed(iss_ref_teme, None, 25544)
    raw = TLE.from_state_unfitted(first, norad_id=25544)

    seed_err = float(
        np.linalg.norm(_tle_state_at(seed, first.epoch).position - first.position)
    )
    raw_err = float(
        np.linalg.norm(_tle_state_at(raw, first.epoch).position - first.position)
    )
    # The fixed-point seed reproduces the first sample to TLE-column precision
    # (probe: ~mm before formatting; the fixed-column rounding dominates), while
    # the raw osculating-in-mean-slots template is off by the J2 short-period
    # scale (km-tens of km). The refinement must actually refine.
    assert seed_err < 500.0
    assert raw_err > seed_err
    assert seed.norad_id == 25544


def test_seed_epoch_is_reference_start(iss_ref_teme: Trajectory) -> None:
    seed = _build_seed(iss_ref_teme, None, 25544)
    # The TLE epoch field quantizes at 1e-8 day ~ 0.86 ms.
    assert abs(seed.epoch.seconds_since(iss_ref_teme.start_epoch)) < 5e-3


@pytest.mark.usefixtures("orekit")
def test_seed_reanchors_guess_epoch_and_inherits_bstar() -> None:
    # A guess at a different epoch is legal: the seed re-derives the elements at
    # the reference start (fitted epoch = reference start, the contract pin)
    # while inheriting the guess's B*.
    guess = _iss_tle()
    ref = propagate_tle(
        guess, 3600.0, output_step=60.0, start=guess.epoch.shifted_by(7200.0)
    )
    seed = _build_seed(ref, guess, guess.norad_id)
    assert abs(seed.epoch.seconds_since(ref.start_epoch)) < 5e-3
    assert abs(seed.epoch.seconds_since(guess.epoch)) > 7000.0
    assert seed.to_orekit().getBStar() == pytest.approx(1.66e-4, rel=1e-9)
    assert seed.norad_id == 25544


# ---------------------------------------------------------------------------
# The estimator core (Chunk 2) — the self-fit gate, field policy, failure paths
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def iss_ref_2d(orekit: None) -> Trajectory:
    """The self-fit gate reference: ISS, 2 d @ 60 s (2881 TEME samples)."""
    return propagate_tle(_iss_tle(), 2 * 86400.0, output_step=60.0)


@pytest.fixture(scope="module")
def self_fit(iss_ref_2d: Trajectory) -> FitResult:
    """One converged self-fit shared by the gate + FitResult-invariant tests."""
    return fit_tle_detailed(iss_ref_2d, norad_id=25544)


def test_self_fit_gate_recovers_source(
    iss_ref_2d: Trajectory, self_fit: FitResult
) -> None:
    # Path (c), the known-exact-answer case: fit an SGP4 trajectory of a known
    # TLE and reproduce it. The Chunk-0 probe recovered the source to the
    # printed digit (propagate-back residual 0 m over the full grid); pin a
    # tight-but-safe sub-meter bound (contract: Testing / self-fit gate).
    back = propagate_tle(
        self_fit.tle, 2 * 86400.0, output_step=60.0, start=iss_ref_2d.start_epoch
    )
    residuals = np.linalg.norm(back.positions - iss_ref_2d.positions, axis=1)
    assert float(np.sqrt(np.mean(residuals**2))) < 1.0
    assert self_fit.rms_m < 1.0

    # Element recovery: the fitted fields match the source to (at worst) one
    # fixed-column quantum per field. B* recovery included (fit_bstar default).
    source = _iss_tle().to_orekit()
    fitted = self_fit.tle.to_orekit()
    rev_day = 86400.0 / (2.0 * math.pi)
    assert fitted.getMeanMotion() * rev_day == pytest.approx(
        source.getMeanMotion() * rev_day, abs=1e-7
    )
    assert fitted.getE() == pytest.approx(source.getE(), abs=2e-7)
    for getter in ("getI", "getRaan", "getPerigeeArgument", "getMeanAnomaly"):
        assert math.degrees(getattr(fitted, getter)()) == pytest.approx(
            math.degrees(getattr(source, getter)()), abs=2e-4
        )
    assert fitted.getBStar() == pytest.approx(1.66e-4, abs=1e-8)


def test_wrapper_returns_engine_tle(
    iss_ref_2d: Trajectory, self_fit: FitResult
) -> None:
    # Contract: fit_tle(...) is fit_tle_detailed(...).tle — one engine, and the
    # LM fit is deterministic, so a second run reproduces the first exactly.
    assert fit_tle(iss_ref_2d, norad_id=25544) == self_fit.tle


def test_fit_result_invariants(iss_ref_2d: Trajectory, self_fit: FitResult) -> None:
    # 2881 samples subsample to the 300-measurement cap, chronologically.
    assert len(self_fit.measurement_epochs) == 300
    assert self_fit.residuals_m.shape == (300,)
    assert self_fit.measurement_epochs[0] == iss_ref_2d.start_epoch
    assert self_fit.measurement_epochs[-1] == iss_ref_2d.end_epoch
    # rms_m is exactly the RMS of the per-measurement residuals.
    assert self_fit.rms_m == pytest.approx(
        float(np.sqrt(np.mean(self_fit.residuals_m**2))), rel=1e-12
    )
    assert self_fit.iterations >= 1
    assert self_fit.evaluations >= self_fit.iterations


def test_field_policy_without_guess(iss_ref_2d: Trajectory) -> None:
    # Placeholder identity set (features.md §1.2 field-policy table, "Without").
    fitted = fit_tle(iss_ref_2d, fitting_span=21600.0)
    assert fitted.norad_id == 0
    assert fitted.name is None
    assert fitted.line1[2:7] == "00000"
    assert fitted.line1[7] == "U"  # classification placeholder
    j = fitted.to_orekit()
    assert float(j.getMeanMotionFirstDerivative()) == 0.0
    assert float(j.getMeanMotionSecondDerivative()) == 0.0
    assert int(j.getElementNumber()) == 0
    assert int(j.getRevolutionNumberAtEpoch()) == 0


def test_field_policy_inherits_guess_identity(iss_ref_2d: Trajectory) -> None:
    # "With initial_guess": identity inherits verbatim — including the stale
    # rev number — while the physics fields are fitted and n-dot/n-ddot are
    # zeroed even though the guess's line 1 carries .00008813.
    fitted = fit_tle(iss_ref_2d, fitting_span=21600.0, initial_guess=_iss_tle())
    assert fitted.norad_id == 25544
    assert fitted.name == "ISS (ZARYA)"
    assert fitted.line1[9:17].strip() == "98067A"  # international designator
    j = fitted.to_orekit()
    assert int(j.getElementNumber()) == 999  # verbatim, no auto-increment
    assert int(j.getRevolutionNumberAtEpoch()) == 57225  # verbatim (stale)
    assert float(j.getMeanMotionFirstDerivative()) == 0.0  # never inherited
    assert float(j.getMeanMotionSecondDerivative()) == 0.0


def test_field_policy_kwargs_win_over_guess(iss_ref_2d: Trajectory) -> None:
    fitted = fit_tle(
        iss_ref_2d,
        fitting_span=21600.0,
        initial_guess=_iss_tle(),
        norad_id=90000,
        name="RENAMED",
    )
    assert fitted.norad_id == 90000
    assert fitted.name == "RENAMED"
    # Non-kwarg identity still inherits from the guess.
    assert fitted.line1[9:17].strip() == "98067A"


def test_fit_bstar_false_holds_seed_bstar(iss_ref_2d: Trajectory) -> None:
    # Without a guess the seed's B* is 0.0; with a guess it is the guess's.
    # Held bit-exact either way (Chunk-0 probe behavior, now pinned).
    held_zero = fit_tle(iss_ref_2d, fitting_span=21600.0, fit_bstar=False)
    assert float(held_zero.to_orekit().getBStar()) == 0.0
    held_guess = fit_tle(
        iss_ref_2d,
        fitting_span=21600.0,
        fit_bstar=False,
        initial_guess=_iss_tle(),
    )
    assert float(held_guess.to_orekit().getBStar()) == pytest.approx(1.66e-4, rel=1e-12)


# ---------------------------------------------------------------------------
# Progress wiring (Chunk 3) — the reporter's indeterminate mode through the fit
# ---------------------------------------------------------------------------


def _fit_tle_lines(err: str) -> list[str]:
    return [line for line in err.splitlines() if line.startswith("fit_tle:")]


@pytest.mark.usefixtures("orekit")
def test_progress_true_prints_start_iter_and_done_lines(
    iss_ref_2d: Trajectory, capsys: pytest.CaptureFixture[str]
) -> None:
    fit_tle(iss_ref_2d, fitting_span=21600.0, progress=True)
    lines = _fit_tle_lines(capsys.readouterr().err)
    assert lines and lines[0].startswith("fit_tle: start |")

    iter_lines = [line for line in lines if "iter " in line and "| rms " in line]
    assert len(iter_lines) >= 2
    # Dedupe pin: one line per iteration — strictly increasing iteration
    # numbers (Orekit fires the observer per *evaluation*; Chunk 0).
    iterations = [int(line.split("iter ")[1].split(" |")[0]) for line in iter_lines]
    assert all(b > a for a, b in zip(iterations, iterations[1:]))

    done_lines = [line for line in lines if "done | converged in" in line]
    assert len(done_lines) == 1
    assert lines[-1] == done_lines[0]  # exactly one final line, last
    assert "rms" in done_lines[0]
    capsys.readouterr().err.encode("ascii")  # stderr stays ASCII-only


@pytest.mark.usefixtures("orekit")
def test_progress_failure_prints_honest_final_line(
    iss_ref_2d: Trajectory, capsys: pytest.CaptureFixture[str]
) -> None:
    from propygator import TLEFitError

    with pytest.raises(TLEFitError):
        fit_tle(iss_ref_2d, fitting_span=21600.0, max_iterations=1, progress=True)
    lines = _fit_tle_lines(capsys.readouterr().err)
    finals = [
        line for line in lines if "failed at iter" in line and "not converged" in line
    ]
    assert len(finals) == 1
    assert lines[-1] == finals[0]  # the honest final line is the last line
    assert "last rms" in finals[0]


@pytest.mark.usefixtures("orekit")
def test_progress_state_path_phase_line(
    iss_ref_2d: Trajectory,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    reference = _clip_leading(iss_ref_2d, 7200.0)
    monkeypatch.setattr(
        "propygator.propagation.numerical.propagate_numerical",
        lambda *args, **kwargs: reference,
    )
    state = iss_ref_2d[0].to_frame(Frame.EME2000)
    fit_tle(state, fitting_span=7200.0, progress=True)
    err = capsys.readouterr().err
    assert "fit_tle: building reference trajectory | 2.0 h" in err


@pytest.mark.usefixtures("orekit")
def test_progress_false_is_silent(
    iss_ref_2d: Trajectory, capsys: pytest.CaptureFixture[str]
) -> None:
    fit_tle(iss_ref_2d, fitting_span=21600.0, progress=False)
    assert capsys.readouterr().err == ""


@pytest.mark.usefixtures("orekit")
def test_progress_bad_type_raises_before_jvm_work(iss_ref_2d: Trajectory) -> None:
    with pytest.raises(TypeError, match="progress"):
        fit_tle(iss_ref_2d, progress="yes")  # type: ignore[arg-type]


@pytest.mark.usefixtures("orekit")
def test_progress_callable_gets_budget_fractions_and_silence(
    iss_ref_2d: Trajectory, capsys: pytest.CaptureFixture[str]
) -> None:
    fractions: list[float] = []
    result = fit_tle_detailed(iss_ref_2d, progress=fractions.append)
    # A callable silences the built-in printer entirely.
    assert capsys.readouterr().err == ""
    # Budget fractions: monotonic, 0-1-typed, and short of 1.0 on a converged
    # fit that did not exhaust the default 100-iteration budget.
    assert fractions
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert fractions == sorted(fractions)
    assert fractions[-1] < 1.0
    assert result.iterations < 100


@pytest.mark.usefixtures("orekit")
def test_progress_callable_reaches_one_only_when_budget_exhausted(
    iss_ref_2d: Trajectory,
) -> None:
    from propygator import TLEFitError

    fractions: list[float] = []
    with pytest.raises(TLEFitError):
        fit_tle(
            iss_ref_2d,
            fitting_span=21600.0,
            max_iterations=3,
            progress=fractions.append,
        )
    assert fractions
    assert fractions == sorted(fractions)
    assert fractions[-1] == 1.0  # the budget-exhausted path, and only that path


def test_non_convergence_raises_tle_fit_error(iss_ref_2d: Trajectory) -> None:
    # The self-fit needs ~14 iterations from the fixed-point seed (Chunk-0
    # probe); a budget of 1 cannot converge. The message carries the iteration
    # count and the last RMS; no Java traceback is chained (architecture §3).
    from propygator import PropagationError, TLEFitError

    with pytest.raises(TLEFitError, match=r"iteration") as excinfo:
        fit_tle(iss_ref_2d, fitting_span=21600.0, max_iterations=1)
    assert "RMS" in str(excinfo.value)
    assert excinfo.value.__cause__ is None
    # Sibling of PropagationError, deliberately not a subclass.
    assert not isinstance(excinfo.value, PropagationError)


# ---------------------------------------------------------------------------
# Validation battery (Chunk 4) — the honest numbers the docs quote
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def numerical_fit(iss_ref_2d: Trajectory) -> FitResult:
    """Path (a) end-to-end: the State path builds its own internal 2-day
    ``leo_default`` / ``high_precision`` reference (the probe's scenario (ii))."""
    state0 = iss_ref_2d[0].to_frame(Frame.EME2000)
    return fit_tle_detailed(state0, norad_id=25544, progress=False)


def test_numerical_fit_documented_rms(numerical_fit: FitResult) -> None:
    # The lossiness caveat made quantitative (contract: Testing / numerical
    # fit): the Chunk-0 probe measured ~495 m RMS / ~1119 m max over 2 days
    # against a leo_default reference. Pinned with slack; these bounds back the
    # docstring's "~495 m RMS / ~1.1 km max" claim.
    assert numerical_fit.rms_m < 1000.0
    assert float(numerical_fit.residuals_m.max()) < 1500.0
    assert numerical_fit.iterations < 100  # converged well inside the budget


def test_numerical_fit_bstar_is_a_fit_residual(numerical_fit: FitResult) -> None:
    # B* absorbs the drag of THIS arc — plausible LEO magnitude, but not the
    # catalog value (probe: 3.0e-5 vs the TLE's 1.66e-4), exactly as the
    # docstring warns.
    bstar = float(numerical_fit.tle.to_orekit().getBStar())
    assert 0.0 < bstar < 1.0e-3
    assert abs(bstar - 1.66e-4) > 1.0e-5


@pytest.fixture(scope="module")
def leo_numerical_ref(iss_ref_2d: Trajectory) -> Trajectory:
    """An external 2-day leo_default reference (600 s grid) for same-reference
    comparisons — the B* on/off discriminator needs one shared measurement set."""
    state0 = iss_ref_2d[0].to_frame(Frame.EME2000)
    return propagate_numerical(
        state0,
        2 * 86400.0,
        output_step=600.0,
        force_models=ForceModelConfig.leo_default(),
        spacecraft=SpacecraftConfig(),
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )


def test_bstar_recovery_beats_held_bstar(leo_numerical_ref: Trajectory) -> None:
    # Contract: Testing / B* recovery — on a drag-observable 2-day LEO arc,
    # estimating B* beats holding it (probe: 495 m vs 541 m RMS).
    fit_on = fit_tle_detailed(leo_numerical_ref, norad_id=25544, progress=False)
    fit_off = fit_tle_detailed(
        leo_numerical_ref, norad_id=25544, fit_bstar=False, progress=False
    )
    assert fit_on.rms_m < fit_off.rms_m
    assert float(fit_on.tle.to_orekit().getBStar()) > 0.0
    assert float(fit_off.tle.to_orekit().getBStar()) == 0.0


# The Vallado AIAA 2006-6753 case 08195 (Molniya 1-36) — the suite's SDP4
# deep-space fixture (tests/tle/test_sgp4_agreement.py).
MOLNIYA_LINE1 = "1 08195U 75081A   06176.33215444  .00000099  00000-0  11873-3 0   813"
MOLNIYA_LINE2 = "2 08195  64.1586 279.0717 6877146 264.7651  20.2257  2.00491383225656"


@pytest.mark.usefixtures("orekit")
def test_deep_space_sdp4_branch_fits() -> None:
    # Contract: Testing / deep-space branch. The fitted mean motion sits far
    # below the 225-minute SDP4 cutoff (~6.4 rev/day), so selectExtrapolator
    # picks the deep-space branch — and the self-fit recovers its source
    # essentially exactly (Chunk-0 probe: 0 m propagate-back).
    molniya = TLE.from_strings(MOLNIYA_LINE1, MOLNIYA_LINE2, name="MOLNIYA 1-36")
    ref = propagate_tle(molniya, 2 * 86400.0, output_step=60.0)
    result = fit_tle_detailed(ref, initial_guess=molniya, progress=False)

    back = propagate_tle(
        result.tle, 2 * 86400.0, output_step=60.0, start=ref.start_epoch
    )
    residuals = np.linalg.norm(back.positions - ref.positions, axis=1)
    assert float(np.sqrt(np.mean(residuals**2))) < 1.0

    rev_day = result.tle.to_orekit().getMeanMotion() * 86400.0 / (2.0 * math.pi)
    assert rev_day == pytest.approx(2.00491383, abs=1e-6)
    assert rev_day < 6.4  # period > 225 min: the SDP4 deep-space branch


def test_path_b_from_arrays_reference_fits(iss_ref_2d: Trajectory) -> None:
    # Contract: Testing / path (b) smoke — the observational path: a user-
    # assembled Trajectory.from_arrays reference (here in EME2000, exercising
    # the any-frame rule end-to-end through the public constructor).
    src = _clip_leading(iss_ref_2d, 21600.0).to_frame(Frame.EME2000)
    reference = Trajectory.from_arrays(
        [s.epoch for s in src],
        src.positions,
        src.velocities,
        Frame.EME2000,
    )
    result = fit_tle_detailed(reference, norad_id=25544, progress=False)
    # SGP4-sourced data round-tripped through EME2000: near-exact recovery.
    assert result.rms_m < 10.0


def test_feature_1_2_top_level_exports() -> None:
    # Chunk 4: the public surface lands (contract: both verbs + FitResult are
    # top-level; TLEFitError joined in Chunk 1). JVM-free row.
    import propygator
    from propygator.tle import fitter

    assert propygator.fit_tle is fitter.fit_tle
    assert propygator.fit_tle_detailed is fitter.fit_tle_detailed
    assert propygator.FitResult is fitter.FitResult
    for exported in ("fit_tle", "fit_tle_detailed", "FitResult", "TLEFitError"):
        assert exported in propygator.__all__
