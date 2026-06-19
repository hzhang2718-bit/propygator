# Tier B drag table — maturity, difficulty, and the interpolation question

> **Status: FINDINGS / ANALYSIS — not a design contract and not a build plan.** A
> standalone assessment of whether (and how) to build the Tier B incidence-keyed box
> drag table (`IncidenceVariableCd`), written to capture the reasoning before any build
> decision. It does **not** supersede anything. The binding designs remain
> `docs/features.md` §1.1 ("Drag-coefficient modeling") and `docs/architecture.md` §13
> ("Coefficient of drag modeling"); the supporting evidence is in
> `experiments/drag-coefficient-verification/`. If Tier B is later adopted, the relevant
> parts here get folded into a build plan the usual way.

## 1. The question

Tier B is the documented faithful box-drag extension: a `(geocentric radius, density,
azimuth, elevation [, array])` table (`IncidenceVariableCd`) that captures per-face flow
incidence, generated offline by a panel method (ADBSat) or DSMC. It ships today as a
**validated skeleton** — `IncidenceVariableCd` constructs/validates/hashes, but
`__call__` and the `propagate_numerical` drag-wiring path raise `NotImplementedError`
(`spacecraft.py`, `numerical.py:447-452`; `features.md` §1.1 failure-modes row).

Two things were asked about it:

1. **Maturity** — do we have enough evidence the strategy works well?
2. **Difficulty** — how hard is it to build? And specifically: **how dangerous is linear
   interpolation over the incidence axes, and can a finely-sampled experiment table
   demonstrate it's safe (with a larger shipped table as the mitigation if not)?**

## 2. Maturity

**The keying strategy is well-evidenced (good).** The load-bearing assumption — that a
box/plate's free-molecular Cd collapses onto `(geocentric radius, density)` *at a fixed
attitude* — is directly tested in `cd_box_experiment.py`: a cube and a thin plate swept
from head-on to 80° grazing across ~130–1400 km with a storm cohort. Collapse RMS is
≤ ~2% even for the 80° grazing plate (`cd_box_results.txt`), an order of magnitude under
the 15–30% thermospheric density-model uncertainty that dominates total drag error. So
Tier B's **axis choice** is as validated as Tier A's, and `cd_box.py` already provides a
working per-face Schaaf–Chambre/Sentman kernel (self-checked against the sphere to <0.1%).

**Where the evidence runs out (the real maturity gap).** The experiment validates collapse
*at each fixed incidence* — it does **not** validate the **incidence interpolation** over
the new azimuth/elevation grid, which is the entire point of Tier B. There is also, by
design, **no shipped default table, no generation script, and no committed box table**
(`features.md` §1.1: a box table is geometry/material-specific, "no shipped default"). So
we have evidence the table is *keyable*, but none yet that a *coarsely-gridded,
interpolated* box table is accurate, and no tooling that produces one.

## 3. Difficulty — split two ways

**(a) Enabling a user-supplied Tier B table (the in-package work): low–moderate.** The
runtime is mostly mechanical on the existing shared `_DragSensitive` proxy
(`numerical.py`): inside `dragAcceleration` you already receive the `SpacecraftState`
(which carries attitude) and the relative-velocity vector, so you rotate the relative
velocity into the body frame via `state.getAttitude().getRotation()`, map to
`(azimuth, elevation)`, and do a multi-D interpolation — the 2-D clamp-to-edge
interpolation and content-hashing machinery already exist in `spacecraft.py`, and the
`IncidenceVariableCd` skeleton already constructs and validates. The wiring points are the
single `NotImplementedError` at `numerical.py:447-452` and `IncidenceVariableCd.__call__`.
The non-mechanical costs are a body-frame/flow-direction convention reconciliation (same
convention-bug class as the ECEF attitude work) and an end-to-end test with a hand-checked
incidence value.

**(b) Shipping a *faithful, validated* default box table: high and evidence-thin.** That
needs an offline panel-method (ADBSat) or DSMC generator handling facet visibility/
shadowing, array articulation, and per-material accommodation, **plus** a new validation
that the interpolated Cd is accurate across the incidence grid — none of which exists
today. This is the research-grade part, and is exactly why the docs class it as a
deferred, user-supplied extension.

**Bottom line:** *enabling* a user table is a modest, well-scoped chunk; shipping a
*validated default* box table is a large undertaking gated on external tooling and an
interpolation-fidelity study that hasn't been done. If pursued, scope it as "accept and
propagate a user-supplied incidence table" and keep the validity claim narrow.

## 4. The interpolation question

### 4.1 How dangerous is linear interpolation here? — Low-risk for a convex box

In free-molecular flow, molecules don't collide near the body, so faces don't shadow or
wake each other — total Cd is a **sum of independent per-face contributions**, each
depending only on its own incidence. Each per-face term is a smooth (C∞) sin/cos/erf
expression (Schaaf–Chambre/Sentman) that turns on/off **continuously** as the face crosses
windward↔leeward (its projected area ∝ max(cosθ, 0) → 0 smoothly at θ = 90°).

