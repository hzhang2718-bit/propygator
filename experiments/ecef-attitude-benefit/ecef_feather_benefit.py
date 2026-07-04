"""
ECEF InPlaneTracking benefit study -- build-plan-ecef-attitudes.md Chunk 1
evidence, refreshed at Chunk 4 with the SHIPPED mode (contract:
general-upgrades-1.md "ECEF InPlaneTracking" -> Evidence gate).

Quantifies what InPlaneTracking(velocity_reference="ecef") buys for the
headline feathered sail. The "ecef" leg is the shipped mode (Chunk 4 refresh;
the Chunk-1 gate ran it via a CustomAttitude stand-in law before the runtime
existed -- that law is kept below and propagated as a THIRD leg, so the results
carry a shipped-vs-stand-in cross-check: the two should agree up to the
stand-in's hardcoded-omega pole offset, ~0.3 deg on the wind vector). The
"inertial" leg is InPlaneTracking(). Both use BoxFaceCd.default() -- only the
attitude reference differs. Chunk-4 scenario change (maintainer): sail mass
0.5 kg (more realistic; the Chunk-1 gate ran 2.0 kg -- effects scale ~4x).

  >>> RUN IN THE propygator CONDA ENV (starts the JVM, needs orekit-data). <<<

      conda run -n propygator python ecef_feather_benefit.py > ecef_feather_benefit_results.txt

What it reports (contract: Evidence gate):
  (a) big-face angle-of-attack (AoA) history vs the co-rotating flow for both
      legs. The inertial leg is the real content -- predicted to oscillate
      0 -> ~3.7 deg -> 0 per half-orbit (max at the equator crossings of this
      near-polar SSO). The shipped ecef leg's AoA reads ~0 up to the DIAGNOSTIC
      wind model's own pole offset (the readout wind is the hardcoded-omega
      form, the shipped mode tracks the exact transform).
  (b) assembled per-face CdA history for both legs (BoxFaceCd is a pure-Python
      table; direct lookups at a representative density -- diagnostic only, the
      propagations use the real NRLMSISE-00 density internally).
  (c) PRIMARY: the along-track divergence between the two legs over the window,
      plus each leg's drag effect vs a no-drag baseline (the feather drag-
      reduction factor) and the SRP effect for scale.
  (d) the shipped-vs-stand-in cross-check (along-track agreement).

Reference-only: not shipped, not in CI, outside testpaths. ASCII-only stdout
(cp1252 redirect). The Checkpoint A GO was called on the Chunk-1 run (2 kg,
stand-in ecef leg: divergence -63.3 km / 5 d, drag ratio 1.12x).
"""
from __future__ import annotations

import argparse
import math
import time
from pathlib import Path

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

import propygator as pgr  # noqa: E402
from propygator import (  # noqa: E402
    BoxFaceCd,
    CustomAttitude,
    ForceModelConfig,
    InPlaneTracking,
    IntegratorConfig,
    KeplerianElements,
    Orientation,
    SpacecraftConfig,
    SpacecraftGeometry,
    propagate_numerical,
)
from propygator.core.frames import Frame  # noqa: E402
from propygator.core.time import Epoch, TimeScale  # noqa: E402

# ---------------------------------------------------------------------------
# Scenario (build plan "Decisions to confirm" default): thin-plate sail on a
# ~500 km SSO -- near-max out-of-plane co-rotation wind (i ~ 97.4 deg), the
# maximum-benefit regime. Sail dims/mass/epoch match the Tier B edge-on study
# (cd_box_benefit_study_edgeon.py) for comparability; only the orbit differs.
# ---------------------------------------------------------------------------
EPOCH_ISO = "2002-07-01T00:00:00"  # solar MAX (high-drag case, Tier B epoch)
ALT_KM = 500.0                     # circular
INC_DEG = 97.4                     # SSO at ~500 km; near-max out-of-plane wind
SAIL_SIDE_M = 1.0                  # 1 m^2 square sail -> +/-Z faces = 1 m^2
Z_THICK_M = 0.01                   # 1 cm edge thickness
MASS_KG = 0.5                      # A/m = 2.0 m^2/kg (chunk-4 realistic sail mass)
WINDOW_DAYS = 5.0
OUTPUT_STEP_S = 120.0

