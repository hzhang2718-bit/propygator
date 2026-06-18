"""
Model cross-validation (drag-validity addendum sec. 5) + Phase-2 derived band
(sec. 4).

THE single most important correctness constraint in the addendum. The experiment
C_D model (cd_core.py) and the SHIPPED table generator
(scripts/generate_sphere_cd_table.py) are TWO INDEPENDENT reconstructions of the
same Sentman/DRIA free-molecular physics -- by deliberate design the generator
does not copy the experiment code. A validity limit derived from the experiment
(the high-altitude collapse cut, the Knudsen floor) transfers to the shipped table
ONLY if the two implementations agree at the boundary; otherwise we certify one
codebase and ship another. This script drives BOTH off one identical set of
NRLMSISE-00 rows at shared (radius, density, condition) points and asserts max
relative agreement << 1% (well inside the sec. 3.1 green line).

It reconciles the two known default divergences first (sec. 5):
  (i)  Accommodation anchor -- both calibrate to alpha = 0.90 at the 400 km /
       solar-max anchor. cd_core hardcodes the anchor (n_O, T); the generator
       derives them live from NRLMSISE-00. We verify the resulting Langmuir K
       agrees.
  (ii) Relative-speed formula -- the Earth-rotation rate is written two ways
       (2*pi/86164.1 s vs the 7.2921159e-5 rad/s constant), numerically equal.
       We also surface a second, subtler difference the sec. 5(ii) note does not
       mention: cd_core.v_rel uses a SPHERICAL radius (R_earth + alt) while the
       generator uses the true GEOCENTRIC radius, so the two speeds coincide only
       at the equator and differ by ~0.1-0.3% at high latitude -- a documented,
       sub-1% effect that does not move either validity boundary.

Then it checks the shared algebra (per-species closed form, accommodation) is
identical to machine precision, and runs the end-to-end agreement test.

Reference-only (experiment README): not shipped, not in CI. Runs in the throwaway
venv (docs/experiments_venv.md) with pymsis + scipy. Capture stdout as evidence:

    python cross_validate_models.py > cross_validate_results.txt

All printed output is ASCII (the redirect goes through cp1252 on Windows).
"""
import sys
from pathlib import Path

import numpy as np
from pymsis import msis

from cd_core import (
    IDX,
    SPECIES,
    U,
    alpha_sesam,
    calibrate_K,
    cd_sphere_species,
    cd_total,
    geocentric_radius,
    v_rel,
)
from kn_floor import CONSERVATIVE_HIGH, REFERENCE_BODIES, floor_altitude

# The generator is a repo maintainer script (scripts/), NOT the package; importing
# its _sphere_cd_* internals here is exactly what sec. 5 asks for. Its heavy
# imports (pymsis, scipy) are deferred inside generate(), so this import is cheap.
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import generate_sphere_cd_table as gen  # noqa: E402


def rel_diff(a, b):
    """Relative difference |a - b| / |b| (b is the generator/reference value)."""
    return float(np.abs(a - b) / np.abs(b))


# Shared conditions: quiet + storm, across latitude / local solar time / solar
# cycle, so the comparison exercises the certified extremes (sec. 5 condition
# coverage), including high latitude where the radius-convention speed nuance bites.
CONDITIONS = [
    dict(date=np.datetime64("2002-07-01T12:00"), lon=30.0, lat=0.0, f107=200.0, f107a=200.0, ap=15.0),
    dict(date=np.datetime64("2008-07-21T18:00"), lon=210.0, lat=45.0, f107=70.0, f107a=70.0, ap=6.0),
    dict(date=np.datetime64("2014-10-05T21:00"), lon=120.0, lat=-60.0, f107=150.0, f107a=150.0, ap=30.0),
    dict(date=np.datetime64("2003-01-15T03:00"), lon=300.0, lat=70.0, f107=250.0, f107a=250.0, ap=200.0),  # storm
    dict(date=np.datetime64("2011-06-01T15:00"), lon=80.0, lat=-30.0, f107=120.0, f107a=120.0, ap=45.0),
]
# Cross-validate over the FULL range the Chunk-4 generator builds the table from:
# the signed-off 150-1400 km grid PLUS the internal-sampling margin (~130-1450 km)
# the generator samples so the regrid interpolates the mesh corners rather than
# nearest-filling them. Proving the two models agree across ALL of it -- not just to
# 1200 km -- is what lets the 1400 km grid claim transfer to the shipped table
# (addendum sec. 5: certify exactly what is shipped).
ALTS_KM = np.linspace(130.0, 1450.0, 30)


def _msis_rows(cond):
    """NRLMSISE-00 rows over ALTS_KM for one condition (shape (len(ALTS), 11))."""
    return np.asarray(
        msis.run(
            [cond["date"]], [cond["lon"]], [cond["lat"]], ALTS_KM,
            [cond["f107"]], [cond["f107a"]], [[cond["ap"]] * 7], version=0,
        )
    ).reshape(-1, 11)


