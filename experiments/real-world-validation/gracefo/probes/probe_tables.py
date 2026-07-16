"""Scratch probe (2026-07-12): what Cd do propygator's shipped tables return at
GRACE-FO conditions?

Retained (under ``probes/`` since the 2026-07-15 reorganization) as the Chunk
2b diagnostic template (build plan "Reuse") -- mechanism only. **Superseded geometry:** this probe predates the
plan's refined base-averaged box. It uses LX,LY,LZ = 3.1 x 1.9 x 0.8 with x as
the ram axis (A_ram = 1.52 m^2, side area 16.74 m^2); the refined Chunk 2b
mapping is x = 0.780, y = 3.123 (ram -- matching InPlaneTracking's +Y-on-wind
convention), z = 1.3165, with A_ram = 1.027 m^2 and side area 13.09 m^2. Its
numbers seeded the plan's flagged ISSUE notes; what Chunk 2b reuses is the
mechanism -- table lookups at fixed face-flow angles + the hand-summed
Sigma Cd_i*A_i. Run 5's driver code, not this probe, is the evidence path.

**Known flaw in the comparisons (kept as-is -- it is the provenance of the
plan's ISSUE notes):** every ANCHORS line mixes reference areas. The sphere Cd
and the Run-3 fitted Cd are referenced to the driver's A = 1.0 m^2; the box
Cd*A is built on its own (already oversized) 1.52 m^2 ram face + 16.74 m^2
sides; and the "(= Cd ... referenced to frontal 1.0 m^2)" label divides the box
sum by the *driver's* area, not the box's own frontal area. The sphere-vs-box
gap and the "ratio" lines therefore overstate the disagreement. Chunk 2b's
diagnostic block is the fix: restate everything on the common
A_ram = 1.027 m^2 reference before comparing to the DSMC band.

For each window (quiet 2019 / active 2023): query NRLMSISE-00 density along the
first day, then look up VariableCd.sphere_default (isotropic sphere Cd) and
BoxFaceCd.default (per-face) at GRACE-FO's (radius, density, incidence). Hand-sum
the box's effective Cd*A for the ram-forward orientation. No propagation, no fit.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

import propygator

propygator.init()

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent))  # gracefo/ (moved to probes/ 2026-07-15)
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402

from propygator import Frame  # noqa: E402
from propygator.core import bodies  # noqa: E402
from propygator.propagation.spacecraft import BoxFaceCd, VariableCd  # noqa: E402

# GRACE-FO box dimensions (m), long axis (x) along-track = ram; z = radial (the
# large flat nadir/zenith faces); y = cross-track. [Superseded by the Chunk 2b
# base-averaged mapping -- see the module docstring.]
LX, LY, LZ = 3.1, 1.9, 0.8
A_RAM = LY * LZ  # small front/back end faces
A_Y = LX * LZ  # +/-y side faces (cross-track normal)
A_Z = LX * LY  # +/-z faces (radial normal) -- the large flat faces

FRONTAL_A = 1.0  # the sphere-equivalent reference area used in the driver
FITTED = {"quiet_2019": 2.03, "active_2023": 3.40}  # effective Cd from Run 3 (A=1.0)


def main() -> None:
    from org.hipparchus.geometry.euclidean.threed import Vector3D
    from org.orekit.models.earth.atmosphere import NRLMSISE00
    from org.orekit.models.earth.atmosphere.data import CssiSpaceWeatherData

    sphere_cd = VariableCd.sphere_default()
    box_cd = BoxFaceCd.default()
    cssi = CssiSpaceWeatherData(CssiSpaceWeatherData.DEFAULT_SUPPORTED_NAMES)
    atm = NRLMSISE00(cssi, bodies._sun(), bodies._earth())
    itrf = Frame.ITRF.to_orekit()

    # The BoxFaceCd per-face curve (density-independent shape check), at a mid density.
    print("=" * 74)
    print("BoxFaceCd.default per-face Cd vs face-flow angle theta (at rho=1e-12):")
    for deg in (0, 15, 30, 45, 60, 75, 90, 105, 120, 150, 180):
        th = math.radians(deg)
        cd = box_cd(6.876e6, 1e-12, th)
        tag = ""
        if deg == 0:
            tag = " <- ram (head-on)"
        elif deg == 90:
            tag = " <- edge-on (grazing)"
        elif deg == 180:
            tag = " <- leeward"
        print(f"  theta = {deg:3d} deg: Cd_face = {cd:6.3f}{tag}")

    for window in ("quiet_2019", "active_2023"):
        files = find_window_files(_HERE.parents[1] / "data" / "gracefo" / window)
        eph = parse_gnv1b(files[:1], sat_id="C", subsample_s=600.0)  # 144 pts/day
        r = np.linalg.norm(eph.positions_m, axis=1)
        r_mean = float(np.mean(r))

        # NRLMSISE-00 density along the first day.
        rho = []
        for i in range(len(eph.epochs)):
            p = eph.positions_m[i]
            rho.append(
                float(atm.getDensity(eph.epochs[i].to_orekit(), Vector3D(*p), itrf))
            )
        rho = np.array(rho)
        rho_min, rho_mean, rho_max = rho.min(), rho.mean(), rho.max()

        print("=" * 74)
        print(f"[{window}]  r_mean = {r_mean / 1e3:.1f} km "
              f"(alt {r_mean / 1e3 - 6378.1:.0f} km)")
        print(
            f"  NRLMSISE-00 density over day 1: min {rho_min:.3e}, mean {rho_mean:.3e}, "
            f"max {rho_max:.3e} kg/m^3"
        )

        # Isotropic sphere table: one scalar Cd (density-dependent).
        cd_s_mean = sphere_cd(r_mean, rho_mean)
        cd_s_lo = sphere_cd(r_mean, rho_min)
        cd_s_hi = sphere_cd(r_mean, rho_max)
        print(
            f"  sphere_default Cd: {cd_s_mean:.3f} at mean rho "
            f"(range {cd_s_lo:.3f}..{cd_s_hi:.3f} over the day)"
        )
        print(
            f"    -> effective Cd*A (x frontal {FRONTAL_A} m^2) = "
            f"{cd_s_mean * FRONTAL_A:.3f} m^2"
        )

        # BoxFaceCd effective Cd*A for the ram-forward box (hand-summed faces).
        cd_ram = box_cd(r_mean, rho_mean, 0.0)
        cd_graze = box_cd(r_mean, rho_mean, math.pi / 2)
        cd_lee = box_cd(r_mean, rho_mean, math.pi)
        cda_box = (
            cd_ram * A_RAM  # +x ram face, theta=0
            + cd_lee * A_RAM  # -x leeward face, theta=pi
            + cd_graze * (2 * A_Y + 2 * A_Z)  # 4 side faces, theta=pi/2
        )
        print(
            f"  BoxFaceCd faces: ram(0) {cd_ram:.3f}, edge(90) {cd_graze:.3f}, "
            f"leeward(180) {cd_lee:.3f}"
        )
        print(
            f"    ram face {cd_ram * A_RAM:.3f} + grazing sides "
            f"{cd_graze * (2 * A_Y + 2 * A_Z):.3f} "
            f"(2x{A_Y:.2f} + 2x{A_Z:.2f} m^2) + leeward {cd_lee * A_RAM:.3f}"
        )
        # NOTE: divides by the driver's FRONTAL_A (1.0), not the box's own ram
        # area -- the mislabeled reference the docstring's known-flaw note covers.
        print(f"    -> effective Cd*A = {cda_box:.3f} m^2 "
              f"(= Cd {cda_box / FRONTAL_A:.3f} referenced to frontal {FRONTAL_A} m^2)")

        # Anchors. NOTE: mixed reference areas (docstring known-flaw note) --
        # the ratios overstate; Chunk 2b compares on the common A_ram instead.
        eff_fit = FITTED[window]
        print(
            f"  ANCHORS  effective Cd*A (referenced to A=1.0): "
            f"nominal 2.30 | fitted(Run 3) {eff_fit:.2f} | "
            f"DSMC physical ~3.0-4.5"
        )
        print(
            f"    sphere_default Cd*A {cd_s_mean * FRONTAL_A:.2f} vs fit {eff_fit:.2f}"
            f"  ratio {cd_s_mean * FRONTAL_A / eff_fit:.2f}"
        )
        print(
            f"    BoxFaceCd    Cd*A {cda_box:.2f} vs fit {eff_fit:.2f}"
            f"  ratio {cda_box / eff_fit:.2f}"
        )


if __name__ == "__main__":
    main()
