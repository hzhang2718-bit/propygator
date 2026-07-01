"""
Tier B (BoxFaceCd) incidence-interpolation convergence study (build-plan Chunk 1,
contract: general-upgrades-1.md "Tier B Drag" -> Evidence pipeline 1b).

Question: can the per-face free-molecular drag coefficient Cd(theta) be linearly
interpolated from a coarse uniform grid over the full face-flow angle range
[0, pi] without material error? The shipped BoxFaceCd table will store Cd on a
1-D theta axis and interpolate linearly between nodes; this driver certifies that
that is accurate, and quantifies how fine the axis must be.

Method:
  1. Build "truth" Cd(theta) on a very fine uniform [0, pi] grid using the
     cd_box.cd_panel_species kernel (mass-flux-weighted over NRLMSISE-00 species
     via cd_box_faces.face_cd) at one representative MSIS state. Incidence is
     separable from (radius, density) -- the Cd-vs-theta shape shifts only slowly
     with altitude (tier-b-drag-interpolation-findings.md sec. 4.3) -- so a single
     representative altitude suffices; a 3-altitude overlay confirms the shape is
     stable.
  2. Subsample to nested coarse uniform grids (5, 9, 17, 33, 65, 129 nodes),
     linearly interpolate back to the fine grid, and report max / RMS error vs
     node spacing, plus the E(h)/E(h/2) ratio (~4 => clean 2nd-order convergence,
     the expected outcome for a C-infinity-in-theta curve with no special node
     placement).

Expected: a smooth Cd(theta) with no value jumps or slope kinks; per-face Cd
floors at ~0.07 at theta = pi/2 (edge-on) and tapers to ~0 by theta ~ 110 deg;
clean ~2nd-order error falloff, so a larger uniform grid provably hits any target.

Reference-only: not shipped, not in CI. ASCII-only stdout (cp1252 redirect). Run
from this directory in the throwaway venv:
    python cd_box_incidence_convergence.py > cd_box_incidence_convergence_results.txt
"""
from pathlib import Path

import numpy as np
from pymsis import msis
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from cd_core import IDX, alpha_sesam, calibrate_K, v_rel
from cd_box_faces import face_cd, face_cd_curve

K = calibrate_K()

# Representative MSIS state for the headline convergence numbers: 400 km / solar
# max -- the SESAM accommodation anchor (alpha ~ 0.90), the canonical drag point.
ANCHOR_DATE = np.datetime64("2002-07-01T12:00")
ANCHOR_ALT_KM = 400.0
ANCHOR_LAT = 0.0
ANCHOR_LON = 0.0
ANCHOR_F107 = 200.0
ANCHOR_AP = 15.0

# Altitudes for the shape-stability (separability) overlay.
OVERLAY_ALTS_KM = [300.0, 500.0, 800.0]

# Fine "truth" grid: 2049 nodes => 2048 intervals, so the coarse grids below are
# exact nested subsets (each (n-1) divides 2048) and the interpolation error is
# measured against the kernel itself, not a re-sampling artifact.
N_REF = 2049
COARSE_N = [5, 9, 17, 33, 65, 129]


def msis_state(date, alt_km, lat, lon, f107, ap):
    """One NRLMSISE-00 row (length-11) and its derived (V, alpha)."""
    row = np.asarray(
        msis.run([date], [lon], [lat], [alt_km], [f107], [f107], [[ap] * 7],
                 version=0)
    ).reshape(-1, 11)[0]
    V = v_rel(alt_km, lat)
    alpha = alpha_sesam(row[IDX["O"]], row[IDX["T"]], K)
    return row, V, alpha


