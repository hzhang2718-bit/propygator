"""
Validity-domain test for the (geocentric radius, density) -> C_D lookup surface.

This is the boundary-finding successor to the original interior-only collapse
study (addendum Chunk 1). Three changes from the 300-800 km / geodetic-altitude
version it replaces:
  1. A DENSE sweep ~130-1400 km (production axis = geocentric radius), run
     modestly above the ~1200 km table ceiling so the high-altitude degradation
     curve is seen on both sides of the cut (addendum sec. 3.2/3.6).
  2. A deliberate STORM cohort (Ap up to 400, F10.7 up to 320) layered on the
     quiet interior, since that is where drag matters most and the (alt, rho)
     mapping is most stressed (addendum sec. 3.3).
  3. Acceptance thresholds AS CODE -- per-radius-band collapse RMS reported PASS/
     WARN/FAIL against green <= 5% / red >= 30% (addendum sec. 3.1), so locating
     the high-altitude cut is a threshold crossing, not an eyeballed plot.

Procedure:
  1. Build genuinely different atmospheric conditions (date/season, local solar
     time, latitude, F10.7, Ap) -- i.e. different "epochs" -- including a storm
     cohort.
  2. At each altitude, evaluate the DRIA/Sentman C_D under every condition,
     giving a cloud of (radius, density, C_D) points.
  3. If (radius, rho) is a sufficient statistic for C_D, points from different
     epochs collapse onto ONE single-valued surface. The collapse THICKNESS
     (scatter at matched radius, rho) is measured per radius band; where it
     crosses the green line is the (soft, non-binding) high-altitude cut.

Note: this measures only the HIGH-altitude (collapse) limit. The low-altitude
model-validity floor is a separate Knudsen diagnostic (addendum sec. 2/3.4,
Chunk 2) -- the collapse metric is blind to it by construction.
"""
from pathlib import Path

import numpy as np
from pymsis import msis
from scipy.interpolate import LinearNDInterpolator
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
from cd_core import (cd_total, calibrate_K, IDX, R_EARTH, geocentric_radius,
                     collapse_rms_by_radius, print_collapse_report,
                     GREEN_RMS_PCT, RED_RMS_PCT)

rng = np.random.default_rng(7)
K = calibrate_K()

# Dense sweep on the production axis: ~130-1400 km, modestly above the ~1200 km
# table ceiling (addendum sec. 3.2). 80 points keeps each radius bin well populated.
ALTS = np.linspace(130., 1400., 80)  # km

DATES = ["2003-01-15T03:00", "2003-04-10T09:00", "2008-07-21T12:00",
         "2014-10-05T18:00", "2019-12-30T21:00", "2011-06-01T15:00",
         "2000-03-20T06:00", "2016-09-12T00:00"]


# --- build genuinely different epochs / conditions, incl. a storm cohort ---
def make_conditions(n_quiet=55, n_storm=12):
    conds = []
    for _ in range(n_quiet):                      # quiet interior: F10.7<=250, Ap<=80
        conds.append(dict(
            date=np.datetime64(rng.choice(DATES)),
            lon=float(rng.uniform(0, 360)),       # varies local solar time
            lat=float(rng.uniform(-70, 70)),      # varies latitude
            f107=float(rng.uniform(70, 250)),     # solar cycle position
            f107a=float(rng.uniform(70, 250)),
            ap=float(rng.uniform(4, 80)),         # geomagnetic activity
            storm=False,
        ))
    for _ in range(n_storm):                      # storm tail (addendum sec. 3.3)
        conds.append(dict(
            date=np.datetime64(rng.choice(DATES)),
            lon=float(rng.uniform(0, 360)),
            lat=float(rng.uniform(-70, 70)),
            f107=float(rng.uniform(200, 320)),    # elevated solar flux
            f107a=float(rng.uniform(200, 320)),
            ap=float(rng.uniform(100, 400)),      # storm-level geomagnetic activity
            storm=True,
        ))
    return conds


conds = make_conditions()
n_storm = sum(c["storm"] for c in conds)

# --- evaluate C_D over all (condition, altitude); key on geocentric radius ---
rows = []
for ci, c in enumerate(conds):
    for alt in ALTS:
        m = msis.run([c["date"]], [c["lon"]], [c["lat"]], [alt],
                     [c["f107"]], [c["f107a"]], [[c["ap"]]*7], version=0)[0]
        rho = m[IDX["rho"]]
        if not np.isfinite(rho) or rho <= 0:
            continue
        cd, alpha = cd_total(m, alt, c["lat"], K)
        r = float(geocentric_radius(alt, c["lat"]))     # production axis
        rows.append((alt, r, rho, cd, alpha, ci, c["storm"]))

