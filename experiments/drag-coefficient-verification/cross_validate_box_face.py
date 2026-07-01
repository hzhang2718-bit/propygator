"""
Per-face model cross-validation for Tier B (BoxFaceCd) -- the box twin of
cross_validate_models.py (build-plan Chunk 3; contract: general-upgrades-1.md
"Tier B Drag" -> Evidence pipeline 3).

THE §5-equivalence invariant for the per-face table. The experiment per-face
kernel (cd_box.cd_panel_species, wrapped by cd_box_faces) and the SHIPPED table
generator (scripts/generate_box_face_cd_table.py) are TWO INDEPENDENT
reconstructions of the same Schaaf-Chambre / Sentman DRIA flat-face physics --
normal pressure AND tangential shear. The Chunk-1 incidence convergence evidence
and the fixed-attitude collapse evidence transfer to the shipped box_face_cd
table ONLY if the two reconstructions agree; otherwise we certify one codebase and
ship another. This script drives BOTH off one identical set of NRLMSISE-00 rows
and asserts agreement on the FORCE-RELEVANT assembled CdA = sum_i Cd_i * A_i for a
representative convex box swept over attitude x radius x density -- mirroring how
the Tier A check (cross_validate_models.py) asserts on TOTAL sphere Cd, not
per-species terms.

Structure (mirroring the sphere cross-validator's reconcile-first shape):
  A. Reconcile the shared Langmuir-K calibration (the box paths inherit the same
     accommodation model as the sphere -- cd_core.calibrate_K vs the generator's
     live anchor -- already certified by cross_validate_models.py; re-verified
     here for self-containedness).
  B. Shared per-face closed form: feed IDENTICAL (theta, V, T, mass, alpha) to
     both per-species evaluators and assert ~machine precision. This is the direct
     term-by-term proof the two reconstructions are the same physics -- the check
     that catches a dropped or mis-written SHEAR term (the contract's named
     hazard), which only shows up at large theta.
  C. End-to-end CdA over attitude x radius x density: each pipeline runs with its
     OWN conventions (experiment v_rel uses a spherical radius; the generator uses
     the geocentric radius) at a shared K, exactly like the sphere e2e. Headline
     assertion: max relative CdA difference << 1%. Secondary: max ABSOLUTE per-face
     difference < eps_abs (well under the smallest force-relevant Cd) -- a bare
     relative per-face gate is ill-posed near grazing/leeward where Cd_i -> ~0.07
     -> 0 carries negligible force.

Two benign, documented divergences (sub-1%, the same flavor cross_validate_models
records for the sphere): (1) the relative-speed radius convention (spherical vs
geocentric) differs ~0.1-0.3% at high latitude; (2) the He molecular mass differs
in the 7th digit (cd_core 4.0026 vs generator 4.002602 amu) for a trace species.
Neither moves CdA.

Reference-only (experiment README): not shipped, not in CI, not linted/type-
checked. Runs in the throwaway venv (docs/experiments_venv.md) with pymsis +
scipy. Capture stdout as evidence:

    python cross_validate_box_face.py > cross_validate_box_face_results.txt

All printed output is ASCII (the redirect goes through cp1252 on Windows).
"""
import sys
from pathlib import Path

import numpy as np
from pymsis import msis

from cd_box import cd_panel_species
from cd_box_faces import face_cd
from cd_core import (
    IDX,
    SPECIES,
    alpha_sesam,
    calibrate_K,
    v_rel,
)

# The generators are repo maintainer scripts (scripts/), NOT the package. Importing
# the box generator's per-face internals here is exactly what the contract's
# Evidence-pipeline item 3 asks for; generate_sphere_cd_table supplies the shared
# Tier-A maps (radius/speed/accommodation). Heavy imports (pymsis, scipy) are
# deferred inside each generate()/_face_cd_* call site, so these imports are cheap.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import generate_box_face_cd_table as boxgen  # noqa: E402
import generate_sphere_cd_table as gen  # noqa: E402


def rel_diff(a, b):
    """Relative difference |a - b| / |b| (b is the generator/reference value)."""
    return float(np.abs(a - b) / np.abs(b))


