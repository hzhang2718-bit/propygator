"""GRACE-FO leg configuration for the extended-validation study (reference-only).

The leg-wide facts every GRACE-FO driver in this study shares. It deliberately
does **not** import ``real-world-validation/gracefo/gracefo_common.py``: this
study revises the reference area and the mass to more authoritative sources, so
every constant below is transcribed with its provenance rather than inherited
(build plan Chunk 0, "imported or transcribed with provenance -- never
redefined silently").

Sources, both read directly (not recalled):

- **GRACE-FO Level-1 Data Product User Handbook**, JPL D-56935 / GFZ, dated
  2019-09-11. Local copy: ``data/reference/`` (gitignored; re-fetch from
  https://isdc-data.gfz.de/grace-fo/DOCUMENTS/Level-1/ ). Table 4 gives the
  per-satellite launch mass; Table 5 the faceted surface model; section 3.2.3
  the Science Reference Frame and the in-flight attitude convention.
- **JPL GRACE-FO Launch Press Kit**, "Spacecraft and Instruments"
  (https://www.jpl.nasa.gov/news/press_kits/grace-fo/mission/spacecraft/) --
  the dimensioned envelope and the propellant load.
- **MAS1B**, the Level-1B spacecraft/tank mass product, present in every daily
  tarball already on disk -- the per-window propellant state (see mas1b.py).

WHY THIS DIFFERS FROM THE v0.7.2 STUDY (docs/extended-validation.md sec 2.2):
T scales exactly as A_ref and as 1/m, so both constants are part of the
measurement, not bookkeeping. The v0.7.2 evidence is quoted on
(A_ref = 1.027 m^2, m = 600.0 kg) and is **frozen** -- never recomputed and
never divided into a number produced here. Its numbers are quoted as a
continuity row only; the conversion is a closed-form scalar and is printed
beside it.

Imports ``propygator`` (JVM-free at import time) but never starts the JVM.
Not shipped, not in CI, outside ``testpaths``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from propygator import (
    BoxFaceCd,
    ForceModelConfig,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
)

# --- data roots ---------------------------------------------------------------
# This study's own tree (gitignored). The Chunk 0 windows live in the FROZEN
# v0.7.2 tree instead, which is read -- never written -- via --data-root.
DATA_ROOT = Path(__file__).resolve().parents[1] / "data" / "gracefo"
FROZEN_DATA_ROOT = (
    Path(__file__).resolve().parents[2]
    / "real-world-validation"
    / "data"
    / "gracefo"
)

# --- identity -----------------------------------------------------------------
# GRACE-FO 1 = GRACE C = NORAD 43476; GRACE-FO 2 = GRACE D = NORAD 43477.
NORAD_IDS = {"C": 43476, "D": 43477}
SAT_LABELS = {"C": "GRACE-FO 1 (GRACE C)", "D": "GRACE-FO 2 (GRACE D)"}
SAT_IDS = ("C", "D")

# --- reference area -----------------------------------------------------------
# L1 Handbook Table 5 ("GRACE / GRACE-FO surface properties") lists Front and
# Rear panels at 0.9551567 m^2 each, unit normal +X / -X. In that faceted model
# the X-projected area IS the Front panel, so this is the published ram-facing
# area of the modelled body.
#
# The JPL press-kit envelope implies a larger figure: the trapezoidal
# cross-section 0.5 * (1.943 + 0.690) * 0.780 = 1.0269 m^2, which is what the
# v0.7.2 study used as A_ram. The two are reconciled by the boom: Table 5
# itemizes it separately at 0.0461901 m^2, and 0.9552 + 0.0462 = 1.0014 m^2 sits
# within 2.5% of the envelope figure. So the sources differ mainly in whether
# the boom is folded in, not by a true 7%.
#
# BoxFaceCd requires a convex box and cannot represent a boom, so the point
# value is the body panel alone and the boom rides as a stated omission (about
# 3.6% of the box CdA -- see BOX_GEOMETRY_SYSTEMATIC below). The bracket spans
# both sources; the point value sits at its LOWER bound, not its centre.
A_REF_M2 = 0.9551567  # Handbook Table 5, Front/Rear panel
A_REF_BRACKET_M2 = (0.9551567, 1.0269)  # body panel .. press-kit envelope
BOOM_PROJ_M2 = 0.0461901  # Table 5; cylindrical boom, Z-aligned (see below)

# --- box geometry -------------------------------------------------------------
# The base-averaged rectangle standing in for the trapezoidal prism. Its
# dimensions come from the DIMENSIONED DIAGRAM -- L1 Handbook Figures 2 and 3,
# the satellite drawing with its envelope dimensions -- NOT from Table 5's
# faceted panel list:
#   length = the diagram's along-track dimension, read off as-is;
#   width  = the AVERAGE of the trapezoid's two bases, read off the diagram;
#   height = FITTED, not read -- h = A_REF_M2 / width, so the rectangle's ram
#            face reproduces the reference area.
#
# Axis mapping matches InPlaneTracking's convention (body +Y on the wind,
# +Z best-effort on the orbit normal):
#   x = height (radial), y = length (ram; the long axis rides the wind),
#   z = base-averaged width (cross-track).
BOX_X_M = 0.72388  # radial (height) -- FITTED so BOX_X * BOX_Z == A_REF_M2
BOX_Y_M = 3.1225  # along-track (length), diagram
BOX_Z_M = 1.3195  # cross-track, mean of the trapezoid's two bases, diagram

A_RAM_M2 = BOX_X_M * BOX_Z_M  # +/-Y ram/leeward faces -- 0.95516 m^2
A_SIDE_X_M2 = BOX_Y_M * BOX_Z_M  # +/-X nadir/zenith faces -- 4.1201 m^2 each
A_SIDE_Z_M2 = BOX_X_M * BOX_Y_M  # +/-Z slant-side faces -- 2.2603 m^2 each
A_SIDES_TOTAL_M2 = 2.0 * (A_SIDE_X_M2 + A_SIDE_Z_M2)

# ONE check this geometry passes, and one identity that is NOT a check:
#   nadir+zenith  8.24028 vs Table 5 6.0711120 + 2.1673620 = 8.238474  (0.02%)
#       A real check -- the diagram-derived length x width against Table 5's
#       independently published panel areas. Nothing here was fitted to it.
#   ram face      0.95516 vs A_REF_M2 0.9551567  (3e-6)
#       NOT a check. BOX_X was solved for this above, so the agreement is the
#       definition and the 3e-6 is only BOX_X's rounding. Recorded so the
#       number is never mistaken for corroboration.
#
# KNOWN LEVEL SYSTEMATIC, stated rather than tuned away. Two geometry
# approximations both UNDER-predict drag and therefore compound:
#   (a) flattening the trapezoid loses slant-face area -- the rectangle's
#       non-ram faces total 12.761 m^2 against the true prism's 14.209 m^2
#       (-10.2%), worth about -2.9% of box CdA at the grazing-incidence Cd;
#   (b) the boom is omitted entirely, worth about -3.6% of box CdA.
# Together about -6.5%. Both are window-INDEPENDENT, so they cancel from every
# ratio-of-extremes claim (B2, B5, A3, B3) and shift only the level, which this
# study withholds. The one claim they touch is B1's sign test on T_box near 1:
# carry the correction explicitly on that row.
BOX_GEOMETRY_SYSTEMATIC = 0.065  # box CdA under-predicts by ~6.5%

# --- mass ---------------------------------------------------------------------
# Handbook Table 4, "Mass at Launch [5]": FM1 601.214 kg, FM2 601.209 kg -- the
# twins differ by 5 g (8 ppm), which is the strongest available support for
# treating them as build-identical.
LAUNCH_MASS_KG = {"C": 601.214, "D": 601.209}
# JPL press kit, propulsion: "69 pounds (31.3 kilograms)" of gaseous nitrogen.
PROPELLANT_LAUNCH_KG = 31.3
# Dry mass follows. NOTE the two sources disagree on launch mass by ~1 kg (the
# press kit says 600.2 kg), so this constant carries a ~0.17% ambiguity. It is
# a CONSTANT OFFSET and therefore cancels from every cross-window ratio; it
# touches only the level.
DRY_MASS_KG = LAUNCH_MASS_KG["C"] - PROPELLANT_LAUNCH_KG  # 569.914 kg


def window_mass_kg(gas_mass_kg: float) -> float:
    """Total spacecraft mass for a window, from its MAS1B tank gas mass."""
    return DRY_MASS_KG + gas_mass_kg


# BOTH TWINS SHARE ONE ASSUMED MASS PER WINDOW -- this is binding, not a
# convenience. Contract sec 2.3 M1 requires the shared constant to cancel from
# kappa so that T(C,w)/T(D,w) measures the ratio of the twins' TRUE A/m, and it
# makes the three-term label ("noise floor + fore/aft asymmetry + any true A/m
# difference") mandatory. Giving each twin its own MAS1B mass would remove the
# third term by construction and force the forbidden two-term form. The
# measured C-vs-D mass difference is REPORTED instead, as the bound on term 3.

# --- attitude -----------------------------------------------------------------
# Handbook sec 3.2.3: "During flight, the satellites have nadir-pointing Yaw
# axis orientation, with the Roll axes in the anti-flight and in-flight
# directions for the leading and trailing satellites, respectively."
#
# So the twins differ by a 180 deg yaw about the nadir-aligned axis: both keep
# the wide (bottom) face nadir, and only the +/-X ends swap. Front and Rear
# panels are the same 0.9551567 m^2, so A_ram is IDENTICAL between the twins --
# contract sec 2.3 M1 confirmed from the primary source, not assumed.
#
# Which twin leads is measured per window by run_twin_checkout.py rather than
# taken from literature (it is stated inconsistently in secondary sources, and
# it could in principle change across a mission). Measured 2026-08-09: C leads
# in all three inherited windows, sign constant.
#
# The boom's Table 5 note -- "planar projection area ... along any direction in
# the SF (X-Y) plane" -- is the signature of a Z-aligned cylinder, whose
# projection is direction-independent in X-Y. It therefore adds the SAME ram
# area to both twins and does NOT contribute fore/aft asymmetry.

# --- inherited, unchanged from v0.7.2 -----------------------------------------
# Transcribed from real-world-validation/gracefo/gracefo_common.py with the
# lines cited, so a diff against that file is a one-line check.
CD_NOMINAL = 2.3  # gracefo_common.py:40 -- free-molecular nominal
CR = 1.3  # gracefo_common.py:41 -- sphere reflection coefficient
SUBSAMPLE_S = 60.0  # gracefo_common.py:47 -- the truth diff grid

# Cd-fit coarse-scan ceilings. The v0.7.2 values were 5.0 / 8.0 on
# A_ref = 1.0 m^2; this study's smaller A_ref inflates every reported Cd by
# ~7%, so the ceilings rise with it and the guard-rail behaviour (including the
# shipped _SOFT_CD_LIMIT = 5 warn-once) is exercised at the same PHYSICAL
# ballistic coefficient as before.
CD_FIT_HI_DEFAULT = 5.4
CD_FIT_HI_STORM = 8.6

# THE FIT TOLERANCE IS THE FIT'S RESOLUTION, NOT A COSMETIC KNOB. Golden section
# shrinks its bracket by a fixed ratio every step, so the returned midpoint can
# only land on a discrete lattice whose rungs are phi and phi^2 times the FINAL
# bracket width. A difference between two fits smaller than one rung is not
# measured -- it is quantized, and it can be quantized UPWARD as easily as down.
# At the v0.7.2 value 0.02 the rungs are ~0.007 in Cd (~0.3% at GRACE-FO's quiet
# Cd), which is the same size as A1's twin deviation; at 0.002 they are ~0.001
# (~0.04%), about 20x below it. Five extra objective evaluations per fit.
CD_FIT_TOL = 0.002

# --- measured anchors ---------------------------------------------------------
# Study results consumed as inputs by later chunks, recorded once with
# provenance. Empty at Chunk 0; Chunk 2 fills it from the curve leg.
MEASURED_ANCHORS: dict[str, dict[str, float]] = {}


# --- spacecraft / force factories ---------------------------------------------
def sphere_spacecraft(
    cd: float | VariableCd,
    mass_kg: float,
    area_m2: float = A_REF_M2,
) -> SpacecraftConfig:
    """The sphere-equivalent GRACE-FO spacecraft on this study's A_ref."""
    return SpacecraftConfig(
        mass_kg=mass_kg,
        geometry=SpacecraftGeometry.sphere(
            area_m2=area_m2,
            drag_coefficient=cd,
            reflectivity_coefficient=CR,
        ),
    )


