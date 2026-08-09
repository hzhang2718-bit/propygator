# propygator — Extended Validation Study: the GRACE lineage, the density-bias lever, and the fitting playbook under transfer

> **Status: BUILD CONTRACT (draft, not started).** This is a **validation study, not a
> feature** — no public API is added or changed on its branch, so there is no
> `features.md` section to write. The binding outputs are **evidence**: committed
> experiment results, a findings doc, a revised playbook, and pinned regression tests.
> The chunked build plan (`docs/build-plan-extended-validation.md`) is derived from this
> document. **This is not itself a build plan** — it carries no chunk sequencing, no
> per-file work lists, and no session sizing.
>
> Where this document and a *non-binding* doc conflict (`tle-fitting-playbook.md`,
> `tle-fit-strategy-findings.md`, `real-world-validation-findings.md`), **this one wins**
> until the wrap-up folds it back (§1). Where it appears to conflict with a *binding*
> contract (`features.md` §1.1/§1.2, `architecture.md`), the binding contract wins and the
> conflict is a **bug report**, handled on the normal fix path — this study never silently
> amends a shipped contract (§1, the no-API-change rule).
>
> **Supersedes the Swarm-based draft of 2026-08-03/08-04**, retired 2026-08-08. That draft
> proposed Swarm A + Swarm B as the second bus; §2.1 and §12 record why the body set
> changed and what the change costs.
>
> Archive to `docs/history/` at wrap-up, alongside its build plan.

---

## 0. Purpose & scope

The v0.7.2 real-world validation study and the v0.8.0 TLE fit-strategy experiment produced
propygator's entire external evidence base, and **all of it rests on one satellite**:
GRACE-FO 1, ~490 km, near-polar, a conventional ram-dominated bus, one window per drag
regime. `tle-fit-strategy-findings.md` §1 says so plainly — the r/s thresholds, the regime
arms, the fitted-Cd density lever, and the Checkpoint-B "the box adds only absorbable
scale" deferral are all **bets on transfer**, taken with wide margins but never tested
outside their own data.

This study takes those bets across the **GRACE lineage**: GRACE-FO 2 (a formation twin,
already on disk), and original GRACE A/B (the same bus lineage, 2002–2017, spanning a full
solar cycle and a wider drag-level range). Four goals, in the maintainer's ordering:

1. **The numerical propagator under drag, and what can honestly be said about the two
   shipped Cd tables** — the drag stack replicated on new bodies and new epochs, an
   empirical measurement-noise floor established for the first time, and the density-model
   bias measured and **reported as a curve**, quoted beside the tables' own modelled response
   with the attribution between them explicitly declined (§4, §5, §2.5).
2. **The fitting playbook at scale, against the catalog on a fair footing** — the playbook
   arms replicated across many more anchor-window combinations than the strategy
   experiment's 9, and the `tle-fit-strategy-findings.md` route-4 **matched-staleness**
   catalog comparison that turns "crushes a stale catalog" into a same-footing claim (§6).
3. **The r/s gate under transfer and under stress** — thresholds **frozen** as
   pre-registered predictions, replicated across a wide drag-level range on one bus
   lineage, plus a storm library that attacks the gate's one dangerous failure mode
   (§6, §7).
4. **A verdict on fading-memory fitting** — the pre-registered promotion bar in
   `tle-fit-strategy-findings.md` §3, executed and resolved. **Default outcome is defer**;
   promotion requires clearing the bar as written (§8).

**In scope:** GRACE-FO 2 activation and the twin noise floor; GRACE truth acquisition and
leg configuration; the drag-stack runs at the new points; the density-bias curve and its
LST stratification; the 2008–09 known-answer anchor; the table analysis that survives §2's
identifiability argument; playbook/r-s replication and matched-staleness catalog parity;
the State-path × a-priori-table composition rows; the storm library; the fading-memory
τ-sweep and its checkpoint; the findings doc, playbook revision, pinned tests, README and
notebook reconciliation.

**Out of scope (named, deliberate):**

- **Any change to `src/`.** No new public name, no signature change, no config field, no
  `features.md` edit. If Checkpoint D promotes fading memory, that is a **separate feature
  branch off `main` after this study merges** (§11) — the Chunk 5/6/7 pattern from
  v0.7.3/v0.8.0. The symmetric rule also binds: if Checkpoint A's INVESTIGATE arm confirms
  a defect, the fix lands on `main` and **every already-committed group is re-run and
  re-recorded** before the study resumes (§9).
- **Swarm A and Swarm B.** Retired from the design 2026-08-08. The reasoning is in §2.1 and
  §12; the short form is that Swarm's geometry and mass bookkeeping error swamps the
  quantity the table leg exists to measure, and that a Swarm row would look like a geometry
  test without being one. **A genuine bus contrast is a named follow-on** (§10), and its
  better candidate is TerraSAR-X / TanDEM-X, not Swarm.
- **The NRLMSISE-00 ap-history mode** (`withSwitch(9, -1)`). It is a shipped-code change
  that would move every storm-time number in the repo; it needs its own study, with this
  study's committed storm windows as its ready-made test cases. Every storm result here is
  explicitly a result **for the daily-Ap-driven model as shipped** (§7).
- **The `box_and_panels` fitted-geometry upgrade** (the standing Checkpoint-B deferral).
  This study re-tests the deferral's premise (§5) but does not lift it; if the premise
  fails, that elects a follow-on, it does not authorize the upgrade here.
- **`earth_radiation`** (parked; the upstream blocker is lifted but the resume is a
  separate `feature/` branch off `main`) and the edge-on / high-A/m sail regime, for which
  no public POD truth exists.
- **Accelerometer-derived densities** (ACC1B and the published thermosphere-density
  products). They are inverted under an assumed Cd model and measure the same ρ·Cd
  product, so they cannot break §2's degeneracy — only relocate it. Named here because
  they look like an obvious fix and are not.

---

## 1. Relationship to existing docs (read this first)

| Doc | Relationship | What may change |
|---|---|---|
| `docs/features.md` §1.1 / §1.2 | **READ-ONLY — under test** | Nothing. The study reads these as the contracts being measured. A contradiction is a bug report, not an amendment. |
| `docs/architecture.md` §4 / §10 / §11 | **READ-ONLY — honored** | Nothing. §11 supplies the pinned-reference-data precedent the new tests extend. |
| `docs/tle-fitting-playbook.md` | **REVISED (this study supersedes it at wrap-up)** | Evidence base widens from one satellite to four across two missions and two decades; the r/s thresholds are either **re-labelled as transfer-validated** or **corrected**; a new **s-gate domain-of-validity** statement is added (§7); the catalog claim is restated on matched-staleness footing (§6). |
| `docs/tle-fit-strategy-findings.md` | **CLOSED IN PART** | §2 routes 1 (more windows), 2 (second satellite), 3 (storm library), 4 (matched staleness) and 6 (State-path composition) are **executed** here; route 5 (refit-cadence sweep) stays open. §3 (fading memory) is **resolved** by Checkpoint D. Archive to `docs/history/` at wrap-up if nothing but route 5 survives. |
| `docs/real-world-validation-findings.md` | **EXTENDED + CORRECTED (prose only)** | Gains a cross-reference to the new findings doc; its §4 fitted-Cd-lever and §5 table claims are re-scoped from "measured on GRACE-FO 1" to whatever the transfer shows. Its **numbers are not edited** — but two *claims* resting on the retracted DSMC band are withdrawn by dated correction note at wrap-up (§9, "The DSMC correction"). |
| `experiments/real-world-validation/` | **FROZEN — import-only; one additive prose block** | No code, constant, or results file changes — and with Swarm retired, **nothing in this study can force one**. New code imports `common.py` and `gracefo/gnv1b.py`; it never edits them. GRACE lands as a **new module in the new tree**, not as an additive change to `gnv1b.py`'s `_SAT_NAMES`. The single exception is a **correction block appended to `gracefo/README.md`** for the DSMC retraction — prose only, no number, no `--verify` impact (§9). |
| `experiments/tle-fit-strategy/` | **FROZEN — pattern source** | Nothing. Probes 1–4 are the templates the new probes follow; the GRACE-FO 1 rows they contain are the comparison baseline. |
| `notebooks/07_tle_fitting.ipynb` §9, `notebooks/00_showcase.ipynb` | **RECONCILED at wrap-up** | Both transcribe playbook/validation numbers by hand (CLAUDE.md). If the playbook changes, both must be updated — `00_showcase.ipynb` additionally requires a fresh static HTML export. Any edits to the notebooks should aim to **not** make them longer.|
| `README.md` "Validation" | **EXTENDED** | One paragraph: the evidence base is no longer single-satellite. |

**New artifacts (not supersessions):** `experiments/extended-validation/` (the evidence
body + orchestrator), `docs/extended-validation-findings.md` (the findings record), and new
pinned tests under `tests/` (§9). **No new public name, export, exception, metadata key, or
signature parameter** — the `__init__.py` re-export list and the public type inventory are
untouched.

---

## 2. The measurement design (the core of this contract)

### 2.1 What an orbit residual can and cannot identify

An orbit residual constrains only the **product ρ·Cd·A/m**, so a scalar-Cd fit is forced to
`ρ_model·Cd_fitted·(A/m)_asm = ρ_true·Cd_true·(A/m)_true`. Solving and dividing the known
table value through gives, for satellite *s* and window *w*:

> **T(s, w) = Cd_table / Cd_fitted = Cd_table / (Cd_true·κ·D) ≡ E(s) / D(w)**

with **D ≡ ρ_true/ρ_model** the density-model bias for that window (common-mode across
bodies only where they share altitude, LST and epoch), **κ ≡ (A/m)_true/(A/m)_asm**, and
**E ≡ Cd_table/(Cd_true·κ)** the body's combined table × geometry × bookkeeping error
(window-independent only to first order). The factoring is forced, not chosen. Then:

- **Ratios across bodies at fixed window** give **E ratios** — D cancels.
- **Variation across windows at fixed body** gives **D variation** — E cancels.
- **The level is never identified.** Scale every E *and* every D by the same *c* and every
  orbit observable is unchanged. **Exactly one degree of freedom is unresolvable, and no
  amount of orbit data touches it.**

**Consequence, and it is the reason this contract exists in its current form: the claim
"the shipped Cd tables carry a table error of X %" is unearnable by any orbit-only design,
and is withdrawn.** The Swarm-based draft made that claim conditional on its prediction B2;
B2 would have yielded `E(SwarmB)/E(GRACE-FO)` — a *body-to-body* ratio, not a level — and
`E(SwarmB)` was in any case dominated by an excluded 4 m boom, a base-averaged trapezoid, a
literature frontal area, and an unpublished in-window mass history. The old design
maximized the very error term it existed to remove. **The honest replacements are §2.3's
four measurements.**

### 2.2 Two bookkeeping corrections that ride on every T

**T ∝ 1/m_assumed, exactly.** The orbit measures a ballistic coefficient `B = Cd·A/m`; the
Run-3 scalar fit converts it to a Cd using the *assumed* mass, `Cd_fitted = B·m/A`, while
`Cd_table` has no mass term at all.

**T ∝ A_ref for the sphere table, exactly.** `T = Cd_table · A_ref / (B_obs · m_asm)`. Only
the **box** table's `A_ref` cancels — its `Cd_table` is itself `ΣCd·A / A_ref` — and even
there the assumed box *dimensions* enter in full. The Swarm-based draft claimed the area
convention cancels; it does not, and that error is the same class as the mass correction
made 2026-08-04.

> **Every T is reported as a bracket over the assumed A/m, not over m alone.** The
> dependence is exact and closed-form, so the bracket is a scalar multiply on an
> already-computed number: no second run, no re-propagation.

**T_sphere is not a table metric at all.** With no geometry in the sphere model it measures
the assumed A/m against truth, times the true physical Cd. It is retained as a
*normalization convention* that makes windows and bodies comparable, and it is never quoted
as a statement about the sphere table.

