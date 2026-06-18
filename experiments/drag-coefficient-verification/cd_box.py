"""
Tier B placeholder: per-face flat-plate drag coefficient (Schaaf-Chambre /
Sentman, diffuse re-emission at the DRIA reflected temperature).

>>> PLACEHOLDER <<<  cd_panel_species() is the standard closed form. Swap in
your propygator per-face coefficient when ready; the harness around it is the
deliverable. Correctness gate: integrating these panels over a sphere must
reproduce cd_core.cd_sphere_species to <0.1%.
"""
import numpy as np
from scipy.special import erf
from scipy.integrate import quad
from cd_core import KB, T_WALL, cd_sphere_species


def cd_panel_species(gamma, V, T_inf, m, alpha):
    """Drag coeff of one flat face (ref to its OWN area) for one species.

    gamma = n_hat . ram_hat   (cos of incidence from the ram direction;
            >0 windward, <0 leeward). Re-emission uses the DRIA reflected
            temperature T_r = (1-alpha) m V^2/(3k) + alpha T_wall.
    """
    S = V * np.sqrt(m / (2.0 * KB * T_inf))
    Tr = (1.0 - alpha) * m * V**2 / (3.0 * KB) + alpha * T_WALL
    tr = Tr / T_inf
    a = S * gamma
    E = np.exp(-a * a)
    Zp = 1.0 + erf(a)                     # (1 + erf(a))
    ell = np.sqrt(max(0.0, 1.0 - gamma * gamma))

    Cp_inc = (1.0 / S**2) * (a / np.sqrt(np.pi) * E + (a * a + 0.5) * Zp)
    Cp_re = (np.sqrt(tr) / (2.0 * S**2)) * (E + np.sqrt(np.pi) * a * Zp)
    Cp = Cp_inc + Cp_re                   # normal pressure coeff
    Ctau = (ell / (np.sqrt(np.pi) * S)) * (E + np.sqrt(np.pi) * a * Zp)  # shear
    return Cp * gamma + Ctau * ell        # project onto drag (ram) direction


def sphere_from_panels(V, T_inf, m, alpha):
    """Integrate the panel coeff over a unit sphere -> sphere C_D (ref pi R^2)."""
    # C_D = 2 * integral_0^pi cd_panel(cos psi) sin psi dpsi
    f = lambda psi: cd_panel_species(np.cos(psi), V, T_inf, m, alpha) * np.sin(psi)
    val, _ = quad(f, 0.0, np.pi, limit=200)
    return 2.0 * val


if __name__ == "__main__":
    U = 1.66053906660e-27
    cases = [
        ("400km solar-max, O", 7174.0, 1284.0, 15.9994 * U, 0.90),
        ("400km solar-min, O", 7174.0, 782.0, 15.9994 * U, 0.23),
        ("high-alt, He",       7050.0, 1000.0, 4.0026 * U, 0.40),
        ("low-S cool, N2",     7300.0, 700.0, 28.0134 * U, 0.90),
    ]
    print(f"{'case':24s} {'panel-integral':>14s} {'closed-form':>12s} {'err %':>8s}")
    for name, V, T, m, al in cases:
        a = sphere_from_panels(V, T, m, al)
        b = cd_sphere_species(V, T, m, al)
        print(f"{name:24s} {a:14.5f} {b:12.5f} {100*(a-b)/b:8.3f}")
