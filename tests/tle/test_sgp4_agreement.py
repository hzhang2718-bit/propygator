"""SGP4/SDP4 implementation-agreement tests (Feature 1.3, build-plan chunk 4).

Proves ``propagate_tle`` reproduces the reference SGP4/SDP4 algorithm against the
**published Vallado verification vectors** — the *Revisiting Spacetrack Report #3* /
AIAA 2006-6753 suite (the canonical ``SGP4-VER.TLE`` inputs and ``tcppver.out``
expected output) — to **centimetre agreement**, compared **in the native TEME frame**
(features.md §1.3 "Testing"). The reference rows are TEME position (km) and velocity
(km/s); comparing after a TEME→EME2000 conversion would inject EOP-dependent
differences that blow the centimetre budget, so the test reads the raw SGP4 output
frame that ``propagate_tle`` returns.

Two cases exercise **both** branches of ``TLEPropagator.selectExtrapolator`` (the
automatic near-Earth vs deep-space pick, with no user knob):

* **00005** (Vanguard 1, ~10.82 rev/day → period ~133 min < 225) → **SGP4** near-Earth.
* **08195** (Molniya 1-36, ~2.00 rev/day → period ~718 min > 225) → **SDP4** deep-space.

This is *implementation-agreement* with the reference SGP4/SDP4 — not absolute accuracy
against truth, which degrades with time from the TLE epoch (see the accuracy caveat in
``propagate_tle``'s docstring). Measured residuals on the installed Orekit build are
~9 µm / 1e-6 m s⁻¹ (00005) and ~0.3 mm / 1e-6 m s⁻¹ (08195) — comfortably inside the
1 cm / 0.1 mm s⁻¹ budgets pinned below.

Every test starts the JVM once via the session-scoped ``orekit`` fixture, so
``conftest``'s ordering hook schedules this module after the pure-Python
``tests/core/*`` "no JVM started" guards (architecture §11).
"""

from __future__ import annotations

from typing import NamedTuple

import numpy as np
import pytest

from propygator import TLE, Frame, propagate_tle

# Every test here needs the JVM up + orekit-data loaded.
pytestmark = pytest.mark.usefixtures("orekit")

# Centimetre agreement (features.md §1.3). The measured worst-case residuals on the
# installed Orekit build are far tighter (see the module docstring); these bounds carry
# a generous margin while still pinning genuine agreement.
_POS_TOL_M = 1.0e-2  # 1 cm
_VEL_TOL_MS = 1.0e-4  # 0.1 mm/s


class _Case(NamedTuple):
    name: str
    line1: str
    line2: str
    step_min: float
    # (t_min, x_km, y_km, z_km, vx_kms, vy_kms, vz_kms) in TEME, from tcppver.out.
    rows: list[tuple[float, float, float, float, float, float, float]]


# The reference rows are verbatim tcppver.out values (TEME, km / km per s). The format
# toggle keeps the table aligned and the per-line lint waivers below relax the 88-col
# limit on the data lines, mirroring the long-data-table convention in
# propagation/guards.py.
# fmt: off

# --- 00005: near-Earth (SGP4). Full reference series, 0..4320 min @ 360 min. -------
CASE_00005 = _Case(
    name="00005",
    line1="1 00005U 58002B   00179.78495062  .00000023  00000-0  28098-4 0  4753",
    line2="2 00005  34.2682 348.7242 1859667 331.7664  19.3264 10.82419157413667",
    step_min=360.0,
    rows=[
        (0.0, 7022.46529266, -1400.08296755, 0.03995155, 1.893841015, 6.405893759, 4.53480725),  # noqa: E501
        (360.0, -7154.03120202, -3783.17682504, -3536.19412294, 4.741887409, -4.151817765, -2.093935425),  # noqa: E501
        (720.0, -7134.59340119, 6531.68641334, 3260.27186483, -4.113793027, -2.911922039, -2.557327851),  # noqa: E501
        (1080.0, 5568.53901181, 4492.06992591, 3863.87641983, -4.209106476, 5.159719888, 2.74485298),  # noqa: E501
        (1440.0, -938.55923943, -6268.18748831, -4294.02924751, 7.536105209, -0.427127707, 0.98987808),  # noqa: E501
        (1800.0, -9680.56121728, 2802.47771354, 124.10688038, -0.905874102, -4.65946797, -3.227347517),  # noqa: E501
        (2160.0, 190.19796988, 7746.96653614, 5110.00675412, -6.112325142, 1.527008184, -0.139152358),  # noqa: E501
        (2520.0, 5579.55640116, -3995.61396789, -1518.82108966, 4.767927483, 5.123185301, 4.276837355),  # noqa: E501
        (2880.0, -8650.73082219, -1914.93811525, -3007.03603443, 3.067165127, -4.828384068, -2.515322836),  # noqa: E501
        (3240.0, -5429.79204164, 7574.36493792, 3747.39305236, -4.99944211, -1.800561422, -2.22939283),  # noqa: E501
        (3600.0, 6759.04583722, 2001.5819822, 2783.55192533, -2.180993947, 6.402085603, 3.644723952),  # noqa: E501
        (3960.0, -3791.44531559, -5712.95617894, -4533.48630714, 6.668817493, -2.516382327, -0.082384354),  # noqa: E501
        (4320.0, -9060.47373569, 4658.70952502, 813.68673153, -2.232832783, -4.11045349, -3.157345433),  # noqa: E501
    ],
)