# Shared conditions: quiet + storm across latitude / local solar time / solar
# cycle (the same coverage as the sphere cross-validator), including high latitude
# where the radius-convention speed nuance bites. Redefined locally rather than
# imported -- cross_validate_models.py is a script that runs its whole pipeline at
# import time.
CONDITIONS = [
    dict(date=np.datetime64("2002-07-01T12:00"), lon=30.0, lat=0.0, f107=200.0, f107a=200.0, ap=15.0),
    dict(date=np.datetime64("2008-07-21T18:00"), lon=210.0, lat=45.0, f107=70.0, f107a=70.0, ap=6.0),
    dict(date=np.datetime64("2014-10-05T21:00"), lon=120.0, lat=-60.0, f107=150.0, f107a=150.0, ap=30.0),
    dict(date=np.datetime64("2003-01-15T03:00"), lon=300.0, lat=70.0, f107=250.0, f107a=250.0, ap=200.0),  # storm
    dict(date=np.datetime64("2011-06-01T15:00"), lon=80.0, lat=-30.0, f107=120.0, f107a=120.0, ap=45.0),
]
# Sweep the signed-off validated grid band (150-1400 km); the per-face Cd is
# defined everywhere, so the table edges (not a model-breakdown cut) bound this.
ALTS_KM = np.linspace(150.0, 1400.0, 14)


def _msis_rows(cond):
    """NRLMSISE-00 rows over ALTS_KM for one condition (shape (len(ALTS), 11))."""
    return np.asarray(
        msis.run(
            [cond["date"]], [cond["lon"]], [cond["lat"]], ALTS_KM,
            [cond["f107"]], [cond["f107a"]], [[cond["ap"]] * 7], version=0,
        )
    ).reshape(-1, 11)


# --- representative convex geometries (face order +X,-X,+Y,-Y,+Z,-Z) ---------
# Normals are geometry-independent, so the six face-flow angles depend only on the
# attitude (flow direction); only the FULL face areas change between geometries.
X, Y, Z = np.eye(3)
NORMALS = [X, -X, Y, -Y, Z, -Z]


def _areas(lx, ly, lz):
    """Full face areas for a box, in NORMALS order."""
    return np.array([ly * lz, ly * lz, lx * lz, lx * lz, lx * ly, lx * ly])


GEOMETRIES = [
    # The contract's example bus -- all faces carry real area, so the leeward/edge
    # shear (~5-11% of total drag at face-on) is exercised; CdA never near zero.
    ("box 2.0x1.5x1.0", _areas(2.0, 1.5, 1.0)),
    # A thin plate (large +/-Z faces): stresses the grazing/leeward regime where a
    # face's Cd floors at ~0.07 and the secondary ABSOLUTE per-face gate matters.
    ("plate 1.0x1.0x0.02", _areas(1.0, 1.0, 0.02)),
]


def _attitude_flow_dirs(n_fib=48):
    """Flow (ram) directions sweeping all incidences: a Fibonacci sphere plus the
    canonical head-on / edge-on / corner-on attitudes."""
    dirs = []
    golden = np.pi * (3.0 - np.sqrt(5.0))
    for i in range(n_fib):
        z = 1.0 - 2.0 * (i + 0.5) / n_fib
        r = np.sqrt(max(0.0, 1.0 - z * z))
        phi = golden * i
        dirs.append(np.array([r * np.cos(phi), r * np.sin(phi), z]))
    dirs.append(X.copy())                       # head-on to +X
    dirs.append((X + Z) / np.sqrt(2.0))         # edge-on
    dirs.append((X + Y + Z) / np.sqrt(3.0))     # corner-on
    return dirs


def _face_thetas(flow_hat):
    """Six face-flow angles theta_i in [0, pi] for a flow direction (the runtime's
    arccos(clip(.)) guard: a finite-precision dot just past +/-1 would make an
    unclamped arccos return NaN)."""
    cos_i = np.array([float(np.dot(n_hat, flow_hat)) for n_hat in NORMALS])
    return np.arccos(np.clip(cos_i, -1.0, 1.0))


# ============================================================================
# A. Reconcile the shared accommodation / Langmuir K (contract: shared Tier-A model)
# ============================================================================
print("=" * 72)
print("RECONCILE: shared Langmuir K (the box inherits the Tier-A accommodation)")
print("=" * 72)
K_exp = calibrate_K()  # cd_core: hardcoded 400 km / solar-max anchor
K_gen = gen._calibrate_accommodation_K(msis.run, gen.ANCHOR_ALPHA)  # live MSIS anchor
print(f"  K_exp (cd_core)   = {K_exp:.4e} 1/Pa")
print(f"  K_gen (generator) = {K_gen:.4e} 1/Pa")
print(f"  K rel diff = {rel_diff(K_exp, K_gen):.3%}   "
      f"[{'PASS' if rel_diff(K_exp, K_gen) < 0.01 else 'FAIL'} < 1%]")