Consequence: `Cd(azimuth, elevation)` for a convex box is **continuous and piecewise-
smooth, with at worst mild slope-kinks** at face-transition directions (flow parallel to a
face — the cube's edge-on / corner-on orientations). There are **no value jumps**.

That governs the linear-interpolation error, which scales as ~`(h²/8)·|f''|` (quadratic in
grid spacing `h`):

- Over the smooth interior: very accurate even on a modest grid.
- Worst curvature is near grazing (θ → 90°) — but the drag **force** → 0 there (area → 0),
  so the **absolute** error stays bounded. (Seen in the experiment: the 80° grazing plate
  has the largest scatter ~2% but the smallest Cd 0.43, so its force contribution is tiny.)
- At the face-transition kinks: locally first-order (not second-order) error, but it's a
  slope kink not a jump — small, bounded, and it shrinks under refinement.

So the one thing linear interpolation truly smears — a **value discontinuity** — does
**not** occur in the closed-form convex box. **Where it could get dangerous** is the
effects the closed form omits but a real generator (ADBSat/DSMC) includes: multiple
reflections, **inter-panel shadowing** (e.g. a solar array shadowing the bus at certain
articulation/incidence combos), or sharp specular lobes. Those can create steep ridges or
near-discontinuities, and articulated arrays add a coupling axis.

### 4.2 Can a fine experiment table demonstrate it's reasonable? — Yes, cheaply

`cd_box.py` already has the vectorized per-face kernel, so a convergence/refinement study
is cheap to add:

1. Generate Cd on a **very fine** `(azimuth, elevation)` grid = "truth."
2. Subsample to candidate **coarse** grids; linearly interpolate back to the fine grid;
   measure **max & RMS error vs truth**. Plot Cd vs incidence to eyeball for kinks/cusps.

How to read it — and whether a **larger table mitigates** (the second sub-question):

- **If error falls ~4× each time you halve the spacing** (clean second-order convergence)
  → smooth regime confirmed; you can pick a spacing to hit any error target, and a larger
  table **provably mitigates**. This is the expected outcome for the convex FM box.
- **If error plateaus under refinement** → there's a near-discontinuity, and a larger
  *uniform* table only **narrows** the bad band — it does **not** drive the peak error to
  zero. The fix there isn't "more points" but "put grid nodes *on* the feature" (align to
  face-transition angles), store in a coordinate that removes the kink, or accept bounded
  error where the force is small. The convergence study is precisely what tells you which
  regime you're in.

### 4.3 Scope caveats so the evidence stays honest

- A convergence study on the **closed-form** kernel only certifies linear-interp fidelity
  for the **convex, no-shadowing** box. A table later produced by ADBSat/DSMC for an
  articulated/shadowed geometry must be re-checked the same way against its own fine grid.
  Since propygator ships **no default box table** (user-supplied), the right deliverables
  are (1) the convergence study as evidence the keying + linear-interp *design* is sound
  for the canonical box, and (2) a documented recommendation that users validate their own
  table's interpolability identically. The runtime already clamps out-of-grid rather than
  extrapolating — keep that.
- The incidence dependence is largely **separable** from the `(radius, density)`
  dependence (the shape of Cd-vs-incidence shifts only slowly with altitude, and the
  fixed-attitude collapse is already validated), so the incidence-resolution study can run
  at a single representative altitude and be trusted to transfer — keeping the experiment
  small.

## 5. Net assessment

- **Strategy maturity:** the `(radius, density)` keying is well-proven for boxes/plates;
  the **incidence-interpolation** fidelity is unproven but is low-risk for the canonical
  convex box on physics grounds, and is **cheaply demonstrable** with a fine-grid
  convergence study built on the existing `cd_box.py` kernel.
- **Difficulty:** *enabling* a user-supplied incidence table is a modest, well-scoped
  chunk on the existing drag proxy; shipping a *faithful validated default* box table is a
  large, evidence-thin, externally-gated effort (correctly deferred).
- **If pursued:** add the convergence study to the box experiment first (direct evidence
  for the safe case + a reusable template for users), then build only the "accept and
  propagate a user table" path, with a narrow, documented validity claim and the existing
  clamp-don't-extrapolate behavior retained.

## 6. See also

- `docs/features.md` §1.1 — "Drag-coefficient modeling" (Tier A / Tier B design).
- `docs/architecture.md` §13 — "Coefficient of drag modeling" (contract-level note).
- `experiments/drag-coefficient-verification/` — `cd_box.py` (per-face kernel),
  `cd_box_experiment.py` / `cd_box_results.txt` (fixed-attitude collapse evidence),
  `README.md` (full provenance).