# --- 08195: deep-space (SDP4). Sampled 0..2880 min (step 120 min), across ~4 revs. --
CASE_08195 = _Case(
    name="08195",
    line1="1 08195U 75081A   06176.33215444  .00000099  00000-0  11873-3 0   813",
    line2="2 08195  64.1586 279.0717 6877146 264.7651  20.2257  2.00491383225656",
    step_min=120.0,
    rows=[
        (0.0, 2349.8948335, -14785.93811562, 0.02119378, 2.721488096, -3.256811655, 4.498416672),  # noqa: E501
        (360.0, 19089.29762968, 3107.89495018, 39958.1466137, -0.410308034, 1.640332277, -0.306873818),  # noqa: E501
        (720.0, 2622.13222207, -15125.15464924, 474.51048398, 2.688287199, -3.078426664, 4.49497953),  # noqa: E501
        (1440.0, 2890.80638268, -15446.439523, 948.77010176, 2.65440749, -2.909344895, 4.486437362),  # noqa: E501
        (2160.0, 3155.85126036, -15750.70393364, 1422.32496953, 2.620085624, -2.748990396, 4.473527039),  # noqa: E501
        (2880.0, 3417.20931586, -16038.79510665, 1894.74934058, 2.585515864, -2.596818146, 4.456882556),  # noqa: E501
    ],
)
# fmt: on


def _mean_motion_rev_per_day(line2: str) -> float:
    """Mean motion (rev/day) from TLE line 2 cols 53–63 (pure-Python)."""
    return float(line2[52:63])


def test_cases_exercise_both_selectextrapolator_branches():
    """The two cases straddle the ~225-min period cutoff (features.md §1.3).

    ``selectExtrapolator`` switches from the near-Earth (SGP4) to the deep-space
    (SDP4) branch at that period, so a near-Earth *and* a deep-space case make the
    agreement check below exercise both branches automatically.
    """
    period_near = 1440.0 / _mean_motion_rev_per_day(CASE_00005.line2)
    period_deep = 1440.0 / _mean_motion_rev_per_day(CASE_08195.line2)
    assert period_near < 225.0 < period_deep


@pytest.mark.parametrize("case", [CASE_00005, CASE_08195], ids=lambda c: c.name)
def test_sgp4_agreement_in_teme(case: _Case):
    """propagate_tle matches the Vallado TEME reference vectors to centimetres.

    Propagates from the TLE epoch (the default ``start``) on the reference time grid,
    then compares each on-grid sample to the published TEME position/velocity in the
    native frame — no TEME→EME2000 conversion (features.md §1.3).
    """
    tle = TLE.from_strings(case.line1, case.line2)
    step_s = case.step_min * 60.0
    duration_s = case.rows[-1][0] * 60.0
    traj = propagate_tle(tle, duration_s, output_step=step_s)

    # Compared in the SGP4-native frame; no silent conversion (architecture §10).
    assert traj.frame is Frame.TEME

    for t_min, x, y, z, vx, vy, vz in case.rows:
        k = round(t_min * 60.0 / step_s)  # on-grid sample index for this epoch
        pos_ref_m = np.array([x, y, z]) * 1000.0
        vel_ref_m = np.array([vx, vy, vz]) * 1000.0
        pos_err = float(np.linalg.norm(traj.positions[k] - pos_ref_m))
        vel_err = float(np.linalg.norm(traj.velocities[k] - vel_ref_m))
        assert pos_err < _POS_TOL_M, (
            f"{case.name} t={t_min:.0f}min: |dpos|={pos_err * 100:.4f} cm"
        )
        assert vel_err < _VEL_TOL_MS, (
            f"{case.name} t={t_min:.0f}min: |dvel|={vel_err * 1000:.4f} mm/s"
        )
