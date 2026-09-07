# Earth radiation pressure — Orekit Knocke bug evidence + parked runtime

Evidence for the **Outcome** note of `docs/history/general-upgrades-1.md` "Planetary
Third-Body & Earth Radiation Pressure": the `earth_radiation` feature (build
plan `docs/history/build-plan-additional-perturbations.md`, Chunks 2–3) is
**blocked** — `KnockeRediffusedForceModel` is defective in every Orekit release
installable in the pinned env, so the fully-built Chunk-2 runtime was reverted
rather than shipped, and is parked here as a patch.

**Two independent defects.** The first is fixed upstream; the second is not, so
the block stands.

| # | defect | status |
|---|---|---|
| 1 | crown loop bounded by `asin(R/r)` instead of `acos(R/r)` | **fixed in Orekit 13.1.6** (2026-06-03) |
| 2 | Lambertian emission cosine computed as the geocentric central angle | **present in 13.1.7.1** — ERP ~1.98× hot at LEO |

**Reference-only.** Not shipped, not in CI, outside `testpaths`. Runs in a conda
env (starts the JVM, needs orekit-data):

```
conda run -n propygator python knocke_bug_probe.py > knocke_bug_probe_results.txt
conda run -n <13.1.6+ clone env> python knocke_cosine_probe.py > knocke_cosine_probe_results.txt
```

## Bug 1 — the horizon bound (fixed in 13.1.6)

Orekit discretizes Earth's visible cap into crowns of Earth-central angle.
Through **13.1.5** the crown loop was bounded by `FastMath.asin(R/r)` — the
*satellite-centered* horizon half-angle — where the correct Earth-central bound
is `acos(R/r)`. Verified by reading the source at the release tags:

| Orekit tag | released | crown bound | cosine (bug 2) |
|---|---|---|---|
| 13.1 … 13.1.4 (conda-forge `orekit_jpype 13.1.4.0` — **installed**) | ≤ 2026-02-08 | `asin(R/r)` — buggy | present |
| 13.1.5 (PyPI `orekit-jpype 13.1.5.0`) | 2026-05-02 | `asin(R/r)` — buggy | present |
| **13.1.6** | **2026-06-03** | `acos(R/r)` — fixed | present |
| 13.1.7 (conda-forge `orekit_jpype` 13.1.7.0 / 13.1.7.1) | 2026-07-04 | `acos(R/r)` — fixed | **present** |

The wrong bound integrated a ~70° cap at LEO (true ~20°) and an ~8.7° cap at GEO
(true ~81°), so the error **flipped sign with altitude**. Measured on 13.1.4.0
(`knocke_bug_probe_results.txt`): ~2.4× hot at LEO in eclipse, ~10–20× cold at
GEO. Measured on 13.1.7.1 (`knocke_bug_probe_results_13.1.7.txt`): GEO rose
**39×** (6.23e-12 → 2.41e-10 m/s²) and the altitude flip is gone — bug 1 is
fixed, confirmed both in source and in behavior.

A second finding from the 13.1.4.0 ladder still stands: the model only converges
for `angularResolution` ≲ 2°, and the fix changes the LEO cap, so any resolution
constant must be re-benchmarked after an upgrade.

## Bug 2 — the Lambertian cosine (present in 13.1.7.1)

`KnockeRediffusedForceModel.computeElementaryFlux`, Orekit 13.1.7 line 486:

```java
// Get satellite viewing angle as seen from current elementary area
final double cosAlpha = Vector3D.dotProduct(elementCenter, satellitePosition) /
                        (centerNorm * satellitePosition.getNorm());
```

used at line 518 in the Lambertian slot:

```java
final Vector3D projectedAreaVector = r.scalarMultiply(elementArea * cosAlpha /
                                                     (FastMath.PI * rNorm * rNorm * rNorm));
```

`cosAlpha` is the cosine of the **geocentric** angle between the element and the
satellite. The factor the formula needs is the **emission** cosine — between the
element's own outward normal and the element→satellite vector:

```java
cosTheta = Vector3D.dotProduct(r, elementCenter) / (rNorm * centerNorm);   // r = satPos - elementCenter
```

The two agree only at the sub-satellite point. At the true horizon `cosTheta` is
0 while `cosAlpha` is R/r — **0.94 at 400 km** — so limb elements are weighted
almost as heavily as the nadir element instead of vanishing. Analytically the
resulting inflation → 2 as r → R.

Two indications this is a coding slip rather than a modelling choice: the
comment above the line names the correct quantity ("as seen from current
elementary area"), and the `if (cosAlpha > 0)` visibility guard below it is dead
code under the current formula, since the crown loop already stops at the
horizon.

### Measured cost

`knocke_cosine_probe.py` re-implements Orekit's exact discretisation in numpy —
center cap, crowns from 1.5·res, its sector-area formula, its Legendre
emissivity/albedo models, `ES_COEFF` flux — and runs it twice, as coded and with
only that cosine corrected. The as-coded replica reproduces the live Orekit
acceleration to **1.0000** on all three states, which is what makes the
corrected column trustworthy (`knocke_cosine_probe_results.txt`, 13.1.7.1):

| state | live Orekit | cosine fixed | inflation |
|---|---|---|---|
| LEO 400 km, eclipse | 8.6622e-09 | 4.3661e-09 | **1.984×** |
| LEO 400 km, lit | 1.4333e-08 | 7.2100e-09 | 1.988× |
| GEO | 2.4108e-10 | 2.0007e-10 | 1.205× |

With the cosine corrected the eclipse case matches the closed-form isotropic
sphere anchor `Cr (A/m) (e·S/4) (R/r)² / c` to **1.2%** — evaluated at the
model's own flux-weighted mean emissivity (0.551 at that latitude, not the
uniform 0.68 the hand anchor assumes). The residual is therefore fully
explained: **no third defect.**