### 2.3 The four measurements that replace the old design

| # | Measurement | Mechanism | What it earns |
|---|---|---|---|
| **M1** | **The measurement-noise floor** | GRACE-FO 1 vs 2 in the same windows: same bus, altitude, LST, ~180 km apart, so `T(C,w)/T(D,w)` should be 1 | The first empirical error bar on T. Everything downstream gets a pass criterion instead of an eyeball. |
| **M2** | **The density-bias curve `D(w)`, reported** | Many windows on one bus lineage, **LST-stratified** as well as activity-stratified | The curve itself as a *measurement*, quoted beside the tables' own modelled response over the same conditions — **without** an attribution between the two (§2.5). |
| **M3** | **A shape-transfer test on `D`** | The 2008–09 minimum on GRACE against that same body's own high-activity window | That the density-bias lever is a property of NRLMSISE-00 rather than of one epoch. **No purchase on the level** — that stays unresolved (§2.1). |
| **M4** | **The geometry statement** | A near-same-bus cross-check plus an explicit limit on the box table | An honest scope statement instead of an unsupportable geometry claim. |

**M1 is an upper bound, not an identity.** GRACE-FO 1 and 2 fly with a relative yaw so
their ranging horns face each other, putting opposite ends of the same trapezoid into the
wind. The taper is radial (bottom/top widths 1.943 / 0.690 m, the documented geometry note
at `gracefo_common.py:50-58`; `BOX_Z_M` at `:61` is their average), so `A_ram` is unchanged,
but appendage asymmetry is not. The measured deviation is therefore **noise floor + fore/aft
asymmetry + any true A/m difference between the twins** — an upper bound on the floor, which
is exactly what a pass criterion needs. The attitude convention is verified at chunk time,
not assumed.

> **The third term is a systematic, not noise, and the label must carry it.** Both twins are
> given the same assumed area and mass, so that shared constant cancels from §2.1's **κ** and
> `T(C,w)/T(D,w) = κ_D/κ_C = (A_true,D/A_true,C)·(m_true,C/m_true,D)` — **A1 measures the
> ratio of the twins' true A/m, times estimator noise.** A real A/m difference reproduces
> identically on every re-run, so
> folding it into "noise floor" inflates the band every cross-body claim is judged against.
> Bounding it is *optional refinement* — the area ratio is ≈ 1 by build-identical
> construction, and the mass ratio is bounded above by the total propellant loaded, since a
> spacecraft cannot expend more than it carried — but **the three-term label is mandatory**.

**M2's bound is withdrawn; the two numbers are reported side by side instead.** The earlier
form — "the tables' own dynamic range bounds how much of the observed variation can be
table-shape error" — is not a bound. Writing `log T = log ε − log D + const` with
`ε ≡ Cd_table/Cd_true`, bounding `Var(log ε)` by the table's own range holds only if
`Cd_true` varies no more than `Cd_table` does and in the same sense. If the true Cd responds
more strongly to composition than the table does, ε varies *more* than the table's range and
the bound fails. That conditional is unmeasurable from orbit data — it is the §2.1 problem
one level up, on the variance instead of the level — so **the "at least X % is density-model
bias" attribution is withdrawn along with the level claim.** What is reported instead is in
§2.5.

**M3 is a *shape* prediction, deliberately, and it needs no external anchor.** A density
model that over-predicts at deep solar minimum drives the fitted Cd low, because
`Cd_fitted = Cd_true·κ·D` (§2.1) and over-prediction means D < 1. GRACE-FO's committed quiet
of **1.98** against its own active **3.32** is that signature as a *ratio*. An absolute
reading is unavailable twice over: the 1.98 carries `GRACEFO_MASS_KG = 600.0`, a round launch
mass (`:38`), on `A_RAM_M2 = 1.027` (§2.2 — neither cancels), and this study has **no
external level anchor at all** (see M4 below). **M3 therefore predicts the deep-minimum point
sitting low *relative to the same body's own high-activity point*, and never anything else.**

**M3's circularity is partial and must be stated.** The 2008–09 thermospheric density
anomaly was itself established from orbital-drag-derived densities under assumed Cd models.
This is a cross-check between two drag-based paths using different objects, different
epochs and different reductions — agreement is meaningful, disagreement is diagnostic, and
neither is ground truth. The published magnitude is pulled with citations at chunk time,
**papers in hand, not recalled.**

**M4 has two parts, and both are limits.**

- **(a) GRACE ↔ GRACE-FO is a reported diagnostic, not a prediction.** Same bus lineage, so
  `E` is nearly the same by construction — but the ratio is
  `T(GRACE,w₁)/T(GRACE-FO,w₂) = [E_G/E_F]·[D(w₂)/D(w₁)]`, and the second bracket is 1 only if
  the two windows share a density bias. §5's own data puts the D-swing across the driver
  range at O(2), against an expected A1 floor of a few percent, so **"≈ 1" is not a testable
  expectation and is withdrawn as a pre-registered prediction.** Matching "at comparable
  activity" cannot pin D, because D depends on at least (F10.7, Ap, LST, altitude) — that
  premise is why M2 exists. `E` also does not cancel analytically: GRACE-FO's height is
  0.780 m (`gracefo_common.py:59`) against original GRACE's ~0.72 m, and launch masses differ
  (~487 vs ~600 kg). **The ratio is reported with its confounds enumerated and licenses
  nothing.** Pipeline validation across the 17-year gap comes from the *direct, unconfounded*
  checks instead — the A–B separation self-check, |r|, |v|, the t₀ round-trip and seam
  continuity (§3, Chunk 1) — which do that job better and without a physics assumption.
- **(b) The box table is not validatable against flight data at all.** `BoxFaceCd` requires
  a convex box with no arrays; `cd_box_benefit_study` found its material benefit is in
  large, flat, edge-on bodies; and high A/m — what makes drag measurable — comes from
  deployed arrays. **"True convex box" and "strong drag signal" are anti-correlated by
  construction.** No satellite fixes this. What survives is the absorbable-scale retest (§5).

> **DSMC is retracted, and this study therefore has no external level anchor at all.** The
> earlier design named published DSMC Cd as the one anchor on the unresolvable degree of
> freedom, resting on `DSMC_CD_BAND = (2.65, 4.5)` (`gracefo_common.py:65`, frozen). Checked
> 2026-08-08: the band's **upper edge is mis-sourced**. Its second citation, arXiv 2503.21651,
> is Leipner et al., *Evaluation of Deployable Solar Panels on GRACE-like Satellites by
> Closed-Loop Simulations* — a gravity-recovery simulation that *varies* Cd as an input, "from
> 2.25 (standard) to **4.5 (double-panel)**." The 4.5 is an assumed parameter for a
> hypothetical **double-deployable-panel** configuration: neither a DSMC computation nor the
> GRACE bus. The lower edge traces to a genuine DSMC study of the GRACE bus (Mehta,
> McLaughlin & Sutton 2013, *Adv. Space Res.* 52(12) 2035–2051), but its values have not been
> verified against the paper.
>
> **Decision: the DSMC comparison is dropped from this study in full** — no band is quoted,
> no desk comparison is run, no DSMC value is recalled. Consequently **§2.1's single
> unresolvable degree of freedom stays fully unresolved**, which costs almost nothing, since
> §2.1 already withdrew every level claim and §10 already withheld the level. **M3 is
> unaffected** — it was written as shape-only precisely so it would not depend on a level
> anchor. The v0.7.2 claims that *did* depend on the band are corrected additively, never by
> editing frozen evidence (§9, "The DSMC correction").

### 2.4 Confounds that must be named, not modeled

The design is honest only if these ride in the findings doc:

- **Local solar time.** GRACE and GRACE-FO are near-polar at 89° and deliberately *not*
  sun-synchronous, so the orbit plane precesses through all local times. At ~490 km the
  nodal regression is ≈ 0.135 °/day, giving an LST drift of ≈ 1.12 °/day and a **full cycle
  of the ascending node in ~320 days**. But a near-polar orbit samples its ascending and
  descending nodes ~12 h apart in local time *simultaneously*, so **the diurnal axis is
  covered in ~160 days, not ~320** — the window set needs half the calendar span (and half
  the windows) the node-only figure implies. §2.3's M2 turns this from a confound into an
  axis, but only under the assumption that the density-model's diurnal error is a smooth
  low-order function of LST. That assumption is stated, not proved.
- **The GRACE ↔ GRACE-FO bus difference** (§2.3 M4a) — documented and computable, but not
  zero, and it enters every cross-mission read.
- **Mass.** Absorbed by the scalar-Cd fit, but **not** cancelled in T (§2.2). GRACE's
  15-year propellant history and GRACE-FO's shorter one both enter absolute-Cd statements
  and the T level, though not the T *shape*. Every absolute Cd carries its mass assumption;
  every T carries its A/m bracket.
- **Maneuvers.** GRACE performed regular orbit maintenance across 2002–2017, a materially
  higher risk than GRACE-FO's windows carried. Every window is maneuver-screened at chunk
  time by a named, automatable test; a screen failure retires that window rather than being
  modeled.
- **Late-mission GRACE degradation.** Battery limits, attitude-mode changes and reduced
  operation on GRACE B make the lowest-altitude years unsuitable despite carrying the
  strongest drag signal. **The study does not chase the ~300 km end**; window selection
  stops where the attitude convention is still nominal, screened at chunk time. **But the
  screen is narrower than "late mission is unusable":** `GNV1B` is a **GPS-derived orbit
  product**, not an accelerometer product, so the instrument and power failures that ended
  GRACE's *science* return do not by themselves disqualify a window. What actually
  disqualifies one is an **attitude-mode change** (it breaks the box run's assumed
  convention) or a **data gap / degraded tracking** (it breaks the parse and the fit). Screen
  on those two, per window, and record the result — the mid-cycle years that §3's E1 window
  draws on are expected to pass.
- **ITRF realization changes inside the span.** `itrf-versions.conf` maps `finals2000A.` to
  ITRF-2005 before 2011-02-01, ITRF-2008 from 2011-02-01, and ITRF-2014 from 2017-03-01, so
  Orekit interprets the EOP as the era-appropriate realization automatically. The truth
  product's own realization is checked against that, and the cm-level residual difference is
  **noted, not modeled** — it is far below the metre-level signal being measured.
- **Anchor correlation.** Adjacent anchors share arc days and forecast days; N anchors are
  not N independent samples. Carried on every claim (§6).

### 2.5 What Leg B reports instead of a decomposition

**Leg B is scoped to report the curve and state what it cannot resolve, not to measure a
decomposition.** The identifiability argument of §2.1 bites on the variance exactly as it
bites on the level (§2.3 M2), so the study declines the attribution rather than buying it
with an unmeasurable assumption. Three consequences, all binding:

- **The `D(w)` curve is a measurement and stands on its own.** It is quoted with its
  uncertainty and its A/m bracket, LST-stratified, across the window set. Nothing about it
  requires an assumption about the true Cd.
- **The tables' own modelled response over the same conditions is quoted beside it, and the
  attribution is explicitly declined.** The findings doc states: *"T varies by ⟨X⟩× across the
  window set; the tables' own modelled response over the same conditions is ⟨Y⟩ %. Attributing
  the remainder to density-model bias would require assuming the true Cd's response is no
  larger than the table's, which this study does not measure."* Both numbers are computed; the
  reader draws the inference the study will not.
- **Every quantity on T is reported as a ratio of extremes, never an absolute difference.**
  §2.2 defines T only up to the assumed A/m, so **a claim on T must be invariant under
  `T → cT`.** `max_w T / min_w T − 1` is; `max_w T − min_w T` is not, and would rescale with
  the assumed mass while nothing physical changed. This is the same invariance §2.1 uses to
  withdraw the level.

