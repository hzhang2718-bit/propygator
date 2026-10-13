"""
Physically-rigorous free-molecular drag coefficient (C_D) for a sphere over
NRLMSISE-00, using the Sentman closed form with Diffuse Reflection and
Incomplete Accommodation (DRIA), per-species mass-flux weighting, and SESAM
energy accommodation (Pilinski et al. 2013; docs/history/sesam-accommodation.md).

The time-independence conclusion is a property of the *mechanism* (alpha tied to
O coverage, which tracks the same thermospheric heating that sets density), not
of the exact accommodation constants.
"""
import numpy as np
from scipy.special import erf

# ---- constants ----
KB = 1.380649e-23           # J/K
U  = 1.66053906660e-27      # kg per atomic mass unit
MU_EARTH = 3.986004418e14   # m^3/s^2
R_EARTH  = 6378137.0        # m  (WGS84 equatorial radius)
WGS84_F  = 1.0 / 298.257223563  # WGS84 flattening (for the geocentric-radius map)

# Acceptance thresholds for the collapse residual (addendum sec. 3.1): the
# collapse RMS is a *secondary* error term under the 15-30% thermospheric
# density-model uncertainty. Green = "as good as it needs to be"; red is a STOP
# line (the (alt, rho) pair has stopped being a sufficient statistic for C_D).
GREEN_RMS_PCT = 5.0
RED_RMS_PCT = 30.0

# pymsis NRLMSISE-00 output column indices
IDX = dict(rho=0, N2=1, O2=2, O=3, HE=4, H=5, AR=6, N=7, ANOM_O=8, NO=9, T=10)

# species: (column index, molecular mass kg)
SPECIES = {
    'N2': (IDX['N2'], 28.0134 * U),
    'O2': (IDX['O2'], 31.9988 * U),
    'O' : (IDX['O'],  15.9994 * U),
    'HE': (IDX['HE'],  4.002602 * U),
    'H' : (IDX['H'],   1.0080 * U),
    'AR': (IDX['AR'], 39.9480 * U),
    'N' : (IDX['N'],  14.0067 * U),
}

T_WALL = 300.0  # K, spacecraft surface temperature

# SESAM (Pilinski, Argrow, Palo & Bowman 2013, JSR 50(3) 556-571): published
# constants, no free parameter.
EV = 1.602176634e-19        # J
SESAM_K_S = 2.4             # substrate coefficient
SESAM_M_S = 65.0 * U        # surface molecule mass (kg)
SESAM_E_B = 5.7 * EV        # adsorption energy (J)
SESAM_T_AB = 93.31          # transition temperature (K)
SESAM_K_LO = 5e6            # initial Langmuir parameter (1/torr)
SESAM_K_LF = 3e4            # final Langmuir parameter (1/torr)
TORR = 101325.0 / 760.0     # Pa


def v_rel(alt_km, lat_deg=0.0):
    """Relative speed wrt corotating atmosphere for a circular orbit (m/s)."""
    r = R_EARTH + alt_km * 1e3
    v_orb = np.sqrt(MU_EARTH / r)
    v_corot = 2 * np.pi * r * np.cos(np.radians(lat_deg)) / 86164.1  # sidereal day
    return v_orb - v_corot


def cd_sphere_incident(S):
    """Incident-only Sentman sphere C_D at speed ratio S (no re-emission)."""
    term1 = (2.0 * S**2 + 1.0) / (np.sqrt(np.pi) * S**3) * np.exp(-S**2)
    term2 = (4.0 * S**4 + 4.0 * S**2 - 1.0) / (2.0 * S**4) * erf(S)
    return term1 + term2


def cd_sphere_species(V, T_inf, m, alpha):
    """Sentman/DRIA sphere C_D for one species (referenced to projected area)."""
    S = V * np.sqrt(m / (2.0 * KB * T_inf))            # molecular speed ratio
    Tr = (1.0 - alpha) * m * V**2 / (3.0 * KB) + alpha * T_WALL  # DRIA reflected temp
    term3 = (2.0 * np.sqrt(np.pi) / (3.0 * S)) * np.sqrt(Tr / T_inf)
    return cd_sphere_incident(S) + term3