def box_spacecraft(cd: BoxFaceCd, mass_kg: float) -> SpacecraftConfig:
    """The base-averaged GRACE-FO rectangle as a convex box.

    SRP optics stay at the ``box_and_panels`` defaults -- negligible at ~490 km;
    drag is what these runs measure.
    """
    return SpacecraftConfig(
        mass_kg=mass_kg,
        geometry=SpacecraftGeometry.box_and_panels(
            x_length_m=BOX_X_M,
            y_length_m=BOX_Y_M,
            z_length_m=BOX_Z_M,
            solar_array_area_m2=0.0,  # convex bus -- the BoxFaceCd contract
            drag_coefficient=cd,
        ),
    )


def force_config(drag: bool) -> ForceModelConfig:
    """The v0.7.2 conservative force set (gracefo_common.py:118-126), unchanged."""
    return ForceModelConfig(
        drag=drag,
        atmosphere_model="NRLMSISE-00",
        srp=True,
        solid_tides=True,
        ocean_tides=True,
        relativity=True,
    )


# --- the scalar-Cd fitter (shared; Chunks 2 and 3 consume it) -----------------
def fit_cd_scalar(
    objective: Callable[[float], float],
    cd_hi: float,
    *,
    cd_lo: float = 1.5,
    n_coarse: int = 7,
    tol: float = CD_FIT_TOL,
) -> tuple[float, int, float]:
    """Coarse scan + golden-section refine on a scalar Cd.

    ``objective`` is any deterministic scalar function of Cd -- the drivers pass
    a closure that propagates and returns an along-track RMS. Returns
    ``(best_cd, n_evaluations, bracket_width)``.

    Structure carried from the v0.7.2 ``run_gracefo.py:347`` fit so the two
    studies estimate the same quantity; only ``tol`` differs (see CD_FIT_TOL).

    ``bracket_width`` is a FIT-QUALITY DIAGNOSTIC only -- a flat minimum is a
    weak-drag warning worth seeing. It never enters an error bar (contract
    sec 5): the objective is a deterministic optimization against a residual
    dominated by unmodelled systematics, so its curvature measures optimizer
    resolution, not uncertainty in T.
    """
    n_evals = 0

    def f(cd: float) -> float:
        nonlocal n_evals
        n_evals += 1
        return objective(cd)

    grid = np.linspace(cd_lo, cd_hi, n_coarse)
    vals = [f(float(cd)) for cd in grid]
    k = int(np.argmin(vals))
    a = float(grid[max(k - 1, 0)])
    b = float(grid[min(k + 1, len(grid) - 1)])

    phi = (np.sqrt(5.0) - 1.0) / 2.0
    c, d = b - phi * (b - a), a + phi * (b - a)
    fc, fd = f(c), f(d)
    while (b - a) > tol:
        if fc < fd:
            b, d, fd = d, c, fc
            c = b - phi * (b - a)
            fc = f(c)
        else:
            a, c, fc = c, d, fd
            d = a + phi * (b - a)
            fd = f(d)
    return 0.5 * (a + b), n_evals, float(b - a)