**The modelled response is a lookup, not a regeneration.** Verified on disk 2026-08-08: the
shipped tables are grids in **(radius, density) only** — `sphere_cd_default.npz`
`grid (26, 25)` over `radius_axis` / `density_axis`, and `box_face_cd_default.npz`
`grid (26, 25, 65)` adding `incidence_axis`. Neither carries a composition, LST, F10.7 or Ap
axis. So `range_table` is obtained by **evaluating the committed `.npz` at each window's mean
(radius, density)** — an evaluation the drag runs already perform internally, reachable
through the public JVM-free `VariableCd.__call__(radius_m, density_kgm3)` and
`BoxFaceCd.__call__(radius_m, density_kgm3, theta_rad)`. **No generator run, no
`pymsis`/`scipy`, no second environment, no α sweep.** The earlier plan to re-derive it
through `scripts/generate_*_cd_table.py` is withdrawn as unnecessary.

### The dimensional-collapse finding — stated with its measured size, not as an absence

**What replaces the withdrawn "at least X %" claim is *not* "the tables have no composition
axis."** That sentence is true about the grid shape and misleading about the physics, and an
earlier draft of this contract made exactly that error. **The collapse onto (radius, density)
is a deliberate, validated design decision whose residual the generator already measured**,
and the number is carried in the shipped asset. Verified on disk 2026-08-08 in
`scripts/generate_sphere_cd_table.py` and each `.npz`'s `metadata_json`:

- The generator samples **80 thermospheric conditions explicitly varying local solar time**
  (`lon` uniform 0–360°, commented *"varies local solar time"*), latitude (±80°), F10.7
  (65–320) and Ap (2–400) across 56 altitudes — a **4480-point cloud** — mass-flux-weighted
  over NRLMSISE-00 species, then regridded onto the 2-D surface.
- `metadata_json.confidence` records the cost of that regrid: *"Collapse RMS stays <= 5 %
  (green) across the full validated sweep (**overall 0.490 %, storm 0.672 %**)"*, with
  model cross-validation at 0.0191 %.

**So the LST axis was inside the sampled cloud, and what the collapse discards is measured at
sub-1 % RMS.** Two consequences, both binding:

1. **The finding is the *size* of the collapse, not its existence.** The findings doc states
   the 0.49 % beside the measured T variation, and the reader sees immediately that a
   sub-1 % table-internal residual cannot account for an O(2) spread in T. **Never write "the
   tables cannot represent an LST-driven composition response at all"** — the shipped
   `metadata_json` contradicts it, the study is already opening that file for `range_table`,
   and a reader who checks will find the study wrong on a claim it called its headline.
2. **What the collapse RMS bounds is table-vs-its-own-generator-physics, not
   table-vs-truth — and *that* is the honest residual claim.** 0.490 % measures how far the
   2-D grid departs from the full Sentman/DRIA + NRLMSISE-00 model it was built from. It says
   nothing about how far that model departs from the true free-molecular Cd. **Whether the
   true Cd's LST response exceeds the Sentman/DRIA model's is unmeasured, and unmeasurable
   from orbit data** — it is §2.1's identifiability problem restated on the composition axis.
   The "at least X % is density bias" withdrawal (§2.3 M2) therefore stands unchanged: the
   collapse residual is *internal* to the table's own physics and cannot bound `ε`.

> **This is a weaker headline than the withdrawn one and a defensible one.** The study gains a
> real, citable number about the shipped tables — *their (radius, density) reduction costs
> 0.49 % RMS against their own generating model* — and states plainly that the remaining
> question is about the gas-surface model, not the grid. An absence-claim would have been
> louder and false.

---

## 3. Truth data & provenance contract

**GRACE-FO (both spacecraft).** GRACE-FO Level-1B RL04 `GNV1B`, ASCII, ITRF, from PO.DAAC
daily tarballs (Earthdata login). **The quiet, active and Gannon windows are already on
disk** and each tarball already contains the satellite-D product alongside satellite C —
verified 2026-08-08: `gracefo_1B_2019-11-14_RL04.ascii.noLRI.tgz` carries
`GNV1B_2019-11-14_D_04.txt`. **GRACE-FO 2 therefore costs zero downloads and zero parser
work**; `parse_gnv1b(..., sat_id="D")` reaches it through the existing member filter at
`gnv1b.py:93`, and D's `qualflg` drop rate is compared against C's before D is treated as a
clean twin.

**Original GRACE (GRACE A / GRACE B).** GRACE Level-1B `GNV1B` from PO.DAAC. **The record
format is the study's one open technical question**: GRACE-FO RL04 is ASCII with a YAML
header, while GRACE L1B historically used a binary record format with an ASCII header. The
resolution rule is binding:

> The format is resolved **by inspection before any GRACE code is written** — first from
> the PO.DAAC file listing (the GRACE-FO products carry an explicit `.ascii.` token in the
> filename, so the listing may answer it with no download), then from one delivered file.
> Neither branch blocks the study: ASCII delegates to the existing column layout; binary
> gets a `struct`-based reader against the documented L1B record layout. **Either way it
> lands as a new module in `experiments/extended-validation/`, never as an edit to
> `gnv1b.py`.**

**The parse is self-checkable, and unusually well.** GRACE A and B fly in trailing formation
on the same ground track. Parsing both and recovering that separation — alongside
|r| ≈ 6870 km and |v| ≈ 7.6 km/s — is a decisive check that the field offsets are right,
which is the failure mode a binary reader actually has.

> **Assert the separation as a band, never a point value.** The formation gap is actively
> maintained and drifts: GRACE A/B ranged roughly 170–270 km across 2002–2017, and the
> GRACE-FO pair measures **181.0 km** (min 180.4 / max 181.5) in this study's own
> `quiet_2019` window, not the ~220 km nominal both missions are usually quoted at. A
> point-value assertion would false-fail a correct reader. The band catches a field
> misalignment (which throws the separation by orders of magnitude, not percent), and
> |r| / |v| carry the sharp part of the check.

If both format branches prove unworkable, the documented fallbacks are, in order: the **GFZ
ISDC** archive as a second source for the same L1B product (worth checking before rewriting
anything), then GRACE reduced-dynamic orbits in **SP3**, which
`experiments/real-world-validation/lageos/sp3.py` already parses.

**Download volume is the binding constraint, and it inverts the old draft's cost model.**
A GRACE-FO daily L1B tarball measures **148 MB** (verified on disk). The Swarm draft
reasoned from < 2 MB/sat/day and concluded that window length was compute-bound rather than
download-bound; for this study the opposite holds.

**But the "10-day window" is a download convention, not a driver requirement, and treating
it as the universal unit over-states the dominant cost line by roughly 3×.** Verified in the
frozen tree: `run_gracefo.py:127` sets `LOAD_DAYS = 3` (a 3-day screen span around a 1-day
fit arc) and `run_fit_vs_catalog.py:98,102` set 4 and 6. **No driver has ever consumed more
than 6 days of a window.** And one tarball carries *both* satellites, so C and D cost
nothing extra. Therefore:

| Leg | Days needed per window | Why |
|---|---|---|
| **`D(w)` curve (Run 3 only)** — the largest *window count* | **3** | inherits `run_gracefo.py`'s screen-span-around-a-1-day-arc geometry |
| GRACE drag anchors (full Run 1–5) | 3 | same geometry |
| Playbook / parity anchors (Legs C, C′) | 10 | 3 d arc + 3 d forecast at ≥ 4 anchors needs the span |
| Storm library | 10 | §7's fixed day-4-onset geometry |

Ten LST-stratified curve windows is therefore **~4.4 GB**, not 10–15 GB; the 10-day unit
applies only to the anchor and storm legs. **Chunk 0 sizes each leg on its own driver's day
count, never on the inherited download convention.**

> **Consequence, binding: Leg C draws only on windows that are already 10 days.** The two
> columns above are not independent — a 3-day curve or GRACE-anchor window **cannot host a
> single Leg C anchor**, let alone four, because 3 d arc + 3 d forecast + 3 anchor offsets is
> a 9–10 day span. So **the curve windows and the GRACE 2008–09 / 2002–03 anchors are not Leg
> C sources**, and §6's anchor set is the enumerated list there. Re-provisioning the ten curve
> windows at 10 days to make them Leg C sources would take this leg from ~4.4 GB to ~14.8 GB
> — back to the figure the per-leg sizing exists to avoid — in exchange for anchors that are
> near-duplicates in drag level, since the LST windows deliberately hold F10.7 fixed and vary
> only local time. **The 3-day sizing is retained and Leg C is scoped instead.**

> **Binding planning question, resolved in Chunk 0:** whether PO.DAAC serves `GNV1B` as a
> standalone product rather than only inside the full L1B bundle. The GNV1B member itself is
> ~23 MB/day/satellite uncompressed (measured inside the tarball), so a standalone product is
> ~23 MB/day raw or single-digit MB compressed — either way the window count stops being
> disk-bound. If PO.DAAC does not serve it standalone, **window count is capped by disk and
> the cap is recorded in the findings doc** rather than being discovered mid-study. Given the
> per-leg day counts above, that cap is likely non-binding for the curve leg regardless.

