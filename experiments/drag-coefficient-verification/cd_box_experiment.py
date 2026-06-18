"""
Tier B time-independence test: does C_D collapse onto a single (alt, rho)
surface AT FIXED ATTITUDE, across epochs? Attitude = ram direction in body
frame. Tested for a cube and a thin plate (sail) over head-on -> grazing.
"""
from pathlib import Path

import numpy as np
from pymsis import msis
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from cd_core import calibrate_K, alpha_sesam, v_rel, SPECIES, IDX
from cd_box import cd_panel_species

rng = np.random.default_rng(11)
K = calibrate_K()
ALTS = np.arange(300., 801., 50.)

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

# --- sweep epochs x altitudes; evaluate every attitude from each MSIS state ---
dates = ["2003-01-15T03:00","2008-07-21T12:00","2014-10-05T18:00",
         "2019-12-30T21:00","2011-06-01T15:00","2000-03-20T06:00"]
N = 45
store = {lab: {"alt": [], "rho": [], "cd": []} for lab, _, _ in ATT}
for _ in range(N):
    c = dict(date=np.datetime64(rng.choice(dates)), lon=rng.uniform(0,360),
             lat=rng.uniform(-70,70), f107=rng.uniform(70,220),
             f107a=rng.uniform(70,220), ap=rng.uniform(4,80))
    for alt in ALTS:
        row = msis.run([c["date"]],[c["lon"]],[c["lat"]],[alt],
                       [c["f107"]],[c["f107a"]],[[c["ap"]]*7], version=0)[0]
        rho = row[IDX["rho"]]
        if not np.isfinite(rho) or rho <= 0:
            continue
        for lab, (faces, Aref), rh in ATT:
            store[lab]["alt"].append(alt)
            store[lab]["rho"].append(rho)
            store[lab]["cd"].append(box_cd(row, alt, c["lat"], faces, Aref, rh))

def thickness(alt, rho, cd):
    """RMS % scatter about per-altitude cubic C_D(log rho) curve."""
    alt = np.array(alt); rho = np.array(rho); cd = np.array(cd)
    lr = np.log10(rho); res = []
    for a in np.unique(alt):
        s = alt == a
        if s.sum() < 5:
            continue
        x = lr[s] - lr[s].mean()          # center for conditioning
        coef = np.polyfit(x, cd[s], 3)
        res.append((cd[s] - np.polyval(coef, x)) / cd[s] * 100)
    res = np.concatenate(res)
    return np.sqrt((res**2).mean()), np.abs(res).max(), cd.min(), cd.max()

print(f"{'attitude':24s} {'mean C_D':>9s} {'thick RMS%':>11s} {'max%':>7s}")
summ = []
for lab, _, _ in ATT:
    d = store[lab]
    rms, mx, lo, hi = thickness(d["alt"], d["rho"], d["cd"])
    summ.append((lab, rms, mx))
    print(f"{lab:24s} {np.mean(d['cd']):9.3f} {rms:11.3f} {mx:7.2f}  "
          f"(C_D {lo:.2f}..{hi:.2f})")

# --- plots ---
fig = plt.figure(figsize=(15, 4.5))

ax1 = fig.add_subplot(1, 3, 1)
labels = [s[0].replace(" (", "\n(") for s in summ]
ax1.bar(range(len(summ)), [s[1] for s in summ], color="steelblue")
ax1.set_xticks(range(len(summ))); ax1.set_xticklabels(labels, fontsize=7, rotation=0)
ax1.set_ylabel("thickness: RMS scatter at matched (alt,rho) [%]")
ax1.set_title("Time-independence per attitude")
ax1.axhline(0.34, color="crimson", ls="--", lw=1, label="sphere baseline 0.34%")
ax1.legend(fontsize=8)

ax2 = fig.add_subplot(1, 3, 2)
d = store["plate 80deg grazing"]
sc = ax2.scatter(np.log10(d["rho"]), d["cd"], c=d["alt"], cmap="plasma", s=12)
ax2.set_xlabel("log10 density"); ax2.set_ylabel("C_D")
ax2.set_title("Worst case (plate 80deg): still collapses")
plt.colorbar(sc, ax=ax2, label="Altitude [km]")

# C_D vs incidence at fixed (alt,rho), for 3 different epochs -> they agree
ax3 = fig.add_subplot(1, 3, 3)
angles = np.linspace(0, 85, 30)
epset = [("2008-07-21T12:00", 90., 1.), ("2019-12-30T21:00", 200., 40.),
         ("2011-06-01T15:00", 150., 20.)]
for dt, f107, ap in epset:
    row = msis.run([np.datetime64(dt)],[10.],[0.],[450.],[f107],[f107],[[ap]*7], version=0)[0]
    cds = [box_cd(row, 450., 0., *PLATE, ram(th)) for th in angles]
    ax3.plot(angles, cds, label=f"F10.7={f107:.0f}, Ap={ap:.0f}")
ax3.set_xlabel("incidence from normal [deg]"); ax3.set_ylabel("plate C_D (ref face area)")
ax3.set_title("Attitude dependence at 450 km (3 epochs)")
ax3.legend(fontsize=8)

plt.tight_layout()
plt.savefig(Path(__file__).with_name("cd_tierB.png"), dpi=130)
print("\nSaved figure.")