def alpha_sesam(msis_row, V):
    """SESAM energy accommodation for one MSIS row at relative speed V (m/s).

    alpha = (1 - theta) * alpha_clean + theta: atomic-O Langmuir coverage theta,
    Goodman clean-surface alpha_clean on the number-weighted mean mass m_bar over
    SPECIES (anomalous O excluded).
    """
    T_inf = msis_row[IDX['T']]
    n_tot = m_tot = 0.0
    for col, m in SPECIES.values():
        n = msis_row[col]
        if not np.isfinite(n) or n <= 0:
            continue
        n_tot += n
        m_tot += n * m
    m_bar = m_tot / n_tot

    m_O = SPECIES['O'][1]
    n_O = msis_row[IDX['O']]
    if not np.isfinite(n_O) or n_O <= 0:
        n_O = 0.0
    S = V * np.sqrt(m_bar / (2.0 * KB * T_inf))        # bulk speed ratio
    P_O = 0.5 * n_O * m_O * V**2 * cd_sphere_incident(S) / TORR  # torr

    # Sticking probability. The published form's second numerator term
    # kT*exp(-(E_b+E_r)/kT)*(exp(E_b/kT) - zeta) is degenerate in double
    # precision; this is its exact equivalent.
    kT = KB * SESAM_T_AB
    E_r = 0.5 * m_O * V**2
    d = np.sqrt(SESAM_E_B) - np.sqrt(E_r)
    a = np.sqrt(np.pi * kT * E_r)
    e = erf(np.sqrt(E_r / kT))
    s_o = ((a * (erf(d / np.sqrt(kT)) + e)
            + kT * (np.exp(-E_r / kT) - np.exp(-d**2 / kT)))
           / (a * (e + 1.0) + kT * np.exp(-E_r / kT)))

    K_L = s_o * SESAM_K_LO + SESAM_K_LF
    theta = K_L * P_O / (1.0 + K_L * P_O)              # fractional coverage
    mu = m_bar / SESAM_M_S
    alpha_clean = SESAM_K_S * mu / (1.0 + mu)**2
    return (1.0 - theta) * alpha_clean + theta


def cd_total(msis_row, alt_km, lat_deg):
    """Mass-flux-weighted total C_D for a sphere from one MSIS state row."""
    T_inf = msis_row[IDX['T']]
    V = v_rel(alt_km, lat_deg)
    alpha = alpha_sesam(msis_row, V)
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


# ---- validity-domain analysis helpers (addendum Chunk 1) ----
# These move the collapse study off the eyeballed per-altitude plot and onto the
# production axis (geocentric radius) with coded pass/fail thresholds. Shared by
# both experiment drivers so the sphere and box studies stay consistent.


def geocentric_radius(alt_km, lat_deg=0.0):
    """Geocentric radius [m] of a WGS84 geodetic point (geodetic altitude, latitude).

    Forward closed form MIRRORED from scripts/generate_sphere_cd_table.py
    `_geocentric_radius` -- the production axis the shipped table keys on -- so the
    collapse analysis lands on the same axis the runtime uses (addendum sec. 3.6).
    Mirrored, NOT imported (the experiment never imports the package). This is the
    forward direction only; there is deliberately no inverse radius->altitude map
    (the per-substep inverse conversion the runtime correctly avoids).
    """
    e2 = WGS84_F * (2.0 - WGS84_F)
    lat = np.radians(lat_deg)
    alt_m = alt_km * 1.0e3
    sin_lat = np.sin(lat)
    prime_vertical = R_EARTH / np.sqrt(1.0 - e2 * sin_lat * sin_lat)
    x = (prime_vertical + alt_m) * np.cos(lat)
    z = (prime_vertical * (1.0 - e2) + alt_m) * sin_lat
    return np.sqrt(x * x + z * z)


def collapse_rms_by_radius(radius_m, logrho, cd, storm=None,
                           bin_width_km=25.0, min_count=5):
    """Per-radius-bin collapse 'thickness': RMS % scatter about the in-bin surface.

    Bins the samples by geocentric radius (the production axis), fits a cubic in
    *centered* log-density inside each populated bin to remove the genuine density
    slope, and measures the residual -- the epoch-to-epoch C_D spread at matched
    (radius, density), i.e. the thickness of the lookup surface there. Latitudes
    are mixed within a bin on purpose: the collapse claim is that (radius, density)
    fixes C_D regardless of how the sample got there.

    Returns ``(records, all_res, all_storm)`` where ``records`` is a list sorted by
    radius of ``(center_km, count, rms_pct, max_pct, storm_rms_pct)`` (the last is
    NaN if the bin holds no storm samples), and ``all_res`` / ``all_storm`` are the
    pooled residuals and their storm mask (for an overall and storm-only RMS).
    """
    radius_km = np.asarray(radius_m, float) / 1.0e3
    logrho = np.asarray(logrho, float)
    cd = np.asarray(cd, float)
    storm = (np.zeros(len(cd), bool) if storm is None
             else np.asarray(storm, bool))

    edges = np.arange(radius_km.min(), radius_km.max() + bin_width_km, bin_width_km)
    idx = np.digitize(radius_km, edges)
    records, all_res, all_storm = [], [], []
    for b in range(1, len(edges)):
        sel = idx == b
        if sel.sum() < min_count:
            continue
        x = logrho[sel] - logrho[sel].mean()        # center for conditioning
        coef = np.polyfit(x, cd[sel], 3)
        res = (cd[sel] - np.polyval(coef, x)) / cd[sel] * 100.0
        st = storm[sel]
        rms = float(np.sqrt((res ** 2).mean()))
        mx = float(np.abs(res).max())
        storm_rms = float(np.sqrt((res[st] ** 2).mean())) if st.any() else float("nan")
        center = 0.5 * (edges[b - 1] + edges[b])
        records.append((center, int(sel.sum()), rms, mx, storm_rms))
        all_res.append(res)
        all_storm.append(st)
    all_res = np.concatenate(all_res) if all_res else np.array([])
    all_storm = np.concatenate(all_storm) if all_storm else np.array([], bool)
    return records, all_res, all_storm