# ============================================================================
# Phase-2 derived band (addendum sec. 4) -- the constants the runtime reads
# ============================================================================
print("=" * 70)
print("PHASE-2 DERIVED VALIDITY BAND (addendum sec. 4)")
print("=" * 70)
print("1. LOWER table boundary: ~150 km (retained; current radius_min =")
print("   6,528,000 m). Not extended downward -- density volatile/unvalidated")
print("   below, and the Knudsen floor (item 3) governs low-altitude validity.")
print("2. UPPER table boundary (collapse cut): NONE within the swept 130-1400 km")
print("   (Chunk 1: collapse RMS stays <= 5% green throughout, overall 0.490%,")
print("   storm 0.672%). The high cut is a soft confidence label and NON-BINDING")
print("   (drag ~ rho -> 0 up there). SIGNED-OFF grid extent: ~1400 km (radius")
print("   7,778,000 m) -- the full green-validated sweep, so high/elliptical LEO")
print("   above the old 1200 km ceiling no longer trips nuisance clamp warnings.")
print("3. KNUDSEN floor floor_altitude(L) (Chunk 2, conservative high-activity):")
for name, length_m in REFERENCE_BODIES:
    fa = floor_altitude(length_m, profile=CONSERVATIVE_HIGH)
    print(f"     {name:>11s}  L={length_m:6.2f} m  ->  {fa:6.1f} km")
print()


# ============================================================================
# Reconcile (i): accommodation anchor / Langmuir K (addendum sec. 5 item i)
# ============================================================================
print("=" * 70)
print("RECONCILE (i): accommodation anchor (alpha = 0.90) -> Langmuir K")
print("=" * 70)
K_exp = calibrate_K()  # cd_core: hardcoded anchor n_O=2.64e14, T=1284.0
K_gen = gen._calibrate_accommodation_K(msis.run, gen.ANCHOR_ALPHA)  # live MSIS anchor
# Verify cd_core's hardcoded anchor matches live NRLMSISE-00 at the same point.
anchor_row = np.asarray(
    msis.run([np.datetime64("2002-07-01T12:00")], [0.0], [0.0], [400.0],
             [200.0], [200.0], [[15.0] * 7], version=0)
).reshape(-1, 11)[0]
n_O_live, T_live = anchor_row[IDX["O"]], anchor_row[IDX["T"]]
print(f"  cd_core hardcoded anchor:  n_O = 2.640e+14   T = 1284.0 K")
print(f"  live NRLMSISE-00 anchor :  n_O = {n_O_live:.3e}   T = {T_live:.1f} K")
print(f"  anchor n_O rel diff = {rel_diff(2.64e14, n_O_live):.3%}   "
      f"T rel diff = {rel_diff(1284.0, T_live):.3%}")
print(f"  K_exp (cd_core)   = {K_exp:.4e} 1/Pa")
print(f"  K_gen (generator) = {K_gen:.4e} 1/Pa")
print(f"  K rel diff = {rel_diff(K_exp, K_gen):.3%}   "
      f"[{'PASS' if rel_diff(K_exp, K_gen) < 0.01 else 'FAIL'} < 1%]")
print()


# ============================================================================
# Reconcile (ii): relative-speed formula (addendum sec. 5 item ii)
# ============================================================================
print("=" * 70)
print("RECONCILE (ii): relative-speed formula")
print("=" * 70)
print("  cd_core.v_rel uses spherical r = R_earth + alt; the generator uses the")
print("  geocentric radius. Equal at the equator; the radius convention differs by")
print("  ~0.1-0.3% at high latitude -> a sub-1% speed difference (documented).")
print(f"  {'alt km':>7s} {'lat':>5s} {'v_exp m/s':>11s} {'v_gen m/s':>11s} {'rel diff':>9s}")
speed_max_rel = 0.0
for alt, lat in [(400.0, 0.0), (400.0, 45.0), (400.0, 80.0), (1200.0, 0.0), (1200.0, 80.0)]:
    v_e = v_rel(alt, lat)
    r_geo = gen._geocentric_radius(np.array([alt * 1e3]), np.radians(lat))[0]
    v_g = gen._relative_speed(np.array([r_geo]), np.radians(lat))[0]
    rd = rel_diff(v_e, v_g)
    speed_max_rel = max(speed_max_rel, rd)
    print(f"  {alt:7.0f} {lat:5.0f} {v_e:11.2f} {v_g:11.2f} {rd:9.4%}")
print(f"  max speed rel diff = {speed_max_rel:.4%}  (equator -> rotation-rate")
print(f"  constant only ~1e-5; latitude -> spherical-vs-geocentric radius)")
print()


# ============================================================================
# Shared algebra: per-species closed form + accommodation (machine precision)
# ============================================================================
print("=" * 70)
print("SHARED ALGEBRA: per-species C_D + accommodation (expect ~machine eps)")
print("=" * 70)
cd_max_rel = 0.0
for V, T, m, al in [(7500.0, 1000.0, 16 * U, 0.90), (7000.0, 900.0, 28 * U, 0.50),
                    (7800.0, 1200.0, 4 * U, 0.10), (6900.0, 700.0, 32 * U, 0.80)]:
    a = cd_sphere_species(V, T, m, al)
    b = gen._sphere_cd_species(np.array([V]), np.array([T]), m, np.array([al]))[0]
    cd_max_rel = max(cd_max_rel, rel_diff(a, b))
