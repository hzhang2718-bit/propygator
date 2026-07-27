"""Real-world pinned regression: GRACE-FO drag stack vs. GNV1B truth.

The study Chunk 4 pins (docs/history/build-plan-real-world-validation.md; evidence in
``experiments/real-world-validation/gracefo/``):

1. **Drag-signal + pipeline ratio** — over the pinned solar-active day, the
   drag-off residual must show the drag signal inside a wide band, and the
   drag-on run must be materially better. Relationships, not absolute meters:
   the absolute numbers ride the CSSI space-weather file (final history for
   2023, but the ratio is the wiring-sensitive fact).
2. **Box face-sum axis pin** — the ``BoxFaceCd.default`` face-sum for the
   study's base-averaged GRACE-FO box, evaluated at **fixed** (radius,
   density, theta) inputs so the pin is independent of orekit-data entirely,
   with the wired +Y-on-wind mapping required smallest — the quantity that
   caught the Chunk 2b axis-convention risk. Pure Python, no JVM.

Tolerance policy (build-plan Chunk 4, binding): measured x generous margin.
Measured (results.txt active_2023, 2026-07-12): t0 diff 3.9e-9 m; drag-off
day-1 3D RMS 1058 m; drag-on/drag-off ratio 0.325; face-sum 4.18 m^2 vs
13.02 / 8.22 m^2 for the two wrong-axis mappings. The Chunk 5
``box_face_default`` leeward floor-at-zero regeneration moves the face-sum by
~1e-7 m^2 — far inside the band.
"""

from __future__ import annotations

import math

import numpy as np

from propygator import (
    BoxFaceCd,
    Epoch,
    ForceModelConfig,
    Frame,
    IntegratorConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    State,
    TimeScale,
    propagate_numerical,
)
from tests.propagation.real_world_gnv1b import (
    STEP_S,
    T0_ISO,
    TRUTH_POS_M,
    TRUTH_VEL_MS,
)

# GRACE-FO sphere-equivalent parameters (experiment README citations).
GRACEFO_MASS_KG = 600.0
GRACEFO_AREA_M2 = 1.0
GRACEFO_CD_NOMINAL = 2.3
GRACEFO_CR = 1.3

# Measured 3.9e-9 m — anything near a meter is a frame/time conversion bug.
T0_DIFF_BOUND_M = 1.0
# Measured 1058 m: the band brackets a genuine solar-max drag signal while
# absorbing any CSSI refresh (the conservative floor is ~4 m/day, so even the
# low edge is unmistakably drag).
DRAG_OFF_RMS_BAND_M = (200.0, 5000.0)
# Measured ratio 0.325 — drag-on must stay materially better than drag-off.
DRAG_ON_RATIO_BOUND = 0.6

# The study's base-averaged GRACE-FO box (ram area preserved exactly).
BOX_X_M, BOX_Y_M, BOX_Z_M = 0.780, 3.123, 1.3165
# Fixed table inputs (the scratch-probe idiom) — no orekit-data dependence.
FACE_SUM_RADIUS_M = 6.876e6
FACE_SUM_DENSITY = 1e-12
FACE_SUM_BAND_M2 = (3.3, 5.2)  # measured 4.18


def test_gracefo_drag_signal_and_pipeline(orekit):
    t0 = Epoch.from_iso(T0_ISO, TimeScale.TAI)
    truth = np.asarray(TRUTH_POS_M)
    state0 = State(t0, truth[0], np.asarray(TRUTH_VEL_MS[0]), Frame.ITRF).to_frame(
        Frame.EME2000
    )
    span_s = STEP_S * (len(truth) - 1)

    def run(drag: bool) -> np.ndarray:
        traj = propagate_numerical(
            state0,
            span_s,
            output_step=STEP_S,
            force_models=ForceModelConfig(
                drag=drag,
                atmosphere_model="NRLMSISE-00",
                srp=True,
                solid_tides=True,
                ocean_tides=True,
                relativity=True,
            ),
            spacecraft=SpacecraftConfig(
                mass_kg=GRACEFO_MASS_KG,
                geometry=SpacecraftGeometry.sphere(
                    area_m2=GRACEFO_AREA_M2,
                    drag_coefficient=GRACEFO_CD_NOMINAL,
                    reflectivity_coefficient=GRACEFO_CR,
                ),
            ),
            integrator=IntegratorConfig.high_precision(),
            progress=False,
        )
        positions = traj.to_frame(Frame.ITRF).positions
        assert len(positions) == len(truth)
        return np.linalg.norm(positions - truth, axis=1)

    d_off = run(drag=False)
    d_on = run(drag=True)

    # t0 sample isolates frame/time conversion from all dynamics.
    assert d_off[0] < T0_DIFF_BOUND_M

    rms_off = float(np.sqrt(np.mean(d_off**2)))
    rms_on = float(np.sqrt(np.mean(d_on**2)))
    # The drag signal is present (drag-off residual IS the unmodeled drag)...
    assert DRAG_OFF_RMS_BAND_M[0] < rms_off < DRAG_OFF_RMS_BAND_M[1]
    # ...and the NRLMSISE-00 pipeline carries it (drag-on materially better).
    assert rms_on < DRAG_ON_RATIO_BOUND * rms_off


def test_box_face_sum_axis_convention():
    """The wired +Y-on-wind face-sum must be smallest and inside its band.

    Sigma Cd_i*A_i with ram theta=0 / leeward theta=pi on one face pair and
    theta=pi/2 on the other four — computed for each candidate wind axis. A
    wrong box<->attitude axis mapping puts a large face on the wind and
    multiplies the sum (13.0 / 8.2 vs 4.2 m^2). No JVM: the shipped table is
    pure Python.
    """
    box = BoxFaceCd.default()
    cd_ram = box(FACE_SUM_RADIUS_M, FACE_SUM_DENSITY, 0.0)
    cd_side = box(FACE_SUM_RADIUS_M, FACE_SUM_DENSITY, math.pi / 2)
    cd_lee = box(FACE_SUM_RADIUS_M, FACE_SUM_DENSITY, math.pi)

    a_ram = BOX_X_M * BOX_Z_M  # +/-Y faces (the wired wind axis): 1.027 m^2
    a_x = BOX_Y_M * BOX_Z_M  # +/-X nadir/zenith faces: 4.111 m^2
    a_z = BOX_X_M * BOX_Y_M  # +/-Z slant-side faces: 2.436 m^2

    def face_sum(a_wind: float, a_others: tuple[float, float]) -> float:
        return (cd_ram + cd_lee) * a_wind + cd_side * 2.0 * sum(a_others)

    wired = face_sum(a_ram, (a_x, a_z))
    wrong_x = face_sum(a_x, (a_ram, a_z))
    wrong_z = face_sum(a_z, (a_ram, a_x))

    assert wired < wrong_x
    assert wired < wrong_z
    assert FACE_SUM_BAND_M2[0] < wired < FACE_SUM_BAND_M2[1]
