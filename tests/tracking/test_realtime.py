"""Tests for the realtime primitives (Feature 1.4, build-plan chunk 2).

Covers the cheap "where is it now" layer: the single-shot ``_tle_state_at`` helper and
the ``current_state`` / ``current_ground_position`` verbs built on it. ``Epoch.now`` is
monkeypatched to a fixed epoch so the wall-clock-dependent verbs are deterministic.

Every test starts the JVM once via the session-scoped ``orekit`` fixture, so
``conftest``'s ordering hook schedules this module after the pure-Python
``tests/core/*`` "no JVM started" guards (architecture §11). This is the first test
module under ``tests/tracking/`` (its ``__init__.py`` makes the package collectable).
"""

from __future__ import annotations

import numpy as np
import pytest

from propygator import (
    TLE,
    Epoch,
    Frame,
    GeodeticPosition,
    PropagationError,
    State,
    TimeScale,
    TLEPropagationError,
    current_ground_position,
    current_state,
    propagate_tle,
)
from propygator.tle.propagator import _tle_state_at

# Every test here needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used across the Feature-1.3/1.4 tests — epoch
# 2026-06-20T09:57:02 UTC, NORAD 25544, a near-Earth (SGP4) orbit (inclination 51.6°).
ISS_NAME = "ISS (ZARYA)"
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


def _iss_tle(name: str | None = None) -> TLE:
    return TLE.from_strings(ISS_LINE1, ISS_LINE2, name=name)


def _freeze_now(monkeypatch, epoch: Epoch) -> None:
    """Pin ``Epoch.now()`` to ``epoch`` so the realtime verbs are deterministic."""
    monkeypatch.setattr(
        Epoch, "now", classmethod(lambda cls, scale=TimeScale.UTC: epoch)
    )


# --- _tle_state_at: the shared single-shot helper ---------------------------


def test_tle_state_at_matches_propagate_tle_at_start():
    """The single-shot helper equals propagate_tle's first sample at the same epoch.

    Both go through selectExtrapolator -> propagate -> PV-in-TEME, so evaluating at
    ``start`` must agree to numerical identity (features.md §1.4 realtime primitives).
    """
    tle = _iss_tle()
    epoch = tle.epoch  # where SGP4 is most accurate (and inside the envelope)

    single = _tle_state_at(tle, epoch)
    first = propagate_tle(tle, 60.0, output_step=60.0, start=epoch)[0]

    assert single.frame is Frame.TEME
    assert single.epoch.seconds_since(first.epoch) == 0.0
    # Same deterministic SGP4 evaluation at one instant -> identical to tight tol.
    np.testing.assert_allclose(single.position, first.position, rtol=0, atol=1e-6)
    np.testing.assert_allclose(single.velocity, first.velocity, rtol=0, atol=1e-9)


def test_tle_state_at_returns_teme_state():
    tle = _iss_tle()
    st = _tle_state_at(tle, tle.epoch)
    assert isinstance(st, State)
    assert st.frame is Frame.TEME
    assert st.position.shape == (3,) and st.velocity.shape == (3,)


# --- _tle_state_at: decay handling (mirrors propagate_tle) ------------------


def test_tle_state_at_decay_raises_tle_propagation_error():
    """A decayed TLE evaluated past its envelope raises a clean TLEPropagationError.

    _tle_state_at mirrors propagate_tle's decay contract: when SGP4/SDP4 leaves its
    validity envelope Orekit raises an OrekitException, which _tle_state_at catches and
    re-raises as a clean TLEPropagationError (a message, no raw Java trace,
    architecture §3) — never a leaked JException. So current_state /
    current_ground_position report a decayed satellite cleanly. (The sibling
    non-finite-PV branch is identical to propagate_tle's and is covered by its 29141
    decay case in tests/tle.)

    Case: Vallado SGP4-VER 20413 (MOLNIYA 1-83), a highly eccentric deep-space orbit
    whose secular terms pump the eccentricity to 1; by ~6 yr past epoch the analytic
    model raises TOO_LARGE_ECCENTRICITY_FOR_PROPAGATION_MODEL.
    """
    tle = TLE.from_strings(
        "1 20413U 83020D   05363.79166667  .00000000  00000-0  00000+0 0  7041",
        "2 20413  12.3514 187.4253 7864447 196.3027 356.5478  0.24690082  7978",
    )
    decayed_epoch = tle.epoch.shifted_by(6.0 * 365.25 * 86400.0)

    with pytest.raises(TLEPropagationError) as excinfo:
        _tle_state_at(tle, decayed_epoch)

    exc = excinfo.value
    assert isinstance(exc, PropagationError)  # PropagationError also catches it
    assert "TLE propagation failed" in str(exc)
    assert "org.orekit" not in str(exc)  # no leaked Java stack trace


# --- current_state ----------------------------------------------------------


def test_current_state_is_teme_at_now(monkeypatch):
    tle = _iss_tle()
    frozen = tle.epoch
    _freeze_now(monkeypatch, frozen)

    st = current_state(tle)

    assert isinstance(st, State)
    assert st.frame is Frame.TEME  # native SGP4 frame, no silent conversion
    assert st.epoch.seconds_since(frozen) == 0.0
    # Rides the same single-shot helper at Epoch.now().
    assert st == _tle_state_at(tle, frozen)


# --- current_ground_position ------------------------------------------------


def test_current_ground_position_is_plausible(monkeypatch):
    tle = _iss_tle()
    _freeze_now(monkeypatch, tle.epoch)

    gp = current_ground_position(tle)

    assert isinstance(gp, GeodeticPosition)  # frame-less; internal TEME->ITRF->geodetic
    assert -90.0 <= gp.latitude_deg <= 90.0
    assert -180.0 <= gp.longitude_deg <= 180.0
    # ISS altitude is ~400-420 km; a generous band absorbs SGP4/ellipsoid detail.
    assert 300e3 < gp.altitude_m < 500e3
    # The 51.6° inclination caps the achievable latitude (small margin for the
    # geodetic-vs-geocentric difference).
    assert abs(gp.latitude_deg) <= 53.0