R_EQ_M = 6378137.0
OMEGA_EARTH = 7.292115e-5          # rad/s about EME2000 +Z (stand-in wind model)
W_VEC = np.array([0.0, 0.0, OMEGA_EARTH])
RHO_REPR = 1.0e-12                 # kg/m^3, ~500 km solar max -- CdA panel ONLY

# Full face areas keyed to the outward-normal axis (contract: Runtime,
# Tier B): +/-X faces span y*z, +/-Y span x*z, +/-Z span x*y (the sail faces).
A_X = SAIL_SIDE_M * Z_THICK_M
A_Y = SAIL_SIDE_M * Z_THICK_M
A_Z = SAIL_SIDE_M * SAIL_SIDE_M

CD_PLACEHOLDER = 2.2               # for the drag=False runs (geometry needs one)
AOA_ZOOM_HOURS = 6.0               # AoA/CdA plot window (full history is stats)


def _initial_state():
    epoch = Epoch.from_iso(EPOCH_ISO, TimeScale.UTC)
    a = R_EQ_M + ALT_KM * 1e3
    els = KeplerianElements(a, 0.0, math.radians(INC_DEG), 0.0, 0.0, 0.0)
    return els.to_state(epoch, Frame.EME2000)


# --- the two attitude frames (contract: Axis construction) ------------------

def _inertial_axes(r, v):
    """Shipped InPlaneTracking: +Y on inertial velocity, +Z on the orbit
    normal (both exact -- v is perpendicular to h)."""
    y = v / np.linalg.norm(v)
    h = np.cross(r, v)
    z = h / np.linalg.norm(h)
    return np.cross(y, z), y, z


def _feathered_axes(r, v):
    """The contract's ecef frame: +Y exact on v_rel = v - omega x r; +Z
    best-effort on the orbit normal (its along-wind component removed);
    X = Y x Z completes the right-handed triad."""
    v_rel = v - np.cross(W_VEC, r)
    y = v_rel / np.linalg.norm(v_rel)
    h = np.cross(r, v)
    h = h / np.linalg.norm(h)
    z = h - np.dot(h, y) * y
    z = z / np.linalg.norm(z)
    return np.cross(y, z), y, z


def _feathered_law(state) -> Orientation:
    """The Chunk-1 CustomAttitude stand-in for velocity_reference="ecef", kept
    as the cross-check leg now that the shipped mode exists. Orientation is
    the ACTIVE body->inertial rotation (pinned by
    test_custom_attitude_provider_body_to_inertial), so the matrix columns are
    the body axes expressed in EME2000."""
    x, y, z = _feathered_axes(state.position, state.velocity)
    return Orientation.from_matrix(np.column_stack((x, y, z)))


# --- propagation legs -------------------------------------------------------

def _propagate(state, attitude, days, *, drag=True, srp=True):
    geom = SpacecraftGeometry.box_and_panels(
        x_length_m=SAIL_SIDE_M, y_length_m=SAIL_SIDE_M, z_length_m=Z_THICK_M,
        drag_coefficient=BoxFaceCd.default() if drag else CD_PLACEHOLDER,
    )
    sc = SpacecraftConfig(mass_kg=MASS_KG, geometry=geom)
    fm = ForceModelConfig(
        gravity_degree=70, gravity_order=70,
        drag=drag, atmosphere_model="NRLMSISE-00", srp=srp,
    )
    return propagate_numerical(
        state, days * 86400.0, output_step=OUTPUT_STEP_S,
        force_models=fm, spacecraft=sc, attitude=attitude,
        integrator=IntegratorConfig.default(),
    )


# --- diagnostics off the sampled states -------------------------------------