def band_verdict(rms_pct):
    """Coded acceptance label for a collapse RMS (addendum sec. 3.1)."""
    if rms_pct <= GREEN_RMS_PCT:
        return "PASS"
    if rms_pct >= RED_RMS_PCT:
        return "FAIL"
    return "WARN"


def green_crossing_radius_km(records, threshold=GREEN_RMS_PCT):
    """Lowest bin-center radius [km] whose collapse RMS exceeds the green line,
    scanning upward (the high-altitude cut). ``None`` if no bin crosses -- the cut
    lies above the swept range, so the high limit is non-binding over it."""
    for center, _n, rms, _mx, _srms in records:
        if rms > threshold:
            return center
    return None


def print_collapse_report(records, all_res, all_storm, label=""):
    """Print the per-band pass/fail table + overall/storm RMS + the green crossing."""
    head = f"Collapse thickness vs geocentric radius{(' - ' + label) if label else ''}"
    print(f"\n{head}")
    print(f"  thresholds: green <= {GREEN_RMS_PCT:.0f}% (negligible), "
          f"red >= {RED_RMS_PCT:.0f}% (model breakdown / stop line)")
    print(f"  {'radius':>9s} {'alt~km':>7s} {'n':>5s} {'RMS%':>7s} {'max%':>7s} "
          f"{'storm%':>7s}  verdict")
    for center, n, rms, mx, srms in records:
        srms_s = "   -  " if np.isnan(srms) else f"{srms:6.2f}"
        print(f"  {center:8.1f} {center - R_EARTH / 1e3:7.1f} {n:5d} "
              f"{rms:7.3f} {mx:7.2f} {srms_s:>7s}  [{band_verdict(rms)}]")
    overall = float(np.sqrt((all_res ** 2).mean())) if all_res.size else float("nan")
    storm_overall = (float(np.sqrt((all_res[all_storm] ** 2).mean()))
                     if all_storm.any() else float("nan"))
    print(f"  OVERALL collapse RMS {overall:.3f}%  [{band_verdict(overall)}]")
    if np.isfinite(storm_overall):
        print(f"  STORM-cohort collapse RMS {storm_overall:.3f}%  "
              f"[{band_verdict(storm_overall)}]")
    crossing = green_crossing_radius_km(records)
    if crossing is None:
        print(f"  HIGH-ALTITUDE CUT: none within swept range "
              f"(collapse stays <= green {GREEN_RMS_PCT:.0f}% throughout; "
              f"high limit non-binding here)")
    else:
        print(f"  HIGH-ALTITUDE CUT (green crossing): r ~ {crossing:.0f} km "
              f"(alt ~ {crossing - R_EARTH / 1e3:.0f} km)")
    return overall, storm_overall, crossing


if __name__ == "__main__":
    from pymsis import msis
    # 400 km, solar max
    row = msis.run([np.datetime64('2002-07-01T12:00')], [0.0], [0.0], [400.0],
                   [200.0], [200.0], [[15.0]*7], version=0)[0]
    cd, a = cd_total(row, 400.0, 0.0)
    print(f"400 km solar-max:  rho={row[0]:.3e} kg/m^3  T={row[10]:.0f} K  "
          f"alpha={a:.3f}  V_rel={v_rel(400.):.0f} m/s  ->  C_D = {cd:.3f}")
    # Solar-min comparison at same altitude
    row2 = msis.run([np.datetime64('2008-07-01T12:00')], [0.0], [0.0], [400.0],
                    [70.0], [70.0], [[4.0]*7], version=0)[0]
    cd2, a2 = cd_total(row2, 400.0, 0.0)
    print(f"400 km solar-min:  rho={row2[0]:.3e} kg/m^3  T={row2[10]:.0f} K  "
          f"alpha={a2:.3f}  ->  C_D = {cd2:.3f}")
    # Hyperthermal sanity: large S, full accommodation -> ~2.0 incident
    print(f"Hyperthermal incident-only check (S->inf, alpha=1): "
          f"{cd_sphere_species(7500., 1000., 16*U, 1.0):.3f}")
