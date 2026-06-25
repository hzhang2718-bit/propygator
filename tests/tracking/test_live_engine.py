"""Tests for the live-tracker buffer engine (Feature 1.4, build-plan chunk 7).

The engine (``tracking/live._TrackerEngine``) is the pure, **headless** state machine
behind the chunk-8 dashboard: a now-centred ``Trajectory`` buffer, drain-triggered
rebuilds, auto-refresh for fetched targets, surgical stale-warning suppression, and the
per-rebuild precomputed arrays the speed/sky panels consume. No matplotlib is imported
by these tests (a subprocess check pins that for the module itself).

Every test starts the JVM via the session-scoped ``orekit`` fixture (the buffer is a
real SGP4 propagation), so ``conftest``'s ordering hook schedules this module after the
pure-Python ``tests/core/*`` "no JVM started" guards (architecture §11). The clock is
injected explicitly (``now=``) rather than monkeypatched — the state-machine methods are
pure functions of ``now`` — so the span arithmetic is exact and deterministic.

Buffer magnitudes are tiny on purpose (``output_step=10 s``, ``half_window_s=100 s``,
``guard_s=20 s``): the 220 s span is an exact multiple of the step, so the realized grid
endpoints land on round numbers the assertions can pin.
"""

from __future__ import annotations

import ast
import warnings
from pathlib import Path

import numpy as np
import pytest

from propygator import (
    TLE,
    Frame,
    GroundStation,
    StaleTLEWarning,
    State,
)
from propygator.core.observation import look_angles_track
from propygator.tracking.live import _TrackerEngine

# Every test here needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3/1.4 tests — epoch
# 2026-06-20T09:57:02 UTC, NORAD 25544, a near-Earth (SGP4) orbit (inclination 51.6°).
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"

# Compact, exact-grid magnitudes shared by most tests (see module docstring).
_STEP = 10.0
_HALF = 100.0
_GUARD = 20.0


def _iss_tle(name: str | None = None) -> TLE:
    return TLE.from_strings(ISS_LINE1, ISS_LINE2, name=name)


def _engine(target, station=None, *, now, **overrides):
    """Build a ``_TrackerEngine`` with the compact test magnitudes."""
    params = {
        "output_step": _STEP,
        "half_window_s": _HALF,
        "guard_s": _GUARD,
        "now": now,
    }
    params.update(overrides)
    return _TrackerEngine(target, station, **params)


# --- buffer geometry --------------------------------------------------------


def test_buffer_centred_and_spans_window_plus_guard():
    """The buffer is centred on ``now`` and reaches a guard margin past the edge."""
    tle = _iss_tle()
    now = tle.epoch  # fresh -> no stale notice
    engine = _engine(tle, now=now)

    buf = engine.buffer
    assert buf.frame is Frame.TEME
    # Centred: first sample at now - half_window.
    assert buf.start_epoch.seconds_since(now) == pytest.approx(-_HALF, abs=1e-6)
    # Realized last sample at now + half_window + guard (220 s is an exact 10 s grid).
    assert buf.end_epoch.seconds_since(now) == pytest.approx(_HALF + _GUARD, abs=1e-6)


# --- drain-triggered rebuild ------------------------------------------------


def test_rebuild_triggers_on_drain_not_refresh():
    """``needs_rebuild`` fires only once ``now`` reaches the displayed leading edge."""
    tle = _iss_tle()
    now = tle.epoch
    engine = _engine(tle, now=now)

    # Before the displayed leading edge (now + half_window): no rebuild, however many
    # refresh ticks elapse — the path is static between re-propagations.
    assert engine.needs_rebuild(now) is False
    assert engine.needs_rebuild(now.shifted_by(_HALF / 2.0)) is False
    assert engine.needs_rebuild(now.shifted_by(_HALF - 1.0)) is False
    # At / past the leading edge: rebuild (note this is < buffer.end_epoch, the guard).
    assert engine.needs_rebuild(now.shifted_by(_HALF)) is True
    assert engine.needs_rebuild(now.shifted_by(_HALF + _GUARD)) is True