def _diagnostics(traj, table, axes_fn):
    """Big-face AoA [deg] vs the (stand-in) true wind, and the assembled
    per-face CdA [m^2] at the representative density, per sample."""
    pos, vel = traj.positions, traj.velocities
    n = len(pos)
    aoa = np.empty(n)
    cda = np.empty(n)
    for k in range(n):
        r, v = pos[k], vel[k]
        x, y, z = axes_fn(r, v)
        v_rel = v - np.cross(W_VEC, r)
        w_hat = v_rel / np.linalg.norm(v_rel)
        # AoA of the +/-Z sail faces = angle between the wind and the face
        # plane = asin(|w . z|); 0 when the wind lies in the sail plane.
        aoa[k] = math.degrees(math.asin(min(1.0, abs(float(np.dot(w_hat, z))))))
        flow = -w_hat
        radius = float(np.linalg.norm(r))
        total = 0.0
        for normal, area in (
            (x, A_X), (-x, A_X), (y, A_Y), (-y, A_Y), (z, A_Z), (-z, A_Z),
        ):
            c = max(-1.0, min(1.0, float(np.dot(normal, flow))))
            total += table(radius, RHO_REPR, math.acos(c)) * area
        cda[k] = total
    return aoa, cda


def _along_track(traj_a, traj_b) -> np.ndarray:
    """Along-track separation [m] of A relative to B on the shared grid."""
    n = min(len(traj_a.positions), len(traj_b.positions))
    dr = traj_a.positions[:n] - traj_b.positions[:n]
    v = traj_a.velocities[:n]
    vhat = v / np.linalg.norm(v, axis=1, keepdims=True)
    return np.einsum("ij,ij->i", dr, vhat)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=WINDOW_DAYS,
                        help="window length [days] (short value = smoke run)")
    args = parser.parse_args()
    days = args.days

    t0 = time.perf_counter()
    state = _initial_state()
    v_circ = math.sqrt(3.986004418e14 / (R_EQ_M + ALT_KM * 1e3))
    wind = OMEGA_EARTH * (R_EQ_M + ALT_KM * 1e3)
    aoa_pred = math.degrees(math.asin(wind * abs(math.sin(math.radians(INC_DEG)))
                                      / v_circ))

    print("=" * 76)
    print("ECEF InPlaneTracking BENEFIT STUDY (feathered sail: inertial vs ecef ref)")
    print("=" * 76)
    print(f"propygator {getattr(pgr, '__version__', '?')}; real propagate_numerical;")
    print("ecef leg = SHIPPED InPlaneTracking(velocity_reference='ecef'); cross-check")
    print("leg = the Chunk-1 CustomAttitude stand-in (hardcoded omega_earth wind)")
    print(f"Sail: {SAIL_SIDE_M:.1f} x {SAIL_SIDE_M:.1f} m ({A_Z:.1f} m^2 faces), edge "
          f"{Z_THICK_M:.2f} m, m={MASS_KG:.1f} kg, A/m={A_Z / MASS_KG:.2f} m^2/kg")
    print(f"Orbit: {ALT_KM:.0f} km circular SSO, inc {INC_DEG:.1f} deg, "
          f"{days:g}-day window, output_step={OUTPUT_STEP_S:.0f} s")
    print(f"Epoch {EPOCH_ISO} (solar MAX; matches the Tier B edge-on study epoch)")
    print("Forces: gravity 70x70 + Sun/Moon + NRLMSISE-00 drag + SRP; BoxFaceCd")
    print(f"Predicted inertial-leg max AoA ~ {aoa_pred:.2f} deg (out-of-plane wind)")
    print()

    print("... propagating inertial leg (InPlaneTracking) ...", flush=True)
    t = time.perf_counter()
    traj_in = _propagate(state, InPlaneTracking(), days)
    print(f"    {time.perf_counter() - t:.0f} s", flush=True)

    print("... propagating feathered leg (SHIPPED InPlaneTracking ecef) ...",
          flush=True)
    t = time.perf_counter()
    traj_fe = _propagate(state, InPlaneTracking(velocity_reference="ecef"), days)
    print(f"    {time.perf_counter() - t:.0f} s", flush=True)

    print("... propagating cross-check leg (CustomAttitude ecef stand-in) ...",
          flush=True)
    t = time.perf_counter()
    traj_standin = _propagate(state, CustomAttitude(_feathered_law), days)
    print(f"    {time.perf_counter() - t:.0f} s", flush=True)

    print("... propagating no-drag (SRP+gravity) and gravity-only baselines ...",
          flush=True)
    t = time.perf_counter()
    traj_nodrag = _propagate(state, InPlaneTracking(), days, drag=False, srp=True)
    traj_grav = _propagate(state, InPlaneTracking(), days, drag=False, srp=False)
    print(f"    {time.perf_counter() - t:.0f} s", flush=True)

    table = BoxFaceCd.default()
    aoa_in, cda_in = _diagnostics(traj_in, table, _inertial_axes)
    aoa_fe, cda_fe = _diagnostics(traj_fe, table, _feathered_axes)

    s_div = _along_track(traj_fe, traj_in)      # feathered relative to inertial
    s_check = _along_track(traj_fe, traj_standin)  # shipped vs stand-in
    drag_in = _along_track(traj_in, traj_nodrag)
    drag_fe = _along_track(traj_fe, traj_nodrag)
    srp_eff = _along_track(traj_nodrag, traj_grav)

    f_div, m_div = float(s_div[-1]), float(np.max(np.abs(s_div)))
    f_check, m_check = float(s_check[-1]), float(np.max(np.abs(s_check)))
    f_in = float(drag_in[-1])
    f_fe = float(drag_fe[-1])
    f_srp = float(srp_eff[-1])
    reduction = abs(f_in) / max(abs(f_fe), 1e-9)

    print()
    print("-" * 76)
    print("RESULTS")
    print("-" * 76)
    print("(a) Big-face AoA vs the true co-rotating flow:")
    print(f"     inertial leg : max {np.max(aoa_in):.3f} deg, "
          f"mean {np.mean(aoa_in):.3f} deg  (predicted max ~{aoa_pred:.2f} deg)")
    print(f"     feathered leg: max {np.max(aoa_fe):.4f} deg  "
          "(~0 up to the diagnostic wind's pole-offset scale)")
    print()
    print("(b) Assembled per-face CdA at representative density "
          f"rho={RHO_REPR:.1e} kg/m^3 (diagnostic):")
    print(f"     inertial leg : mean {np.mean(cda_in):.4f} m^2, "
          f"max {np.max(cda_in):.4f}, min {np.min(cda_in):.4f}")
    print(f"     feathered leg: mean {np.mean(cda_fe):.4f} m^2, "
          f"max {np.max(cda_fe):.4f}, min {np.min(cda_fe):.4f}")
    print(f"     mean-CdA ratio inertial/feathered = "
          f"{np.mean(cda_in) / np.mean(cda_fe):.2f}x")
    print()
    print("(c) PRIMARY -- along-track over the window:")
    print(f"     divergence feathered-vs-inertial : final {f_div / 1e3:9.1f} km, "
          f"max {m_div / 1e3:8.1f} km")
    print(f"     inertial-leg drag effect (vs no-drag) : final {f_in / 1e3:9.1f} km")
    print(f"     feathered-leg drag effect (vs no-drag): final {f_fe / 1e3:9.1f} km")
    print(f"     -> feathering to the true wind cuts the drag effect by "
          f"~{reduction:.2f}x")
    print(f"     SRP effect (no-drag vs gravity-only)  : final {f_srp / 1e3:9.1f} km")
    print(f"     drag(inertial)/SRP = {abs(f_in) / max(abs(f_srp), 1e-9):.1f}x")
    print()
    print("(d) Shipped-mode vs CustomAttitude stand-in cross-check:")
    print(f"     along-track shipped - stand-in: final {f_check / 1e3:8.2f} km, "
          f"max {m_check / 1e3:7.2f} km")
    print("     (expected small vs the (c) divergence: the two ecef legs differ")
    print("      only by the stand-in's hardcoded-omega pole offset)")
    print()
    print("-" * 76)
    print("HEADLINE")
    print("-" * 76)
    print(f"Over {days:g} days the attitude REFERENCE alone (inertial vs ecef) moves")
    print(f"this sail {abs(f_div) / 1e3:.0f} km along-track "
          f"(max {m_div / 1e3:.0f} km) -- the drag effect drops ~{reduction:.2f}x when")
    print("feathered to the true co-rotating flow (shipped mode; agrees with the")
    print(f"Chunk-1 stand-in to {m_check / 1e3:.2f} km max along-track).")
    print("READING: Checkpoint A (GO) was called on the Chunk-1 stand-in run (2 kg:")
    print("  -63.3 km / 5 d, 1.12x). This Chunk-4 refresh re-measures with the")
    print("  SHIPPED mode at the 0.5 kg sail mass -- the numbers the docs quote.")
    print(f"\nTotal wall time: {time.perf_counter() - t0:.0f} s")

    _figure(days, aoa_in, aoa_fe, cda_in, cda_fe, s_div, drag_in, drag_fe)


