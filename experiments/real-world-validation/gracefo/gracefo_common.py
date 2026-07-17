"""GRACE-FO leg configuration for the real-world-validation study (reference-only).

The leg-wide facts every GRACE-FO driver shares, extracted from
``run_gracefo.py`` during the 2026-07-15 study reorganization so that
``run_fit_vs_catalog.py`` (and any future driver) no longer imports a chunk
driver module for its constants and factories:

- the GRACE-FO 1 physical parameters and the Chunk 2b box geometry,
- the spacecraft / force-model config factories the Chunk 2/2b/2c and Chunk 3
  evidence was produced with,
- the **measured anchors** — study results consumed as inputs by later
  experiments, recorded once with provenance.

Imports ``propygator`` (JVM-free at import time) but never starts the JVM.
Not shipped, not in CI, outside ``testpaths``.
"""

from __future__ import annotations

from pathlib import Path

from propygator import (
    BoxFaceCd,
    ForceModelConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
)

DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "gracefo"

# GRACE-FO 1 (GRACE C, NORAD 43476). Sphere-equivalent drag/SRP parameters
# (citations in README.md): launch mass ~600 kg; the body is a ~3.1 x 1.9 x 0.8 m
# trapezoidal prism flying narrow-end-forward, so the ram frontal area is ~1 m^2;
# Cd 2.3 is the free-molecular nominal. The scalar Cd fit (Run 3) is the real
# diagnostic -- it absorbs the Cd x A / m product, so the exact A only sets the
# nominal starting point, not the answer.
GRACEFO_MASS_KG = 600.0
GRACEFO_AREA_M2 = 1.0
GRACEFO_CD_NOMINAL = 2.3
GRACEFO_CR = 1.3  # sphere reflection coefficient (1.0 absorbing .. 2.0 specular)
GRACEFO_SAT_ID = "C"
NORAD_ID = 43476
SAT_NAME = "GRACE-FO 1"

# The truth subsample grid every GRACE-FO driver diffs on (seconds).
SUBSAMPLE_S = 60.0

# --- Chunk 2b geometry: the base-averaged rectangle at real dimensions -------
# GRACE-FO is a trapezoidal prism (JPL GRACE-FO Launch Press Kit, cross-checked
# vs eoPortal FLEXBUS/Astrium): length 3.123 m (along-track), height 0.780 m
# (radial), bottom/top widths 1.943 / 0.690 m. Averaging the two parallel widths
# gives a rectangle that preserves the ram (frontal) area exactly and
# under-counts the wetted side area by ~9.5% (~2% of Cd*A -- far below the
# density confound these runs measure). Axis mapping matches InPlaneTracking's
# convention (body +Y on the wind, +Z best-effort on the orbit normal):
# x = height (radial), y = length (ram -- the long axis rides the wind),
# z = base-averaged width (cross-track).
BOX_X_M = 0.780  # radial (height)
BOX_Y_M = 3.123  # along-track (ram; the long axis)
BOX_Z_M = 1.3165  # cross-track (base-averaged width = (1.943 + 0.690) / 2)
A_RAM_M2 = BOX_X_M * BOX_Z_M  # +/-Y ram/leeward faces: 1.027 m^2 (exact)
A_SIDE_X_M2 = BOX_Y_M * BOX_Z_M  # +/-X nadir/zenith faces: 4.111 m^2 each
A_SIDE_Z_M2 = BOX_X_M * BOX_Y_M  # +/-Z slant-side faces: 2.436 m^2 each
DSMC_CD_BAND = (2.65, 4.5)  # physical free-molecular Cd on the frontal
# reference for GRACE-class bodies (Mehta 2013; arXiv 2503.21651)
LENGTH_CORRECTION_M = 0.33  # Verify-5 one-off sensitivity check only -- the
# plan forbids length-correcting the baseline box (false precision)

# --- Measured anchors ---------------------------------------------------------
# Study results consumed as *inputs* by later experiments -- recorded once, with
# provenance, so no driver carries its own diverging literal.
#
# Run-3 scalar-Cd fits (run_gracefo.py, evidence in results.txt). The committed
# Chunk 3 state-path evidence consumed the checkpoint-rounded quiet value 2.030
# (results.txt prints the raw fit as 2.034); kept as-is so the evidence
# reproduces byte-identically. The storm_2024 peak-arc fit (4.080) is recorded
# for completeness; the onset-arc 1.777 is a flagged daily-Ap smearing artifact
# (see README.md "Storm window") and is deliberately NOT an anchor.
RUN3_FITTED_CD = {"quiet_2019": 2.030, "active_2023": 3.405, "storm_2024": 4.080}


def sphere_spacecraft(
    cd: float | VariableCd, area_m2: float = GRACEFO_AREA_M2
) -> SpacecraftConfig:
    """The sphere-equivalent GRACE-FO spacecraft (Chunk 2 Runs 1-3, Run 4)."""
    return SpacecraftConfig(
        mass_kg=GRACEFO_MASS_KG,
        geometry=SpacecraftGeometry.sphere(
            area_m2=area_m2,
            drag_coefficient=cd,
            reflectivity_coefficient=GRACEFO_CR,
        ),
    )


def box_spacecraft(cd: BoxFaceCd, y_length_m: float = BOX_Y_M) -> SpacecraftConfig:
    """The base-averaged GRACE-FO rectangle as a convex box (Chunk 2b, Run 5).

    SRP optics stay at the ``box_and_panels`` defaults -- negligible at ~500 km;
    drag is what these runs measure.
    """
    return SpacecraftConfig(
        mass_kg=GRACEFO_MASS_KG,
        geometry=SpacecraftGeometry.box_and_panels(
            x_length_m=BOX_X_M,
            y_length_m=y_length_m,
            z_length_m=BOX_Z_M,
            solar_array_area_m2=0.0,  # convex bus -- the BoxFaceCd contract
            drag_coefficient=cd,
        ),
    )


# The conservative force set (shared with Run 1 drag-off); Run 2/3 flip drag on.
# Matches the LAGEOS Chunk 0 baseline: 70x70, sun+moon, SRP, solid+ocean tides,
# relativity -- so the drag-off run reproduces the proven conservative floor.
def force_config(drag: bool) -> ForceModelConfig:
    return ForceModelConfig(
        drag=drag,
        atmosphere_model="NRLMSISE-00",
        srp=True,
        solid_tides=True,
        ocean_tides=True,
        relativity=True,
    )
