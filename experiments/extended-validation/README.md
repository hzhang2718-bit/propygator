# Extended Validation — drag propagations, TLE fitting tests, and table noise

Evidence tree for the study contracted in `docs/extended-validation-updated.md`.
**The contract wins on every conflict**; `docs/features.md` and
`docs/architecture.md` win over the contract. There is no build plan yet —
`docs/build-plan-extended-validation.md` belongs to the retired GRACE-lineage
design and must not be implemented from.

Every external claim propygator makes rests on one satellite (GRACE-FO 1). This
study widens that base in three parts: **drag propagations** over ~10 stratified
GRACE-FO windows plus **Swarm A/B** as a limited-information stress case,
**TLE fitting tests** against the playbook and the r/s gate, and **table noise**
measured on the GRACE-FO C/D formation twin.

## Layout

```
extended-validation/
├── README.md          this file
├── run_all.py         regenerate / --verify orchestrator
├── data/              raw truth + reference docs (gitignored, never committed)
│   └── reference/     third-party reference PDFs (see "Reference documents")
├── gracefo/           the GRACE-FO drag, TLE-fitting and twin runs
├── swarm/             the Swarm A/B leg (its own reader, config, drivers)
└── probes/            fitter / storm / fading-memory probes
```

## Running

Everything runs in the **propygator conda env** — the locked departure from
`docs/experiments_venv.md`, because propygator is the system under test. Nothing
here needs the `pymsis`/`scipy` generation venv: the table figures are `.npz`
lookups, not generator runs.

```
conda run -n propygator python run_all.py --list
conda run -n propygator python run_all.py --only twin
conda run -n propygator python run_all.py --verify --only twin
```

**Per-group `--verify` is the documented default.** A whole-study regenerate is
a multi-hour, deliberately scheduled act, not a pre-commit check.

## The frozen-evidence rule

`experiments/real-world-validation/` is **imported, never edited**. This tree
imports exactly two modules from it — `common.py` and `gracefo/gnv1b.py` — both
read-only. `find_window_files` and `parse_gnv1b` take arbitrary `Path`s, so the
Chunk 0 windows are read out of the frozen tree via `--data-root` without an
edit; `run_all.py` records that path in the group definition so the provenance
is visible. GRACE lands as a **new module here**, never as an additive change to
`gnv1b.py`'s `_SAT_NAMES`.

**No `src/` change on this branch.** A contradiction with a binding contract is a
bug report exiting to the normal fix path, never a silent amendment.

## The A/m convention — this study differs from v0.7.2 deliberately

`T = Cd_table / Cd_fitted` scales **exactly** as `A_ref` and as `1/m`
(contract §2.2), so both constants are part of the measurement rather than
bookkeeping. This study uses more authoritative figures than v0.7.2 did:

| | v0.7.2 | this study | source |
|---|---|---|---|
| `A_ref` | 1.027 m² (press-kit envelope) | **0.9551567 m²** | L1 Handbook Table 5, Front panel |
| mass | 600.0 kg (round launch mass) | **dry 569.914 + MAS1B tank gas** | Handbook Table 4 + JPL press kit + MAS1B |
| box height | 0.780 m (press-kit envelope) | **0.72388 m** | fitted so the ram face reproduces Table 5 |

Consequences, all worked out before the first run:

- **Levels move 5–7 %; ratios move under 1 %.** Every headline claim in the
  contract is a ratio of extremes precisely so that `T → cT` invariance holds.
- **A1 / Checkpoint A is untouched** — both twins share the convention, so it
  cancels exactly.
- **Legs C, C′, D and E are untouched** — r, s and forecast RMS never involve an
  A/m convention.
- **The v0.7.2 evidence stays frozen.** Its numbers are quoted as a *continuity
  row* and are never recomputed and never divided into a number produced here.
  Every driver prints the conversion beside them.

`A_ref` carries a bracket **[0.9552, 1.027] m²** with the point value at the
**lower** bound. The two sources reconcile through the boom, which Table 5
itemizes separately at 0.0461901 m²: `0.9552 + 0.0462 = 1.0014 m²` sits within
2.5 % of the envelope figure. `BoxFaceCd` requires a convex box and cannot
represent a boom, so the point value is the body panel alone.

**Known level systematic on the box, stated rather than tuned away (~6.5 %).**
Flattening the trapezoid loses slant-face area (−10.2 % of the non-ram faces,
worth ~−2.9 % of box CdA) and the boom is omitted (~−3.6 %). Both under-predict
drag, so they compound. Both are window-independent, so they cancel from every
ratio-of-extremes claim (B2, B5, A3, B3) and shift only the level, which this
study withholds. The one claim they touch is **B1**'s sign test on `T_box` near
1 — carry the correction explicitly on that row.

## Data access

- **GRACE-FO GNV1B** — PO.DAAC daily tarballs, Earthdata login, **148 MB/day**
  and the daily bundle is the only route (checked 2026-08-09; PO.DAAC does not
  serve `GNV1B` standalone). Each tarball carries **both** satellites, so
  GRACE-FO 2 costs zero downloads. The quiet, active and Gannon windows are
  already on disk in the frozen tree.
