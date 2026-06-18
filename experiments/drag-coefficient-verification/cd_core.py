"""
Physically-rigorous free-molecular drag coefficient (C_D) for a sphere over
NRLMSISE-00, using the Sentman closed form with Diffuse Reflection and
Incomplete Accommodation (DRIA), per-species mass-flux weighting, and a
SESAM-style Langmuir energy-accommodation model keyed on atomic-oxygen coverage.

This reconstructs the chain established previously. Swap `alpha_sesam` and the
constants for your exact propygator implementation; the time-independence
conclusion is a property of the *mechanism* (alpha tied to O coverage, which
tracks the same thermospheric heating that sets density), not of the exact
calibration.
"""
import numpy as np
from scipy.special import erf

# ---- constants ----
KB = 1.380649e-23           # J/K
U  = 1.66053906660e-27      # kg per atomic mass unit
MU_EARTH = 3.986004418e14   # m^3/s^2
R_EARTH  = 6378137.0        # m

# pymsis NRLMSISE-00 output column indices
IDX = dict(rho=0, N2=1, O2=2, O=3, HE=4, H=5, AR=6, N=7, ANOM_O=8, NO=9, T=10)

# species: (column index, molecular mass kg)
SPECIES = {
    'N2': (IDX['N2'], 28.0134 * U),
    'O2': (IDX['O2'], 31.9988 * U),
    'O' : (IDX['O'],  15.9994 * U),
    'HE': (IDX['HE'],  4.0026 * U),
    'H' : (IDX['H'],   1.0080 * U),
    'AR': (IDX['AR'], 39.9480 * U),
    'N' : (IDX['N'],  14.0067 * U),
}

T_WALL = 300.0  # K, spacecraft surface temperature


def v_rel(alt_km, lat_deg=0.0):
    """Relative speed wrt corotating atmosphere for a circular orbit (m/s)."""
    r = R_EARTH + alt_km * 1e3
    v_orb = np.sqrt(MU_EARTH / r)
    v_corot = 2 * np.pi * r * np.cos(np.radians(lat_deg)) / 86164.1  # sidereal day
    return v_orb - v_corot


def cd_sphere_species(V, T_inf, m, alpha):
    """Sentman/DRIA sphere C_D for one species (referenced to projected area)."""
    S = V * np.sqrt(m / (2.0 * KB * T_inf))            # molecular speed ratio
    Tr = (1.0 - alpha) * m * V**2 / (3.0 * KB) + alpha * T_WALL  # DRIA reflected temp
    term1 = (2.0 * S**2 + 1.0) / (np.sqrt(np.pi) * S**3) * np.exp(-S**2)
    term2 = (4.0 * S**4 + 4.0 * S**2 - 1.0) / (2.0 * S**4) * erf(S)
    term3 = (2.0 * np.sqrt(np.pi) / (3.0 * S)) * np.sqrt(Tr / T_inf)
    return term1 + term2 + term3


def alpha_sesam(n_O, T_inf, K):
    """SESAM-style energy accommodation from atomic-O Langmuir surface coverage."""
    P_O = n_O * KB * T_inf            # atomic-oxygen partial pressure (Pa)
    theta = K * P_O / (1.0 + K * P_O) # fractional coverage
    return theta


def calibrate_K(target_alpha=0.90, n_O_ref=2.64e14, T_ref=1284.0):
    """Pick Langmuir K so alpha hits the 400 km / solar-max anchor.

    The anchor energy-accommodation coefficient is 0.90, a commonly-accepted
    value at 400 km / solar max: Pilinski, Argrow & Palo (2010, J. Spacecraft &
    Rockets 47(6), 951-956) SESAM lands ~0.85-0.93 there, and CHAMP-derived
    values (Moe & Moe 2005, Planet. Space Sci. 53(8), 793-801) are ~0.86-0.89.
    Reconciled with scripts/generate_sphere_cd_table.py (ANCHOR_ALPHA=0.90) per
    the Feature 1.1 drag-validity addendum, section 5. (The committed *_results.txt
    predate this change and are regenerated when the addendum's Phase 1 experiment
    is re-run.)
    """
    P_O = n_O_ref * KB * T_ref
    return (target_alpha / (1.0 - target_alpha)) / P_O


def cd_total(msis_row, alt_km, lat_deg, K):
    """Mass-flux-weighted total C_D for a sphere from one MSIS state row."""
    T_inf = msis_row[IDX['T']]
    V = v_rel(alt_km, lat_deg)
    n_O = msis_row[IDX['O']]
    alpha = alpha_sesam(n_O, T_inf, K)
    num = den = 0.0
    for col, m in SPECIES.values():
        n = msis_row[col]
        if not np.isfinite(n) or n <= 0:
            continue
        rho_s = n * m
        cd_s = cd_sphere_species(V, T_inf, m, alpha)
        num += rho_s * cd_s
        den += rho_s
    return num / den, alpha


if __name__ == "__main__":
    from pymsis import msis
    K = calibrate_K()
    print(f"Calibrated Langmuir K = {K:.3e} 1/Pa")
    # Anchor check: 400 km, solar max
    row = msis.run([np.datetime64('2002-07-01T12:00')], [0.0], [0.0], [400.0],
                   [200.0], [200.0], [[15.0]*7], version=0)[0]
    cd, a = cd_total(row, 400.0, 0.0, K)
    print(f"400 km solar-max:  rho={row[0]:.3e} kg/m^3  T={row[10]:.0f} K  "
          f"alpha={a:.3f}  V_rel={v_rel(400.):.0f} m/s  ->  C_D = {cd:.3f}")
    # Solar-min comparison at same altitude
    row2 = msis.run([np.datetime64('2008-07-01T12:00')], [0.0], [0.0], [400.0],
                    [70.0], [70.0], [[4.0]*7], version=0)[0]
    cd2, a2 = cd_total(row2, 400.0, 0.0, K)
    print(f"400 km solar-min:  rho={row2[0]:.3e} kg/m^3  T={row2[10]:.0f} K  "
          f"alpha={a2:.3f}  ->  C_D = {cd2:.3f}")
    # Hyperthermal sanity: large S, full accommodation -> ~2.0 incident
    print(f"Hyperthermal incident-only check (S->inf, alpha=1): "
          f"{cd_sphere_species(7500., 1000., 16*U, 1.0):.3f}")
