**This document needs future work**

# Extended Validation — drag propagations, TLE fitting tests, and table noise

Evidence tree for the study contracted in `docs/extended-validation-updated.md`.
**The contract wins on every conflict**; `docs/features.md` and
`docs/architecture.md` win over the contract. The working blueprint is
`docs/build-plan-extended-validation-updated.md`.

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
│   ├── reference/     third-party reference PDFs (see "Reference documents")
│   ├── tarballs/      TRANSIENT download staging; one tarball at a time,
│   │                  deleted as soon as its six members are extracted
│   └── gracefo/       one directory per window, named for the window, so
│       └── <window>/  --data-root behaves as it does on the frozen tree:
│                        GNV1B_<date>_<C|D>_04.txt.gz   truth ephemeris
│                        MAS1B_<date>_<C|D>_04.txt.gz   tank-gas mass
│                        THR1B_<date>_<C|D>_04.txt.gz   thruster log
│                      14 days x 3 products x 2 satellites = 84 files/window,
│                      ~269 MB/window, ~2.6 GB for all ten
├── gracefo/           the GRACE-FO table-noise, drag and TLE-fitting runs
│   ├── windows.py     the frozen ten-window list, its CSSI re-read, and this
│   │                  study's .gz finder                        (Chunk 1)
│   ├── thr1b.py       the tier-1 thruster parser                (Chunk 1)
│   ├── fetch_windows.py   download -> extract -> gzip -> screen (Chunk 1)
│   ├── run_screen.py  both maneuver gates -> results_screen.txt (Chunk 1)
│   ├── mas1b.py       the MAS1B mass parser
│   └── gracefo_ext_common.py   leg-wide geometry, fitter, force set
└── swarm/             the Swarm A/B leg (its own reader, config, drivers)
```

**The A/m convention** and **Findings at a glance / Chunk 0** below are
**retired-design text** (the `T` framing, Legs, Checkpoints, the superseded
`A_ref`); Chunk 2 rewrites them. Everything else on this page is current.

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

### Landing the truth data (Chunk 1, maintainer's step)

All commands on this page run from the study root (`experiments/extended-validation/`).

```
conda run -n propygator python gracefo/fetch_windows.py --all --dry-run  # URLs + budget
conda run -n propygator python gracefo/fetch_windows.py --all            # ~1.5-3 h
```

One day at a time: fetch, extract the six kept members, gzip them, run the
tier-1 THR1B screen when the window's fourteenth day lands, delete the tarball.
Idempotent — an interrupted run resumes by being re-run, and a partial transfer
resumes mid-file. Peak disk is the retained tree plus one 148 MB tarball.

Then the committed screening evidence, both gates over all ten windows:

```
conda run -n propygator python run_all.py --only screen              # ~1-1.5 h
conda run -n propygator python gracefo/run_screen.py --parse-only    # tier 1, no JVM
```

**`results_screen.txt` must be generated after Chunk 2's geometry rewrite.** The
tier-2 propagation reads `A_REF_M2` from `gracefo_ext_common.py`, which Chunk 2
moves from 0.9551567 to 1.0013468 m², so generating it earlier guarantees a red
`--verify` the moment Chunk 2 lands. The resolved value is printed in the
results header so any file says which geometry produced it.

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

- **GRACE-FO daily tarballs — GFZ ISDC, no login.**
  `isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04/<year>/gracefo_1B_<date>_RL04.ascii.noLRI.tgz`
  serves the identical JPL RL04 bundles PO.DAAC does, from an open directory,
  which is what makes `fetch_windows.py` scriptable without Earthdata auth. The
  `ACX` and `LRI` variants hold only accelerometer and laser-ranging products;
  GNV1B, MAS1B and THR1B are all in `noLRI`, so there is **no lighter route to
  THR1B and no way to screen before downloading.** Each tarball carries **both**
  satellites, so GRACE-FO 2 costs zero extra downloads.
  Verified 2026-08-17: every day of all ten windows is served (archive currently
  runs through 2026-07-30), and **no checksums are published** — hence
  `fetch_windows.py`'s functional integrity check (Content-Length match, tarball
  opens, all six members present and non-empty).
  Note `low_2019_12` straddles two yearly directories (2019-12-23 → 2020-01-05),
  so the URL year comes from each **day**, never from the window's `t0`.
- **Measured budget** (one delivered tarball, 2019-11-14): **148 MB/day in,
  19.23 MB/day retained** gzipped for both satellites — 8× smaller. Ten windows
  = 140 days = **~20.2 GB downloaded, ~2.6 GB retained.** Sustained ISDC
  throughput measured at **2.1–3.6 MB/s**, so the full pull is **~1.5–3 h** plus
  ~21 min of extract/gzip CPU. Single-threaded and resumable (HTTP Range);
  re-running skips days already extracted.
- **Parse cost, measured:** **0.6 s/day/satellite from the extracted `.gz`**
  against 4.7 s from a tarball — the tarball cost is `tarfile.getmembers()`
  scanning 148 MB, which the extracted tree skips entirely. So the build plan's
  conditional `.npy` cache (Chunk 3, "if it turns out to cost minutes rather
  than seconds") is **not needed**: a 14-day two-satellite load is ~17 s.
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