- **GRACE L1B** — PO.DAAC **monthly bundles, ~250 MB** ≈ 8 MB/day, roughly 18×
  cheaper per day than GRACE-FO. The granularity inverts, though: cost scales
  with **distinct months touched**, not days, so a 3-day window and a 10-day
  window cost the same. The upside is that a month bought is a month of days
  free, which makes GRACE window screening (sliding off a maneuver) cost
  nothing. Chunk 1 confirms the figure from the first delivered bundle and
  records the record format.
- **Catalog TLEs** — per-anchor Space-Track `gp_history` pulls. Close-formation
  pairs are a cross-tagging hazard; object identity is checked on every pull.
- **Raw truth files are never committed** (`data/` gitignored).

## Reference documents

Not committed — `data/reference/` is gitignored, consistent with how this repo
treats orekit-data and raw truth. Re-fetch:

- **GRACE-FO Level-1 Data Product User Handbook**, dated 2019-09-11 —
  <https://isdc-data.gfz.de/grace-fo/DOCUMENTS/Level-1/>
  Table 4 (per-satellite launch mass), Table 5 (faceted surface model),
  §3.2.3 (Science Reference Frame + the in-flight attitude convention),
  §4.2.17 (MAS1B format).
- **JPL GRACE-FO Launch Press Kit**, "Spacecraft and Instruments" —
  <https://www.jpl.nasa.gov/news/press_kits/grace-fo/mission/spacecraft/>
  Dimensioned envelope; propellant load.

Values extracted from these live as cited literals in `gracefo/gracefo_ext_common.py`.

## Findings at a glance

Filled in per chunk. Every chunk that produces a number resolves its
pre-registered predictions explicitly as **hit or miss**; a **withheld** claim is
written down as withheld.

| Chunk | Group | Results file | Headline |
|---|---|---|---|
| 0 | `twin` | `gracefo/results_twin.txt` | **A1 = −0.88 % / +0.41 % / +0.46 %** (quiet / active / storm) — a **≤ 0.88 %** floor against a Checkpoint A tolerance of 10 %. All criteria met in all three windows; the GO / INVESTIGATE call is the maintainer's. |

### Chunk 0 — GRACE-FO 2, the noise floor, Checkpoint A

Zero downloads. Both satellites over the three inherited windows: parse report,
MAS1B masses, measured formation geometry, t₀ round-trip, maneuver screen,
drag-off/drag-on pair, and the Run-3 scalar-Cd fit per satellite. The driver runs
all three windows in one process and closes with a computed `[A1 summary]` block
— **read the numbers there, not here.**

**M1, the measurement-noise floor — the first error bar this method has had.**
`T(C,w)/T(D,w)` deviates from 1 by at most **0.88 %**, and its window-to-window
spread (**1.35 %**) sits far below the spread in `T` itself (**131 %**), so **A1
is a hit on both halves.** The mandatory three-term label applies: *"noise floor
+ fore/aft asymmetry + any true A/m difference between the twins."* Term 3 is
measured from MAS1B at 0.001 / 0.102 / 0.097 %, so it accounts for essentially
none of the deviation. **No scaling with drag strength is claimed** — the
deviation is not monotone in it (0.88 / 0.41 / 0.46 % against drag-off
along-track of 44 / 1058 / 3812 m). It does change sign, which a fixed geometric
asymmetry would not.

**Fit resolution is part of the measurement.** The scalar-Cd fit terminates at
`CD_FIT_TOL = 0.002`, a golden-section lattice rung of 0.025–0.045 % in Cd —
about 20× below A1. At the v0.7.2 tolerance of 0.02 the rung is ~0.3 %, the same
size as A1 itself, and every deviation above was quantized rather than measured
(the storm window read 0.17 % instead of 0.46 %). **Any later chunk that
differences two fits inherits this constraint** — Chunk 2's sub-arc floor most of
all.

**Wiring cross-check against frozen v0.7.2.** The ballistic coefficient `B` is
convention-free, so it must reproduce despite the changed `A_ref` and mass:
measured **−0.02 / +0.08 / −0.11 %**, i.e. agreement within the fits' own
resolution — the frozen side is still quantized at ~0.3 % and cannot be
tightened, so no finer claim is available. The Run-3 along-track residuals also
land on the frozen values (1.87 vs 1.86 m; 6.30 vs 6.36 m; 118.93 vs 119.02 m),
and `T_sphere` bracketed up to the press-kit area reproduces v0.7.2's 1.4730 to
0.05 %, the residual being the mass.

**Attitude convention, resolved from the primary source and from the data.** The
Handbook (§3.2.3) puts the Roll axes anti-flight and in-flight for the leading
and trailing satellites, so the twins differ by a **180° yaw about the
nadir-aligned axis** — both keep the wide face nadir and only the ±X ends swap.
Front and Rear panels are both 0.9551567 m², so **A_ram is identical between the
twins**. Which twin leads is measured per window rather than taken from
literature: **C leads in all three**, sign constant.