print(f"  per-species closed form: max rel diff = {cd_max_rel:.2e}")
acc_max_rel = 0.0
for n_O, T in [(2.64e14, 1284.0), (5.0e13, 900.0), (1.0e15, 1100.0)]:
    a = alpha_sesam(n_O, T, K_gen)
    b = gen._accommodation(np.array([n_O]), np.array([T]), K_gen)[0]
    acc_max_rel = max(acc_max_rel, rel_diff(a, b))
print(f"  accommodation isotherm : max rel diff = {acc_max_rel:.2e}")
print()


# ============================================================================
# END-TO-END (the headline sec. 5 assertion): both full pipelines, one MSIS set
# ============================================================================
print("=" * 70)
print("END-TO-END: both full C_D pipelines off identical NRLMSISE-00 rows")
print("=" * 70)
e2e_at_kexp = []   # both pipelines held at K_exp: isolates physics+speed. NOT
                   # "each its own K" -- K-independence is checked separately (the
                   # rel_diff(K_exp, K_gen) assert below), then combined in the verdict.
e2e_shared = []  # both driven off K_gen (isolates physics + speed from K)
e2e_equator = []  # lat = 0 subset with shared K (pure physics, radius coincides)
for cond in CONDITIONS:
    rows = _msis_rows(cond)
    rho = rows[:, IDX["rho"]]
    finite = np.isfinite(rho) & (rho > 0.0)
    rows = rows[finite]
    alts = ALTS_KM[finite]
    lat = cond["lat"]
    # generator pipeline (geocentric radius)
    r_geo = gen._geocentric_radius(alts * 1e3, np.radians(lat))
    speed = gen._relative_speed(r_geo, np.radians(lat))
    alpha_gen = gen._accommodation(rows[:, IDX["O"]], rows[:, IDX["T"]], K_gen)
    cd_gen = gen._sphere_cd_total(rows, speed, alpha_gen)
    cd_gen_Kexp = gen._sphere_cd_total(
        rows, speed, gen._accommodation(rows[:, IDX["O"]], rows[:, IDX["T"]], K_exp))
    for i, alt in enumerate(alts):
        cd_exp_Kexp, _ = cd_total(rows[i], alt, lat, K_exp)
        cd_exp_Kgen, _ = cd_total(rows[i], alt, lat, K_gen)
        e2e_at_kexp.append(rel_diff(cd_exp_Kexp, cd_gen_Kexp[i]))  # both at K_exp
        e2e_shared.append(rel_diff(cd_exp_Kgen, cd_gen[i]))     # shared K_gen
        if lat == 0.0:
            e2e_equator.append(rel_diff(cd_exp_Kgen, cd_gen[i]))

e2e_at_kexp = np.array(e2e_at_kexp)
e2e_shared = np.array(e2e_shared)
e2e_equator = np.array(e2e_equator)
n_pts = e2e_at_kexp.size
print(f"  {n_pts} shared (condition x altitude) points, 130-1450 km, lat -60..70")
print(f"  equator subset (shared K, pure physics): max rel diff = "
      f"{e2e_equator.max():.2e}  (radius conventions coincide)")
print(f"  shared K (physics + speed)             : max rel diff = "
      f"{e2e_shared.max():.4%}  mean {e2e_shared.mean():.4%}")
print(f"  physics+speed at K_exp (both models)   : max rel diff = "
      f"{e2e_at_kexp.max():.4%}  mean {e2e_at_kexp.mean():.4%}")

THRESHOLD = 0.01  # << 1% (well inside the sec. 3.1 green line)
verdict = "PASS" if e2e_at_kexp.max() < THRESHOLD else "FAIL"
print()
print("=" * 70)
# The two pipelines genuinely differ only in their Langmuir-K calibration, so the
# full independent agreement = (physics+speed agreement at a shared K) x (K agreement).
# Report both factors rather than a single "independent" number that holds K fixed.
print(f"VERDICT: the two C_D models' physics+speed agree to {e2e_at_kexp.max():.4%} at a "
      f"shared K; their independently-calibrated K agrees to {rel_diff(K_exp, K_gen):.4%} "
      f"-> full independent agreement is bounded by the product, << 1%  [{verdict}]")
print("=" * 70)
assert e2e_at_kexp.max() < THRESHOLD, (
    f"model cross-validation FAILED: max rel diff {e2e_at_kexp.max():.4%} >= 1% -- "
    "reconcile before regenerating the table (addendum sec. 5)"
)
assert rel_diff(K_exp, K_gen) < 0.01, "Langmuir K calibration diverged >= 1%"
assert cd_max_rel < 1e-9 and acc_max_rel < 1e-9, "shared algebra is not identical"
print("All sec. 5 reconciliations and the end-to-end agreement check PASS.")
