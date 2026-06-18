"""
Tier B validity-domain test: does C_D collapse onto a single (geocentric radius,
rho) surface AT FIXED ATTITUDE, across epochs and out to the table edges?
Attitude = ram direction in body frame. Tested for a cube and a thin plate (sail)
over head-on -> grazing.

Boundary-finding successor to the interior-only version (addendum Chunk 1), with
the same three changes as the sphere driver: a dense ~130-1400 km sweep keyed on
geocentric radius (sec. 3.2/3.6), a storm cohort (sec. 3.3), and per-radius-band
collapse RMS reported PASS/WARN/FAIL against green 5% / red 30% (sec. 3.1) per
attitude.
"""
from pathlib import Path

import numpy as np
from pymsis import msis
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cd_core import (calibrate_K, alpha_sesam, v_rel, SPECIES, IDX, R_EARTH,
                     geocentric_radius, collapse_rms_by_radius,
                     band_verdict, green_crossing_radius_km,
                     GREEN_RMS_PCT, RED_RMS_PCT)
from cd_box import cd_panel_species

rng = np.random.default_rng(11)
K = calibrate_K()
ALTS = np.linspace(130., 1400., 80)  # km; dense sweep on the production axis (sec. 3.2)

DATES = ["2003-01-15T03:00", "2008-07-21T12:00", "2014-10-05T18:00",
         "2019-12-30T21:00", "2011-06-01T15:00", "2000-03-20T06:00"]

# --- geometries: list of (normal, area); reference area = one face ---
X, Y, Z = np.eye(3)
CUBE = ([(X, 1.), (-X, 1.), (Y, 1.), (-Y, 1.), (Z, 1.), (-Z, 1.)], 1.0)
PLATE = ([(X, 1.), (-X, 1.)], 1.0)  # thin flat plate, normal +/- x


def ram(theta_deg, axis2=Z):
    """Ram unit vector at angle theta from +x, rotated toward axis2."""
    t = np.radians(theta_deg)
    return np.cos(t) * X + np.sin(t) * axis2


# attitudes to test: (label, geometry, ram_hat)
ATT = [
    ("cube head-on (0deg)",   CUBE,  X),
    ("cube edge-on (45deg)",  CUBE,  (X + Z) / np.sqrt(2)),
    ("cube corner-on",        CUBE,  (X + Y + Z) / np.sqrt(3)),
    ("plate face-on (0deg)",  PLATE, X),
    ("plate 60deg",           PLATE, ram(60)),
    ("plate 80deg grazing",   PLATE, ram(80)),
]


def box_cd(row, alt, lat, faces, A_ref, ram_hat):
    T_inf = row[IDX["T"]]; V = v_rel(alt, lat)
    alpha = alpha_sesam(row[IDX["O"]], T_inf, K)
    total = 0.0
    for n_hat, area in faces:
        g = float(np.dot(n_hat, ram_hat))
        num = den = 0.0
        for col, m in SPECIES.values():
            n = row[col]
            if not np.isfinite(n) or n <= 0:
                continue
            rho_s = n * m
            num += rho_s * cd_panel_species(g, V, T_inf, m, alpha)
            den += rho_s
        total += (num / den) * area / A_ref
    return total


# --- build conditions incl. a storm cohort (addendum sec. 3.3) ---
def make_conditions(n_quiet=40, n_storm=10):
    conds = []
    for _ in range(n_quiet):
        conds.append(dict(date=np.datetime64(rng.choice(DATES)), lon=rng.uniform(0, 360),
                          lat=rng.uniform(-70, 70), f107=rng.uniform(70, 250),
                          f107a=rng.uniform(70, 250), ap=rng.uniform(4, 80), storm=False))
    for _ in range(n_storm):
        conds.append(dict(date=np.datetime64(rng.choice(DATES)), lon=rng.uniform(0, 360),
                          lat=rng.uniform(-70, 70), f107=rng.uniform(200, 320),
                          f107a=rng.uniform(200, 320), ap=rng.uniform(100, 400), storm=True))
    return conds


conds = make_conditions()
n_storm = sum(c["storm"] for c in conds)