# --- shipped-table lookups (JVM-free, no propagation) -------------------------
# Evaluations of the committed data/*.npz grids through the public JVM-free
# __call__ surfaces. Chunk 2's range_table is built on these; Chunk 0 uses them
# to form T. No generator run, no pymsis/scipy, no second environment
# (contract sec 2.5).
_SPHERE_TABLE: VariableCd | None = None
_BOX_TABLE: BoxFaceCd | None = None


def sphere_table() -> VariableCd:
    global _SPHERE_TABLE
    if _SPHERE_TABLE is None:
        _SPHERE_TABLE = VariableCd.sphere_default()
    return _SPHERE_TABLE


def box_table() -> BoxFaceCd:
    global _BOX_TABLE
    if _BOX_TABLE is None:
        _BOX_TABLE = BoxFaceCd.default()
    return _BOX_TABLE


def box_cda(cd_ram: float, cd_side: float, cd_lee: float) -> float:
    """Face-sum Sigma Cd_i * A_i (m^2) for the wind-aligned box.

    Under InPlaneTracking(ecef) the face-flow angles are constant by
    construction: ram theta=0, leeward theta=pi, all four sides theta=pi/2.
    Each face's tabulated Cd is referenced to that face's own full area with
    the incidence projection already baked in, so the raw sum IS the along-wind
    effective Cd*A.
    """
    return (cd_ram + cd_lee) * A_RAM_M2 + cd_side * A_SIDES_TOTAL_M2
