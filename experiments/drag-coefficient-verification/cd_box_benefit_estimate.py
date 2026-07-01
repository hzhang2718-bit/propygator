"""
Tier B (BoxFaceCd) cheap benefit estimate (build-plan Chunk 1, contract:
general-upgrades-1.md "Tier B Drag" -> Evidence pipeline 4, reduced to a
kernel-only estimate). Feeds GO/NO-GO Checkpoint A.

Question (the ship-or-drop gate, made cheap): for a representative Sun-pointing
LEO sail, does the per-face BoxFaceCd drag differ from Tier A in a way that a
single best-fit constant Cd cannot absorb? If a recalibrated scalar soaks up the
divergence, BoxFaceCd is not worth shipping; if a coherent, attitude-correlated
residual survives recalibration, it is.

Method (NO Orekit, NO integrator -- pure kinematics + the cd_box kernel):
  * Build a circular Kepler LEO orbit and a low-precision analytic Sun direction
    over a multi-day window. Sun-pointing attitude: the sail's large face normal
    tracks the Sun, so the face-flow angle theta sweeps the full [0, pi] as the
    satellite orbits, with the sweep set by the beta angle (Sun vs orbit plane).
  * At each sample form the per-face truth CdA_BoxFace(t) = sum_i Cd_i(theta_i)*A_i
    over ALL faces, and the Tier-A shape A_proj(t) = sum_i max(0, cos theta_i)*A_i
    (Orekit windward projected area). Density rho(t) and composition come from
    NRLMSISE-00 at the sub-satellite (lat, local-time), so the drag-work weight
    w(t) = rho * v_rel^3 is realistic.
  * Best-fit the Tier-A scalar c_star (work-weighted least squares) so Tier A =
    c_star * A_proj(t). The residual r(t) = CdA_BoxFace - c_star*A_proj is the
    part no constant Cd can represent. Report its work-weighted RMS as a % of the
    mean drag area, AND a secular along-track proxy (does the residual accumulate,
    or average to zero?). Swept over a few beta angles, since beta governs how
    much of the [0, pi] incidence range the sail sees.

The residual % is per-unit-area (independent of the exact sail size / mass): only
the orbit + Sun attitude sweep sets it. Sail size, mass, and altitude only scale
the absolute along-track-km proxy.

Reference-only: not shipped, not in CI. ASCII-only stdout (cp1252 redirect). Run
from this directory in the throwaway venv:
    python cd_box_benefit_estimate.py > cd_box_benefit_estimate_results.txt
"""
from pathlib import Path

import numpy as np
from pymsis import msis
from scipy.integrate import cumulative_trapezoid
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cd_core import IDX, MU_EARTH, R_EARTH, alpha_sesam, calibrate_K, v_rel
from cd_box_faces import face_cd

K = calibrate_K()

# ---------------------------------------------------------------------------
# Representative scenario (the maintainer-confirmed sail; build-plan "You
# provide"). The residual % verdict is per-unit-area and independent of A_FACE /
# MASS_KG; those + ALT_KM only scale the absolute along-track proxy.
# ---------------------------------------------------------------------------
EPOCH = np.datetime64("2002-07-01T00:00")  # solar max
ALT_KM = 450.0                              # circular
INC_DEG = 51.6                              # ISS-like
A_FACE = 16.0                               # m^2 per sail face (4 m x 4 m)
MASS_KG = 12.0                              # A/m ~ 1.33 m^2/kg (drag sail)
F107 = 180.0
AP = 15.0
WINDOW_DAYS = 2.0
DT_S = 120.0                                # sample step
TARGET_BETAS = [5.0, 30.0, 60.0]           # deg; realized values reported
C_NOMINAL = 2.2                             # textbook flat-plate scalar Cd, for
#                                            the "no recalibration" baseline

# Thin flat sail: two faces +/- n_sail, full area A_FACE each. The four edges
# have ~zero area for a thin plate, so they are omitted here (their shear matters
# for a near-cubic bus, a separate Chunk-5 regression, not the sail benefit).


def jd_of(dt64):
    """Julian Date of a numpy datetime64 (UT ~ UTC for this purpose)."""
    return 2440587.5 + (dt64 - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "D")