### Why `knocke_bug_probe.py` reads 1.69 on 13.1.7.1

The two bugs compounded in the original 2.42 reading: cap bound ×1.43, cosine
×1.98, against an anchor that assumes a uniform e = 0.68 and a 1 AU Sun while
the model uses e ≈ 0.55 at 51.6° latitude and a January Sun (×1.039). 1.69 lands
in that probe's `UNEXPECTED` band (PASS is 0.5–1.5, BUG is > 1.7) — the STOP
gate correctly refused to flip.

**Expected reading once bug 2 is fixed: ~0.85, not 1.00** — that is the
emissivity and Sun-distance offset above, and it is inside the PASS band. Do not
"fix" the probe's bands to chase 1.00.

## Environment findings (2026-09-06)

- `orekit_jpype` 13.1.7.0 and 13.1.7.1 are on conda-forge; the working
  `propygator` env is still 13.1.4.0.
- **`orekit_jpype 13.1.7.x` requires `jpype1 1.7.1.*`**, so `environment.yml`'s
  `jpype1=1.5.*` pin blocks the upgrade — a fresh `conda env create` still lands
  13.1.4.0, and CI is *not* silently exposed to 13.1.7. Adoption is a two-pin
  change, not one.
- `jpype1 1.7.1` carries no `openjdk` constraint, so OpenJDK 17 still resolves.
  The clone env used here built clean at **orekit_jpype 13.1.7.1 / jpype1 1.7.1 /
  OpenJDK 17.0.18 / Python 3.11**, and was deleted after use.
- Note for the eventual upgrade: `jpype1 1.5.2 → 1.7.1` is the larger boundary
  move, since every `@JImplements` proxy rides on it. Measured in the clone env
  before deleting it: **the full suite passes unchanged — 1105 passed**,
  including the three real-world pinned modules, the fitter pins, the plot
  snapshots and `test_stack_compat.py`. The upgrade moves no pinned number.

## Files

- `knocke_bug_probe.py` — self-contained probe (SRP control, LEO/GEO resolution
  ladders, PASS/FAIL verdict; ASCII-only stdout). **This is the resume sanity
  check** — run it against any new env first.
- `knocke_bug_probe_results.txt` — captured stdout, 2026-07-05, orekit_jpype
  13.1.4.0 (both bugs present; verdict BUG PRESENT, 2.42).
- `knocke_bug_probe_results_13.1.7.txt` — captured stdout, 2026-09-06,
  orekit_jpype 13.1.7.1 (bug 1 fixed, bug 2 present; verdict UNEXPECTED, 1.69).
- `knocke_cosine_probe.py` — the bug-2 replica; needs an Orekit ≥ 13.1.6 env.
- `knocke_cosine_probe_results.txt` — captured stdout, 2026-09-06, 13.1.7.1.
- `erp-runtime-chunk2.patch` — the complete, reverted Chunk-2 runtime as a
  `git diff` against commit `a9259dc` (config field + serializer token +
  `_build_earth_radiation_force` + widened metadata gates + docstrings + tests;
  all tests passed except the effect-envelope test, whose failure exposed bug 1).
  Verified 2026-09-06 to still apply clean. Excluded from the trailing-whitespace
  pre-commit hook (diff context lines are significant).

## Resume recipe (when an Orekit carrying **both** fixes exists)

1. **Clone-and-test env** — never mutate the working env: copy
   `environment.yml`, bump the `orekit_jpype` **and** `jpype1` pins,
   `conda env create` under a new name, run `pytest` (stack-compat included).
2. **Run both probes** in the new env. `knocke_bug_probe.py` must read ~0.85
   (LOOKS FIXED), and `knocke_cosine_probe.py` must show an inflation of
   **1.000×** — that is the bug-2 gate.
3. **Re-apply the runtime**: `git apply experiments/earth-radiation/
   erp-runtime-chunk2.patch` (or replay Chunk 2 from the archived plan if the
   seams have drifted). Recalibrate the effect-envelope test bounds against the
   fixed physics.
4. **Run the resolution benchmark** (`docs/build-plan-earth-radiation.md` Chunk
   A3) to pick `_EARTH_RADIATION_ANGULAR_RESOLUTION` — pre-fix sweep numbers do
   not carry over.
5. Ship as its own small branch, with the contract section's Outcome note
   updated.

**Upstream first.** Bug 2 has not been reported. Filing it (the one-line fix
above, this replica as the reproduction, the measured factors) is the cheapest
path to unblocking the feature.
