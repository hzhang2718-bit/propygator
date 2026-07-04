# ECEF InPlaneTracking benefit study (build-plan Chunk 1 + Chunk 4 evidence)

Evidence for `docs/history/build-plan-ecef-attitudes.md` (binding contract:
`docs/general-upgrades-1.md` "ECEF InPlaneTracking" -> Evidence gate): what
does `InPlaneTracking(velocity_reference="ecef")` buy for the headline
feathered sail?

**Reference-only.** Not shipped, not in CI, outside `testpaths`. Unlike the
`drag-coefficient-verification/` experiment this one needs **no throwaway
venv** — every piece is shipped, so it runs in the **propygator conda env**
(starts the JVM, needs orekit-data):

```
conda run -n propygator python ecef_feather_benefit.py > ecef_feather_benefit_results.txt
```

(`--days 0.15` is the quick smoke mode; the committed evidence is the 5-day
default. Full run ~1-3 min wall.)

## Method

Three attitude legs over the same scenario, all with `BoxFaceCd.default()`:
the shipped `InPlaneTracking()` (**inertial** reference), the shipped
`InPlaneTracking(velocity_reference="ecef")` (the headline leg), and the
Chunk-1 `CustomAttitude` **stand-in** law — the contract's exact axis
construction (+Y on `v_rel = v − ω⊕×r`, +Z best-effort on the orbit normal,
X = Y×Z) with a hardcoded `ω⊕` about EME2000 +Z — kept as a cross-check of the
shipped mode. Scenario: 1 m² × 1 cm sail, **0.5 kg** (Chunk-4 realistic mass;
the Chunk-1 gate ran 2.0 kg), 500 km circular SSO (i = 97.4°, near-max
out-of-plane wind), 2002-07-01 solar max (the Tier B epoch), gravity 70×70 +
Sun/Moon + NRLMSISE-00 + SRP, 5 days.

**History:** the Chunk-1 Checkpoint A gate ran *before the runtime existed*,
using the stand-in law as the ecef leg (2 kg: divergence −63.3 km / 5 d, drag
ratio 1.12×) → **GO**. The Chunk-4 refresh swapped in the shipped mode and the
0.5 kg mass; the docs quote the shipped-mode numbers below.

## Files

- `ecef_feather_benefit.py` — the driver (ASCII-only stdout; cp1252 redirect).
- `ecef_feather_benefit_results.txt` — captured stdout (the committed numbers).
- `ecef_feather_benefit.png` — (a) AoA histories, (b) assembled per-face CdA,
  (c) along-track divergence + per-leg drag effects.

## Result summary (2026-07-04 shipped-mode run, 0.5 kg)

- Inertial-leg big-face AoA oscillates 0 → **3.707°** (predicted ~3.75°),
  mean 2.36°; the shipped ecef leg holds ~0 (reads 0.0000° against the
  diagnostic wind).
- Mean per-face CdA: 0.2170 m² (inertial) vs 0.1955 m² (ecef) — **1.11×**;
  the propagated drag effects differ by **1.12×** (2414.7 vs 2157.1 km
  along-track over 5 d) — internally consistent.
- **Headline: the attitude reference alone moves the sail −272.7 km
  along-track over 5 days** (~11 % of the total drag effect; drag dominates
  SRP ~10,600× here).
- **Shipped-vs-stand-in cross-check: 0.02 km max along-track over 5 days** —
  the shipped primary-slot provider and the independently-written feathered
  law agree to the pole-offset scale, against a 273 km signal.
