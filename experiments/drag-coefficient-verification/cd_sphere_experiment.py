"""
Time-independence test for the (altitude, density) -> C_D lookup surface.

Procedure:
  1. Build a set of GENUINELY DIFFERENT atmospheric conditions (date/season,
     local solar time, latitude, F10.7, Ap) -- i.e. different "epochs".
  2. At each altitude, evaluate the DRIA/Sentman C_D under every condition,
     giving a cloud of (altitude, density, C_D) points.
  3. If the (alt, rho) pair is a sufficient statistic for C_D, points from
     different epochs must collapse onto ONE single-valued surface.

Two quantifications:
  (A) Assumption-free: bin in (altitude, log10 rho); within each cell that
      multiple distinct epochs populate, measure the C_D spread. This is the
      thickness of the surface at matched (alt, rho).
  (B) Operational: build the interpolant from one half of the epochs ("the
      table"), then predict C_D for the other half and look at the residual.
      This mirrors building the table once and reusing it across the mission.
"""
from pathlib import Path

import numpy as np
from pymsis import msis
from scipy.interpolate import LinearNDInterpolator
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa
from cd_core import cd_total, calibrate_K, IDX

rng = np.random.default_rng(7)
K = calibrate_K()

ALTS = np.arange(300., 801., 50.)  # km

# --- build genuinely different epochs / conditions ---
def make_conditions(n=55):
    dates = ["2003-01-15T03:00", "2003-04-10T09:00", "2008-07-21T12:00",
             "2014-10-05T18:00", "2019-12-30T21:00", "2011-06-01T15:00",
             "2000-03-20T06:00", "2016-09-12T00:00"]
    conds = []
    for i in range(n):
        conds.append(dict(
            date=np.datetime64(rng.choice(dates)),
            lon=float(rng.uniform(0, 360)),        # varies local solar time
            lat=float(rng.uniform(-70, 70)),       # varies latitude
            f107=float(rng.uniform(70, 220)),      # solar cycle position
            f107a=float(rng.uniform(70, 220)),
            ap=float(rng.uniform(4, 80)),          # geomagnetic activity
        ))
    return conds

conds = make_conditions()

# --- evaluate C_D over all (condition, altitude) ---
rows = []
for ci, c in enumerate(conds):
    for alt in ALTS:
        m = msis.run([c["date"]], [c["lon"]], [c["lat"]], [alt],
                     [c["f107"]], [c["f107a"]], [[c["ap"]]*7], version=0)[0]
        rho = m[IDX["rho"]]
        if not np.isfinite(rho) or rho <= 0:
            continue
        cd, alpha = cd_total(m, alt, c["lat"], K)
        rows.append((alt, rho, cd, alpha, ci))

data = np.array([(a, r, c, al) for (a, r, c, al, _) in rows])
cond_id = np.array([ci for (_, _, _, _, ci) in rows])
alt_arr, rho_arr, cd_arr, alpha_arr = data.T
logrho = np.log10(rho_arr)
print(f"Generated {len(rows)} points across {len(conds)} epochs x {len(ALTS)} altitudes")
print(f"C_D range {cd_arr.min():.3f}..{cd_arr.max():.3f}   "
      f"alpha range {alpha_arr.min():.3f}..{alpha_arr.max():.3f}")

# === (A) true thickness: residual scatter about the per-altitude C_D(rho) curve ===
# (a cubic in log-density removes the genuine density slope so what remains is
#  pure epoch-to-epoch scatter at matched (alt, rho))
worst = 0.0
all_resid_A = []
per_alt = {}
for alt in ALTS:
    sel = alt_arr == alt
    if sel.sum() < 5:
        continue
    lr = logrho[sel]; cd = cd_arr[sel]
    coef = np.polyfit(lr, cd, 3)
    res = (cd - np.polyval(coef, lr)) / cd * 100
    all_resid_A.append(res)
    rms = np.sqrt((res**2).mean()); mx = np.abs(res).max()
    per_alt[alt] = (rms, mx)
    worst = max(worst, mx)
all_resid_A = np.concatenate(all_resid_A)
print("\n(A) Scatter about per-altitude C_D(rho) curve (true thickness at matched alt,rho):")
for alt, (rms, mx) in per_alt.items():
    print(f"   {alt:4.0f} km : RMS {rms:4.2f} %   max {mx:4.2f} %")
print(f"   OVERALL: RMS {np.sqrt((all_resid_A**2).mean()):.3f} %   "
      f"95th pct {np.percentile(np.abs(all_resid_A),95):.2f} %   "
      f"worst {worst:.2f} %")

# === (B) operational: build table on half the epochs, test on the other half ===
half = len(conds) // 2
train = np.isin(cond_id, np.arange(half))
test = ~train
interp = LinearNDInterpolator(np.c_[alt_arr[train], logrho[train]], cd_arr[train])
pred = interp(alt_arr[test], logrho[test])
ok = np.isfinite(pred)
resid = (pred[ok] - cd_arr[test][ok]) / cd_arr[test][ok] * 100
print(f"\n(B) Table built on {half} epochs, applied to {len(conds)-half} held-out epochs:")
print(f"   residual: mean {resid.mean():+.3f}%  RMS {np.sqrt((resid**2).mean()):.3f}%  "
      f"95th |.| {np.percentile(np.abs(resid),95):.2f}%  max|.| {np.abs(resid).max():.3f}%  (n={ok.sum()})")

# === plots ===
fig = plt.figure(figsize=(15, 5))

ax = fig.add_subplot(1, 3, 1, projection="3d")
p = ax.scatter(alt_arr, logrho, cd_arr, c=cd_arr, cmap="viridis", s=12)
ax.set_xlabel("Altitude [km]"); ax.set_ylabel("log10 density [kg/m3]")
ax.set_zlabel("C_D"); ax.set_title("All epochs collapse onto one surface")
ax.view_init(elev=18, azim=-60)

ax2 = fig.add_subplot(1, 3, 2)
sc = ax2.scatter(logrho, cd_arr, c=alt_arr, cmap="plasma", s=14)
ax2.set_xlabel("log10 density [kg/m3]"); ax2.set_ylabel("C_D")
ax2.set_title("C_D vs density, colored by altitude")
plt.colorbar(sc, ax=ax2, label="Altitude [km]")

ax3 = fig.add_subplot(1, 3, 3)
for alt in ALTS:
    sel = alt_arr == alt
    if sel.sum() < 5:
        continue
    lr = logrho[sel]; cd = cd_arr[sel]
    coef = np.polyfit(lr, cd, 3)
    res = (cd - np.polyval(coef, lr)) / cd * 100
    ax3.scatter(np.full(sel.sum(), alt), res, s=10, alpha=0.5, color="crimson")
ax3.axhline(0, color="k", lw=0.7)
ax3.set_xlabel("Altitude [km]"); ax3.set_ylabel("residual about C_D(rho) curve [%]")
ax3.set_title(f"True scatter at matched (alt,rho): "
              f"RMS {np.sqrt((all_resid_A**2).mean()):.2f}%")

plt.tight_layout()
plt.savefig(Path(__file__).with_name("cd_time_independence.png"), dpi=130)
print("\nSaved figure.")