**The GRACE-era per-day volume is a second, independent unknown.** The 148 MB figure is a
*GRACE-FO* tarball, whose bulk is modern high-rate instrument data the GRACE-era product does
not carry. GRACE's 2002–2017 daily L1B volume could be far smaller, and it is what actually
sizes the storm library (the study's largest 10-day-window consumer). **Chunk 1 measures and
records it from the first delivered day**, alongside the format resolution; the storm-library
size is not committed until that number is in hand.

**Windows.** Five classes. Exact dates for the new classes are screened at chunk time;
defaults and selection rules are binding.

| Class | Bodies | Purpose |
|---|---|---|
| **Inherited** — quiet 2019-11-14 → 11-23, active 2023-12-20 → 12-29 (10 days each, as on disk), Gannon **2024-05-07 → 05-16** (extended, see below) | GRACE-FO 1 **and 2** | M1 noise floor; like-for-like continuity with the committed v0.7.2 evidence |
| **LST-stratified** — GRACE-FO era, F10.7 held in a narrow band, LST separated | GRACE-FO 1 **only** (§9: the twin buys nothing this leg's claims are judged against) | M2's diurnal axis |
| **GRACE anchors** — the 2008–09 deep minimum and a 2002–03 solar-max window | GRACE A and B | M3's known-answer test; the high-activity end on the same bus lineage |
| **E1 drag-timescale** — a GRACE mid-cycle window at **~420–440 km** with F10.7 matched to `active_2023` (≈ 2014–2015), 10 days | GRACE A (B if it screens clean) | Leg E's E1 pairing (§8); a matched-activity, altitude-contrasted GRACE point |
| **Storm library** — ≥ 3 events from 2002–2017 plus the extended Gannon window | GRACE A/B, GRACE-FO | §7's s-gate domain-of-validity |

**The E1 window is a distinct, load-bearing provision, not a nice-to-have.** §8's E1 requires
two bodies at *genuinely different drag timescales*, and neither GRACE-anchor window supplies
one: 2008–09 (~475 km) and 2002–03 (~500 km) both sit inside GRACE-FO's own altitude
envelope, so pairing either against GRACE-FO varies the epoch and not the timescale. A
2014–2015 window at ~430 km against `active_2023` at ~490 km holds F10.7 fixed and changes
the density by roughly a factor of ~2.5–3 — a real timescale contrast with **no event
confound**. One 10-day download serves three legs: a Run-3 row for §5's curve, Leg C anchors,
and Leg E's active regime.

**LST stratification rule.** At ≈ 1.12 °/day of LST drift, windows ~80 days apart differ by
~6 h of node local time and ~90 days apart by ~100°. Because each window also carries its
descending-node LST ~12 h from its ascending one (§2.4), **~160 days of calendar span covers
the full diurnal axis** — so the LST leg is sized around a ~160-day span, and every window
records *both* node local times, not a single mean LST. The 2019–2020 deep minimum holds
F10.7 nearly constant across that span, which is what makes the axis usable. **The window
list is fixed and recorded, never randomized** — both satellites decay and the solar cycle
moves, so a random draw confounds LST with activity and altitude, and §9's bit-determinism
rule forbids a seeded draw in any case.

**Storm-library window geometry.** Every anchor carries a **3 d arc and a 3 d forecast** —
the same geometry as §6, so storm rows stay comparable to quiet/active rows. Placing the
onset at **the start of day 4 of a 10 d window** yields all three anchor classes by
construction, and 10 days is exact — not tight, not short.

> **Day-labelling convention, so the table below is unambiguous.** Truth days are numbered
> 1…10 and **each label is an inclusive whole-day count** (`days 1–3` = days 1, 2 and 3 =
> 3 days). **An anchor sits at the *start* of its named day**, so the anchor at day 4 fits
> over days 1–3 and forecasts over days 4–6. Every arc and every forecast below is exactly
> 3 days; the last forecast ends with the last truth day.

| Anchor | Arc | Forecast | Class |
|---|---|---|---|
| day 4 | days 1–3, entirely pre-onset | days 4–6, spans onset | **pre-onset** — expected *unforecastable onset* |
| day 6 | days 3–5, contains onset | days 6–8 | **mid-storm** |
| day 8 | days 5–7, entirely post-onset | days 8–10 | **post-onset** |

**The Gannon window is extended to 2024-05-07 → 05-16 so it carries the geometry above.** The
committed 4-day window (2024-05-10 → 05-13) cannot host even one 3 d + 3 d anchor — v0.7.2's
`probe4` was forced down to a **1-day** forecast for exactly this reason
(`results_probe4_storm.txt:3`). With the model's onset at the 05-10 UTC day boundary (the
daily-Ap caveat, §7), day 1 = 05-07 and day 10 = 05-16, which is six more days (~0.9 GB).
Without the extension the study's only GRACE-FO storm — the one event with committed
comparison numbers in the repo — is the one storm that cannot be run at the study's own
geometry, and Leg C's storm rows become GRACE-only. **The existing 4-day committed rows are
untouched and remain the continuity baseline.**

**The Gannon arc-start convention is inherited, not re-chosen.** The v0.7.2 study runs its
1-day `storm_2024` arc from **2024-05-11** (the peak arc; fitted Cd 4.08, i.e. 3.97 on
`A_ram`); the 05-10 onset arc is a separate block whose **1.73 on `A_ram`** fit (1.777 on the
driver's `A = 1.0 m²`, `results.txt:328`) is a flagged daily-Ap smearing artifact and
deliberately **not** an anchor. Any new comparison against that row starts 05-11 or it lands
on the artifact. The extension adds days around that arc; it does not move it.

> **Every Cd in this document is quoted on `A_ram = 1.027 m²` unless the driver reference
> `A = 1.0 m²` is named alongside it.** §2.2 is the reason: the reference area does not
> cancel, so an unlabelled Cd is not a number. The pair above is the worked example.

**Catalog TLEs (matched staleness).** Per-anchor `gp_history` pulls from Space-Track
(maintainer's credentials, `.env` convention). The selection rule is **binding**:

> For an anchor at time T, the matched catalog TLE is the one with the **latest epoch ≤ T**.
> A TLE with epoch > T is future information and must never enter a comparison. Per-anchor
> staleness Δ = T − epoch is **reported alongside every catalog row**.

The v0.8.0 evidence's ~6-day-stale rows are retained as a continuity baseline, labelled as
such. **Close-formation pairs are a named catalog hazard:** GRACE-FO 1/2 fly ~181 km apart
and GRACE A/B ~170–270 km, and cross-tagged catalog entries are a real failure mode. Every
pull is checked for object-identity consistency before use.

**orekit-data coverage — verified on disk 2026-08-08, and 2002–2017 is fully supported:**

| Dependency | Coverage | 2002–2017 |
|---|---|---|
| EOP `finals2000A.all` | 1973-01-02 (MJD 41684) → 2027-07-04 | inside the final/observed block |
| CSSI space weather | `BEGIN OBSERVED` 1957-10-01 → 2026-05-09 | observed F10.7/Ap throughout |
| Leap seconds `tai-utc.dat` | 1961 → 2017-01-01 (the last one) | complete |
| DE-440 | `lnxp1990.440` | covered |
| Gravity `eigen-6s.gfc` | max_degree 240, tide-free, 6616 trend/annual/semiannual terms; a 2011 model | see below |

Two notes worth carrying rather than rediscovering. **Five leap seconds fall inside the
span** (2006-01-01, 2009-01-01, 2012-07-01, 2015-07-01, 2017-01-01); this is a non-issue
*because* the inherited convention converts GPS-time products leap-free as GPS + 19 s = TAI —
both scales are continuous, so a leap second **cannot** reach the truth-ingest path at all.
It reaches only the UTC *display* of an epoch, which nothing in this study measures against.
No window is placed to "test" it: there is nothing there to test. And **the gravity model
favors the GRACE era**: EIGEN-6S is a 2011 model whose
trend and annual terms are fitted over the GRACE/GOCE data span, so GRACE-era runs sit
inside that span while GRACE-FO-era runs extrapolate it by a decade or more. Small, but it
points the opposite way from the usual intuition and should be stated once.

**Inherited conventions (from the v0.7.2 study, unchanged):** raw truth files are never
committed (`data/` gitignored); GPS-time products convert leap-second-free as GPS + 19 s =
TAI, never a hand-rolled leap-second table; truth frames are ITRF realizations whose
differences vs Orekit's are noted, not modeled; every driver is cwd-independent with
**ASCII-only stdout** (cp1252 capture) and progress on stderr; everything runs in the
**propygator conda env** (the locked departure from `docs/experiments_venv.md` — propygator
is the system under test). **No carve-out is needed** — the table-range figure is a lookup on
the committed `.npz` grids (§2.5), not a generator run, so nothing in this study requires the
`pymsis`/`scipy` generation venv.

**The environment is frozen for the study's duration.** The installed env carries
`orekit_jpype` **13.1.4.0** while conda-forge offers 13.1.7.0 under the same `13.1.*` pin,
so a recreation lands a different Orekit build (CLAUDE.md "Version drift warning"). Chunk 1
and Chunk 9 landing on different builds would make the evidence internally inconsistent and
`run_all.py --verify` permanently red. Therefore: **do not recreate or update the env
mid-study**, and **every results file records the resolved `orekit_jpype` version *and* the
propygator version in its header** (the v0.7.2 evidence records neither, which is why a
version question about it can only be answered from the git log). Upgrading to 13.1.6+
happens after this study merges, not during it.

---

## 4. Leg A — the drag stack, the twin, and Checkpoint A (goal 1)

Replicate the v0.7.2 Run 1–5 structure (drag off / drag on at nominal Cd / scalar-Cd fit /
sphere table no-fit / box table no-fit) on the study's conservative force baseline, at the
new bodies and epochs.

**Checkpoint A moves to the twin, and is sharper than the old draft's.** The Swarm draft
gated on a drag-off residual ratio predicted from a ballistic-coefficient × density
argument — a prediction with real uncertainty on both terms. The GRACE-FO twin has a known
answer: **`T(C,w)/T(D,w)` should be 1**, and no density model, altitude gradient or
ballistic-coefficient arithmetic enters. A wiring bug has nowhere to hide.

> **Checkpoint A — GO / INVESTIGATE, never a shrug.** GO requires: D's parse clean with a
> `qualflg` drop rate comparable to C's; t₀ frame/time diff at float-noise level (the
> v0.7.2 study measured ≤ 5e-9 m for GRACE-FO); and **`T(C,w)/T(D,w)` within 10 % of 1 in
> every inherited window.** The 10 % is deliberately generous, because this gate hunts
> wiring bugs — **the measured deviation itself is the deliverable** (M1), and it becomes
> the noise floor every later prediction is judged against.

A bad number reroutes into localized bug-hunting exactly as the v0.7.2 Checkpoint A did; a
confirmed defect exits to the normal fix path, and §9's symmetric rule then requires
re-running the affected committed groups before the study resumes.

**Pre-registered predictions (falsifiable; a miss is a finding, not a failure):**

- **A1 — The twin agrees.** `T(C,w)/T(D,w)` is within 10 % of 1 in all three inherited
  windows, and its window-to-window spread is smaller than the spread of `T` itself. The
  measured value is reported as the noise floor, explicitly labelled **"floor + fore/aft
  asymmetry + any true A/m difference between the twins"** (§2.3 M1) — the three-term label
  is mandatory, because the third term is a systematic that reproduces on every re-run.
- **A2 — The scalar-Cd fit collapses the residual** to the v0.7.2 class (single-metre quiet,
  ~10 m active) on every new body and epoch. A miss on GRACE-FO 2 with GRACE-FO 1 passing is
  a wiring signal; a miss on GRACE at a new epoch with both GRACE-FO bodies passing is an
  epoch or truth-product signal.
- **A3 — Fitted Cd on a common reference area rises quiet → active → storm** on GRACE as it
  did on GRACE-FO 1 (1.98 → 3.32 → 3.97). This is the direct transfer test of the density-
  bias lever, and it is a **direction and rough-magnitude** test, not a level test (§2.2).
- **A4 — The GRACE ↔ GRACE-FO cross-check is a *reported diagnostic*, not a prediction.**
  `T(GRACE,w₁)/T(GRACE-FO,w₂)` is computed and printed with its confounds enumerated: the
  documented dimension and mass differences, and — dominant — the unmatched density bias
  `D(w₂)/D(w₁)`, which §5 measures at O(2) across the driver range against an A1 floor of a
  few percent. **There is no "≈ 1" pass criterion**, because none is testable at that
  confound level (§2.3 M4a). Pipeline validation across the 17-year gap is carried by the
  direct checks in §3 / Chunk 1 instead.

---

## 5. Leg B — the density-bias curve and what can be said about the tables (goal 1)

The analysis Leg A's runs make possible, restructured around §2's identifiability argument.

**The curve.** `T(s, w)` for both tables across the full window set, each cell **a bracket
over the assumed A/m** (§2.2), plotted against F10.7, Ap, LST and altitude. The v0.7.2
`results.txt` supplies the GRACE-FO 1 column for free — it already reports T under another
name, the box table carrying 2.23× / 1.21× / 0.97× the fitted ρ·Cd·A product being exactly
`Cd_table/Cd_fitted` on the common `A_ram = 1.027 m²` — transcribed with a provenance line,
never recomputed.

**The reported comparison, in place of a decomposition (§2.5).** Quote the T variation and
the tables' own modelled response over the same conditions side by side, both as **ratios of
extremes**, and **decline the attribution in writing**. `range_table` is a lookup on the
committed `.npz` grids at each window's mean (radius, density) — no generator run. The
**dimensional-collapse finding rides with it, stated with its measured size**: the shipped
grids reduce to (radius, density), and the generator's own `metadata_json` puts the cost of
that reduction at **0.490 % RMS overall / 0.672 % storm** against the full
LST-and-activity-sampled cloud it was built from. Quoted beside an O(2) T spread, that is the
finding. **It is a bound on table-vs-its-own-physics only** — the true Cd's LST response
remains unmeasured and unmeasurable from orbit data (§2.5).

**The absorbable-scale retest.** The v0.7.2 Checkpoint-B evidence was that scaling the box
table's Cd·A onto the fitted product collapses the box run onto the fitted run (1.85 vs
1.86 m; 6.45 vs 6.36 m; 118.6 vs 119.0 m). Retest at the new epochs and drag levels.

**Attitude sensitivity** — the box run under `InPlaneTracking(velocity_reference="ecef")`
vs `inertial` vs default `LofAligned`, to bound how much of the box answer is attitude
convention rather than the table.

**Regime-guard exercise** at GRACE's lower-altitude windows: confirm the two-tier
drag-regime warn-once (Kn floor + table edges) behaves as documented and does not fire
spuriously.

**The DSMC comparison is dropped** (§2.3 M4). No band is quoted, no desk comparison is run,
no DSMC value is recalled. The study has **no external level anchor**, and says so.

**Pre-registered predictions** — note that B2 and B5 are *reported measurements*, not
pass/fail predictions; only B1, B3 and B4 carry verdicts:

- **B1 — The box table's T crosses ~1 at storm peak** on the new bodies as it did on
  GRACE-FO 1 (the sign test that resolved H1 — over-prediction is density bias, not
  geometric over-drag).
- **B2 — reported, not predicted.** Three numbers, all as ratios of extremes (§2.5):
  `spread_T = max_w T/min_w T − 1`, the **window-to-window** floor (below), and
  `range_table = max_w Cd_table/min_w Cd_table − 1`. **No 3×/2× pass criterion** — the earlier
  thresholds sat on quantities whose own floors are estimated, and the inference they licensed
  is the one §2.3 M2 withdraws. The findings doc quotes the three and declines the
  attribution.
- **B3 — The deep-minimum shape anchor (M3).** GRACE's 2008–09 fitted Cd sits low *relative
  to that same body's own high-activity window*, in the same direction and rough proportion
  as GRACE-FO 1's 1.98 → 3.32. Reproducing that across a 17-year gap on the same bus lineage
  establishes the lever as a property of NRLMSISE-00 rather than of one epoch. **Never
  stated as an absolute comparison** (§2.3 M3), and no external band is available to state
  one against.
- **B4 — The absorbable-scale result holds**, leaving the Checkpoint-B `box_and_panels`
  deferral intact. A miss elects a follow-on; it does not authorize the upgrade inside this
  study (§0).
- **B5 — reported, not predicted.** The LST dependence of T at fixed activity is measured and
  plotted alongside the tables' response over the same LST range. **It is not a prediction**,
  because §2.4 already concedes the two terms are not separately identified without assuming
  the density bias is smooth and low-order in LST. **The like-for-like comparison *is*
  available and is made:** the tables' LST response is mediated entirely through
  (radius, density), and §2.5's collapse residual — **0.490 % RMS** from the generator's own
  metadata — is exactly how much LST-driven composition response that mediation discards. Plot
  the measured LST dependence of T against that 0.49 % band. What stays unresolved is not the
  table's response but the **true** Cd's, which no orbit-only design reaches (§2.5).

**σ(T) is derived, not omitted — and the two floors are routed by their cancellation
structure, not pooled.** Every T carries **one of two floors**, selected by what the claim
compares:

- **A1's twin floor governs *cross-body* claims.** At fixed window `Cd_table` cancels and so
  does `D(w)`, along with truth-product quality, index error, EOP and the fit's conditioning
  at that drag level: `T(C,w)/T(D,w) = κ_D/κ_C` exactly. That is the right bar for A4 and
  M4a, where the same cancellation holds.
- **A *within-window sub-arc* floor governs *cross-window* claims (B2, B5).** A1 is the wrong
  bar there, and wrong in the anti-conservative direction: it cancels precisely the terms that
  vary between windows, so using it would let genuine measurement scatter be read as `D`.
  Measure it instead by **fitting each of the 3 loaded days separately** and taking the spread
  of the three `Cd` — zero new downloads (`run_gracefo.py:127` already loads 3 days around a
  1-day arc), ~2 extra fits per window (day 1's separate fit **is** the main fit). It contains
  real day-to-day density variation, so it **over**-estimates the floor — the same
  conservative direction M1 already argues for itself.

> **The golden-section minimum's curvature is *not* a third σ source, and is not reported as
> one.** The Cd fit is a deterministic optimization against a residual that is dominated by
> unmodelled systematics, not measurement noise, so the width of its minimum measures
> **optimizer resolution**, not uncertainty in T. Quoting it beside the two floors would
> publish a σ tighter than the honest one by an order of magnitude. The bracket may be printed
> as a *fit-quality diagnostic* (a flat minimum is a weak-drag warning worth seeing); it never
> enters an error bar.

The Swarm draft judged its headline prediction by eyeball against a Cd_fitted that carried no
error bar anywhere in the design; that gap is closed here.

---

## 6. Leg C — playbook transfer and catalog parity (goals 2, 3)

**Thresholds are frozen.** The playbook's r < 0.05 and s < 0.1 enter this study as
**pre-registered predictions carried verbatim from single-satellite data**. Re-fitting
thresholds to the new data and then reporting that they classify correctly is circular and
is forbidden. If the frozen thresholds misclassify, the finding is the misclassification,
and any re-calibration is reported separately and labelled as post-hoc.

**Anchor supply.** GRACE-FO 1 and 2 are one dynamical case but **two independent catalog
objects** — different NORAD IDs, tracking histories and B\* — so for the catalog legs they
are two genuine samples at zero download cost. GRACE A and B add epochs across 2002–2017
and, more importantly, a **drag-level range** that no single-altitude body can supply.

**Replication protocol.** The `probe3` pattern — a 2 d free staging fit for r, a 3 d fit for
s, then the gate's chosen arm and its rivals on a common 3-day forecast window — at **≥ 4
anchors per window per satellite**. The target is comfortably more than the strategy
experiment's 9 anchor-window combinations; the exact count is a build-plan tuning call
against the compute and disk budget, and **the achieved count is reported, not promised in
advance**.

> **The anchor windows are enumerated, not "every window class in §3".** Leg C's geometry
> needs a 10-day window (§3), so its sources are exactly the windows already provisioned at
> that length — **zero additional downloads**:
>
> | Window | Bodies | Drag level |
> |---|---|---|
> | `quiet_2019` (inherited, 10 d) | GRACE-FO 1 **and 2** | weakest — ~495 km at deep solar minimum |
> | `active_2023` (inherited, 10 d) | GRACE-FO 1 **and 2** | ~495 km at solar max |
> | **E1 drag-timescale** (§3, 10 d) | GRACE A (B if it screens clean) | ~430 km at F10.7 matched to `active_2023` — **~2.5–3× denser** |
> | Storm library (§7, 10 d each) | GRACE A/B, GRACE-FO | storm peaks |
>
> **This set spans C1's actual requirement, which is drag-level range, not window-class
> coverage.** It runs from GRACE-FO at solar minimum through GRACE at ~430 km solar max to
> storm peaks — a wider range than the LST curve windows could contribute, since those hold
> F10.7 fixed by construction and differ only in local time. The **3-day** curve and GRACE
> 2008–09 / 2002–03 anchor windows are Leg B sources and are **not** used here.

**The gate's behavior on a singular covariance is defined before the run, not after.**
`FitResult.sigmas` returns `None` whenever `covariance` is `None` (a converged fit whose
`(JᵀJ)⁻¹` extraction was singular, per §1.2). A singular covariance means **r is not
computable, which is "does not certify" — not a crash and not a pass**. It is printed as an
explicit `r = n/a -> no certification` row and counted in C1's tally.

**Matched-staleness catalog parity** (§3's selection rule) at every anchor, reported as
three rows: playbook arm, matched-staleness catalog, stale catalog (continuity).

**Leg C′ — State-path × a-priori tables (findings route 6, the goals 1↔2 weld).** All
existing playbook evidence is Trajectory-path. The no-truth user's only calibration source
is the shipped Cd tables, which `real-world-validation-findings.md` §5 shows structurally
cannot meet the single-digit-% ballistic-coefficient bar the State path needs. This leg
measures the consequence: run the playbook arms on `propagate_numerical` references built
from (a) the sphere table, (b) the box table, and (c) the window's calibrated scalar Cd, and
measure **how much the r and s margins erode**. §1.2's guidance predicts reference-model
error simply adds; that is unmeasured for r and s.

**Two routes, not one — and the split is forced, not stylistic.** §1.2's *State* path
propagates its own reference internally under **the default `LofAligned` attitude and no
attitude parameter**, so the box table's `InPlaneTracking(ecef)` convention is inexpressible
there. The v0.7.2 driver already hit this and resolved it (`run_fit_vs_catalog.py
--state-path`: the sphere table through **both** the native State path and the external
propagate-then-fit route — the measured equivalence — and the box table through the external
route only). This leg inherits that split verbatim, and every row is labelled with the route
that produced it. Rows on the external route measure *reference-model error in general*;
only native-State rows measure the §1.2 State path as a user would meet it.

**Pre-registered predictions:**

- **C1 — The frozen r gate classifies correctly across the full drag-level range.** Stated
  **behaviorally**, because the earlier "quiet ⇒ r ≥ 0.05" formulation conflated the
  calendar window with the drag regime: GRACE at a low-altitude window has far more drag
  signal than GRACE-FO at solar minimum, so a low r there is the gate *working*, not
  failing. **The criterion is that the arm the gate selects is the best-forecasting arm at
  that anchor**, tallied over all anchors, with the r/s values reported alongside.
- **C2 — Quiet's B\* = 0 catalog-free default beats a held catalog B\* out to ~3 d**, with
  the crossover appearing by ~4 d.
- **C3 — The two-stage self-calibrated transplant is the best catalog-free active-regime
  config on a majority of anchors** (the v0.8.0 claim was 3 of 4; the honest bar under a
  2–3× anchor-noise floor is a majority, not a sweep).
- **C4 — Against a matched-staleness catalog the playbook still wins on the fit day, but
  the forward margin shrinks substantially** from the 2×–30× measured against a 6-day-stale
  catalog. Predicting the shrink up front is what keeps the README claim honest; any anchor
  where the matched catalog *wins* is reported explicitly.
- **C5 — Table-based references degrade the arms measurably but leave the gate's
  *decisions* intact**; the r/s margins narrow without inverting. Resolved **per route** — a
  native-State-path verdict is stated only from native-State-path rows. A margin inversion
  is the important negative result: it would mean the gate is unsafe for users whose
  reference is propygator's own output, and the playbook must say so.

**The anchor-correlation caveat is printed in every results header**: adjacent anchors share
2 of 3 arc days and 2 of 3 forecast days, so N anchors per window are roughly 3–4 effective
independent samples. It rides on every claim in this leg.

---

## 7. Leg D — the storm library and the s-gate's domain of validity (goal 3)

One storm (Gannon 2024) established the s-gate. The library tests it — and **2002–2017 is a
far richer source than the GRACE-FO era**, which is one of the clearest gains from the body
set change. Candidate events are screened at chunk time for data availability, maneuver
cleanliness and signal strength; the library needs **≥ 3 events** beyond the committed
Gannon evidence, sized and placed by §3's 10-day / day-4-onset geometry.

**The distinction this leg must draw** — and it is the leg's principal contribution:

- **A gate failure** is nonstationarity that is *visible inside the fit arc* while s stays
  below 0.1, certifying a transplant that then fails. This is the dangerous mode; it never
  occurred in the single storm tested, and it is what the library exists to hunt.
- **An unforecastable event** is nonstationarity that *begins after the arc ends*. Here s is
  small, the transplant is certified, and the forecast fails anyway — and **no data-driven
  gate computed from past measurements can do better.** This is not a defect.

The distinction is drawn by construction: anchors are placed **pre-onset**, **mid-storm**
and **post-onset** at §3's fixed day-4 / day-6 / day-8 positions. The pre-onset anchor is
expected to produce a certified-and-then-failed forecast, and the honest reading of that is
a **domain-of-validity statement for the playbook**, not a threshold change:

> **D1 (pre-registered)** — s detects nonstationarity that is present in the arc, and cannot
> detect nonstationarity that begins after it. The playbook must say so explicitly; a user
> could otherwise read s as certifying forward validity, which it does not and cannot.

**A screening rule, binding.** A G4-class event is an *easy* catch for the s-gate; the
false negative lives in the **moderate, gradual** excursion — big enough to wreck a
forecast, small enough that cross-span B\* drift stays under 10 %. The library must contain
at least one moderate event, not only large ones, or it cannot hunt the mode it exists for.
A candidate window whose cross-span B\* drift *and* raw forecast degradation are both null
teaches nothing and is replaced.

> **The moderate event is a search, not a pick, so the candidate pool is named up front and
> the search is capped.** Each screening round costs a 10-day GRACE download at a per-day
> volume not known until Chunk 1, so an open-ended hunt is the one way this leg can overrun.
> Candidate pool, large events first and **moderate candidates flagged**: 2003-10/11
> (Halloween, G5), 2004-11 (G5), 2005-05 (G5), **2006-12 (moderate)**, **2015-03 (St
> Patrick's, G4)**, **2015-06 (moderate)**, 2017-09 (G4, late-mission — screen hard). Screen
> in that order, stop at **≥ 3 events including ≥ 1 moderate**, and **cap the search at five
> screened windows**: if no moderate event has been found by then, the library ships with what
> it has and the findings doc records the moderate mode as **untested**, which is an honest
> result and a named follow-on. It is not a reason to keep downloading.

**Every storm result inherits the daily-Ap caveat** (`real-world-validation-findings.md`
§4): Orekit's `NRLMSISE00` at default switches is driven by the daily Ap, so the
prediction-error boundary around a storm is the UTC day boundary of the index, not the
physical onset. These are results for the model **as shipped**, and each storm row must say
so. The caveat bites *harder* on large, fast events, which the 2002–2017 library supplies
more of — state that rather than letting it pass as a constant.

---

## 8. Leg E — the fading-memory decision (goal 4)

**The bar is pre-registered and binding, carried verbatim from
`tle-fit-strategy-findings.md` §3:**

> Amend §1.2 only if the weighted fit's median +3 d improvement over the corresponding
> playbook arm is **≥ 1.5× in at least two regimes** (i.e. above the anchor-noise floor)
> **with no regime made > 1.25× worse**, under a **single** recommended τ (or a τ rule
> computable from the fit itself). Anything weaker stays an experiments recipe.

**Default outcome is DEFER.** The bar is cleared or it is not; a near-miss is a defer with
the numbers written down.

**The design, as specified in the findings note:** τ ∈ {0.5, 0.75, 1, 1.5, 2, 3} d ×
{quiet, active, **storm**} × ≥ 3 anchors, in both B\*-free and B\*-held modes; a **sampling-
skew axis** (uniform vs log-spaced-toward-recency subsampling — a short τ under uniform
300-sample subsampling wastes most of the measurement budget on near-zero-weight samples,
and folding that in silently would confound the result); and the **conservative r-gate
protocol** — compute r/s on *unweighted* staging fits and forecast with the weighted fit,
which preserves the calibrated thresholds at the cost of two cheap extra fits.

**Three conditions this contract adds:**

- **E1 — Two satellites with genuinely different drag timescales, resolved in the quiet and
  active regimes.** A τ that is satellite-specific is disqualifying on its face.
  **GRACE-FO 2 does not satisfy E1** — same altitude, same windows, same timescale as
  GRACE-FO 1, so it is one dynamical case and counting it would be self-deception. The
  pairing that satisfies E1 is **GRACE at a lower-altitude window against GRACE-FO at
  ~490 km**, which varies the drag timescale — what τ is actually about — with the geometry
  controlled by the shared bus lineage. Concretely: **§3's E1 drag-timescale window
  (~430 km, F10.7 matched to `active_2023`) carries the active regime, and the 2008–09 GRACE
  minimum against `quiet_2019` carries the quiet regime.**

  > **The storm regime cannot satisfy E1, and the reason is structural: the missions do not
  > overlap in time.** GRACE re-entered before GRACE-FO launched, so **no storm event exists
  > that both bodies flew through** — a GRACE storm row and a GRACE-FO storm row are always
  > different events, and satellite is therefore confounded with event in that regime by
  > construction. The storm regime accordingly contributes **one satellite per event**, the
  > confound is stated on every storm row, and **the E1 verdict is read off the quiet and
  > active regimes only.** Any earlier instruction to acquire a single storm window "for both
  > bodies of the E1 pairing" is void — it describes something unobtainable.
- **E2 — Report the sensitivity curve, not the optimum.** τ 0.75 → 1.0 d moved a +3 d RMS by
  1.75× in the teaser. A knob whose optimum is sharp is a foot-gun even if it clears the bar,
  and the curve is what tells a reviewer which it is.
- **E3 — Statistics disclosure.** Weighting makes σ₀ and the covariance *weighted*
  quantities. If the bar is cleared, the promotion must state explicitly what happens to the
  r-gate under weighting; a knob that silently invalidates the gate is not shippable even at
  a good RMS.

**Checkpoint D (the study's second and last binding decision gate):**

- **DEFER** (default) → record the measured verdict in the findings doc, close
  `tle-fit-strategy-findings.md` §3, archive that note if only route 5 survives. The τ-sweep
  evidence stays committed as an experiments recipe.
- **PROMOTE** → the study still ships **without** the API change. A `measurement_decay_tau`
  parameter is a §1.2 amendment on its own `feature/` branch off `main`, after this study
  merges, with its own release (§11).

Mechanism note: the weighted fit is expressible only through `propygator.tle.fitter`
internals, as `probe2` documented. Driving internals is sanctioned **in an experiment probe**
with the unsupported-usage docstring; it is not sanctioned anywhere else.

---

## 9. Evidence, deliverables, and the frozen-evidence rule

**Layout** — a new sibling of the existing study, importing from it and never editing it:

```
experiments/extended-validation/
├── README.md          study index: provenance, method, findings at a glance
├── run_all.py         regenerate / --verify orchestrator (the v0.7.2 pattern)
├── data/              raw truth (gitignored, never committed)
├── gracefo/           the twin + LST-stratified legs: config, drivers, results
├── grace/             the GRACE leg: its own reader, config, drivers, results
└── probes/            the fitter/storm/fading-memory probes and their results
```

**The frozen-evidence rule (binding), and this study cannot violate it by construction.**
`experiments/real-world-validation/` reproduces its committed v0.7.2 numbers and must
continue to. With Swarm retired, **no path in this study can force a change to a frozen
module**: the only imports are `common.py` and `gracefo/gnv1b.py`, both read-only;
`find_window_files` and `parse_gnv1b` each take an arbitrary `Path`, so new GRACE-FO rows
point at the new tree's `data/` (or at the old tree's, via a `--data-root` argument) without
an edit; and GRACE lands as a **new module in the new tree**, never as an additive change to
`gnv1b.py`'s `_SAT_NAMES`. If some unforeseen change is nonetheless forced, it is strictly
additive, backward-compatible, and followed by `run_all.py --verify` on the affected groups,
with the result recorded.

**The symmetric rule for `src/`.** The environment is frozen (§3); shipped code must be too,
for the same reason. If Checkpoint A's INVESTIGATE arm confirms a defect and it is fixed on
`main`, **every already-committed group is re-run and re-recorded against the fixed build
before the study resumes**, and the findings doc says which groups moved. A study whose
evidence spans two versions of the system under test is not evidence.

### The DSMC correction — scoped now, applied at wrap-up (Chunk 10)

§2.3 M4 retracts the DSMC anchor. Two v0.7.2 claims rest on it and must be corrected, but
**the correction is additive prose only — no constant is edited and no number is
regenerated.** `DSMC_CD_BAND` at `gracefo_common.py:65` is printed into `results.txt` at
**eight lines — 43, 80, 124, 161, 206, 243, 288, 328** (`DSMC physical band …` and the
`chunk 2b …` summary rows), so changing it would alter committed evidence and red
`run_all.py --verify` permanently. The **v0.7.3 precedent binds and is stronger than this
case**: a genuine *code* fix (the leeward floor) did not trigger regeneration — evidence
stayed frozen at v0.7.2 numbers with the delta documented. A citation error warrants less,
not more. **So the frozen-evidence rule is honored, not excepted.**

**Blast radius, re-verified 2026-08-08 (count, not a spot check):**

| Location | Refs | Disposition |
|---|---|---|
| `src/`, `tests/`, `README.md`, the notebooks, `tle-fitting-playbook.md` | **0** | Nothing to do. It never reached the public surface, so **no showcase re-export and no user-facing correction**. |
| `docs/features.md` §1.1 (`:431`) | 1 | **No action — checked, not assumed.** It is a *generation-method* mention ("a protruding, articulating array … needs a panel method / DSMC — out of scope"), **not** a Cd-band claim. The binding contract is untouched by the retraction. |
| `docs/real-world-validation-findings.md` | 2 | **Corrected additively** — the two rows in the table below. |
| `experiments/real-world-validation/gracefo/README.md` | 8 | **One correction block appended**; body text and tables left in place. |
| `experiments/real-world-validation/gracefo/results.txt` | 8 | **Frozen — never regenerated.** |
| `…/gracefo_common.py:65`, `…/run_gracefo.py` (6), `…/probes/probe_tables.py` (2) | 9 | **Frozen — never edited.** The band is defined once and printed/consumed by the drivers; all of it is committed evidence. |
| `docs/history/build-plan-real-world-validation.md` (`:376`, `:430`, `:441`, `:472-474`) | 9 | **Deliberately left as written.** It is the archived historical record of what was concluded in v0.7.2 and why; editing it would destroy exactly the record the frozen-evidence rule exists to preserve. The new findings doc supersedes it, and §1's doc-precedence table already makes archived plans non-binding. Named here so a later reader does not mistake the omission for an oversight. |

**The edits to apply at wrap-up (do not apply early):**

| File | Location | Change |
|---|---|---|
| `docs/real-world-validation-findings.md` | `:125-129` | **Withdraw** "The a-priori Cd tables are physically credible" and the "sphere at the band's low edge, box inside it" reading. It rests on the **4.5** upper edge, which is an assumed input parameter for a hypothetical double-deployable-panel bus (arXiv 2503.21651 = Leipner et al.), not a DSMC result and not the GRACE geometry. Add a dated correction note; **do not delete the surrounding measured numbers.** |
| `docs/real-world-validation-findings.md` | `:118-120` | **Withdraw** "NRLMSISE-00 over-predicts deep-solar-minimum density by ≳ 25 %". It rests on the **2.65** lower edge *and* on `GRACEFO_MASS_KG = 600.0` + `A_RAM_M2`, which §2.2 shows do not cancel — doubly exposed. The *relative* lever 1.98 → 3.32 → 3.97 survives and is not touched. |
| `experiments/real-world-validation/gracefo/README.md` | `:95`, `:224-227`, `:247`, `:251`, `:301`, `:349`, `:616` | Add a **correction block at the top of the DSMC discussion** pointing at the new findings doc. Leave the body text and every table value in place — the README is committed evidence prose, and rewriting it in situ destroys the record of what was concluded and why. |
| `experiments/real-world-validation/gracefo/gracefo_common.py:65` | `DSMC_CD_BAND` | **Do not touch.** Frozen. The new tree defines no band at all. |
| `experiments/real-world-validation/gracefo/results.txt` | lines 43 / 80 / 124 / 161 / 206 / 243 / 288 / 328 | **Do not regenerate.** Frozen. |

**Wording discipline: withdrawn, not refuted.** Mehta, McLaughlin & Sutton (2013,
*Adv. Space Res.* 52(12) 2035–2051) is a genuine DSMC study of the GRACE bus, but its values
have not been checked against the paper, so the correction may **not** assert that the box
table falls outside a correctly-sourced band. The recorded statement is: *the credibility
claim rested on a mis-sourced upper edge and is withdrawn; absent a verified reference this
project makes no statement about absolute Cd level, consistent with §2.1.*

**Deliverables:**

1. **Committed results files** per leg, regenerable by one orchestrator command, ASCII,
   deterministic modulo wall-clock lines. **Determinism is a requirement, not an
   observation** — no RNG anywhere (Leg E's log-spaced-toward-recency subsampling is a
   closed-form index rule, not a sample; §3's window list is fixed and recorded, not drawn),
   no `Epoch.now()`, no wall-clock-dependent anchor placement. `--verify` is the only proof
   the evidence is reproducible, and one stray random draw silently retires it. **Every
   header records the resolved `orekit_jpype` version and the propygator version.**
2. **`docs/extended-validation-findings.md`** — the findings record, in the style of
   `real-world-validation-findings.md`: what was measured, what it means, what is honestly
   caveated, **every pre-registered prediction resolved as hit or miss**, and **every
   reported-only quantity (A4, B2, B5) printed with its confounds rather than a verdict**.
3. **A revised `docs/tle-fitting-playbook.md`** — thresholds validated or corrected,
   evidence base restated, the s-gate domain-of-validity statement added (§7), the catalog
   claim on matched-staleness footing (§6).
4. **New pinned regression tests** mirroring the v0.7.2 study's three, with the **inherited
   tolerance policy: measured × a margin generous enough to absorb orekit-data refreshes,
   relationships over absolutes.** The pins prove the wiring didn't regress, not that a
   number is exact. New JVM-touching tests acquire the `orekit` fixture (architecture §11);
   fixtures are in-file literals emitted by a driver `--emit-fixture` flag.
5. **Reconciliation:** README "Validation"; `notebooks/07_tle_fitting.ipynb` §9 and
   `notebooks/00_showcase.ipynb` (hand-transcribed numbers + a fresh static HTML export if
   the showcase changes). **The DSMC retraction touches none of these** — verified zero
   references in `README.md`, the notebooks, and the playbook.
6. **The DSMC correction** — the additive prose edits tabulated above, applied at wrap-up
   only, with the frozen constant and results files untouched.
7. **CHANGELOG entry and version bump — the maintainer's** (§11).

**Compute and storage budget (planning input, not a contract term):**

- **Storage is the new constraint** (§3) — but sized **per leg on its driver's own day
  count**, not on the 10-day download convention: 3 days per curve window, 10 only for the
  anchor and storm legs. Ten LST curve windows is ~4.4 GB. The standalone-`GNV1B` question
  and the GRACE-era per-day volume resolve in Chunks 0 and 1, and both answers are recorded.
- **The `D(w)` sweep runs Run 3 only — for a scientific reason, not a compute one.** The
  curve needs the scalar-Cd fit and nothing else: Runs 1/2/4/5 exist to put **the tables**
  under test, and the tables are not under test at a curve window. Running them there would
  produce rows no prediction consumes.

  > **The compute argument that used to sit here was wrong and is withdrawn.** Measured from
  > the frozen v0.7.2 evidence, an *entire* Run 1–5 window — maneuver screen, t₀ check, the
  > golden-section fit, both table runs, verify-4 and verify-5 — sums to **≈ 390 s wall**, not
  > the "~15–30 min" this section previously claimed, because Runs 1/2/4/5 cost only 12–43 s
  > each (`results.txt`: run 4 at 12 s, run 5 at 23 s, verify-4 at 21 s) while the **fit alone
  > is 210–239 s**. Dropping Runs 1/2/4/5 therefore saves ~10 %, not a "fraction". With the
  > sub-arc floor added (§5), a Run-3-only curve window costs **more** than a full Run 1–5
  > window. Keep the decision; do not repeat the justification.

- **Chunk 2's curve leg is the study's largest compute block — larger than Leg E.** Per
  window: screen + t₀ + the main fit + **2** sub-arc fits ≈ **700–900 s**, per satellite.
  Ten LST windows ≈ **2.5 h at one satellite**, ~5 h if run on both. Leg E, by contrast, is
  budgeted at ~1.5 h. Any statement about "the heaviest group" means Chunk 2.
- **The LST curve windows run satellite C only.** The twin buys nothing the curve leg's own
  claims are judged against: §5 routes A1's twin floor to **cross-body** claims, while the
  curve leg produces only **cross-window** claims (B2, B5), which are judged against the
  sub-arc floor. M1 is already measured in full in Chunk 0 on the three inherited windows.
  Running D at every curve window would double the study's largest block to buy extra M1
  samples that no prediction consumes. **Both satellites are still run at the inherited
  windows (Chunk 0) and throughout Leg C**, where they are two genuine catalog objects (§6).
- **Leg C** — cheap. `probe3` measured **4 anchors in ~80 s wall**
  (`results_probe3_rule_replication.txt:24`), i.e. ~20 s per *anchor*; each anchor is 2
  staging fits + 4 arms, so the unit cost is **~3.4 s per fit-and-forecast**, not 20 s.
- **Leg E** — the heaviest group, though lighter than the headline count suggests. The
  declared axes multiply to τ (6) × regimes (3) × anchors (3) × B\*-modes (2) × skew (2) ×
  satellites (2) ≈ **430 weighted fits**; at ~3.4 s each that is ~25 min, and roughly triples
  once the unweighted staging pairs and the playbook-arm baselines each row is scored against
  are included. **Budget ~1.5 h, cap at 3 h**, and make the group resumable per regime. The
  earlier "~20 s per fit" figure misread `probe3`'s per-anchor wall time.

**A whole-study `--verify` is therefore a multi-day-scale commitment — on the order of 6–10
hours once Chunk 2 (~2.5 h), the GRACE drag anchors, Leg C and Leg E (~1.5 h) are summed —
and per-group verify is the documented default.** The orchestrator exists so groups run unattended and resume
independently; a full regenerate is a deliberate, scheduled act, and the study README says
so.

> **Resumability is a requirement on every multi-hour group, not just Leg E.** The curve leg
> (§5) and the playbook leg (§6) both run long enough that a mid-run interruption must not
> cost the whole group. Each is checkpointed at its natural unit — **per window** for the
> curve leg, **per window** for the playbook leg, **per regime** for Leg E — writing completed
> units as it goes and skipping them on a re-run. This is a property of the group's driver,
> not of `run_all.py`, and it costs nothing to build in from the start; retrofitting it after
> the first four-hour run dies at hour three is the expensive path.

---

## 10. What the end product looks like

The claims this study is built to be able to make — each either earned or explicitly
withheld:

- *"propygator's drag stack is validated against precise orbits from **two independent
  missions and four spacecraft**, spanning 2002–2024 and a range of drag regimes, and the
  fitted-Cd density lever transfers across a 17-year gap on the same bus lineage."*
- *"The measurement noise floor of the fitted-Cd method is X %, measured on a formation
  twin"* — the first error bar the method has ever had.
- *"`Cd_table/Cd_fitted` varies by X× across an LST- and activity-stratified window set,
  against a tables' own modelled response of Y % over the same conditions"* — the two numbers
  side by side, each with its A/m bracket, **with the attribution between them explicitly
  declined** (§2.5).
- *"The shipped Cd tables reduce a 4480-point cloud sampled over local solar time, latitude,
  F10.7 and Ap onto a (radius, density) grid, and that reduction costs **0.49 % RMS** against
  the model that generated it"* — read off the committed `.npz` `metadata_json`, needing no
  external anchor and no assumption about the true Cd. Quoted beside an O(2) measured T
  spread, it is the replacement for the withdrawn decomposition claim. **Its scope is stated
  with it:** the residual bounds table-vs-its-own-physics, not table-vs-truth, so whether the
  *true* Cd's LST response exceeds the model's stays unmeasured (§2.5).
- **Explicitly withheld:** *"the shipped Cd tables carry a table error of X %."* Unearnable
  by any orbit-only design (§2.1). The findings doc states the limit rather than leaving a
  reader to assume the study just didn't get to it.
- **Explicitly withheld:** *"at least X % of the observed variation is density bias rather
  than table error."* The variance decomposition needs an unmeasurable assumption about the
  true Cd's response — §2.1's problem one level up (§2.3 M2).
- **Explicitly withheld:** any claim about the tables' *geometry* dependence from flight
  data, **and any claim about the absolute Cd level**. §2.3 M4b explains why no reachable
  satellite supplies the first; the DSMC retraction (§2.3 M4) leaves the study with **no
  external level anchor at all**, so §2.1's unresolvable degree of freedom stays unresolved
  and is reported as such.
- *"The TLE fitting playbook's r/s gate selects the best-forecasting arm at N of N anchors
  across a wide drag-level range, under thresholds frozen from prior single-satellite
  data."*
- *"A playbook-fitted TLE beats a same-footing catalog TLE by X on the fit day and Y at +3
  days"* — the matched-staleness claim, README-worthy in a way the stale-catalog claim was
  not.
- *"The s-gate detects in-arc nonstationarity and provably cannot detect post-arc onset"* —
  the domain-of-validity statement.
- *"Fading-memory weighting was measured against a pre-registered bar and deferred"* — or
  promoted, on its own branch.

**Named follow-ons this study elects rather than executes:** a genuine **bus contrast**
(TerraSAR-X / TanDEM-X is the candidate worth checking — ~515 km, hexagonal prism,
body-mounted panels, close-formation twins, so a bus contrast *and* a second noise-floor
pair; public POD terms unconfirmed, which is why it is not a leg); the **NRLMSISE-00
ap-history mode**; **route 5** (refit-cadence sweep); a **drag-free high-LEO point** for the
r-gate's "no" arm; and the **70×70 gravity truncation self-ablation** — never ablated at LEO,
only at LAGEOS altitude where degree 70 is suppressed by ~1e-20 against ~5e-3 here, and
`eigen-6s.gfc` carries 240 degrees. It needs no truth data and it sits underneath every
along-track residual this study measures.

---

## 11. Git & versioning

**Branch:** `study/extended-validation`, created off `main` by the maintainer and already
pushed. The `study/` prefix matches `study/real-world-validation`; `feature/` would
misdescribe it. The branch name is retained across the 2026-08-08 body-set change — it still
describes the work.

**One branch, whole study.** The precedent held for the last study, and the checkpoints here
are analysis gates rather than merge gates. **The API-change firewall is the reason it
works:** nothing on this branch touches `src/`, so the release notes cannot end up claiming
that a surface was validated against evidence produced by the same branch that changed it.

**Version — deliberately not decided in advance**, because it depends on Checkpoint D:

- **Evidence + docs + pinned tests + README, no API change → PATCH, `v0.8.1`.** This is the
  expected outcome and it matches the v0.7.2 precedent exactly.
- **Checkpoint D promotes → a MINOR release later, from a separate branch.** A
  `measurement_decay_tau` parameter is new public surface (`v0.9.0`), shipped by
  `feature/fading-memory-weights` off `main` **after** this study merges.
- A playbook threshold *correction* is still docs → still a patch.

**Per-chunk rhythm** is the repo's usual: `git status` → `git add -A` → `git commit -m
"study chunk N: <summary>"` → `git push`. **Commits, CHANGELOG narrative, chunk-header
"done" marks, truth-data downloads, Space-Track pulls, and the release are the
maintainer's.** Claude writes scripts/tests/docs and runs read-only and test commands.

---

## 12. Decisions log

### Resolved by this contract

- **The body set is the GRACE lineage: GRACE-FO 1 + 2, GRACE A + B.** Swarm A and B were
  retired 2026-08-08. Three reasons, in order of weight: (i) Swarm's `E` — an excluded 4 m
  boom, a base-averaged trapezoid, a literature frontal area, an unpublished in-window mass
  history — swamps the table error its ratio was meant to isolate; (ii) on objective 2's own
  terms it adds nothing scarce, since GRACE supplies anchor count, drag-level range and
  orbit type, leaving only a marginal and unquantified tracking-population difference; and
  (iii) a Swarm row would *look* like a geometry test without being one, and the temptation
  to read it as one survives any caveat. Retiring it also removes the study's only path to
  an edit of frozen code (§9) and its largest technical unknown (the ESA `.DBL` archive and
  `parse_sp3`'s LAGEOS-specific dialect assumptions).
- **The "X % table error" claim is withdrawn as unearnable** (§2.1). The level is one
  unresolvable degree of freedom in any orbit-only design.
- **The DSMC comparison is retracted in full** (§2.3 M4). `DSMC_CD_BAND`'s upper edge traces
  to arXiv 2503.21651 = Leipner et al., a closed-loop *simulation* that varies Cd as an input
  and whose 4.5 is a hypothetical **double-deployable-panel** configuration — not DSMC, not
  the GRACE bus. The study quotes no band, runs no desk comparison, and recalls no DSMC
  value; it therefore has **no external level anchor**, which costs nothing because §2.1 had
  already withdrawn every level claim. The two dependent v0.7.2 claims are corrected
  **additively at wrap-up**, with the frozen constant and results untouched (§9).
- **Leg B is downscoped from decomposition to reporting** (§2.5). M2's "at least X % is
  density bias" is withdrawn — bounding the table's shape error by the table's own range
  holds only if the true Cd varies no more than the table does, which is unmeasurable from
  orbit data. B2 and B5 become **reported measurements, not pass/fail predictions**; A4
  becomes a **reported diagnostic**, since its `D(w₂)/D(w₁)` confound is O(2) against a
  few-percent floor. What replaces the withdrawn claim is the **dimensional-collapse finding
  stated with its measured size**: the shipped grids reduce an LST-, latitude-, F10.7- and
  Ap-sampled 4480-point cloud onto (radius, density) at a cost of **0.490 % RMS**, per the
  generator's own `metadata_json`. **Corrected 2026-08-08** — an earlier draft stated this as
  *"the tables have no composition axis and cannot represent an LST-driven composition
  response at all"*, which the shipped metadata contradicts. The residual bounds
  table-vs-its-own-generator-physics only; table-vs-truth stays unreachable (§2.5).
- **The table-range figure is a lookup on the committed `.npz`, not a generator run** — so
  the study needs no `pymsis`/`scipy` venv and §3's conda-env lock has no carve-out.
- **The two error floors are routed by cancellation structure, not pooled** (§5): A1's twin
  floor for cross-body claims, a within-window **sub-arc** floor (3 separate 1-day fits on
  data already loaded) for cross-window claims, because A1 cancels exactly the terms that vary
  between windows and is anti-conservative there.
- **A1's label carries three terms** — floor + fore/aft asymmetry + any true twin A/m
  difference — because the third is a systematic, not noise (§2.3 M1).
- **T is demoted from primary quantity to normalization convention**, is bracketed over the
  assumed **A/m** rather than mass alone (§2.2), and is never quoted as a statement about
  the sphere table.
- **GRACE-FO 2 is activated first and costs nothing** — already inside the tarballs on disk,
  reachable through the frozen parser's existing `sat_id` path.
- **Checkpoint A moves to the twin**, where the expected answer is 1 and no density or
  ballistic-coefficient arithmetic can hide a wiring bug (§4).
- **The GRACE record format is resolved by inspection before any GRACE code is written**,
  with both branches costed and neither blocking; GRACE lands as a new module in the new
  tree regardless (§3, §9).
- **Storage, not compute, is the binding constraint** — but **sized per leg on its driver's
  own day count** (3 days for the curve, 10 only for the anchor and storm legs), never on the
  inherited 10-day download convention. The standalone-`GNV1B` question is answered in Chunk 0
  and the GRACE-era per-day volume in Chunk 1, both recorded (§3, §9).
- **The `D(w)` sweep runs Run 3 only**, and the reason is **scientific, not compute**: Runs
  1/2/4/5 put the tables under test, and the tables are not under test at a curve window. The
  earlier compute justification is withdrawn — measured, a whole Run 1–5 window is ≈ 390 s and
  the fit alone is 210–239 s, so dropping the other runs saves ~10 % (§9).
- **The LST curve windows run GRACE-FO 1 only.** The twin floor governs cross-body claims;
  the curve leg makes only cross-window claims, judged against the sub-arc floor. Both
  satellites still run at the inherited windows and throughout Leg C (§9).
- **Leg C draws only on windows already provisioned at 10 days** — inherited quiet/active,
  the E1 drag-timescale window, and the storm library. The 3-day curve and GRACE-anchor
  windows cannot host a 3 d + 3 d anchor and are not Leg C sources; the enumerated set spans
  the drag-level range C1 actually requires (§3, §6).
- **Windows are stratified on LST as well as activity**, from a fixed recorded list, never
  randomized (§3).
- **r/s thresholds are frozen as pre-registered predictions.** Post-hoc re-calibration is
  reported separately and labelled.
- **C1 is stated behaviorally** — the gate's chosen arm is the best-forecasting arm —
  because the earlier formulation conflated the calendar window with the drag regime (§6).
- **Matched-staleness rule: latest catalog epoch ≤ T, staleness always reported**, with
  close-formation cross-tagging named as a hazard to check (§3).
- **Storm anchors are placed pre-onset / mid / post by construction**, and the library must
  contain at least one *moderate* event or it cannot hunt the false negative (§7).
- **GRACE-FO 2 does not count toward Leg E's two-satellite condition** (§8 E1), and **E1 is
  resolved in the quiet and active regimes only** — the missions do not overlap in time, so no
  storm event exists that both bodies flew through, and satellite is confounded with event in
  the storm regime by construction. E1's active regime requires the **new §3 E1
  drag-timescale window** (GRACE ~430 km, F10.7 matched to `active_2023`); neither GRACE
  anchor window supplies a timescale contrast, since both sit inside GRACE-FO's own altitude
  envelope.
- **The Gannon window is extended to 2024-05-07 → 05-16** so it carries §7's 3 d + 3 d anchor
  geometry; the committed 4-day rows stay untouched as the continuity baseline (§3).
- **The storm-anchor day labels are inclusive whole-day counts and an anchor sits at the
  *start* of its named day** — under that convention a 10-day window is exact for the
  day-4-onset geometry (§3).
- **Fading memory: bar carried verbatim, default DEFER, promotion exits to its own branch.**
- **No `src/` change on this branch**, with a symmetric re-run rule if a defect is fixed on
  `main` mid-study (§9).
- **Version follows the outcome**, defaulting to patch `v0.8.1` (§11).

### Open — to confirm before or during the build

- **The GRACE L1B record format** (ASCII vs binary) and, if binary, the delivered record
  layout — resolved by inspection in Chunk 1.
- **Whether PO.DAAC serves `GNV1B` standalone** — resolved in Chunk 0; caps window count if
  not, though the per-leg day counts in §3 make that cap likely non-binding for the curve leg.
- **The GRACE-era daily L1B volume** — independent of the GRACE-FO 148 MB figure and the
  thing that actually sizes the storm library; measured and recorded in Chunk 1.
- **GRACE equivalent-box dimensions and per-window mass** — chunk-time literature pull with
  citations, in the style of `gracefo_common.py`'s documented geometry note.
- **GRACE-FO 1/2 relative-yaw attitude convention** — verified before M1's deviation is
  labelled.
- **The LST-stratified and GRACE-anchor window dates**, after maneuver and data-availability
  screening.
- **The storm-library events**, after the moderate-event screening rule in §7.
- **The E1 drag-timescale window dates** (~2014–2015, ~420–440 km, F10.7 matched to
  `active_2023`), after the attitude-mode and data-gap screen of §2.4.
- **The tables' modelled response** over the actual LST and activity span — a lookup on the
  committed `.npz` grids, computed in **Chunk 2** so B2 resolves in the chunk that produces
  its other two numbers, and consumed by Chunk 4 (§2.5).
- **Anchor count per window** — ≥ 4 is the contract floor; more is a build-plan tuning call
  against the compute and disk budget.
- **Checkpoint A (GO / INVESTIGATE) and Checkpoint D (DEFER / PROMOTE) are the maintainer's
  calls.**

---

## 13. Definition of done

1. **GRACE-FO 2 stands up (§3, §4):** D parsed through the imported frozen parser with a
   `qualflg` drop rate comparable to C's; t₀ frame/time diff at float-noise level;
   **Checkpoint A resolved GO** against the twin criterion (or a defect exited to the fix
   path, the affected groups were re-run per §9, and the study resumed).
2. **GRACE stands up (§3):** the record format resolved by inspection, the reader landed as
   a new module, the A–B separation / |r| / |v| self-checks clean, maneuver and
   late-mission-degradation screens clean on every window.
3. **Leg A complete (§4):** the Run 1–5 structure measured at the new bodies and epochs;
   **A1–A3 resolved hit or miss and A4 reported as a diagnostic** with its confounds
   enumerated; the M1 noise floor measured and labelled with **all three** terms.
4. **Leg B complete (§5):** the `D(w)` curve computed for both tables with every cell
   bracketed over the assumed A/m; the tables' modelled response over the same conditions
   obtained **by lookup on the committed `.npz`** and quoted beside it **with the attribution
   declined in writing** (§2.5); the **dimensional-collapse finding recorded with its measured
   0.490 % RMS** and its table-vs-own-physics scope stated (never as an absence claim); the
   absorbable-scale retest, attitude-sensitivity bound and regime-guard exercise run; **B1,
   B3 and B4 resolved hit or miss, B2 and B5 reported**; σ(T) reported with the two floors
   routed by cancellation structure — the twin floor for cross-body claims, the sub-arc floor
   for cross-window claims, and **no third source** (the golden-section curvature is a
   fit-quality diagnostic, never an error bar; §5). **No DSMC comparison** (§2.3
   M4), and the withheld level stated as withheld.
5. **Leg C complete (§6):** the playbook replicated across the achieved anchor set under
   **frozen** thresholds; matched-staleness catalog rows at every anchor with staleness
   reported; Leg C′ rows measured **and labelled by route**; C1–C5 resolved, C5 per route;
   the anchor-correlation caveat in every header.
6. **Leg D complete (§7):** ≥ 3 additional storm events including at least one moderate,
   plus the **extended Gannon window (2024-05-07 → 05-16)**; anchors at the starts of days
   4 / 6 / 8 of 10-day windows under §3's labelling convention; the gate-failure vs
   unforecastable-onset distinction resolved; **the s-gate domain-of-validity statement
   written into the playbook**; the daily-Ap caveat attached to every storm row.
7. **Leg E resolved (§8):** the τ-sweep executed with the sampling-skew axis, the
   conservative r-gate protocol, and conditions E1–E3 — with **E1 satisfied by GRACE against
   GRACE-FO in the quiet and active regimes** (the 2008–09 minimum and the §3 E1
   drag-timescale window), **not** by the twin and **not** in the storm regime, where the
   satellite/event confound is stated instead; **Checkpoint D recorded as DEFER or PROMOTE
   against the verbatim bar**, with the sensitivity curve in evidence.
8. **Evidence body committed (§9):** results files regenerable by one orchestrator command,
   every header carrying both versions; `docs/extended-validation-findings.md` written with
   every pre-registered prediction resolved **and every withheld claim stated as withheld**;
   the playbook revised; new pinned tests green under the inherited tolerance policy and
   acquiring the `orekit` fixture.
9. **Frozen-evidence rule honored (§9):** no code, constant, or results file in
   `experiments/real-world-validation/` changed; the DSMC correction landed as **additive
   prose only**, and `run_all.py --verify` on that tree is still green.
10. **Reconciliation done (§1):** README "Validation"; notebook 07 §9 and
    `00_showcase.ipynb` updated if playbook numbers moved (with a fresh static HTML export
    for the showcase); `tle-fit-strategy-findings.md` closed or archived.
11. **No `src/` change on this branch**; `pre-commit run --all-files` clean; CHANGELOG entry
    and version bump authored by the maintainer (§11).
