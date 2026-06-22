"""``TLE.from_state_unfitted`` tests (Feature 1.3, build-plan chunk 8).

Covers the row -> **format-valid (not round-trip-faithful)** TLE utility: the
produced lines are valid (they re-parse through ``from_strings`` and Orekit with no
checksum error), the caller-controllable ``norad_id`` / ``bstar`` land correctly
while the unsupplied fields take their pinned placeholders, the input frame is
normalised to TEME internally, and emitting one TLE per row of a single orbit yields
a *family* of slightly different element sets (the osculating-vs-mean wobble the
``unfitted`` name warns about).

``from_state_unfitted`` is JVM-touching (it calls ``State.to_frame`` /
``State.to_keplerian``), so every test starts the JVM once via the session-scoped
``orekit`` fixture and ``conftest``'s ordering hook schedules this module after the
pure-Python ``tests/core/*`` "no JVM started" guards (architecture §11).
"""

from __future__ import annotations

import pytest

from propygator import TLE, Frame, propagate_tle

pytestmark = pytest.mark.usefixtures("orekit")

# The same fixed, real ISS (ZARYA) TLE used across the 1.3 tests — epoch
# 2026-06-20T09:57:02 UTC, NORAD 25544, a near-Earth orbit (~92.7 min period).
ISS_LINE1 = "1 25544U 98067A   26171.41461525  .00008813  00000+0  16600-3 0  9990"
ISS_LINE2 = "2 25544  51.6327 284.1189 0004557 208.5194 151.5545 15.49333088572250"


@pytest.fixture
def iss_orbit():
    """One ISS revolution sampled coarsely, in its native TEME frame.

    ~5600 s a touch over one period at ~200 s spacing — enough rows that two
    samples a quarter-orbit apart exhibit a clear osculating-element wobble.
    """
    tle = TLE.from_strings(ISS_LINE1, ISS_LINE2)
    return propagate_tle(tle, 5600, output_step=200)


# --- format validity --------------------------------------------------------


def test_result_is_a_validated_tle(iss_orbit):
    """The returned lines re-parse cleanly through ``from_strings`` and Orekit."""
    tle = TLE.from_state_unfitted(iss_orbit[0])
    assert isinstance(tle, TLE)
    assert len(tle.line1) == 69 and len(tle.line2) == 69
    # from_strings already validated the checksums on the way out; re-parsing the
    # emitted lines must not raise (a corrupt checksum would), and Orekit must
    # accept them too.
    TLE.from_strings(tle.line1, tle.line2)
    tle.to_orekit()  # Orekit re-parse: no JException


# --- caller-controllable fields vs placeholders -----------------------------


def test_norad_id_placeholder_and_explicit(iss_orbit):
    state = iss_orbit[0]
    assert TLE.from_state_unfitted(state).norad_id == 0  # placeholder 00000
    assert TLE.from_state_unfitted(state, norad_id=25544).norad_id == 25544


def test_bstar_placeholder_and_explicit(iss_orbit):
    state = iss_orbit[0]
    # Default: no drag info -> exactly 0.0.
    assert TLE.from_state_unfitted(state).to_orekit().getBStar() == 0.0
    # Explicit B* lands in the drag field (the TLE B* field is a 5-digit mantissa
    # + exponent, so it round-trips to limited precision — assert approximately).
    bstar = 1.5e-4
    got = float(TLE.from_state_unfitted(state, bstar=bstar).to_orekit().getBStar())
    assert got == pytest.approx(bstar, rel=1e-3)


def test_pinned_placeholder_fields(iss_orbit):
    """Fields a State cannot supply take their fixed placeholders."""
    ok = TLE.from_state_unfitted(iss_orbit[0]).to_orekit()
    assert str(ok.getClassification()) == "U"
    assert ok.getEphemerisType() == 0
    assert ok.getElementNumber() == 0
    assert ok.getRevolutionNumberAtEpoch() == 0
    assert float(ok.getMeanMotionFirstDerivative()) == 0.0
    assert float(ok.getMeanMotionSecondDerivative()) == 0.0


def test_name_is_carried(iss_orbit):
    assert TLE.from_state_unfitted(iss_orbit[0], name="MY SAT").name == "MY SAT"
    assert TLE.from_state_unfitted(iss_orbit[0]).name is None


# --- frame handling ---------------------------------------------------------


def test_input_frame_normalised_to_teme(iss_orbit):
    """The same physical state yields identical lines regardless of input frame.

    The utility converts to TEME internally (a TLE lives in TEME), so feeding the
    EME2000 view of one state must produce byte-identical lines to feeding its
    TEME view — not a TEME-vs-EME2000 element mix-up.
    """
    teme_state = iss_orbit[0]
    eme_state = teme_state.to_frame(Frame.EME2000)
    from_teme = TLE.from_state_unfitted(teme_state)
    from_eme = TLE.from_state_unfitted(eme_state)
    assert (from_teme.line1, from_teme.line2) == (from_eme.line1, from_eme.line2)


# --- the osculating-vs-mean wobble artifact ---------------------------------


def test_two_rows_of_one_orbit_yield_different_element_sets(iss_orbit):
    """Emitting one TLE per row gives a *family* of distinct TLEs (wobble)."""
    early = TLE.from_state_unfitted(iss_orbit[0])
    # ~7 * 200 s ≈ a quarter ISS revolution later.
    late = TLE.from_state_unfitted(iss_orbit[7])
    assert (early.line1, early.line2) != (late.line1, late.line2)
    # The wobble is specifically in the *elements*, not just the advancing
    # anomaly: the osculating semi-major axis (hence the derived mean motion) and
    # eccentricity differ between two samples of the very same orbit.
    e_okt, l_okt = early.to_orekit(), late.to_orekit()
    assert float(e_okt.getMeanMotion()) != float(l_okt.getMeanMotion())
    assert float(e_okt.getE()) != float(l_okt.getE())
