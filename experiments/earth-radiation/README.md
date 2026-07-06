# Earth radiation pressure — Orekit Knocke bug evidence + parked runtime

Evidence for the **Outcome** note of `docs/general-upgrades-1.md` "Planetary
Third-Body & Earth Radiation Pressure": the `earth_radiation` feature (build
plan `docs/history/build-plan-additional-perturbations.md`, Chunks 2–3) is
**blocked** — `KnockeRediffusedForceModel` is defective in every Orekit
release installable in the pinned env, so the fully-built Chunk-2 runtime was
reverted rather than shipped, and is parked here as a patch.

**Reference-only.** Not shipped, not in CI, outside `testpaths`. Runs in the
**propygator conda env** (starts the JVM, needs orekit-data):

```
conda run -n propygator python knocke_bug_probe.py > knocke_bug_probe_results.txt
```

## The bug

Orekit's `KnockeRediffusedForceModel` discretizes Earth's visible cap into
crowns of Earth-central angle. Through **Orekit 13.1.5** the crown loop is
bounded by `FastMath.asin(R/r)` — the *satellite-centered* horizon half-angle
— where the correct Earth-central bound is `acos(R/r)`. Verified by reading
the source at the release tags (2026-07-04/05):

| Orekit tag | released | crown-loop bound |
|---|---|---|
| 13.1 … 13.1.4 (conda-forge `orekit_jpype 13.1.4.0` — **installed**) | ≤ 2026-02-08 | `asin(R/r)` — **buggy** |
| 13.1.5 (PyPI `orekit-jpype 13.1.5.0`, newest wrapper anywhere) | 2026-05-02 | `asin(R/r)` — **buggy** |
| **13.1.6** | **2026-06-03** | `acos(R/r)` — **fixed** |
| 13.1.7 / master | 2026-07-04 | `acos(R/r)` — fixed |

The wrong bound integrates a ~70° cap at LEO (true: ~20°) and an ~8.7° cap at
GEO (true: ~81°), so the error **flips sign with altitude** — the probe's
fingerprint (measured, converged resolution): **~2.4× hot at LEO even in
eclipse** (1.24e-8 vs the 5.13e-9 m/s² IR-only anchor) and **~10–20× cold at
GEO** (~5e-12–1e-11 vs the ~1.3e-10 IR-only anchor). The SRP control matches
theory to 0.1%, validating the probe pattern. A second, independent finding:
the model only converges for `angularResolution` ≲ 2° (15° is ~7× inflated at
LEO), so any future resolution constant must be re-benchmarked **after** the
fix (the fixed, smaller LEO cap changes the convergence behavior).

## Files

- `knocke_bug_probe.py` — self-contained probe (SRP control, LEO/GEO
  resolution ladders, PASS/FAIL verdict; ASCII-only stdout). **This is the
  resume sanity check** — run it against any new env first.
- `knocke_bug_probe_results.txt` — captured stdout (the committed numbers,
  2026-07-05, orekit_jpype 13.1.4.0).
- `erp-runtime-chunk2.patch` — the complete, reverted Chunk-2 runtime as a
  `git diff` against commit `a9259dc` (config field + serializer token +
  `_build_earth_radiation_force` + widened metadata gates + docstrings +
  tests; all tests passed except the effect-envelope test, whose failure is
  what exposed the bug). Excluded from the trailing-whitespace pre-commit
  hook (diff context lines are significant).

## Resume recipe (when an orekit_jpype wrapping Orekit >= 13.1.6 exists)

1. **Clone-and-test env** — never mutate the working env: copy
   `environment.yml`, bump the `orekit_jpype` pin, `conda env create` under a
   new name, run `pytest` (stack-compat included) there.
2. **Run this probe** in the new env — the verdict must flip to LOOKS FIXED
   (LEO eclipse within ~±50% of the IR-only anchor).
3. **Re-apply the runtime**: `git apply experiments/earth-radiation/
   erp-runtime-chunk2.patch` (or replay build-plan Chunk 2 from the archived
   plan if the seams have drifted). Recalibrate the effect-envelope test
   bounds against the fixed physics.
4. **Run the Chunk-3 resolution benchmark** (archived build plan) to pick
   `_EARTH_RADIATION_ANGULAR_RESOLUTION` — do not reuse pre-fix sweep numbers.
5. Ship as its own small branch per the general-upgrades rhythm, with the
   contract section's Outcome note updated.