print("  (Identical to the sphere reconcile(i); both anchor alpha=0.90. The two")
print("  per-face pipelines below run at the shared K_exp, so K does not confound")
print("  the physics comparison.)")
print("  Note: species masses match except He (cd_core 4.0026 vs generator")
print("  4.002602 amu) -- a 7th-digit difference on a trace species, sub-ppm on CdA.")
print()


# ============================================================================
# B. Shared per-face closed form: identical inputs -> ~machine precision
# ============================================================================
print("=" * 72)
print("SHARED PER-FACE PHYSICS: closed form off IDENTICAL inputs (expect ~eps)")
print("=" * 72)
print("  Cd_face(theta) per species, both evaluators fed the same (theta, V, T,")
print("  mass, alpha). This is the term-by-term proof the two reconstructions are")
print("  the same Schaaf-Chambre/Sentman physics -- pressure AND shear -- across")
print("  the full [0, pi] axis (the shear term only shows up at large theta).")
# Representative free-molecular states (V m/s, T K, alpha) spanning solar
# max/min and accommodation extremes.
PHYS_STATES = [
    (7174.0, 1284.0, 0.90),  # 400 km solar max (the anchor)
    (7300.0, 700.0, 0.50),   # cool, partial accommodation
    (7050.0, 1000.0, 0.20),  # low accommodation
    (6900.0, 900.0, 0.85),
]
thetas_axis = np.linspace(0.0, np.pi, 129)  # finer than the shipped 65-node axis
species_abs = 0.0
species_rel = 0.0  # only where Cd is not tiny (a relative gate is ill-posed at ~0)
for V, T, al in PHYS_STATES:
    for _name, (_col, mass) in SPECIES.items():
        cd_exp = np.array(
            [cd_panel_species(float(np.cos(t)), V, T, mass, al) for t in thetas_axis]
        )
        cd_gen = boxgen._face_cd_species(
            thetas_axis, np.array([V]), np.array([T]), mass, np.array([al])
        )[0]
        adiff = np.abs(cd_gen - cd_exp)
        species_abs = max(species_abs, float(adiff.max()))
        big = np.abs(cd_exp) > 0.1
        if big.any():
            species_rel = max(species_rel, float((adiff[big] / np.abs(cd_exp[big])).max()))
print(f"  per-species per-face closed form: max abs diff = {species_abs:.2e}  "
      f"max rel diff (Cd>0.1) = {species_rel:.2e}")

# Mass-flux-weighted per-face Cd off identical (V, alpha): isolates the only
# weighted-path difference, the He molecular-mass nuance (sub-1e-6).
anchor_row = _msis_rows(CONDITIONS[0])[5]  # a mid-band row
V0 = v_rel(float(ALTS_KM[5]), CONDITIONS[0]["lat"])
al0 = alpha_sesam(anchor_row[IDX["O"]], anchor_row[IDX["T"]], K_exp)
cd_exp_w = np.array(
    [face_cd(float(t), anchor_row, V0, anchor_row[IDX["T"]], al0) for t in thetas_axis]
)
cd_gen_w = boxgen._face_cd_total(
    anchor_row[None, :], np.array([V0]), np.array([al0]), thetas_axis
)[0]
weighted_abs = float(np.abs(cd_gen_w - cd_exp_w).max())
print(f"  mass-flux-weighted per-face Cd (identical V, alpha): max abs diff = "
      f"{weighted_abs:.2e}  (He-mass nuance only)")
print()


# ============================================================================
# C. END-TO-END: assembled CdA over attitude x radius x density (the headline)
# ============================================================================
print("=" * 72)
print("END-TO-END: assembled CdA = sum_i Cd_i * A_i, both pipelines, one MSIS set")
print("=" * 72)
print("  Experiment uses v_rel (spherical radius); generator uses the geocentric")
print("  radius -- each its own convention, shared K_exp. Swept over a Fibonacci")
print("  fan of flow directions x radius x density for two convex geometries.")
attitudes = _attitude_flow_dirs()
thetas_per_att = [_face_thetas(f) for f in attitudes]

