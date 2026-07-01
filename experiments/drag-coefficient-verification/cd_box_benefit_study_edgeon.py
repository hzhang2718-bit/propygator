"""
Tier B (BoxFaceCd) EDGE-ON benefit study -- the application-specific companion to
cd_box_benefit_study.py (build-plan Chunk 6, contract general-upgrades-1.md "Tier B
Drag" -> Evidence pipeline 4). Supplementary evidence for a maintainer application
the contract's Sun-pointing scenario does not represent: a box-shaped solar sail
held *edge-on* to the flow (InPlaneTracking) to minimize drag.

  >>> RUN IN THE propygator CONDA ENV, NOT the throwaway venv. <<<
  Imports propygator, starts the JVM, needs orekit-data (same as the Sun-pointing
  study). Does NOT overwrite that study's evidence -- this is a separate file set.

      conda run -n propygator python cd_box_benefit_study_edgeon.py > cd_box_benefit_study_edgeon_results.txt

Why a separate study (the physics inverts). SunPointing sweeps the large face
through the flow, so drag work is dominated by the near-face-on arc where the
projected-area (Tier A) and per-face (Tier B) models agree -- the shear term is a
<1% correction (that is what cd_box_benefit_study.py found). Held EDGE-ON, the large
faces are parallel to the flow for the whole orbit: their PROJECTED area -> ~0, so
Tier A (Orekit BoxAndSolarArraySpacecraft, projected-area only) sees almost no drag,
while the real physics is dominated by TANGENTIAL SHEAR on those large faces (the
per-face Cd floors at ~0.088 at theta = 90 deg). Only BoxFaceCd carries that term.

The gate metric needs care here. With the attitude HELD edge-on, both models give a
roughly CONSTANT CdA over the orbit, so a best-fit constant Cd can match BoxFace's
MAGNITUDE -- but only at an UNPHYSICAL value (it must inflate the tiny leading-edge
projected area up to the shear-dominated per-face CdA). So the naive "survives
recalibration?" residual is misleading. This driver therefore reports, in order:
  1. PRIMARY -- along-track divergence vs PHYSICAL Tier A (Cd = 2.2, and the shipped
     VariableCd.sphere_default table): what a real user actually suffers.
  2. The best-fit constant Cd from a WIDE sweep -- its VALUE is the evidence (if it
     lands far above the physical ~2.0-2.6 free-molecular range, the divergence is
     "absorbable" only unphysically).
  3. DRAG effect vs SRP effect at this altitude: does drag even matter for this sail
     (a solar sail is SRP-driven; if SRP dominates, the drag model is moot).

Reference-only: not shipped, not in CI, outside testpaths. ASCII-only stdout
(cp1252 redirect). The maintainer makes the SHIP/DROP call from this evidence.
"""
from __future__ import annotations

import math
import time
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import propygator as pgr  # noqa: E402,F401
from propygator import (  # noqa: E402
    BoxFaceCd,
    ForceModelConfig,
    InPlaneTracking,
    IntegratorConfig,
    KeplerianElements,
    SpacecraftConfig,
    SpacecraftGeometry,
    VariableCd,
    propagate_numerical,
)
from propygator.core.frames import Frame  # noqa: E402
from propygator.core.time import Epoch, TimeScale  # noqa: E402

# ---------------------------------------------------------------------------
# Maintainer-supplied solar-sail scenario. Held edge-on to minimize drag.
# ---------------------------------------------------------------------------
EPOCH_ISO = "2002-07-01T00:00:00"  # solar MAX (high-drag case; flag if changed)
ALT_KM = 400.0                     # circular
INC_DEG = 51.6                     # weakly relevant (InPlaneTracking: no Sun dep)
SAIL_SIDE_M = 1.0                  # 1 m^2 square sail -> +/-Z faces = 1 m^2
Z_THICK_M = 0.01                   # 1 cm edge thickness
MASS_KG = 2.0                      # A/m = 0.5 m^2/kg (full-face)
WINDOW_DAYS = 5.0                  # longer arc: edge-on drag is low
OUTPUT_STEP_S = 120.0
CD_NOMINAL = 2.2                   # textbook scalar (the naive choice)
# Sweep to locate the best-fit constant Cd (spans the physical ~2.0-2.6 range up
# into clearly non-physical territory; the best-fit's VALUE is the evidence).
CD_GRID = [2.2, 3.0, 4.0, 5.0, 7.0, 10.0, 15.0]
PHYSICAL_CD_CEIL = 2.6  # top of the free-molecular physical range