# --- sweep epochs x altitudes; evaluate every attitude from each MSIS state ---
store = {lab: {"r": [], "rho": [], "cd": [], "storm": []} for lab, _, _ in ATT}
for c in conds:
    for alt in ALTS:
        row = msis.run([c["date"]], [c["lon"]], [c["lat"]], [alt],
                       [c["f107"]], [c["f107a"]], [[c["ap"]]*7], version=0)[0]
        rho = row[IDX["rho"]]
        if not np.isfinite(rho) or rho <= 0:
            continue
        r = float(geocentric_radius(alt, c["lat"]))
        for lab, (faces, Aref), rh in ATT:
            store[lab]["r"].append(r)
            store[lab]["rho"].append(rho)
            store[lab]["cd"].append(box_cd(row, alt, c["lat"], faces, Aref, rh))
            store[lab]["storm"].append(c["storm"])

print(f"Generated {len(conds)} epochs ({n_storm} storm) x {len(ALTS)} altitudes "
      f"({ALTS[0]:.0f}-{ALTS[-1]:.0f} km) per attitude")
print(f"thresholds: green <= {GREEN_RMS_PCT:.0f}% / red >= {RED_RMS_PCT:.0f}% "
      f"(collapse thickness on the geocentric-radius axis)\n")
print(f"{'attitude':24s} {'mean C_D':>9s} {'RMS%':>8s} {'storm%':>8s} {'max%':>7s} "
      f"{'cut(km)':>9s}  verdict")
summ = []
for lab, _, _ in ATT:
    d = store[lab]
    records, all_res, all_storm = collapse_rms_by_radius(
        d["r"], np.log10(d["rho"]), d["cd"], storm=d["storm"])
    rms = float(np.sqrt((all_res ** 2).mean())) if all_res.size else float("nan")
    storm_rms = (float(np.sqrt((all_res[all_storm] ** 2).mean()))
                 if all_storm.any() else float("nan"))
    mx = float(np.abs(all_res).max()) if all_res.size else float("nan")
    crossing = green_crossing_radius_km(records)
    cut_s = "  none  " if crossing is None else f"{crossing:7.0f}"
    summ.append((lab, rms, mx, records))
    print(f"{lab:24s} {np.mean(d['cd']):9.3f} {rms:8.3f} {storm_rms:8.3f} {mx:7.2f} "
          f"{cut_s:>9s}  [{band_verdict(rms)}]")

# --- plots ---
fig = plt.figure(figsize=(15, 4.5))

ax1 = fig.add_subplot(1, 3, 1)
labels = [s[0] for s in summ]
ax1.bar(range(len(summ)), [s[1] for s in summ], color="steelblue")
ax1.set_xticks(range(len(summ)))
ax1.set_xticklabels(labels, fontsize=7, rotation=30, ha="right")
ax1.set_ylabel("collapse RMS at matched (radius, rho) [%]")
ax1.set_title("Validity-domain thickness per attitude")
ax1.axhline(GREEN_RMS_PCT, color="green", ls="--", lw=1, label=f"green {GREEN_RMS_PCT:.0f}%")
ax1.legend(fontsize=8)

ax2 = fig.add_subplot(1, 3, 2)
d = store["plate 80deg grazing"]
r_km = np.array(d["r"]) / 1e3
sc = ax2.scatter(np.log10(d["rho"]), d["cd"], c=r_km, cmap="plasma", s=10)
ax2.set_xlabel("log10 density"); ax2.set_ylabel("C_D")
ax2.set_title("Worst case (plate 80deg): still collapses")
plt.colorbar(sc, ax=ax2, label="geocentric radius [km]")

# C_D vs incidence at fixed (alt,rho), for 3 different epochs -> they agree
ax3 = fig.add_subplot(1, 3, 3)
angles = np.linspace(0, 85, 30)
epset = [("2008-07-21T12:00", 90., 1.), ("2019-12-30T21:00", 200., 40.),
         ("2011-06-01T15:00", 150., 20.)]
for dt, f107, ap in epset:
    row = msis.run([np.datetime64(dt)], [10.], [0.], [450.], [f107], [f107], [[ap]*7], version=0)[0]
    cds = [box_cd(row, 450., 0., *PLATE, ram(th)) for th in angles]
    ax3.plot(angles, cds, label=f"F10.7={f107:.0f}, Ap={ap:.0f}")
ax3.set_xlabel("incidence from normal [deg]"); ax3.set_ylabel("plate C_D (ref face area)")
ax3.set_title("Attitude dependence at 450 km (3 epochs)")
ax3.legend(fontsize=8)

plt.tight_layout()
plt.savefig(Path(__file__).with_name("cd_tierB.png"), dpi=130)
print("\nSaved figure.")