# Per-geometry CdA relative agreement; pure-physics (shared-speed) CdA agreement;
# global absolute per-face agreement.
cda_rel = {name: [] for name, _ in GEOMETRIES}
cda_rel_purephys = {name: [] for name, _ in GEOMETRIES}
face_abs = 0.0
cda_min = {name: np.inf for name, _ in GEOMETRIES}
n_pts = 0
for cond in CONDITIONS:
    lat = cond["lat"]
    rows = _msis_rows(cond)
    for ialt, alt in enumerate(ALTS_KM):
        row = rows[ialt]
        rho = row[IDX["rho"]]
        if not np.isfinite(rho) or rho <= 0.0:
            continue
        T = row[IDX["T"]]
        alpha = alpha_sesam(row[IDX["O"]], T, K_exp)  # == gen._accommodation at K_exp
        V_exp = v_rel(float(alt), lat)                       # spherical radius
        r_geo = gen._geocentric_radius(np.array([alt * 1e3]), np.radians(lat))[0]
        V_gen = gen._relative_speed(np.array([r_geo]), np.radians(lat))[0]  # geocentric
        for thetas in thetas_per_att:
            exp_faces = np.array(
                [face_cd(float(t), row, V_exp, T, alpha) for t in thetas]
            )
            gen_faces = boxgen._face_cd_total(
                row[None, :], np.array([V_gen]), np.array([alpha]), thetas
            )[0]
            gen_faces_shared = boxgen._face_cd_total(
                row[None, :], np.array([V_exp]), np.array([alpha]), thetas
            )[0]
            face_abs = max(face_abs, float(np.abs(gen_faces - exp_faces).max()))
            for name, areas in GEOMETRIES:
                cda_exp = float(np.dot(exp_faces, areas))
                cda_gen = float(np.dot(gen_faces, areas))
                cda_gen_s = float(np.dot(gen_faces_shared, areas))
                cda_rel[name].append(rel_diff(cda_exp, cda_gen))
                cda_rel_purephys[name].append(rel_diff(cda_exp, cda_gen_s))
                cda_min[name] = min(cda_min[name], cda_exp)
            n_pts += 1

print(f"  {n_pts} (condition x altitude x attitude) points, {len(GEOMETRIES)} "
      f"geometries, lat -60..70")
print(f"  {'geometry':20s} {'CdA range':>14s} {'phys+speed max':>15s} "
      f"{'mean':>9s} {'pure-phys max':>14s}")
overall_rel = 0.0
for name, _areas_unused in GEOMETRIES:
    rel = np.array(cda_rel[name])
    rel_pp = np.array(cda_rel_purephys[name])
    overall_rel = max(overall_rel, float(rel.max()))
    print(f"  {name:20s} {('>=%.3f' % cda_min[name]):>14s} {rel.max():14.4%} "
          f"{rel.mean():9.4%} {rel_pp.max():13.2e}")
print(f"  GLOBAL max ABSOLUTE per-face diff = {face_abs:.4e}  "
      f"(smallest force-relevant Cd ~0.07; eps_abs gate = 0.02)")
print()


# ============================================================================
# Verdict + asserts
# ============================================================================
THRESHOLD_CDA = 0.01   # << 1% on the force-relevant CdA (matches the sphere gate)
EPS_ABS = 0.02         # well under the smallest force-relevant per-face Cd
EPS_MACHINE = 1e-9     # shared closed form -> machine precision
k_rel = rel_diff(K_exp, K_gen)
verdict = "PASS" if (overall_rel < THRESHOLD_CDA and face_abs < EPS_ABS
                     and species_abs < EPS_MACHINE and k_rel < 0.01) else "FAIL"
print("=" * 72)
print(f"VERDICT [{verdict}]: the two per-face reconstructions share the same closed")
print(f"  form to {species_abs:.1e} (machine eps); end-to-end they agree on the")
print(f"  force-relevant CdA to {overall_rel:.4%} (phys+speed, shared K), with the")
print(f"  K calibration agreeing to {k_rel:.4%} -- full independent agreement is")
print(f"  bounded by the product, << 1%. Per-face absolute agreement {face_abs:.1e}.")
print("=" * 72)

assert species_abs < EPS_MACHINE, (
    f"per-face closed form is NOT identical: max abs diff {species_abs:.2e} -- a term "
    "(likely the tangential shear at large theta) diverges; reconcile before trusting "
    "the shipped table"
)
assert overall_rel < THRESHOLD_CDA, (
    f"box-face cross-validation FAILED: max CdA rel diff {overall_rel:.4%} >= 1% -- "
    "the generator and kernel disagree on the force-relevant quantity"
)
assert face_abs < EPS_ABS, (
    f"per-face absolute agreement {face_abs:.2e} >= {EPS_ABS} -- local per-face "
    "divergence (near grazing/leeward where a relative gate is ill-posed)"
)
assert k_rel < 0.01, "shared Langmuir K calibration diverged >= 1%"
print("All Tier B per-face cross-validation checks PASS "
      "(the sec. 5 equivalence invariant holds for BoxFaceCd).")
