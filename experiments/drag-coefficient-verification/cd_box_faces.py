"""
Shared per-face free-molecular drag helpers for the Tier B (BoxFaceCd) offline
evidence -- the convergence study (cd_box_incidence_convergence.py) and the cheap
benefit estimate (cd_box_benefit_estimate.py), build-plan Chunk 1.

Single source of the per-face physics so the two Chunk-1 drivers cannot drift.
It wraps cd_box.cd_panel_species (the Schaaf-Chambre / Sentman per-face closed
form, diffuse re-emission at the DRIA reflected temperature) with the same
mass-flux weighting over NRLMSISE-00 species that cd_box_experiment.box_cd uses,
but keyed on the FACE-FLOW ANGLE theta in [0, pi] (theta = 0 head-on, pi/2
edge-on, pi fully leeward) rather than on gamma = cos(theta) -- the axis the
shipped BoxFaceCd table keys on. Per general-upgrades-1.md "Tier B Drag": the
shear's sin(theta) factor is smooth in theta, but written in cos-theta it is
sqrt(1 - cos^2 theta) with an infinite-derivative cusp at the poles, so the
table must key and interpolate in theta even though the kernel evaluates in
cos(theta).

Conventions (matching the runtime contract and cd_box_experiment.box_cd):
  * flow_hat is the incoming-flow direction the body sees = +velocity direction
    (Orekit relativeVelocity = -v_spacecraft, so flow_hat = -relVel/|relVel| =
    +v_hat). gamma = n_hat . flow_hat = cos(theta); >0 windward, <0 leeward.
  * A_i is the FULL face area; the incidence projection (both the cos-theta
    pressure falloff and the tangential-shear floor) is already inside Cd_i, so
    do NOT re-project when assembling CdA.

Reference-only: not shipped, not in CI, not linted/type-checked. ASCII-only.
Run from this directory in the throwaway venv (docs/experiments_venv.md).
"""
import numpy as np

from cd_box import cd_panel_species
from cd_core import SPECIES


def face_cd(theta, row, V, T_inf, alpha):
    """Mass-flux-weighted per-face drag coefficient (ref FULL face area) at
    face-flow angle theta [rad], for one NRLMSISE-00 state row.

    theta is the angle between the face outward normal and the incoming-flow
    direction; gamma = cos(theta) is what cd_panel_species consumes. The weight
    is the per-species mass density rho_s = n_s * m_s, exactly as box_cd.
    """
    gamma = float(np.cos(theta))
    num = den = 0.0
    for col, m in SPECIES.values():
        n = row[col]
        if not np.isfinite(n) or n <= 0:
            continue
        rho_s = n * m
        num += rho_s * cd_panel_species(gamma, V, T_inf, m, alpha)
        den += rho_s
    return num / den


def face_cd_curve(thetas, row, V, T_inf, alpha):
    """face_cd over an array of theta [rad] -> ndarray (cd_panel_species is a
    scalar closed form, so this is a simple vectorizing loop)."""
    return np.array([face_cd(float(t), row, V, T_inf, alpha) for t in thetas])