data = np.array([(a, r, rho, cd, al) for (a, r, rho, cd, al, _, _) in rows])
cond_id = np.array([ci for (*_, ci, _) in rows])
storm_flag = np.array([s for (*_, s) in rows], dtype=bool)
alt_arr, r_arr, rho_arr, cd_arr, alpha_arr = data.T
r_km = r_arr / 1e3
logrho = np.log10(rho_arr)
print(f"Generated {len(rows)} points across {len(conds)} epochs "
      f"({n_storm} storm) x {len(ALTS)} altitudes ({ALTS[0]:.0f}-{ALTS[-1]:.0f} km)")
print(f"radius range {r_km.min():.0f}..{r_km.max():.0f} km   "
      f"C_D range {cd_arr.min():.3f}..{cd_arr.max():.3f}   "
      f"alpha range {alpha_arr.min():.3f}..{alpha_arr.max():.3f}")

# === (A) collapse thickness vs geocentric radius, with coded thresholds ===
records, all_res, all_storm = collapse_rms_by_radius(
    r_arr, logrho, cd_arr, storm=storm_flag)
overall_rms, storm_rms, crossing = print_collapse_report(
    records, all_res, all_storm, label="sphere")

# === (B) operational: build table on half the epochs, test on the other half ===
# Train/test split on the radius axis (the production axis), mirroring building
# the table once and reusing it across the mission.
half = len(conds) // 2
train = np.isin(cond_id, np.arange(half))
test = ~train
interp = LinearNDInterpolator(np.c_[r_km[train], logrho[train]], cd_arr[train])
pred = interp(r_km[test], logrho[test])
ok = np.isfinite(pred)
resid = (pred[ok] - cd_arr[test][ok]) / cd_arr[test][ok] * 100
print(f"\n(B) Table built on {half} epochs, applied to {len(conds)-half} held-out epochs:")
print(f"   residual: mean {resid.mean():+.3f}%  RMS {np.sqrt((resid**2).mean()):.3f}%  "
      f"95th |.| {np.percentile(np.abs(resid),95):.2f}%  max|.| {np.abs(resid).max():.3f}%  (n={ok.sum()})")

# === plots ===
fig = plt.figure(figsize=(15, 5))

ax = fig.add_subplot(1, 3, 1, projection="3d")
ax.scatter(r_km, logrho, cd_arr, c=cd_arr, cmap="viridis", s=8)
ax.set_xlabel("geocentric radius [km]"); ax.set_ylabel("log10 density [kg/m3]")
ax.set_zlabel("C_D"); ax.set_title("All epochs collapse onto one surface")
ax.view_init(elev=18, azim=-60)

ax2 = fig.add_subplot(1, 3, 2)
sc = ax2.scatter(logrho, cd_arr, c=r_km, cmap="plasma", s=10)
ax2.scatter(logrho[storm_flag], cd_arr[storm_flag], facecolors="none",
            edgecolors="k", s=22, lw=0.5, label="storm cohort")
ax2.set_xlabel("log10 density [kg/m3]"); ax2.set_ylabel("C_D")
ax2.set_title("C_D vs density, colored by radius")
ax2.legend(fontsize=8, loc="upper right")
plt.colorbar(sc, ax=ax2, label="geocentric radius [km]")

ax3 = fig.add_subplot(1, 3, 3)
centers = [rec[0] for rec in records]
rmss = [rec[2] for rec in records]
ax3.plot(centers, rmss, "-o", color="crimson", ms=3, label="collapse RMS")
ax3.axhline(GREEN_RMS_PCT, color="green", ls="--", lw=1, label=f"green {GREEN_RMS_PCT:.0f}%")
ax3.axhline(RED_RMS_PCT, color="red", ls="--", lw=1, label=f"red {RED_RMS_PCT:.0f}%")
if crossing is not None:
    ax3.axvline(crossing, color="green", ls=":", lw=1)
ax3.set_yscale("log")
ax3.set_xlabel("geocentric radius [km]"); ax3.set_ylabel("collapse RMS [%]")
ax3.set_title(f"Collapse thickness vs radius (overall {overall_rms:.2f}%)")
ax3.legend(fontsize=8)

plt.tight_layout()
plt.savefig(Path(__file__).with_name("cd_time_independence.png"), dpi=130)
print("\nSaved figure.")