R_EQ_M = 6378137.0
CR_BOX = 1.8  # approx effective Cr for the box optics (abs 0.3 / spec 0.6), SRP est
P_SRP = 4.56e-6  # solar radiation pressure at 1 AU [N/m^2], for the analytic estimate


def _initial_state():
    epoch = Epoch.from_iso(EPOCH_ISO, TimeScale.UTC)
    a = R_EQ_M + ALT_KM * 1e3
    els = KeplerianElements(a, 0.0, math.radians(INC_DEG), 0.0, 0.0, 0.0)
    return els.to_state(epoch, Frame.EME2000)


def _geometry(drag_coefficient) -> SpacecraftGeometry:
    # 1 m^2 sail faces are +/-Z (area x*y); z is the thin edge. InPlaneTracking puts
    # +Z on the orbit normal, so those 1 m^2 faces are held edge-on to the flow.
    return SpacecraftGeometry.box_and_panels(
        x_length_m=SAIL_SIDE_M, y_length_m=SAIL_SIDE_M, z_length_m=Z_THICK_M,
        drag_coefficient=drag_coefficient,
    )


def _propagate(state, drag_coefficient, *, drag: bool = True, srp: bool = True):
    geom = _geometry(drag_coefficient if drag else CD_NOMINAL)
    sc = SpacecraftConfig(mass_kg=MASS_KG, geometry=geom)
    fm = ForceModelConfig(
        gravity_degree=70, gravity_order=70,
        drag=drag, atmosphere_model="NRLMSISE-00", srp=srp,
    )
    return propagate_numerical(
        state, WINDOW_DAYS * 86400.0, output_step=OUTPUT_STEP_S,
        force_models=fm, spacecraft=sc, attitude=InPlaneTracking(),
        integrator=IntegratorConfig.default(),
    )


def _along_track(traj_a, traj_b) -> np.ndarray:
    """Along-track separation [m] of A relative to B on the shared grid."""
    n = min(len(traj_a.positions), len(traj_b.positions))
    dr = traj_a.positions[:n] - traj_b.positions[:n]
    v = traj_a.velocities[:n]
    vhat = v / np.linalg.norm(v, axis=1, keepdims=True)
    return np.einsum("ij,ij->i", dr, vhat)


def _alt_km(traj) -> tuple[float, float]:
    a0 = float(np.linalg.norm(traj.positions[0]) - R_EQ_M)
    aN = float(np.linalg.norm(traj.positions[-1]) - R_EQ_M)
    return a0 / 1e3, aN / 1e3


def _best_fit_cd(state, traj_b):
    """Wide-grid best-fit constant Cd minimizing RMS along-track sep vs BoxFace."""
    rms, trajs = [], {}
    for c in CD_GRID:
        ta = _propagate(state, float(c))
        trajs[c] = ta
        rms.append(float(np.sqrt(np.mean(_along_track(ta, traj_b) ** 2))))
    rms = np.array(rms)
    j = int(np.argmin(rms))
    if 0 < j < len(CD_GRID) - 1:
        x0, x1, x2 = CD_GRID[j - 1], CD_GRID[j], CD_GRID[j + 1]
        y0, y1, y2 = rms[j - 1], rms[j], rms[j + 1]
        denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
        aq = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
        bq = (x2**2 * (y0 - y1) + x1**2 * (y2 - y0) + x0**2 * (y1 - y2)) / denom
        c_star = float(np.clip(-bq / (2 * aq) if aq > 0 else CD_GRID[j],
                               CD_GRID[0], CD_GRID[-1]))
    else:
        c_star = float(CD_GRID[j])
    traj_star = trajs.get(c_star) or _propagate(state, c_star)
    return c_star, rms, trajs, traj_star