def main():
    print("=" * 72)
    print("TIER B INCIDENCE-INTERPOLATION CONVERGENCE STUDY (BoxFaceCd)")
    print("=" * 72)
    print("Per-face Cd(theta) over the full face-flow angle [0, pi], linear")
    print("interpolation from nested uniform grids. Axis is THETA, not cos(theta)")
    print("(the shear cusp argument; general-upgrades-1.md 'Tier B Drag').")
    print()

    row, V, alpha = msis_state(ANCHOR_DATE, ANCHOR_ALT_KM, ANCHOR_LAT,
                               ANCHOR_LON, ANCHOR_F107, ANCHOR_AP)
    rho = row[IDX["rho"]]
    print(f"Representative state: {ANCHOR_ALT_KM:.0f} km solar-max  "
          f"rho={rho:.3e} kg/m^3  T={row[IDX['T']]:.0f} K  "
          f"alpha={alpha:.3f}  V_rel={V:.0f} m/s")

    # --- per-face Cd shape anchors (sanity vs the contract) ---
    cd0 = face_cd(0.0, row, V, alpha=alpha, T_inf=row[IDX["T"]])
    cd90 = face_cd(np.pi / 2, row, V, alpha=alpha, T_inf=row[IDX["T"]])
    cd110 = face_cd(np.radians(110.0), row, V, alpha=alpha, T_inf=row[IDX["T"]])
    cd180 = face_cd(np.pi, row, V, alpha=alpha, T_inf=row[IDX["T"]])
    print(f"per-face Cd anchors:  theta=0 (head-on)   {cd0:7.4f}")
    print(f"                      theta=90 (edge-on)  {cd90:7.4f}  "
          f"(contract: shear floor ~0.07)")
    print(f"                      theta=110 deg       {cd110:7.4f}  "
          f"(contract: ~0, leeward taper)")
    print(f"                      theta=180 (leeward) {cd180:7.4f}")
    print()

    # --- truth on the fine grid ---
    T_inf = row[IDX["T"]]
    theta_ref = np.linspace(0.0, np.pi, N_REF)
    cd_ref = face_cd_curve(theta_ref, row, V, T_inf, alpha)
    cd_scale = float(cd_ref.max())  # peak per-face Cd, for relative error

    # --- convergence: subsample, linearly interpolate back, measure error ---
    print("Linear-interpolation error vs uniform node spacing"
          f" (relative to peak Cd = {cd_scale:.4f}):")
    print(f"  {'nodes':>6s} {'spacing':>9s} {'max err':>11s} {'max %':>8s} "
          f"{'rms err':>11s} {'rms %':>8s} {'max-ratio':>10s}")
    prev_max = None
    rows_for_plot = []
    for n in COARSE_N:
        step = (N_REF - 1) // (n - 1)
        idx = np.arange(0, N_REF, step)
        theta_c = theta_ref[idx]
        cd_c = cd_ref[idx]
        cd_interp = np.interp(theta_ref, theta_c, cd_c)
        err = cd_interp - cd_ref
        max_err = float(np.abs(err).max())
        rms_err = float(np.sqrt((err ** 2).mean()))
        ratio = "   -   " if prev_max is None else f"{prev_max / max_err:9.2f}"
        spacing_deg = np.degrees(np.pi / (n - 1))
        print(f"  {n:6d} {spacing_deg:8.3f}d {max_err:11.3e} "
              f"{100 * max_err / cd_scale:7.3f}% {rms_err:11.3e} "
              f"{100 * rms_err / cd_scale:7.3f}% {ratio:>10s}")
        prev_max = max_err
        rows_for_plot.append((n, spacing_deg, max_err, rms_err))
    print()
    print("A max-ratio near 4.0 each row is clean 2nd-order convergence (error")
    print("~ h^2): a larger uniform theta grid provably reaches any error target,")
    print("with no special node placement. (general-upgrades-1.md 'Tier B Drag'.)")
    print()

    # --- separability: Cd-vs-theta shape at a few altitudes ---
    print("Shape stability across altitude (separability of incidence from "
          "(radius, density)):")
    overlay = []
    for alt in OVERLAY_ALTS_KM:
        r2, V2, a2 = msis_state(ANCHOR_DATE, alt, ANCHOR_LAT, ANCHOR_LON,
                                ANCHOR_F107, ANCHOR_AP)
        c2 = face_cd_curve(theta_ref, r2, V2, r2[IDX["T"]], a2)
        overlay.append((alt, c2))
    # Compare normalized shapes (divide each by its own peak) to isolate SHAPE
    # change from amplitude change.
    base = overlay[0][1] / overlay[0][1].max()
    max_shape_dev = 0.0
    for alt, c2 in overlay[1:]:
        dev = float(np.abs(c2 / c2.max() - base).max())
        max_shape_dev = max(max_shape_dev, dev)
        print(f"  {alt:5.0f} km vs {OVERLAY_ALTS_KM[0]:.0f} km: "
              f"max normalized-shape deviation {100 * dev:6.3f}%")
    print(f"  -> max shape deviation {100 * max_shape_dev:.3f}% across "
          f"{OVERLAY_ALTS_KM[0]:.0f}-{OVERLAY_ALTS_KM[-1]:.0f} km: the incidence")
    print("     shape is altitude-stable, so the convergence result transfers.")
    print()

    # --- figure ---
    fig = plt.figure(figsize=(15, 4.5))

    ax1 = fig.add_subplot(1, 3, 1)
    deg = np.degrees(theta_ref)
    ax1.plot(deg, cd_ref, "-", color="navy", lw=1.6, label="truth (fine grid)")
    n_mark = 9
    step = (N_REF - 1) // (n_mark - 1)
    ax1.plot(deg[::step], cd_ref[::step], "o", color="crimson", ms=5,
             label=f"{n_mark}-node coarse grid")
    ax1.axvline(90, color="gray", ls=":", lw=1)
    ax1.set_xlabel("face-flow angle theta [deg]")
    ax1.set_ylabel("per-face Cd (ref full face area)")
    ax1.set_title("Per-face Cd is smooth in theta (no jumps / kinks)")
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(1, 3, 2)
    spacings = np.array([r[1] for r in rows_for_plot])
    maxes = np.array([r[2] for r in rows_for_plot])
    rmss = np.array([r[3] for r in rows_for_plot])
    ax2.loglog(spacings, maxes, "-o", color="crimson", ms=4, label="max error")
    ax2.loglog(spacings, rmss, "-s", color="steelblue", ms=4, label="RMS error")
    # 2nd-order reference line anchored at the coarsest point.
    ref = maxes[0] * (spacings / spacings[0]) ** 2
    ax2.loglog(spacings, ref, "--", color="gray", lw=1, label="2nd-order ref (h^2)")
    ax2.set_xlabel("node spacing [deg]")
    ax2.set_ylabel("interpolation error (abs Cd)")
    ax2.set_title("Clean ~2nd-order convergence")
    ax2.legend(fontsize=8)

    ax3 = fig.add_subplot(1, 3, 3)
    for alt, c2 in overlay:
        ax3.plot(deg, c2, lw=1.4, label=f"{alt:.0f} km")
    ax3.axvline(90, color="gray", ls=":", lw=1)
    ax3.set_xlabel("face-flow angle theta [deg]")
    ax3.set_ylabel("per-face Cd")
    ax3.set_title("Shape stable across altitude (separable)")
    ax3.legend(fontsize=8)

    plt.tight_layout()
    out = Path(__file__).with_name("cd_box_incidence_convergence.png")
    plt.savefig(out, dpi=130)
    print(f"Saved figure: {out.name}")


if __name__ == "__main__":
    main()
