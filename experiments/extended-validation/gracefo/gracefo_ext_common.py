"""GRACE-FO leg configuration for the extended-validation study (reference-only).

The leg-wide facts every GRACE-FO driver in this study shares. It deliberately
does **not** import ``real-world-validation/gracefo/gracefo_common.py``: this
study revises the reference area and the mass to more authoritative sources, so
every constant below is transcribed with its provenance rather than inherited.

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

THIS IS THE REPOSITORY'S THIRD A_ref. v0.7.2 used 1.027 m^2 (press-kit
envelope); the retired Chunk 0 build used 0.9551567 m^2 (Table 5 front panel
alone). This one folds the boom back in, per the 2026-08-13 contract. A fitted
Cd means nothing without its A_ref and mass, so **never compare a Cd across two
conventions without converting** -- every driver prints the convention-free
ballistic coefficient ``B = Cd*A/m`` beside every fitted Cd for exactly that
reason.

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
# The table-noise part reads the FROZEN v0.7.2 truth tree -- read, never written
# (contract, "The earlier experiment is frozen"). This study's own ten-window
# tree lives in windows.DATA_ROOT.
FROZEN_DATA_ROOT = (
    Path(__file__).resolve().parents[2] / "real-world-validation" / "data" / "gracefo"
)

# --- identity -----------------------------------------------------------------
# GRACE-FO 1 = GRACE C = NORAD 43476; GRACE-FO 2 = GRACE D = NORAD 43477.
NORAD_IDS = {"C": 43476, "D": 43477}
SAT_IDS = ("C", "D")

# --- reference area -----------------------------------------------------------
# L1 Handbook Table 5 ("GRACE / GRACE-FO surface properties") lists Front and
# Rear panels at 0.9551567 m^2 each (unit normal +X / -X) and itemizes the boom
# separately at 0.0461901 m^2. The contract folds the boom into the ram face, so
# A_ref is their sum -- one reference for the Cd = 2.3 run, the fitted-Cd run and
# the sphere-table run alike.
FRONT_PANEL_M2 = 0.9551567  # Table 5, Front/Rear panel
BOOM_PROJ_M2 = 0.0461901  # Table 5; cylindrical boom, Z-aligned
A_REF_M2 = 1.0013468  # = FRONT_PANEL_M2 + BOOM_PROJ_M2, exactly

# --- box geometry -------------------------------------------------------------
# The rectangle standing in for the trapezoidal prism (contract, "The design --
# drag-significant propagations"):
#   width  = 1.3195 m, the average of the trapezoid's two bases (0.695 / 1.944 m,
#            Handbook Figure 2) -- read off the diagram;
#   height = FITTED so the ram face H*W reproduces A_REF_M2;
#   length = FITTED so the four non-ram faces total Table 5's published
#            15.0060150 m^2 (nadir 6.0711120 + zenith 2.1673620 + inner
#            starboard/port 0.2282913 each + outer starboard/port 3.1554792
#            each), solved as 2 * L * (H + W).
#
# THE LENGTH IS NOT A PHYSICAL DIMENSION. The fit preserves the TOTAL side area,
# which is the only side quantity drag sees when the box is flown wind-aligned
# (all four sides then sit at 90 deg incidence and only their sum enters Cd*A).
# It does not preserve the nadir/zenith vs slant split -- the rectangle carries
# ~1.3 m^2 more on the former and that much less on the latter.
#
# Axis mapping matches InPlaneTracking's convention (body +Y on the wind,
# +Z best-effort on the orbit normal): x = height, y = length, z = width.
BOX_X_M = 0.7588835  # radial (height) -- FITTED, BOX_X * BOX_Z == A_REF_M2
BOX_Y_M = 3.6100207  # along-track (length) -- FITTED to the side-area total
BOX_Z_M = 1.3195  # cross-track (width), mean of the trapezoid's two bases

A_RAM_M2 = BOX_X_M * BOX_Z_M  # +/-Y ram/leeward faces
A_SIDE_X_M2 = BOX_Y_M * BOX_Z_M  # +/-X nadir/zenith faces
A_SIDE_Z_M2 = BOX_X_M * BOX_Y_M  # +/-Z slant-side faces
A_SIDES_TOTAL_M2 = 2.0 * (A_SIDE_X_M2 + A_SIDE_Z_M2)

# The two published figures the fitted dimensions must reproduce. Asserted and
# printed by every driver that flies the box -- both hold to 8 figures.
TABLE_5_SIDE_TOTAL_M2 = 15.0060150

# --- mass ---------------------------------------------------------------------
# Handbook Table 4, "Mass at Launch [5]": FM1 601.214 kg, FM2 601.209 kg -- the
# twins differ by 5 g (8 ppm), which is the strongest available support for
# treating them as build-identical.
LAUNCH_MASS_KG = {"C": 601.214, "D": 601.209}
# JPL press kit, propulsion: "69 pounds (31.3 kilograms)" of gaseous nitrogen.
PROPELLANT_LAUNCH_KG = 31.3
# Dry mass follows. NOTE the two sources disagree on launch mass by ~1 kg (the
# press kit says 600.2 kg), so this constant carries a ~0.17% ambiguity. It is a
# CONSTANT OFFSET and cancels from every cross-window ratio; it touches only the
# level.
DRY_MASS_KG = LAUNCH_MASS_KG["C"] - PROPELLANT_LAUNCH_KG  # 569.914 kg


def window_mass_kg(gas_mass_kg: float) -> float:
    """Total spacecraft mass for a window, from its MAS1B tank gas mass."""
    return DRY_MASS_KG + gas_mass_kg


# MASS IS PER SATELLITE -- each twin gets its own MAS1B tank-gas reading
# (maintainer, 2026-08-14). Mass is a reading, so it is read. Its effect on a
# twin Cd ratio is exactly the mass ratio, and the shared-mass form is one
# multiplication away.

# --- attitude -----------------------------------------------------------------
# Handbook sec 3.2.3: "During flight, the satellites have nadir-pointing Yaw
# axis orientation, with the Roll axes in the anti-flight and in-flight
# directions for the leading and trailing satellites, respectively."
#
# So the twins differ by a 180 deg yaw about the nadir-aligned axis: both keep
# the wide (bottom) face nadir, and only the +/-X ends swap. Front and Rear
# panels are the same 0.9551567 m^2, and the boom's Table 5 note -- "planar
# projection area ... along any direction in the SF (X-Y) plane" -- is the
# signature of a Z-aligned cylinder, whose projection is direction-independent
# in X-Y. So A_ram is IDENTICAL between the twins, and the model cannot see the
# relative yaw at all. Which twin leads is measured per window from the two
# ephemerides rather than taken from literature.

# --- Part 2 arc geometry (Chunk 3) --------------------------------------------
# NAME COLLISION WITH PART 1, introduced here and left alone: run_table_noise.py
# carries its own LOAD_DAYS = 3 / ARC_DAYS = 1.0 as module locals. Never add
# either name to that file's import list -- its locals shadow these today, and a
# reorder would silently turn Part 1's 1-day arc into a 7-day one and change
# committed evidence with nothing raising.
#
# ONE 7-day propagation per configuration, read at several days -- never one run
# per day (contract, "The design - drag-significant propagations": five
# propagations per window per body, not fifteen).
ARC_DAYS = 7.0
# 8 days loaded, not 7, so the t0 + 7 d ENDPOINT sample exists: daily truth files
# cover [day, day+1), so the last sample of the seventh file sits one step short
# of t0 + 7 d. Chunk 1 already landed 14 days for GRACE-FO, so this costs parse
# time only; the Swarm leg is delivered at 8 days exactly (contract amendment
# 2026-08-21).
LOAD_DAYS = 8
# NAMED `READ_DAYS`, NOT `READ_HORIZONS_D`. These index INDIVIDUAL days, not
# cumulative horizons: day N is the RMS over [N-1 d, N d] ALONE. The old name
# invites the accumulate-from-t0 read the contract forbids, because a 0-N d
# window is dominated by its early, still well-fitted portion and understates
# the error at the horizon actually being read. There is no 0-1 / 0-3 / 0-7 d
# row anywhere in this study. Day 1 is the one value both conventions share,
# which is what keeps the frozen v0.7.2 comparison valid.
READ_DAYS = (1, 3, 7)

# --- inherited, unchanged from v0.7.2 -----------------------------------------
# Transcribed from real-world-validation/gracefo/gracefo_common.py with the
# lines cited, so a diff against that file is a one-line check.
CD_NOMINAL = 2.3  # gracefo_common.py:40 -- free-molecular nominal
# near Leipner et al.'s cD=2.25 "standard" GRACE-FO value (arXiv 2503.21651,
# via Woske et al. 2018 -- not independently verified)
CR = 1.3  # gracefo_common.py:41 -- sphere reflection coefficient
SUBSAMPLE_S = 60.0  # gracefo_common.py:47 -- the truth diff grid

# Cd-fit coarse-scan ceilings, back at v0.7.2's values (run_gracefo.py:146-147).
# The retired Chunk 0 build raised them to 5.4 / 8.6 to compensate for its
# smaller A_ref; at A_ref ~ 1.0 m^2 the originals are again right, because Cd
# and CdA are then numerically near-equal. The shipped _SOFT_CD_LIMIT = 5
# warn-once is therefore exercised at the same physical ballistic coefficient
# v0.7.2 exercised it at.
CD_FIT_HI_DEFAULT = 5.0
CD_FIT_HI_STORM = 8.0

# THE FIT TOLERANCE IS THE FIT'S RESOLUTION, NOT A COSMETIC KNOB, AND IT IS NOT
# LOOSENED. Golden section shrinks its bracket by a fixed ratio every step, so
# the returned midpoint can only land on a discrete lattice whose rungs are phi
# and phi^2 times the FINAL bracket width. A difference between two fits smaller
# than one rung is not measured -- it is quantized, and it can be quantized
# UPWARD as easily as down. At the v0.7.2 value 0.02 the rungs are ~0.007 in Cd
# (0.5-1% at a fitted Cd of 2-4), the same size as the twin deviations the
# table-noise part exists to measure; at 0.002 they are ~0.001 (0.05-0.1%).
# Five extra objective evaluations per fit buy that.
CD_FIT_TOL = 0.002


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
    """The GRACE-FO rectangle as a convex box.

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


# --- the scalar-Cd fitter (shared by every driver that fits a Cd) -------------
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
    weak-drag warning worth seeing. It never enters an error bar: the objective
    is a deterministic optimization against a residual dominated by unmodelled
    systematics, so its curvature measures optimizer resolution, not uncertainty.
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
# __call__ surfaces. No generator run, no pymsis/scipy, no second environment.
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
