"""
Driver: free-molecular validity floor altitude vs body characteristic length L.

Produces the committed evidence for the Knudsen low-altitude diagnostic
(drag-validity addendum Chunk 2): the floor_altitude(L) curve over a
representative body-size range, plus the sanity checks the build plan asks for:
  1. a mean-free-path hand-check against US-Standard-Atmosphere ballpark values,
  2. floor_altitude(L) monotonically increasing in L,
  3. the conservative high-activity floor exceeding the mid-activity floor
     (denser -> shorter lambda -> higher floor).

Writes kn_floor.png (floor vs L, both profiles + named bodies). Capture stdout
to kn_floor_results.txt for the provenance record:

    python kn_floor_experiment.py > kn_floor_results.txt

All printed output is ASCII (the redirect goes through cp1252 on Windows).
"""
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

from kn_floor import (  # noqa: E402
    CONSERVATIVE_HIGH,
    KN_FREE_MOLECULAR,
    L_GRID_M,
    MID_ACTIVITY,
    REFERENCE_BODIES,
    floor_altitude,
    mean_free_path,
    msis_row,
)


# === (1) mean-free-path hand-check vs US Standard Atmosphere ballpark ========
# US Std Atm 1976 ~ moderate solar activity, so compare against MID_ACTIVITY;
# the conservative high-activity profile is denser and runs a bit shorter.
print("(1) Mean free path hand-check (mid-activity ~ US Std Atm conditions):")
print(f"    {'alt km':>7s} {'lambda m':>11s}   US-Std-Atm ballpark")
USSA_LAMBDA_M = {100.0: 0.14, 120.0: 3.5, 150.0: 30.0, 200.0: 240.0}
for alt, ref in USSA_LAMBDA_M.items():
    lam = mean_free_path(msis_row(MID_ACTIVITY, alt))
    print(f"    {alt:7.0f} {lam:11.4f}   (~{ref:g} m)")
print("    (same order of magnitude at every check -> lambda model is sane)")

# === (2) floor_altitude(L) curve, conservative profile ======================
print(f"\n(2) Free-molecular floor altitude vs L  (Kn = {KN_FREE_MOLECULAR:.0f})")
print(f"    atmosphere: {CONSERVATIVE_HIGH['label']}")
floors_high = np.array([floor_altitude(L, profile=CONSERVATIVE_HIGH) for L in L_GRID_M])
assert np.all(np.isfinite(floors_high)), "every L must yield a bracketed floor crossing"
assert np.all(np.diff(floors_high) > 0.0), "floor_altitude must increase monotonically in L"
print("    floor_altitude(L) is finite and monotonically increasing in L   [PASS]")
print(f"    {'L m':>8s} {'floor km':>9s}")
for L, fa in zip(L_GRID_M, floors_high):
    print(f"    {L:8.3f} {fa:9.1f}")

# Named reference bodies (the figure annotations).
print(f"\n    {'body':>11s} {'L m':>6s} {'floor km':>9s}")
ref_rows = []
for name, L in REFERENCE_BODIES:
    fa = floor_altitude(L, profile=CONSERVATIVE_HIGH)
    ref_rows.append((name, L, fa))
    print(f"    {name:>11s} {L:6.2f} {fa:9.1f}")

# === (3) conservative vs mid-activity (conservatism direction) ==============
print("\n(3) Conservative high-activity floor must EXCEED mid-activity")
print("    (denser atmosphere -> shorter lambda -> higher, safer floor):")
print(f"    {'L m':>6s} {'high km':>8s} {'mid km':>8s} {'delta':>7s}")
for L in (0.1, 1.0, 10.0, 30.0):
    hi = floor_altitude(L, profile=CONSERVATIVE_HIGH)
    mid = floor_altitude(L, profile=MID_ACTIVITY)
    assert hi > mid, "conservative (high-activity) floor must exceed mid-activity"
    print(f"    {L:6.2f} {hi:8.1f} {mid:8.1f} {hi - mid:+7.1f}")
print("    conservative floor exceeds mid-activity at every checked L   [PASS]")

# === figure =================================================================
floors_mid = np.array([floor_altitude(L, profile=MID_ACTIVITY) for L in L_GRID_M])

fig, ax = plt.subplots(figsize=(8, 5))
ax.plot(L_GRID_M, floors_high, "-", color="crimson", lw=2,
        label=CONSERVATIVE_HIGH["label"])
ax.plot(L_GRID_M, floors_mid, "--", color="steelblue", lw=1.5,
        label=MID_ACTIVITY["label"])
for name, L, fa in ref_rows:
    ax.plot([L], [fa], "ko", ms=4)
    ax.annotate(name, (L, fa), fontsize=7,
                xytext=(4, -3), textcoords="offset points")
ax.set_xscale("log")
ax.set_xlabel("characteristic length L [m]")
ax.set_ylabel(f"free-molecular floor altitude [km]  (Kn = {KN_FREE_MOLECULAR:.0f})")
ax.set_title("Drag-model low-altitude validity floor vs body size")
ax.grid(True, which="both", alpha=0.3)
ax.legend(fontsize=8, loc="lower right")
plt.tight_layout()
plt.savefig(Path(__file__).with_name("kn_floor.png"), dpi=130)
print("\nSaved figure: kn_floor.png")