def test_rebuild_recentres_buffer_and_advances_display_edge():
    """A rebuild re-centres the buffer on the new ``now`` and resets the trigger."""
    tle = _iss_tle()
    now = tle.epoch
    engine = _engine(tle, now=now)

    new_now = now.shifted_by(_HALF)
    assert engine.maybe_rebuild(new_now) is True
    assert engine.buffer.start_epoch.seconds_since(new_now) == pytest.approx(
        -_HALF, abs=1e-6
    )
    # The trigger moved forward with the buffer: not yet due again at new_now.
    assert engine.needs_rebuild(new_now) is False
    # maybe_rebuild is a no-op before the (new) edge.
    assert engine.maybe_rebuild(new_now.shifted_by(1.0)) is False


# --- per-frame clamp --------------------------------------------------------


def test_state_at_clamps_past_realized_edge():
    """``state_at`` clamps to the realized last sample and never raises out-of-span."""
    tle = _iss_tle()
    now = tle.epoch
    engine = _engine(tle, now=now)
    end = engine.buffer.end_epoch

    mid = engine.state_at(now)
    assert isinstance(mid, State) and mid.frame is Frame.TEME

    # At the realized edge and well past it: both clamp to buffer.at(end), no error.
    at_edge = engine.state_at(end)
    past_edge = engine.state_at(end.shifted_by(100.0))
    assert past_edge == at_edge


def test_state_at_advances_through_guard_zone():
    """Inside the guard margin the marker keeps advancing — it does not clamp early.

    A query strictly between the displayed leading edge (``now + half_window``) and the
    realized edge (``now + half_window + guard``) must return a distinct, *advancing*
    interpolated state, not the clamped edge sample — the guard's whole purpose: across
    a blocking rebuild stall the live marker slides forward instead of freezing at the
    displayed edge. Without it, a regression that clamped at ``_display_end_epoch`` (or
    dropped ``guard_s``) would pass every other state_at test.
    """
    tle = _iss_tle()
    now = tle.epoch
    engine = _engine(tle, now=now)
    end = engine.buffer.end_epoch

    # now + _HALF + _GUARD/2 lies strictly between the displayed edge (now + _HALF) and
    # the realized edge (now + _HALF + _GUARD).
    in_guard = engine.state_at(now.shifted_by(_HALF + _GUARD / 2.0))
    # Advancing: the realized epoch tracks the query, not clamped back to the edge.
    assert in_guard.epoch.seconds_since(now) == pytest.approx(
        _HALF + _GUARD / 2.0, abs=1e-6
    )
    # Strictly inside the realized span, and distinct from the clamped past-edge state
    # the marker would otherwise freeze at.
    assert in_guard.epoch.seconds_since(end) < 0.0
    assert in_guard != engine.state_at(end.shifted_by(50.0))


# --- target resolution + auto-refresh --------------------------------------


def test_fetched_target_refetches_on_rebuild(monkeypatch):
    """A name/id target fetches once at startup and re-fetches on every rebuild."""
    tle = _iss_tle("ISS (ZARYA)")
    now = tle.epoch
    calls = {"n": 0}

    def fake_fetch(name_or_id, **kwargs):
        calls["n"] += 1
        return tle

    monkeypatch.setattr("propygator.tracking.live.fetch_tle", fake_fetch)

    engine = _engine("ISS", now=now)
    assert engine.auto_refresh is True
    assert calls["n"] == 1  # fetched once at construction

    engine.rebuild(now.shifted_by(_HALF))
    assert calls["n"] == 2  # re-fetched on the rebuild


def test_raw_tle_never_refetches(monkeypatch):
    """A directly-supplied TLE is only ever re-propagated, never fetched."""
    tle = _iss_tle()
    now = tle.epoch
    calls = {"n": 0}

    def fake_fetch(name_or_id, **kwargs):
        calls["n"] += 1
        return tle

    monkeypatch.setattr("propygator.tracking.live.fetch_tle", fake_fetch)

    engine = _engine(tle, now=now)
    assert engine.auto_refresh is False
    engine.rebuild(now.shifted_by(_HALF))
    assert calls["n"] == 0