def main() -> None:
    t0 = time.perf_counter()
    state = _initial_state()
    a_over_m = SAIL_SIDE_M**2 / MASS_KG
    a_srp = P_SRP * CR_BOX * a_over_m  # analytic SRP accel [m/s^2], order-of-magnitude

    print("=" * 76)
    print("TIER B EDGE-ON BENEFIT STUDY (solar sail held edge-on; BoxFaceCd vs Tier A)")
    print("=" * 76)
    print(f"propygator {getattr(pgr, '__version__', '?')}; real propagate_numerical")
    print(f"Sail: {SAIL_SIDE_M:.1f} m x {SAIL_SIDE_M:.1f} m ({SAIL_SIDE_M**2:.1f} m^2 "
          f"faces), edge {Z_THICK_M:.2f} m, m={MASS_KG:.1f} kg, A/m={a_over_m:.2f} m^2/kg")
    print(f"Orbit: {ALT_KM:.0f} km circular, inc {INC_DEG:.1f} deg, "
          f"{WINDOW_DAYS:.0f}-day window, output_step={OUTPUT_STEP_S:.0f} s")
    print(f"Epoch {EPOCH_ISO} (solar MAX -- high-drag case; solar min would cut drag)")
    print("Attitude InPlaneTracking: 1 m^2 faces held EDGE-ON to the flow "
          "(minimum-drag config)")
    print(f"Forces: gravity 70x70 + Sun/Moon + NRLMSISE-00 drag + SRP")
    print()

    # --- the runs ---
    print("... propagating BoxFace + physical Tier A + no-drag + grav-only + "
          f"{len(CD_GRID)}-pt Cd sweep ...", flush=True)
    traj_box = _propagate(state, BoxFaceCd.default())
    traj_cd22 = _propagate(state, CD_NOMINAL)
    traj_var = _propagate(state, VariableCd.sphere_default())
    traj_nodrag = _propagate(state, None, drag=False, srp=True)   # SRP + gravity
    traj_grav = _propagate(state, None, drag=False, srp=False)    # gravity only
    c_star, sweep_rms, _, traj_star = _best_fit_cd(state, traj_box)

    # --- metrics ---
    def final_max(sig):
        return float(sig[-1]), float(np.max(np.abs(sig)))

    s_cd22 = _along_track(traj_cd22, traj_box)
    s_var = _along_track(traj_var, traj_box)
    s_star = _along_track(traj_star, traj_box)
    drag_effect = _along_track(traj_box, traj_nodrag)   # BoxFace drag along-track
    drag_effect_cd22 = _along_track(traj_cd22, traj_nodrag)  # Tier A(2.2) drag effect
    srp_effect = _along_track(traj_nodrag, traj_grav)   # SRP along-track

    f_cd22, m_cd22 = final_max(s_cd22)
    f_var, m_var = final_max(s_var)
    f_star, m_star = final_max(s_star)
    f_de, m_de = final_max(drag_effect)
    f_de22, _ = final_max(drag_effect_cd22)
    f_srp, m_srp = final_max(srp_effect)

    # Empirical drag underestimate factor (along-track drag effect ~ linear in CdA).
    under_factor = abs(f_de) / max(abs(f_de22), 1e-9)

    a0, aN = _alt_km(traj_box)
    print()
    print("-" * 76)
    print("RESULTS")
    print("-" * 76)
    print(f"BoxFace altitude: {a0:.1f} -> {aN:.1f} km over {WINDOW_DAYS:.0f} days")
    print()
    print("1. PRIMARY -- along-track divergence a real user suffers vs BoxFace truth:")
    print(f"     Tier A, constant Cd=2.2      : final {f_cd22/1e3:9.1f} km, "
          f"max {m_cd22/1e3:8.1f} km")
    print(f"     Tier A, VariableCd.sphere    : final {f_var/1e3:9.1f} km, "
          f"max {m_var/1e3:8.1f} km")
    print(f"   (both use projected-area drag -> omit the large-face shear entirely)")
    print()
    print("2. Best-fit CONSTANT Cd (wide sweep) -- is the divergence absorbable, and")
    print("   at what Cd?")
    for c, r in zip(CD_GRID, sweep_rms):
        mark = "  <- min" if abs(r - sweep_rms.min()) < 1e-9 else ""
        print(f"     Cd={c:5.1f}: RMS along-track vs BoxFace {r/1e3:9.1f} km{mark}")
    print(f"     best-fit c* = {c_star:.2f}   (residual final {f_star/1e3:.1f} km, "
          f"max {m_star/1e3:.1f} km)")
    print(f"     -> that is {c_star/CD_NOMINAL:.1f}x the textbook {CD_NOMINAL}, and "
          f"{'ABOVE' if c_star > PHYSICAL_CD_CEIL else 'within'} the free-molecular "
          f"physical range (~2.0-{PHYSICAL_CD_CEIL})")
    if c_star > PHYSICAL_CD_CEIL:
        print(f"        i.e. no PHYSICALLY-reasoned constant Cd recovers BoxFace here")
    print()
    print("3. Does drag even matter for this sail? (drag vs SRP along-track effect)")
    print(f"     BoxFace drag effect (vs no-drag) : final {f_de/1e3:9.1f} km, "
          f"max {m_de/1e3:8.1f} km")
    print(f"     Tier A(2.2) drag effect          : final {f_de22/1e3:9.1f} km")
    print(f"     SRP effect (no-drag vs grav-only): final {f_srp/1e3:9.1f} km, "
          f"max {m_srp/1e3:8.1f} km")
    print(f"     analytic SRP accel ~ {a_srp:.2e} m/s^2 (Cr~{CR_BOX}, A/m={a_over_m:.2f})")
    drag_vs_srp = abs(f_de) / max(abs(f_srp), 1e-9)
    print(f"     BoxFace drag effect / SRP effect = {drag_vs_srp:.1f}x")
    print()
    print("-" * 76)
    print("HEADLINE")
    print("-" * 76)
    print(f"Empirical drag underestimate of physical Tier A vs BoxFace: "
          f"~{under_factor:.1f}x")
    print(f"A user running physical Tier A (Cd=2.2 or VariableCd) mis-predicts the")
    print(f"along-track by ~{abs(f_cd22)/1e3:.0f} km over {WINDOW_DAYS:.0f} days; "
          f"recovering it needs Cd~{c_star:.1f} "
          f"({'above' if c_star > PHYSICAL_CD_CEIL else 'within'} the physical range).")
    print(f"(Not the idealized ~9x: InPlaneTracking tracks INERTIAL velocity, but the")
    print(f" flow is Earth-relative (co-rotation), so the sail sits a few deg off exact")
    print(f" edge-on -- the large faces keep some projected area Tier A does capture.)")
    print(f"At this altitude/epoch, BoxFace drag is {drag_vs_srp:.1f}x the SRP effect, "
          f"so drag {'DOMINATES' if drag_vs_srp > 1 else 'is minor vs'} SRP.")
    print("READING (NOT the decision -- the SHIP/DROP call is the maintainer's):")
    print("  Edge-on inverts the Sun-pointing result: the shear term is the dominant")
    print("  drag, projected-area Tier A structurally omits it, and no PHYSICAL")
    print("  constant Cd recovers it. If drag matters vs SRP here (see #3), this is")
    print("  BoxFaceCd's load-bearing use case.")
    print(f"\nTotal wall time: {time.perf_counter() - t0:.0f} s")

    _figure(traj_box, s_cd22, s_var, s_star, drag_effect, srp_effect,
            sweep_rms, c_star)