def sun_eci_hat(jd):
    """Low-precision Sun unit vector in ECI (mean equator/equinox of date),
    good to ~0.01 deg (Vallado / Montenbruck). Enough for the attitude geometry
    and MSIS local-time."""
    T = (jd - 2451545.0) / 36525.0
    L = np.radians((280.460 + 36000.771 * T) % 360.0)        # mean longitude
    M = np.radians((357.5291 + 35999.0503 * T) % 360.0)      # mean anomaly
    lam = L + np.radians(1.914666 * np.sin(M) + 0.019994 * np.sin(2 * M))  # ecliptic lon
    eps = np.radians(23.439291 - 0.0130042 * T)              # obliquity
    return np.array([np.cos(lam), np.cos(eps) * np.sin(lam), np.sin(eps) * np.sin(lam)])


def gmst_rad(jd):
    """Greenwich mean sidereal time [rad] (IAU-82), for sub-satellite longitude."""
    T = (jd - 2451545.0) / 36525.0
    sec = (67310.54841 + (876600.0 * 3600.0 + 8640184.812866) * T
           + 0.093104 * T ** 2 - 6.2e-6 * T ** 3)
    return np.radians((sec % 86400.0) / 240.0)


def orbit_normal(raan, inc):
    """Orbit angular-momentum unit vector for (RAAN, inclination) [rad]."""
    return np.array([np.sin(inc) * np.sin(raan),
                     -np.sin(inc) * np.cos(raan),
                     np.cos(inc)])


def perifocal_to_eci(raan, inc):
    """R3(RAAN) @ R1(inc) (argument of perigee = 0; circular orbit)."""
    cO, sO = np.cos(raan), np.sin(raan)
    ci, si = np.cos(inc), np.sin(inc)
    R3 = np.array([[cO, -sO, 0.0], [sO, cO, 0.0], [0.0, 0.0, 1.0]])
    R1 = np.array([[1.0, 0.0, 0.0], [0.0, ci, -si], [0.0, si, ci]])
    return R3 @ R1


def choose_raan_for_beta(target_beta_deg, inc, sun_hat):
    """RAAN [rad] whose orbit plane gives a beta angle closest to the target
    against the (fixed-at-epoch) Sun. beta = arcsin(sun_hat . orbit_normal)."""
    raans = np.linspace(0.0, 2 * np.pi, 721)
    betas = np.degrees(np.arcsin(np.clip(
        [float(np.dot(sun_hat, orbit_normal(O, inc))) for O in raans], -1.0, 1.0)))
    j = int(np.argmin(np.abs(betas - target_beta_deg)))
    return raans[j], betas[j]


def run_beta(target_beta_deg, inc, a, n_mean, times, jds, sun_hats):
    """Build the time series for one target beta; return a dict of arrays + the
    realized beta."""
    raan, beta = choose_raan_for_beta(target_beta_deg, inc, sun_hats[0])
    M = perifocal_to_eci(raan, inc)

    nu = n_mean * times                       # true anomaly (circular)
    # Perifocal position / velocity, rotated to ECI (columns are samples).
    r_pf = a * np.vstack([np.cos(nu), np.sin(nu), np.zeros_like(nu)])
    v_pf = a * n_mean * np.vstack([-np.sin(nu), np.cos(nu), np.zeros_like(nu)])
    r_eci = M @ r_pf
    v_eci = M @ v_pf

    flow_hat = v_eci / np.linalg.norm(v_eci, axis=0)   # +v_hat = ram direction
    n_norm = np.linalg.norm(r_eci, axis=0)
    lat = np.degrees(np.arcsin(r_eci[2] / n_norm))
    lon = np.degrees(np.arctan2(r_eci[1], r_eci[0]) - gmst_rad(jds))
    lon = (lon + 180.0) % 360.0 - 180.0

    nsamp = times.size
    cda_bf = np.empty(nsamp)
    a_proj = np.empty(nsamp)
    rho = np.empty(nsamp)
    vrel = np.empty(nsamp)
    for i in range(nsamp):
        # Sun-pointing sail: large face normal tracks the Sun.
        n_sail = sun_hats[i]
        c_plus = float(np.dot(n_sail, flow_hat[:, i]))
        th_plus = float(np.arccos(np.clip(c_plus, -1.0, 1.0)))
        th_minus = np.pi - th_plus
        # MSIS state at the sub-satellite point.
        date = EPOCH + np.timedelta64(int(round(times[i])), "s")
        row = np.asarray(
            msis.run([date], [lon[i]], [lat[i]], [ALT_KM], [F107], [F107],
                     [[AP] * 7], version=0)
        ).reshape(-1, 11)[0]
        rho[i] = row[IDX["rho"]]
        V = v_rel(ALT_KM, lat[i])
        vrel[i] = V
        alpha = alpha_sesam(row[IDX["O"]], row[IDX["T"]], K)
        T_inf = row[IDX["T"]]
        cda_bf[i] = A_FACE * (face_cd(th_plus, row, V, T_inf, alpha)
                              + face_cd(th_minus, row, V, T_inf, alpha))
        # Tier-A windward projected area (one face is always windward).
        a_proj[i] = A_FACE * (max(0.0, c_plus) + max(0.0, -c_plus))

    w = rho * vrel ** 3                        # drag-work weight
    return dict(beta=beta, raan=raan, times=times, lat=lat, lon=lon,
                cda_bf=cda_bf, a_proj=a_proj, rho=rho, vrel=vrel, w=w)