# --- stale-TLE handling -----------------------------------------------------


def test_stale_raw_tle_warns_once_at_startup():
    """A pre-stale raw TLE emits one StaleTLEWarning at startup, none per rebuild."""
    tle = _iss_tle()
    # 31 days past epoch: the whole centred span exceeds the 30-day stale threshold, so
    # the first build surfaces propagate_tle's StaleTLEWarning.
    now = tle.epoch.shifted_by(31.0 * 86400.0)

    with pytest.warns(StaleTLEWarning):
        engine = _engine(tle, now=now)

    # A subsequent rebuild (still far from epoch) must NOT repeat the notice — it is
    # suppressed surgically, by category, so a genuine decay would still raise.
    with warnings.catch_warnings(record=True) as recorded:
        warnings.simplefilter("always")
        engine.rebuild(now.shifted_by(_HALF))
    assert not any(isinstance(w.message, StaleTLEWarning) for w in recorded)


# --- per-rebuild precompute seam -------------------------------------------


def test_precomputed_arrays_match_direct_compute():
    """The held speed/az-el arrays equal a direct norm / to_frame / look_angles."""
    tle = _iss_tle()
    now = tle.epoch
    station = GroundStation("Durham", 36.0, -78.9)
    engine = _engine(tle, station, now=now)
    buf = engine.buffer

    np.testing.assert_allclose(
        engine.inertial_speed_kms, np.linalg.norm(buf.velocities, axis=1) / 1000.0
    )
    np.testing.assert_allclose(
        engine.ground_speed_kms,
        np.linalg.norm(buf.to_frame(Frame.ITRF).velocities, axis=1) / 1000.0,
    )
    # Ground-relative speed is slower than inertial for a prograde orbit (sanity).
    assert np.mean(engine.ground_speed_kms) < np.mean(engine.inertial_speed_kms)

    az, el, rng = look_angles_track(station, buf)
    assert engine.azel is not None
    np.testing.assert_allclose(engine.azel[0], az)
    np.testing.assert_allclose(engine.azel[1], el)
    np.testing.assert_allclose(engine.azel[2], rng)


def test_azel_is_none_without_station():
    tle = _iss_tle()
    engine = _engine(tle, now=tle.epoch)
    assert engine.azel is None


# --- headless invariant -----------------------------------------------------


def test_engine_module_has_no_top_level_display_or_jvm_imports():
    """The engine's *static* import graph is display- and JVM-free.

    A ``sys.modules`` check can't isolate the engine: the package as a whole pulls
    matplotlib/plotly via the re-exported ``plot_*`` verbs (``propygator/__init__`` says
    so), so matplotlib is already loaded the moment any test imports ``propygator``.
    Assert the architectural invariant directly instead — ``tracking/live.py`` imports
    no matplotlib / plotly / plotting / Orekit at module top: the display imports go in
    chunk 8's ``live_track`` body (the ``export_all`` precedent) and all Orekit geometry
    stays in ``core/``, so the engine module itself stays a clean, headless leaf.
    """
    import propygator.tracking.live as live_mod

    tree = ast.parse(Path(live_mod.__file__).read_text(encoding="utf-8"))
    top_level_modules: list[str] = []
    for node in tree.body:  # module-body statements only -> top-level imports
        if isinstance(node, ast.Import):
            top_level_modules += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            top_level_modules.append(node.module or "")

    forbidden = (
        "matplotlib",
        "plotly",
        "plotting",
        "jpype",
        "orekit_jpype",
        "org.orekit",
    )
    offenders = [
        m
        for m in top_level_modules
        if any(m.startswith(prefix) for prefix in forbidden)
    ]
    assert offenders == [], f"engine has forbidden top-level imports: {offenders}"
