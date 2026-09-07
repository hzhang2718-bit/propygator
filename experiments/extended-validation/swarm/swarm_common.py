"""Swarm leg configuration for the extended-validation study (reference-only).

**EVERY NUMBER HERE IS AN ESTIMATE, AND THAT IS THE POINT.** Part B exists as a
limited-information stress case: public sources disagree on Swarm's exact
dimensions and mass, so this leg measures what propygator does when a
spacecraft's properties are *not* well known (contract, "Part B: additional
drag-significant propagations, Swarm A, B"). Every driver prints them flagged as
estimates, and the findings read the Swarm rows accordingly.

The consequence to keep in view when reading a Swarm result: an orbit residual
constrains only ``rho * Cd * A / m``, so the fitted-Cd row absorbs any error in
the area and mass below and cannot be read as a body property. The two *table*
rows are the ones that hurt -- they are directly proportional to these
estimates, so a table-vs-truth gap on this leg conflates geometry error with
model error in a way the GRACE-FO leg's Handbook-traceable geometry does not.

Dimensions and mass are consistent with ESA's mission description
(https://earth.esa.int/eogateway/missions/swarm/description), transcribed from
the contract:

- length 5.0 m -- about the length of Swarm without the boom
- width 1.0 m, height 1.0 m -- the source states a ram area of ~1 m^2, and a
  square shape is assumed here
- mass 419.0 kg -- drag mass with half the propellant load

**Swarm A and B are not a twin pair.** Measured off the delivered ephemerides
rather than taken from literature: ~435 km and ~502 km in window 1. An A-vs-B
difference is an altitude difference before it is a body difference, so the two
are never read as a twin ratio the way GRACE-FO C/D are in Part 1.

**There is no maneuver gate on this leg worth the name.** Swarm has no THR1B
analogue, so the degree-5 polynomial is the only screen, and it went 0-for-2
against the two known-real burns in Chunk 2. Its verdict is recorded and a CLEAN
is weak evidence, not a quiet window (contract amendment 2026-08-21); an
undetected Swarm maneuver stays a live risk on every Part B row.

The force set, the scalar-Cd fitter and the shipped table accessors are imported
from ``gracefo_ext_common`` rather than restated: they are leg-independent, and
both legs importing the SAME objects is what stops the two from drifting into
different physics.

Imports ``propygator`` (JVM-free at import) but never starts the JVM.
Not shipped, not in CI, outside ``testpaths``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
for _p in (str(_STUDY / "gracefo"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from gracefo_ext_common import CR  # noqa: E402,F401  (re-exported for the driver)
from gracefo_ext_common import (  # noqa: E402,F401
    CD_FIT_HI_DEFAULT,
    CD_FIT_HI_STORM,
    CD_FIT_TOL,
    CD_NOMINAL,
    SUBSAMPLE_S,
    box_table,
    fit_cd_scalar,
    force_config,
    sphere_table,
)

from propygator import (  # noqa: E402
    BoxFaceCd,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
)

# This study's own truth tree for the Swarm leg (gitignored). Mirrors the
# GRACE-FO tree's shape -- one directory per window, named for the window.
DATA_ROOT = _STUDY / "data" / "swarm"

SAT_IDS = ("A", "B")

# --- geometry (ESTIMATES) -----------------------------------------------------
# Axis mapping matches InPlaneTracking's convention, identical to the GRACE-FO
# leg: x = height, y = length (held on the wind), z = width.
BOX_X_M = 1.0  # height  -- estimate
BOX_Y_M = 5.0  # length  -- estimate, +Y rides the wind
BOX_Z_M = 1.0  # width   -- estimate
A_REF_M2 = 1.0  # the ram face, and the reference for every non-box run

A_RAM_M2 = BOX_X_M * BOX_Z_M  # +/-Y ram/leeward faces
A_SIDE_X_M2 = BOX_Y_M * BOX_Z_M  # +/-X nadir/zenith faces
A_SIDE_Z_M2 = BOX_X_M * BOX_Y_M  # +/-Z side faces
A_SIDES_TOTAL_M2 = 2.0 * (A_SIDE_X_M2 + A_SIDE_Z_M2)

# --- mass (ESTIMATE, and the same for both satellites) ------------------------
# GRACE-FO reads its mass per window from MAS1B; Swarm has no such product here,
# so this is a fixed literal. It does not vary by window or by satellite, which
# is itself a limitation of this leg rather than a property of the spacecraft.
MASS_KG = 419.0


def sphere_spacecraft(
    cd: float | VariableCd, mass_kg: float = MASS_KG, area_m2: float = A_REF_M2
) -> SpacecraftConfig:
    """The sphere-equivalent Swarm spacecraft on the estimated 1.0 m^2 ram area."""
    return SpacecraftConfig(
        mass_kg=mass_kg,
        geometry=SpacecraftGeometry.sphere(
            area_m2=area_m2,
            drag_coefficient=cd,
            reflectivity_coefficient=CR,
        ),
    )


def box_spacecraft(cd: BoxFaceCd, mass_kg: float = MASS_KG) -> SpacecraftConfig:
    """The estimated Swarm envelope as a convex box.

    SRP optics stay at the ``box_and_panels`` defaults -- negligible at ~450 km;
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


def check_geometry() -> None:
    """Assert the ram-face identity, printed by every driver before it runs.

    Trivial arithmetic here compared with GRACE-FO's fitted dimensions, but
    asserted on the same footing so an edited constant cannot flow silently into
    a result.
    """
    ram = BOX_X_M * BOX_Z_M
    if abs(ram - A_REF_M2) > 1e-9:
        raise SystemExit(
            f"Swarm ram face {ram} m^2 does not match A_ref {A_REF_M2} m^2 -- "
            f"the box dimensions and the reference area have drifted apart"
        )