def fit_and_metrics(res):
    """Work-weighted best-fit scalar c_star and residual diagnostics."""
    w, bf, ap = res["w"], res["cda_bf"], res["a_proj"]
    # c_star = argmin sum w (bf - c*ap)^2.
    c_star = float(np.sum(w * bf * ap) / np.sum(w * ap ** 2))
    resid = bf - c_star * ap
    mean_bf = float(np.sum(w * bf) / np.sum(w))                 # weighted mean drag area
    rms_resid = float(np.sqrt(np.sum(w * resid ** 2) / np.sum(w)))
    pct = 100.0 * rms_resid / mean_bf

    # Rough KINEMATIC along-track proxy: double-integrate the drag-accel difference
    # delta_a(t) = 0.5/m * (bf - c*ap) * rho * vrel^2 over the window. It is only an
    # order-of-magnitude SCALE, not the true secular effect (which is dominated by the
    # induced semi-major-axis change, ~3x): a constant accel offset -> quadratic-in-time
    # drift, and even a zero-MEAN periodic residual leaves a drift linear in the window
    # unless its velocity integral is also zero-mean. So read ds_* alongside the
    # work-weighted resid % (the robust signal); the maintainer makes the GO/NO-GO call.
    t = res["times"]
    da_recal = 0.5 / MASS_KG * resid * res["rho"] * res["vrel"] ** 2
    da_nominal = 0.5 / MASS_KG * (bf - C_NOMINAL * ap) * res["rho"] * res["vrel"] ** 2
    ds_recal = _double_integral(da_recal, t)
    ds_nominal = _double_integral(da_nominal, t)
    # Reference: along-track distance the (recalibrated) Tier-A drag itself
    # removes over the window, same double integral, for scale.
    da_ref = 0.5 / MASS_KG * (c_star * ap) * res["rho"] * res["vrel"] ** 2
    ds_ref = _double_integral(da_ref, t)
    return dict(c_star=c_star, resid=resid, mean_bf=mean_bf, rms_resid=rms_resid,
                pct=pct, ds_recal=ds_recal, ds_nominal=ds_nominal, ds_ref=ds_ref)


def _double_integral(accel, t):
    """Net along-track position offset [m] from an along-track accel a(t)."""
    vel = cumulative_trapezoid(accel, t, initial=0.0)
    pos = cumulative_trapezoid(vel, t, initial=0.0)
    return float(pos[-1])


