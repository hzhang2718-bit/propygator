"""
Tier B (BoxFaceCd) RIGOROUS benefit study (build-plan Chunk 6, contract:
general-upgrades-1.md "Tier B Drag" -> Evidence pipeline 4). The final SHIP/DROP
gate: confirms (or refutes) the Chunk-1 cheap kernel-only signal with REAL
propagations.

  >>> RUN IN THE propygator CONDA ENV, NOT the throwaway venv. <<<
  This driver imports propygator, starts the JVM, and needs orekit-data. Every
  other script in this folder is venv-only (no Orekit); this one is the hybrid
  "propagate in the conda env" half the contract calls for. The shipped per-face
  table (data/box_face_cd_default.npz, Chunk 2) supplies BoxFaceCd.default().

      conda run -n propygator python cd_box_benefit_study.py > cd_box_benefit_study_results.txt

Question (the ship-or-drop gate): for a representative Sun-pointing LEO sail, is
the along-track trajectory divergence between Tier A (a best-fit CONSTANT Cd box)
and BoxFaceCd (the per-face free-molecular table) MATERIAL, and does it SURVIVE
re-fitting the constant Cd? A single scalar Cd has one degree of freedom (overall
drag scale); it can match the window-mean drag but not the attitude-correlated
SHAPE of the per-face drag. If a recalibrated scalar absorbs the divergence,
BoxFaceCd is not worth shipping; if a coherent residual survives recalibration, it
is.

Method (REAL propagate_numerical, conda env -- the rigorous twin of the Chunk-1
kinematic estimate cd_box_benefit_estimate.py):
  * Scenario reused from Chunk 1 (maintainer-confirmed): a flat Sun-pointing drag
    sail, 450 km circular / 51.6 deg, solar-max epoch, high A/m. SunPointing holds
    the body +Z face normal on the Sun, so the face-flow angle theta sweeps the
    full [0, pi] over an orbit; the beta angle (Sun vs orbit plane, set by RAAN)
    governs how much of [0, pi] the sail sees. Low beta = richest sweep = the
    worst (most material) case.
  * Run B (BoxFace): box_and_panels(..., drag_coefficient=BoxFaceCd.default()) ->
    the per-face sum. Run A (Tier A): the SAME box with a scalar drag_coefficient
    -> Orekit's BoxAndSolarArraySpacecraft projected-area drag. Identical in every
    other respect (forces, integrator, attitude, initial state, output grid), so
    the along-track difference isolates the Cd model. SRP / gravity / third-body
    are common-mode and cancel.
  * Along-track divergence: sample both trajectories on the shared grid, project
    (r_A - r_B) onto Run A's velocity unit vector. Recalibration: sweep the scalar
    Cd, minimize the RMS along-track separation vs Run B over the
    window, parabolic-refine the best-fit c*, and report the RESIDUAL divergence
    that survives at c* -- the part no constant Cd can represent. Normalize it by
    the Tier-A drag's own along-track effect (vs a no-drag reference run) so the
    verdict is a fraction, not a raw km that just scales with A/m.

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

import propygator as pgr  # noqa: E402,F401  (kept for provenance / version stamp)
from propygator import (  # noqa: E402
    BoxFaceCd,
    ForceModelConfig,
    IntegratorConfig,
    KeplerianElements,
    SpacecraftConfig,
    SpacecraftGeometry,
    SunPointing,
    propagate_numerical,
)
from propygator.core.frames import Frame  # noqa: E402
from propygator.core.time import Epoch, TimeScale  # noqa: E402

# ---------------------------------------------------------------------------
# Scenario (reused verbatim from Chunk 1 cd_box_benefit_estimate.py; the
# maintainer-confirmed representative sail). Per-unit-area verdict is independent
# of A_SIDE/MASS; those + ALT only scale the absolute along-track km.
# ---------------------------------------------------------------------------
EPOCH_ISO = "2002-07-01T00:00:00"  # solar max (NRLMSISE-00 reads real CSSI SW)
ALT_KM = 450.0  # circular
INC_DEG = 51.6  # ISS-like
A_SIDE_M = 4.0  # square sail edge -> 16 m^2 large faces (+/- body Z)
Z_THICK_M = 0.02  # thin plate (2 cm); edge faces ~0.08 m^2, negligible
MASS_KG = 12.0  # A/m ~ 1.33 m^2/kg (aggressive drag sail)
WINDOW_DAYS = 3.0
OUTPUT_STEP_S = 120.0
TARGET_BETAS = [5.0, 30.0]  # deg; low = worst/richest sweep, mid = sanity
CD_GRID = [2.1, 2.3, 2.45, 2.6, 2.8]  # bracket the Chunk-1 c* ~ 2.4-2.7
CD_NOMINAL = 2.2  # textbook scalar, for the "no recalibration" contrast

R_EQ_M = 6378137.0  # WGS84 equatorial radius (for altitude reporting only)
MU_EARTH = 3.986004418e14


# ---------------------------------------------------------------------------
# RAAN <-> beta geometry (low-precision Sun, ASCII; selection only -- the
# propagator uses its own Sun. beta here is an approximate scenario label.)
# ---------------------------------------------------------------------------
def _jd(iso: str) -> float:
    dt = np.datetime64(iso)
    return 2440587.5 + (dt - np.datetime64("1970-01-01T00:00:00")) / np.timedelta64(1, "D")


def _sun_eci_hat(jd: float) -> np.ndarray:
    """Low-precision Sun unit vector in ECI (mean equator/equinox), ~0.01 deg."""
    T = (jd - 2451545.0) / 36525.0
    L = math.radians((280.460 + 36000.771 * T) % 360.0)
    M = math.radians((357.5291 + 35999.0503 * T) % 360.0)
    lam = L + math.radians(1.914666 * math.sin(M) + 0.019994 * math.sin(2 * M))
    eps = math.radians(23.439291 - 0.0130042 * T)
    return np.array([math.cos(lam), math.cos(eps) * math.sin(lam),
                     math.sin(eps) * math.sin(lam)])


def _orbit_normal(raan: float, inc: float) -> np.ndarray:
    return np.array([math.sin(inc) * math.sin(raan),
                     -math.sin(inc) * math.cos(raan),
                     math.cos(inc)])


def _raan_for_beta(target_beta_deg: float, inc: float, sun_hat: np.ndarray) -> tuple[float, float]:
    """RAAN [rad] whose orbit plane gives the beta closest to target; realized beta."""
    raans = np.linspace(0.0, 2 * math.pi, 1441)
    betas = np.degrees(np.arcsin(np.clip(
        [float(np.dot(sun_hat, _orbit_normal(o, inc))) for o in raans], -1.0, 1.0)))
    j = int(np.argmin(np.abs(betas - target_beta_deg)))
    return float(raans[j]), float(betas[j])


# ---------------------------------------------------------------------------
# Propagation helpers
# ---------------------------------------------------------------------------
def _initial_state(raan: float) -> "pgr.State":
    epoch = Epoch.from_iso(EPOCH_ISO, TimeScale.UTC)
    a = R_EQ_M + ALT_KM * 1e3
    els = KeplerianElements(a, 0.0, math.radians(INC_DEG), raan, 0.0, 0.0)
    return els.to_state(epoch, Frame.EME2000)


def _geometry(drag_coefficient) -> SpacecraftGeometry:
    return SpacecraftGeometry.box_and_panels(
        x_length_m=A_SIDE_M, y_length_m=A_SIDE_M, z_length_m=Z_THICK_M,
        drag_coefficient=drag_coefficient,
    )


def _propagate(state, drag_coefficient, *, drag: bool = True):
    """One propagation of the scenario; returns the Trajectory."""
    geom = _geometry(drag_coefficient if drag else CD_NOMINAL)
    sc = SpacecraftConfig(mass_kg=MASS_KG, geometry=geom)
    fm = ForceModelConfig(
        gravity_degree=70, gravity_order=70,
        drag=drag, atmosphere_model="NRLMSISE-00", srp=True,
    )
    return propagate_numerical(
        state, WINDOW_DAYS * 86400.0, output_step=OUTPUT_STEP_S,
        force_models=fm, spacecraft=sc, attitude=SunPointing(),
        integrator=IntegratorConfig.default(),
    )


def _along_track(traj_a, traj_b) -> np.ndarray:
    """Along-track separation [m] of A relative to B, on the shared grid.

    Projects (r_A - r_B) onto A's velocity unit vector, sample by sample.
    Truncates to the common length defensively (both share start + output_step,
    so samples align by index; a guard could in principle stop one early)."""
    n = min(len(traj_a.positions), len(traj_b.positions))
    dr = traj_a.positions[:n] - traj_b.positions[:n]
    v = traj_a.velocities[:n]
    vhat = v / np.linalg.norm(v, axis=1, keepdims=True)
    return np.einsum("ij,ij->i", dr, vhat)


def _times_days(traj, n: int) -> np.ndarray:
    return np.arange(n) * OUTPUT_STEP_S / 86400.0


def _alt_km(traj) -> tuple[float, float]:
    a0 = float(np.linalg.norm(traj.positions[0]) - R_EQ_M)
    aN = float(np.linalg.norm(traj.positions[-1]) - R_EQ_M)
    return a0 / 1e3, aN / 1e3


# ---------------------------------------------------------------------------
# Per-beta study
# ---------------------------------------------------------------------------
def run_beta(target_beta_deg: float, sun_hat: np.ndarray) -> dict:
    raan, beta = _raan_for_beta(target_beta_deg, math.radians(INC_DEG), sun_hat)
    state = _initial_state(raan)

    # Run B: the per-face BoxFace truth.
    traj_b = _propagate(state, BoxFaceCd.default())

    # Sweep the constant Cd; objective = RMS along-track separation vs B.
    grid_rms = []
    grid_traj = {}
    for c in CD_GRID:
        ta = _propagate(state, float(c))
        s = _along_track(ta, traj_b)
        grid_rms.append(float(np.sqrt(np.mean(s ** 2))))
        grid_traj[c] = ta
    grid_rms = np.array(grid_rms)

    # Parabolic refine over the 3 points bracketing the grid minimum.
    j = int(np.argmin(grid_rms))
    if 0 < j < len(CD_GRID) - 1:
        x0, x1, x2 = CD_GRID[j - 1], CD_GRID[j], CD_GRID[j + 1]
        y0, y1, y2 = grid_rms[j - 1], grid_rms[j], grid_rms[j + 1]
        denom = (x0 - x1) * (x0 - x2) * (x1 - x2)
        a_q = (x2 * (y1 - y0) + x1 * (y0 - y2) + x0 * (y2 - y1)) / denom
        b_q = (x2 ** 2 * (y0 - y1) + x1 ** 2 * (y2 - y0) + x0 ** 2 * (y1 - y2)) / denom
        c_star = -b_q / (2 * a_q) if a_q > 0 else CD_GRID[j]
        c_star = float(np.clip(c_star, CD_GRID[0], CD_GRID[-1]))
    else:
        c_star = CD_GRID[j]

    # Confirmation run at c_star (reuse a grid run if it lands on a node).
    if any(abs(c_star - c) < 1e-9 for c in CD_GRID):
        traj_a_best = grid_traj[min(CD_GRID, key=lambda c: abs(c - c_star))]
    else:
        traj_a_best = _propagate(state, c_star)
    s_best = _along_track(traj_a_best, traj_b)
    s_nom = _along_track(grid_traj.get(CD_NOMINAL) or _propagate(state, CD_NOMINAL), traj_b)

    # Tier-A drag's own along-track effect: best-fit drag run vs a no-drag run.
    traj_nodrag = _propagate(state, None, drag=False)
    s_drag_effect = _along_track(traj_a_best, traj_nodrag)

    n = len(s_best)
    return dict(
        beta=beta, raan=raan, c_star=c_star,
        cd_grid=list(CD_GRID), grid_rms=grid_rms,
        s_best=s_best, s_nom=s_nom, s_drag_effect=s_drag_effect,
        t_days=_times_days(traj_b, n),
        alt_b=_alt_km(traj_b), alt_a=_alt_km(traj_a_best),
        rms_best=float(np.sqrt(np.mean(s_best ** 2))),
        max_best=float(np.max(np.abs(s_best))),
        final_best=float(s_best[-1]),
        final_nom=float(s_nom[-1]),
        final_drag_effect=float(s_drag_effect[-1]),
        max_drag_effect=float(np.max(np.abs(s_drag_effect))),
    )


def main() -> None:
    t_start = time.perf_counter()
    sun_hat = _sun_eci_hat(_jd(EPOCH_ISO))
    dec = math.degrees(math.asin(sun_hat[2]))

    print("=" * 76)
    print("TIER B RIGOROUS BENEFIT STUDY (BoxFaceCd vs best-fit Tier-A constant Cd)")
    print("=" * 76)
    print(f"propygator {getattr(pgr, '__version__', '?')}; real propagate_numerical")
    print(f"Sail: flat {A_SIDE_M:.1f} m x {A_SIDE_M:.1f} m ({A_SIDE_M**2:.0f} m^2/face), "
          f"z={Z_THICK_M:.2f} m, m={MASS_KG:.0f} kg, A/m={A_SIDE_M**2/MASS_KG:.2f} m^2/kg")
    print(f"Orbit: {ALT_KM:.0f} km circular, inc {INC_DEG:.1f} deg, "
          f"{WINDOW_DAYS:.0f}-day window, output_step={OUTPUT_STEP_S:.0f} s")
    print(f"Epoch {EPOCH_ISO} (solar max); attitude SunPointing(+Z face -> Sun); "
          f"Sun declination {dec:+.2f} deg")
    print(f"Forces: gravity 70x70 + Sun/Moon + NRLMSISE-00 drag + SRP "
          f"(SRP/gravity common-mode, cancel in A-B)")
    print(f"Recalibration: minimize RMS along-track separation vs BoxFace over "
          f"Cd grid {CD_GRID}, parabolic refine")
    print()

    results = []
    for tb in TARGET_BETAS:
        print(f"... running beta ~ {tb:.0f} deg (BoxFace + {len(CD_GRID)} Cd-grid + "
              f"confirm + no-drag) ...", flush=True)
        results.append(run_beta(tb, sun_hat))

    print()
    print("-" * 76)
    print("PER-BETA RESULTS")
    print("-" * 76)
    for r in results:
        a0b, aNb = r["alt_b"]
        print(f"\nbeta = {r['beta']:.1f} deg  (RAAN {math.degrees(r['raan']):.1f} deg)")
        print(f"  BoxFace altitude: {a0b:.1f} -> {aNb:.1f} km over {WINDOW_DAYS:.0f} d")
        print(f"  best-fit constant Cd  c* = {r['c_star']:.3f}")
        print("  Cd grid -> RMS along-track sep [km]:")
        for c, rms in zip(r["cd_grid"], r["grid_rms"]):
            mark = "  <- min" if abs(rms - r["grid_rms"].min()) < 1e-9 else ""
            print(f"      Cd={c:.2f}: {rms/1e3:9.3f}{mark}")
        print(f"  RESIDUAL after best-fit (the non-absorbable part):")
        print(f"      RMS along-track     : {r['rms_best']/1e3:8.2f} km")
        print(f"      max |along-track|   : {r['max_best']/1e3:8.2f} km")
        print(f"      final along-track   : {r['final_best']/1e3:8.2f} km")
        print(f"  For contrast, un-recalibrated nominal Cd={CD_NOMINAL}:")
        print(f"      final along-track   : {r['final_nom']/1e3:8.2f} km")
        print(f"  Tier-A drag's own along-track effect (best-fit vs no-drag):")
        print(f"      final               : {r['final_drag_effect']/1e3:8.2f} km")
        print(f"      max                 : {r['max_drag_effect']/1e3:8.2f} km")
        frac_final = 100.0 * abs(r["final_best"]) / max(abs(r["final_drag_effect"]), 1e-9)
        frac_rms = 100.0 * r["rms_best"] / max(abs(r["max_drag_effect"]), 1e-9)
        print(f"  RESIDUAL as fraction of the Tier-A drag effect:")
        print(f"      final residual / final drag effect : {frac_final:6.2f} %")
        print(f"      RMS residual   / max drag effect   : {frac_rms:6.2f} %")
        r["frac_final"] = frac_final
        r["frac_rms"] = frac_rms

    print()
    print("-" * 76)
    print("HEADLINE")
    print("-" * 76)
    worst = max(results, key=lambda r: r["frac_final"])
    print(f"Worst case (beta {worst['beta']:.1f} deg): a best-fit CONSTANT Cd still")
    print(f"leaves {abs(worst['final_best'])/1e3:.1f} km of along-track divergence over "
          f"{WINDOW_DAYS:.0f} days,")
    print(f"= {worst['frac_final']:.2f} % of the Tier-A drag effect itself "
          f"(RMS {worst['rms_best']/1e3:.1f} km).")
    print("This is the part NO constant Cd can absorb: the attitude-correlated")
    print("per-face shape that only BoxFaceCd represents.")
    print()
    print("READING (NOT the decision -- the SHIP/DROP call is the maintainer's):")
    print("  * residual that is a coherent, growing few-% of the drag effect")
    print("    and survives recalibration => MATERIAL => SHIP signal.")
    print("  * residual that collapses to ~0 at the best-fit Cd => DROP.")
    print(f"\nTotal wall time: {time.perf_counter() - t_start:.0f} s")

    _make_figure(results)


def _make_figure(results: list[dict]) -> None:
    fig = plt.figure(figsize=(15, 4.5))
    low = min(results, key=lambda r: r["beta"])

    ax1 = fig.add_subplot(1, 3, 1)
    ax1.plot(low["t_days"], low["s_nom"] / 1e3, "--", color="crimson", lw=1.4,
             label=f"nominal Cd={CD_NOMINAL}")
    ax1.plot(low["t_days"], low["s_best"] / 1e3, "-", color="navy", lw=1.6,
             label=f"best-fit Cd={low['c_star']:.2f}")
    ax1.axhline(0.0, color="gray", ls=":", lw=1)
    ax1.set_xlabel("time [days]")
    ax1.set_ylabel("along-track sep. Tier-A - BoxFace [km]")
    ax1.set_title(f"Along-track divergence, beta={low['beta']:.0f} deg")
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(1, 3, 2)
    ax2.plot(low["cd_grid"], low["grid_rms"] / 1e3, "o-", color="seagreen", lw=1.4)
    ax2.axvline(low["c_star"], color="crimson", ls="--", lw=1.2,
                label=f"c*={low['c_star']:.2f}")
    ax2.set_xlabel("constant Cd")
    ax2.set_ylabel("RMS along-track sep. vs BoxFace [km]")
    ax2.set_title(f"Recalibration objective, beta={low['beta']:.0f} deg")
    ax2.legend(fontsize=8)

    ax3 = fig.add_subplot(1, 3, 3)
    for r in results:
        ax3.plot(r["t_days"], r["s_best"] / 1e3, "-", lw=1.5,
                 label=f"beta={r['beta']:.0f} deg")
    ax3.axhline(0.0, color="gray", ls=":", lw=1)
    ax3.set_xlabel("time [days]")
    ax3.set_ylabel("residual along-track at best-fit Cd [km]")
    ax3.set_title("Non-absorbable residual (survives recalibration)")
    ax3.legend(fontsize=8)

    plt.tight_layout()
    out = Path(__file__).with_name("cd_box_benefit_study.png")
    plt.savefig(out, dpi=130)
    print(f"Saved figure: {out.name}")


if __name__ == "__main__":
    main()