def _figure(days, aoa_in, aoa_fe, cda_in, cda_fe, s_div, drag_in, drag_fe):
    t_all = np.arange(len(aoa_in)) * OUTPUT_STEP_S / 3600.0  # hours
    nz = min(len(t_all), int(AOA_ZOOM_HOURS * 3600.0 / OUTPUT_STEP_S) + 1)
    t_days = np.arange(len(s_div)) * OUTPUT_STEP_S / 86400.0
    fig = plt.figure(figsize=(15, 4.5))

    ax1 = fig.add_subplot(1, 3, 1)
    ax1.plot(t_all[:nz], aoa_in[:nz], "-", color="crimson", lw=1.4,
             label="inertial (shipped)")
    ax1.plot(t_all[:nz], aoa_fe[:nz], "-", color="navy", lw=1.4,
             label="feathered (ecef stand-in)")
    ax1.set_xlabel("time [h]")
    ax1.set_ylabel("big-face AoA vs true wind [deg]")
    ax1.set_title("(a) Angle of attack, first "
                  f"{AOA_ZOOM_HOURS:.0f} h")
    ax1.legend(fontsize=8)

    ax2 = fig.add_subplot(1, 3, 2)
    ax2.plot(t_all[:nz], cda_in[:nz], "-", color="crimson", lw=1.4,
             label="inertial")
    ax2.plot(t_all[:nz], cda_fe[:nz], "-", color="navy", lw=1.4,
             label="feathered")
    ax2.set_xlabel("time [h]")
    ax2.set_ylabel("per-face CdA [m^2]")
    ax2.set_title("(b) Assembled CdA (diagnostic density)")
    ax2.legend(fontsize=8)

    ax3 = fig.add_subplot(1, 3, 3)
    ax3.plot(t_days, s_div / 1e3, "-", color="black", lw=1.6,
             label="feathered - inertial")
    n3 = min(len(t_days), len(drag_in), len(drag_fe))
    ax3.plot(t_days[:n3], drag_in[:n3] / 1e3, "--", color="crimson", lw=1.2,
             label="inertial drag effect")
    ax3.plot(t_days[:n3], drag_fe[:n3] / 1e3, "--", color="navy", lw=1.2,
             label="feathered drag effect")
    ax3.axhline(0.0, color="gray", ls=":", lw=1)
    ax3.set_xlabel("time [days]")
    ax3.set_ylabel("along-track [km]")
    ax3.set_title("(c) Divergence and drag effects")
    ax3.legend(fontsize=8)

    plt.tight_layout()
    out = Path(__file__).with_name("ecef_feather_benefit.png")
    plt.savefig(out, dpi=130)
    print(f"Saved figure: {out.name}")


if __name__ == "__main__":
    main()