def main():
    a = R_EARTH + ALT_KM * 1e3
    n_mean = np.sqrt(MU_EARTH / a ** 3)
    period_min = 2 * np.pi / n_mean / 60.0
    inc = np.radians(INC_DEG)
    times = np.arange(0.0, WINDOW_DAYS * 86400.0, DT_S)
    jds = jd_of(EPOCH) + times / 86400.0
    sun_hats = np.array([sun_eci_hat(jd) for jd in jds])

    print("=" * 72)
    print("TIER B BENEFIT ESTIMATE (BoxFaceCd vs best-fit Tier-A scalar)")
    print("=" * 72)
    print(f"Sail: flat {np.sqrt(A_FACE):.1f} m x {np.sqrt(A_FACE):.1f} m "
          f"({A_FACE:.0f} m^2/face), m={MASS_KG:.0f} kg, A/m={A_FACE/MASS_KG:.2f} m^2/kg")
    print(f"Orbit: {ALT_KM:.0f} km circular, inc {INC_DEG:.1f} deg, "
          f"period {period_min:.1f} min, {WINDOW_DAYS:.0f}-day window, dt={DT_S:.0f} s")
    print(f"Epoch {str(EPOCH)} (solar max, F10.7={F107:.0f}, Ap={AP:.0f}), "
          f"{times.size} samples/beta")
    # Sun ephemeris sanity (obliquity ~23.4 deg, |s|=1, ~1 deg/day motion).
    s0, s1 = sun_hats[0], sun_hats[-1]
    drift = np.degrees(np.arccos(np.clip(float(np.dot(s0, s1)), -1, 1)))
    dec0 = np.degrees(np.arcsin(s0[2]))
    print(f"Sun sanity: |s|={np.linalg.norm(s0):.4f}, declination {dec0:+.2f} deg, "
          f"drift over window {drift:.2f} deg ({drift/WINDOW_DAYS:.2f} deg/day)")
    print()

    print(f"  {'beta':>6s} {'c_star':>8s} {'resid %':>9s} {'ds_recal':>11s} "
          f"{'ds_nominal':>12s} {'ds_ref(TierA)':>14s}")
    summary = []
    for tb in TARGET_BETAS:
        res = run_beta(tb, inc, a, n_mean, times, jds, sun_hats)
        m = fit_and_metrics(res)
        print(f"  {res['beta']:5.1f}d {m['c_star']:8.3f} {m['pct']:8.3f}% "
              f"{m['ds_recal']:10.2f}m {m['ds_nominal']:11.2f}m {m['ds_ref']:13.2f}m")
        summary.append((res, m))
    print()
    print("resid %   = work-weighted RMS of (CdA_BoxFace - c_star*A_proj) as a %")
    print("            of mean drag area: the fraction NO constant Cd absorbs.")
    print("ds_recal  = net along-track offset [m] over the window from the")
    print("            recalibrated residual (the part that survives best-fit).")
    print("ds_nominal= same, vs an un-recalibrated nominal Cd=2.2 (for contrast).")
    print("ds_ref    = along-track distance the Tier-A drag itself removes (scale).")
    print()

    # Headline reading (the maintainer makes the actual GO/NO-GO call).
    worst = max(summary, key=lambda sm: sm[1]["pct"])
    worst_pct = worst[1]["pct"]
    worst_frac = abs(worst[1]["ds_recal"]) / abs(worst[1]["ds_ref"]) * 100.0
    print(f"Worst-case surviving residual: {worst_pct:.2f}% of mean drag at "
          f"beta={worst[0]['beta']:.1f} deg,")
    print(f"  along-track {worst[1]['ds_recal']:.1f} m over {WINDOW_DAYS:.0f} days "
          f"= {worst_frac:.2f}% of the Tier-A along-track drag effect.")
    print("Heuristic reading (NOT the decision -- Checkpoint A is the maintainer's):")
    print("  >~ a few % surviving residual that is COHERENT (accumulates secularly,")
    print("  not zero-mean) => MATERIAL => GO signal; clearly immaterial => DROP.")
    print()

    # --- figure ---
    fig = plt.figure(figsize=(15, 4.5))
    rich = min(summary, key=lambda sm: sm[0]["beta"])  # lowest beta = richest sweep
    res, m = rich
    norb = int(np.ceil(2 * period_min * 60.0 / DT_S))  # ~2 orbits to show the sweep
    hrs = res["times"][:norb] / 3600.0

    ax1 = fig.add_subplot(1, 3, 1)
    ax1.plot(hrs, res["cda_bf"][:norb], "-", color="navy", lw=1.5, label="BoxFace CdA")
    ax1.plot(hrs, m["c_star"] * res["a_proj"][:norb], "--", color="crimson", lw=1.5,
             label=f"Tier A (c*={m['c_star']:.2f})")
    ax1.set_xlabel("time [h]"); ax1.set_ylabel("CdA [m^2]")
    ax1.set_title(f"Drag area, beta={res['beta']:.0f} deg (~2 orbits)")
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(1, 3, 2)
    ax2.plot(hrs, m["resid"][:norb], "-", color="seagreen", lw=1.4)
    ax2.axhline(0.0, color="gray", ls=":", lw=1)
    ax2.set_xlabel("time [h]"); ax2.set_ylabel("residual CdA [m^2]")
    ax2.set_title("Residual after best-fit scalar (coherent?)")

    ax3 = fig.add_subplot(1, 3, 3)
    betas = [s[0]["beta"] for s in summary]
    pcts = [s[1]["pct"] for s in summary]
    ax3.bar(range(len(betas)), pcts, color="steelblue")
    ax3.set_xticks(range(len(betas)))
    ax3.set_xticklabels([f"{b:.0f}d" for b in betas])
    ax3.set_xlabel("beta angle")
    ax3.set_ylabel("surviving residual [% of mean drag]")
    ax3.set_title("Un-absorbable residual vs beta")

    plt.tight_layout()
    out = Path(__file__).with_name("cd_box_benefit_estimate.png")
    plt.savefig(out, dpi=130)
    print(f"Saved figure: {out.name}")


if __name__ == "__main__":
    main()