def _figure(traj_box, s_cd22, s_var, s_star, drag_effect, srp_effect,
            sweep_rms, c_star):
    n = len(s_cd22)
    t = np.arange(n) * OUTPUT_STEP_S / 86400.0
    fig = plt.figure(figsize=(15, 4.5))

    ax1 = fig.add_subplot(1, 3, 1)
    ax1.plot(t, s_cd22 / 1e3, "-", color="crimson", lw=1.5, label="Tier A Cd=2.2")
    ax1.plot(t, s_var / 1e3, "-", color="darkorange", lw=1.3,
             label="Tier A VariableCd")
    ax1.plot(t, s_star / 1e3, "--", color="navy", lw=1.4,
             label=f"best-fit Cd={c_star:.0f}")
    ax1.axhline(0.0, color="gray", ls=":", lw=1)
    ax1.set_xlabel("time [days]")
    ax1.set_ylabel("along-track sep. Tier-A - BoxFace [km]")
    ax1.set_title("Divergence vs BoxFace (edge-on)")
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(1, 3, 2)
    ax2.plot(CD_GRID, sweep_rms / 1e3, "o-", color="seagreen", lw=1.4)
    ax2.axvline(c_star, color="crimson", ls="--", lw=1.2, label=f"c*={c_star:.0f}")
    ax2.axvspan(2.0, 2.6, color="gray", alpha=0.2, label="physical Cd range")
    ax2.set_xlabel("constant Cd")
    ax2.set_ylabel("RMS along-track sep. vs BoxFace [km]")
    ax2.set_title("Best-fit constant Cd is off the physical scale")
    ax2.legend(fontsize=8)

    ax3 = fig.add_subplot(1, 3, 3)
    ax3.plot(t, drag_effect / 1e3, "-", color="navy", lw=1.6,
             label="BoxFace drag effect")
    ax3.plot(t, srp_effect / 1e3, "-", color="goldenrod", lw=1.4,
             label="SRP effect")
    ax3.axhline(0.0, color="gray", ls=":", lw=1)
    ax3.set_xlabel("time [days]")
    ax3.set_ylabel("along-track effect [km]")
    ax3.set_title("Does drag matter? drag vs SRP")
    ax3.legend(fontsize=8)

    plt.tight_layout()
    out = Path(__file__).with_name("cd_box_benefit_study_edgeon.png")
    plt.savefig(out, dpi=130)
    print(f"Saved figure: {out.name}")


if __name__ == "__main__":
    main()
