# Propygator - Extended validation study involving additional drag-significant propagations, TLE fitting tests, and table noise

> Status: drafted

## Purpose and scope

The past real world validation experiment conducted several numerical
propagator runs on LAGEOS and GRACE-FO. For LAGEOS, the results are
highly positive, with sub 100 m errors even over weeks, showing that
propygator is highly accurate and reliable when it comes to working
with conservative forces. The results for GRACE-FO, where drag is
significant, are relatively positive, too. However, the errors were
large enough (usually in the hundreds of meters per day, sometimes
up to kilometers per day) that it is wise to conduct more runs to
gain a better understanding of its accuracies and weaknesses.

In addition, little evidence currently exists for the TLE fitting
playbook, the decided r/s gate for the playbook, and the fading
memory fitting approach. This study seeks to validate or invalidate
the TLE playbook and existing r/s gate. It also seeks to set a
firm decision on whether fading memory fitting should be promoted
or deferred for good.

Furthermore, the numerical propagator should produce nearly identical
drag-related values (atmospheric density and Cd) for similar
satellites under similar locations. This will be validated on
the GRACE-FO twin by computing certain orbital propagation result
ratios.

This study will involve working on the experiments folder, as well
as accompanying doc work. It will consult but not change features.md
or architecture.md. It will not touch anything in src/. It will not
touch anything in previous experiments, unless in the few spots
sanctioned below.

The following are adjacent to this work and are explicitly out of
scope. Each is its own branch off main if it is ever pursued:

- The `earth_radiation` force model. It is parked, and the upstream
  Orekit fix that unblocks it needs an environment upgrade that this
  study forbids (see Conventions and constraints).
- The NRLMSISE-00 ap-history mode (`withSwitch(9, -1)`). It would
  move every storm-time number in the repository.
- The `box_and_panels` fitted-geometry upgrade.

This document is to be archived after its completion.

## The design - drag-significant propagations

### Part A: additional drag-significant propagations, GRACE-FO

This study will use a new, stratified selection of GRACE-FO windows.
Windows will be randomly selected from periods of low solar activity,
moderate solar activity, intense solar activity, and solar storms.
Which windows are selected is yet to be decided.

No window may extend past **2026-05-09**. That is where the OBSERVED
block ends in orekit-data's CSSI file; after it the daily-predicted
rows carry a flat placeholder Ap and Kp, so a storm window there
would contain no storm in the model at all and would read as a
propagator failure rather than as missing input. GRACE-FO launched
2018-05 and Swarm 2013-11, so 2018-06 to 2026-05-09 is the drawable
span -- ample, covering the 2019-2020 minimum, the 2023-2025 maximum
and Gannon 2024-05. Re-check the boundary if orekit-data is ever
refreshed; it moves.
The aim is to have 10 windows, each 13 days long -- 13 because the
longest fit arc in the study is the fading-memory 6-day arc and every
fit is scored 7 days past its arc. Part A propagates days 1-7 from
t0; the TLE forecasts run days 7-13, which is why the maneuver screen
has to be clean across all 13 days and not just Part A's seven. For
each window, the drag test will be the same as the one for the earlier
real world validation experiment. Each window will get propagations
with drag off, drag on (Cd=2.3), drag on (in-arc Cd fit), sphere table, and
box table. If there
is a maneuver, days will be prepended or appended as convenient to
recreate a full, maneuver-free window. The exception to this is
storms, since they are time-sensitive. If a maneuver coincides with
a storm, a different storm will be selected.

Each of those five configurations is **one** propagation, run for
7 days from the window's t0. The 1 day, 3 day and 7 day results are
read off that single run; they are not three separate runs. For each
configuration the results file records radial, along, cross and 3D
RMS accumulated from t0 over 0-1 d, 0-3 d and 0-7 d, and the same
four numbers for each individual day. Five propagations per window
per body, not fifteen.

The fit is the exception to that count and carries the study's
compute: golden section is ~20 propagations, so on a 7 day arc it
costs ~20-25 min against ~1-3 min for each other run, putting Part A
near 16 h overall. Per-window separability is the mitigation; a
whole-study regenerate is a scheduled act. The Cd is in-arc by
design -- the best a scalar Cd can do over the window, and the
reference the other four are judged against. Note its 0-1 d row is
therefore not comparable to the earlier study's 1 day fitted result
(1.9 / 6.4 m): that Cd was optimal over one day, this one over seven.

The GRACE-FO body will be approximated as a box of the following
dimensions, every one of them traceable to the L1 Handbook:
- width = 1.3195 m (average of the trapezoid's top (0.695 m) and
bottom (1.944 m) bases in Figure 2 of the Handbook)
- height = 0.7588835 m (fitted to make the box have the same front
area as GRACE-FO's front (0.9551567 m^2) and boom (0.0461901 m^2)
areas combined, 1.0013468 m^2)
- length = 3.6100207 m (fitted to make the box's four non-ram faces
carry the same total area as GRACE-FO's four non-ram panel groups:
nadir 6.0711120 + zenith 2.1673620 + inner starboard and port
(0.2282913 m^2 each) + outer starboard and port (3.1554792 m^2 each)
= 15.0060150 m^2, solved as 2 * length * (height + width))

Note what that length fit does and does not preserve. It preserves
the total side area, which is the only side quantity drag sees when
the box is flown wind-aligned, because all four side faces then sit
at the same 90 degree flow incidence and only their sum enters Cd*A.
It does not preserve the split between the nadir/zenith pair and the
slant pair: the rectangle carries roughly 1.3 m^2 more on the former
and that much less on the latter. Harmless here, recorded so that
nobody later reads the length as a physical dimension of the
spacecraft. This box also folds the boom into the ram face and
conserves the wetted side area, so it should sit closer to the
published surface model than the earlier study's box did; how much
closer is re-derived when the twin code is rebuilt under this
contract, not carried over from any earlier estimate.

The reference area for every non-box run is A_ref = 1.0013468 m^2 --
the same front face. One convention covers the Cd=2.3 run, the
fitted-Cd run and the sphere-table run, so every Cd printed anywhere
in this study sits on one reference. A fitted Cd means nothing
without its A_ref and mass, so each results file header states
A_ref, the window mass, and the convention-free ballistic
coefficient B = Cd*A/m beside every fitted Cd. This is the second
A_ref the repository has used (v0.7.2 used 1.027 m^2), so never
compare a Cd across two of them without converting first.

The box is flown wind-aligned, with
InPlaneTracking(velocity_reference="ecef"), exactly as the earlier
study's box run was: body +Y is held on the Earth-relative wind, so
every face-flow angle is constant by construction (ram 0, leeward
pi, all four sides pi/2). Axis mapping is x = height, y = length,
z = width.

The box's mass will be extracted from GRACE-FO C's mass during runtime
from the data, out of the MAS1B tank-gas record. This is necessary
because GRACE-FO C's mass changes over time due to propellant use.

> Important: the windows are drawn once, without reference to how
> well the propagator performs on them, and the resulting list is
> then frozen and recorded both here and in the driver. The draw is
> never repeated at runtime. Selecting without regard to the outcome
> is what keeps the study honest; freezing the list afterwards is
> what lets the evidence be re-verified.

> Important: GRACE-FO performs orbit maintenance, so every candidate
> window is screened before it is committed. The screen is the one
> the earlier study used: fit a smooth low-order polynomial to the
> along-track truth signal and measure the departure from it. For
> reference, that study measured a 186.6 m along-track signal with a
> 6.7 m departure from a degree-5 fit and called it clean. The
> threshold is fixed before screening begins, not after. A window
> that fails is retired and replaced by another draw from the same
> activity band, and the retirement is recorded. The same screen
> applies to the Swarm windows in Part B.

> Important: all the runs will be conducted on GRACE-FO C, which is
> the leading of the two satellites. The table noise section below
> needs GRACE-FO D as well, and both satellites live inside the same
> daily tarball, so the extraction step keeps both.

> Important: the data used for these runs will be information that
> is extracted out of daily tarballs. This helps to cut down on
> storage stress. The extraction keeps two products for both
> satellites: GNV1B, the truth ephemeris, at about 23 MB per
> satellite per day before compression, and MAS1B, the tank-gas
> record the window mass is read from, at about 8 kB per satellite
> per day. Everything else in the tarball is discarded. Attempt to
> reuse parser code from the earlier real world validation
> experiment.

> Important: an attempt should be made while constructing the build
> plan to make the run for each window separable. This allows for
> shorter shell run times. If needed, the study needs
> to be capable of running only one window at a time.

### Part B: additional drag-significant propagations, Swarm A, B

This study will also run the identical drag propagations on Swarm
A and B. These are more stress-test cases because the Swarms do
not conform to a very rectangular shape, and their masses are not
known well. The purpose of having these as test cases is to help
understand propygator's accuracy on a different and more
irregularly shaped satellite. The Swarms will use the same
set of windows as above. If a Swarm maneuver happens during one
of those windows, then the windows don't have to match, and days
will be appended/prepended and storms changed as necessary. Record
which windows diverged: a non-matching window confounds body with
epoch, so a Swarm-vs-GRACE-FO difference on that row cannot be
attributed to the body alone.

There appears to be limited public information on the exact
dimensions and masses of the Swarm satellites. As such, estimates
will be used instead. This actually provides an interesting view
into how well propygator operates when a spacecraft's exact properties
are unknown. The box will have the following dimensions and mass:
- length = 5.0 m (around the length of Swarm without boom)
- width = 1.0 m (the source states that the ram area is ~1 m^2,
and we assume a square shape here)
- height = 1.0 m (see above)
- mass = 419.0 kg (drag mass with half of propellant mass)
Sources disagree on the exact dimensions and mass of the Swarm
satellites. These numbers are consistent with the following posting
by ESA: https://earth.esa.int/eogateway/missions/swarm/description
For sphere table and Cd fit runs, the effective cross-sectional area
is 1.0 m^2.

Swarm truth data is the one part of this study with no existing
path. GRACE-FO has the GNV1B product and a working parser; Swarm
has neither in this repository, and it is served by ESA in a
different format. The format is therefore resolved by inspection
**before any Swarm code is written**, in this order:

1. Look at what the ESA archive actually serves for the chosen
   windows. Confirm it against one delivered file rather than
   against documentation.
2. If an SP3 orbit product is available, prefer it. The repository
   already parses SP3 for LAGEOS (`lageos/sp3.py`), which can be
   read as a starting point. It is written against a LAGEOS-specific
   dialect, so it is a reference, not a drop-in.
3. Otherwise write a new reader for whatever format is delivered,
   in the new study's own folder.
4. If neither is workable within a reasonable effort, Part B is
   dropped and the study ships on Part A alone. Nothing else in
   this study depends on Part B.

Whichever reader is used, it is checked before its output is
trusted: position and velocity magnitudes in the expected range for
the orbit, epochs continuous across file seams, and a uniform time
grid. A field misalignment throws these off by orders of magnitude
rather than by percent, which is what makes them a useful check.

Those four catch a misaligned field but not a wrong time scale, which
is the other way a new reader fails: magnitudes, seams and grid all
stay clean while the whole ephemeris sits shifted. Swarm products are
served on GPS time, and reading them as UTC costs ~18 s, or ~137 km
of pure along-track error -- which would read as propygator failing
on Swarm. So: GPS + 19 s = TAI, both leap-free, never a hand-rolled
leap-second table (the locked route, `gracefo/gnv1b.py:44-46`), and
add the check that does catch it -- propagate from t0 and compare the
first sample against truth, as the earlier study does at 4.2e-9 m.

> Only Swarm A and B will be used for these tests. Swarm A
> and C are very similar, and this section aims for variety.

> These runs should also be made separable for each window to
> ensure reasonable shell run times.If needed, the study needs
> to be capable of running only one window at a time.

### Qualifications

This part does not come with a passing benchmark. Rather, it is
a study to gain a better understanding of propygator's orbital
prediction accuracy when drag is present. Notably, the drag tables
are put to test. A good result is when the drag tables runs
consistently beat drag off and Cd=2.3, except perhaps when the
error is very small and negligible anyways.

The earlier study's GRACE-FO results say what pattern to expect.
Reading the drag-off error as the signal the drag model has to
remove, the fraction each option removed was:

| removed | quiet | active | storm |
|---|---|---|---|
| Cd = 2.3 | 86 % | 67 % | 56 % |
| sphere table | 53 % | 80 % | 63 % |
| box table | -24 % | 79 % | 96 % |

The box table overshot a 44 m signal in the quiet window and removed
96 % of a 3.8 km one in the storm window. A bounded loss where drag
is weak, alongside a large gain where drag is strong, is an
acceptable result and is what this part expects to see repeated.

What warrants a bug search is an inversion of that pattern: a table
run losing badly where drag is strong. A table run losing where drag
is weak is expected, provided the absolute error stays small.

## The design - TLE fitting tests

This part will involve fitting TLE to GRACE-FO (no Swarms) data
using various means. For each window, the following TLE fittings
will be conducted on an arc, propagated, and compared to reality.
RMS values against reality 1D, 3D, and 7D after the end of the
fitting arc will be recorded:
- A naive, one-time fitting on the shipped 2-day default (1)
- A fitting for each of the 3 playbook decisions (3)
- Catalogue fitting (pulled from Space-Track by maintainer) (1)
- State fits with sphere and box tables (2)
- Fading memory fits with tau = τ ∈ {0.5, 0.75, 1, 1.5, 2, 3},
fitted over 6-day arc sampled over 300 measurements (6)
That's 13 different fittings, propagations, and results in total.

Every arc, whatever its length, **ends at the same instant** -- the
common forecast start at day 6. The arcs differ in how far back they
reach, never in where they stop. Left-aligning them from t0 instead
would leave each method forecasting from a different epoch, and the
whole part would be measuring arc-end epoch rather than method.

> These runs should also be made separable for each window to
> ensure reasonable shell run times. If needed, the study needs
> to be capable of running only one window at a time.

> Important: the GRACE-FO and Swarm fittings from state will all
> be conduct in InPlaneTracking attitude. To accomplish this, first
> propagate the orbit with the numerical propagator, then fit
> TLE to the trajectory. This should be equivalent to fitting from
> state with InPlaneTracking (which is not available). Supporting
> evidence can be found in result_fit_state_path.txt.

> Important: the catalogue TLE for a given fit must be the one with
> the latest epoch at or before the start of the forecast. A TLE
> with a later epoch carries information none of the other methods
> have, and comparing against it would be meaningless. The staleness,
> meaning the gap between the TLE epoch and the forecast start, is
> recorded on every catalogue row. GRACE-FO C and D fly about 180 km
> apart, and cross-tagged catalogue entries between close-flying
> objects are a known failure mode, so every pull is checked against
> the truth ephemeris before it is used.

> Important: there should be case where the TLE fitting happens
> right before a major change in atmospheric conditions. For instance,
> this may involve fitting to an arc right before, but **not** during,
> a severe solar storm onset. The TLE playbook is expected to fail
> under such a scenario, and it's good to see it happen. If the window
> for this is not available, it is ok to download a couple extra days
> just for this.

> Important: Orekit's NRLMSISE00 at default switches is driven by the
> daily Ap index rather than the 3-hourly values, so in the model a
> storm's onset sits at a UTC day boundary rather than at the physical
> onset time. This decides where the pre-onset arc above has to end:
> before the start of the UTC day containing the storm, not before the
> storm itself. Every storm result here is a result for the model as
> shipped.

> Important: the fading memory affects covariance values used for
> the r/s gate. As such, the computations should be conducted separately
> during runtime. Not a contract issue, but an important build time
> caveat.

> Important: the thresholds are frozen. The gate under test is
> r < 0.05 and s < 0.1 (`tle-fitting-playbook.md:61`), carried into
> this study verbatim as pre-registered predictions made on
> single-satellite data. Re-fitting them to this study's data and
> then reporting that they classify correctly is circular and is
> forbidden. If they misclassify, the misclassification **is** the
> finding. Any recalibration is a separate, post-hoc result and is
> labelled as one.

### Qualifications

This part does have benchmarks, outlined below:
- In order for the r/s gate and the TLE playbook to be validated,
the playbook and gate must beat the naive, one-time fit ≥ 70% of
all propagations for 1D, 3D, and 7D (30 comparisons in total).
In addition, the success rate (success if picking the correct choice,
or picking one of the correct choices) of the r/s gate must be
higher than the success rate of sticking point-blank to any of the
3 gated options.
- In order for the fading memory to be considered for a promotion,
it requires a
median +3 d improvement ≥1.5× in at least two regimes, no
regime >1.25× worse, under a single recommended τ.
The default for fading memory is to defer.

Anchor-to-anchor scatter in comparisons of this kind runs 2-3×, so
differences under 1.5× are not meaningful. Where two options land
within 1.5× of each other at the same anchor, both count as correct.
Without this rule the gate is scored on choices it had no way to get
right, and the bar above becomes harder than it is meant to be.

The 30 comparisons come from 10 independent runs read at three nested
horizons, not 30 independent trials. And a miss on the second clause
means the gate is *redundant*, not wrong -- one arm did the job
everywhere -- which revises the playbook toward that arm rather than
against the gate.

In addition, it is expected that the TLE fitting trials will
all converge and give reasonably close values to reality. If that
is not the case, a search for bugs is warranted.

## The design - table noise

GRACE-FO C and D are essentially the same body flying through
the same atmosphere. For each of the three windows of the earlier real world
validation study (2019 quiet, 2023 active,
and 2024 storm), a Cd will be fitted to the true trajectory of each
GRACE-FO body over 1D. Then, three 1D propagations will
be done on each GRACE-FO body, using the fitted Cd, sphere table, and box
table. The following metrics will be computed:
- Cd_fit(C)/Cd_fit(D)               in sample, 1D
- RMS_Cd_fit(C)/RMS_Cd_fit(D)       propagated on fitted Cd, 1D
- RMS_sphere(C)/RMS_sphere(D)       propagated, 1D
- RMS_box(C)/RMS_box(D)             propagated, 1D

These runs will use the same GRACE-FO geometry as the earlier propagations.

All of the four metrics above should be close to 1.0. Orbits
of essentially the same body propagated through the same atmosphere
should show similar RMS. True orbits of essentially the same body
in the same atmosphere should have similar fitted Cd values.

The two bodies are not perfectly identical, and the difference is
documented. They fly with a relative yaw so their ranging horns face
each other, which puts opposite ends of the same tapered bus into the
wind; the bus is 1.943 m wide at one end and 0.690 m at the other.
The ram area is unchanged but the appendage asymmetry is not, so a
small non-zero deviation here is expected physics rather than a
defect.

> Caveat: use CD_FIT_TOL = 0.002 in the shared fitter. The fit
> returns the midpoint of a bracket it has narrowed to at most tol,
> so it cannot resolve Cd differences much below tol. At a fitted Cd
> of 2-4 that is 0.05-0.1 %, about a tenth of the twin deviations
> this section measures; the v0.7.2 value of 0.02 would put it at
> 0.5-1 %, the same size as the effect. Chunk 0's receipt: bracket
> width 0.00154 at Cd 2.131, or 0.07 %.

> Important: this section reuses the three windows of the earlier
> real world validation experiment, and that experiment is frozen.
> Its tarballs are left exactly as they are and are read in place.
> Nothing is extracted, compressed, moved or deleted inside its data
> directory, because its file finder looks for tarballs first and
> plain text second, and would not find a compressed replacement.

### Qualifications

The Cd_fit(C)/Cd_fit(D) ratio should come within 10 % of 1.0.
A failure warrants a bug search. The RMS ratios should be close
to 1.0, and a significant departure (>20 % of 1.0) demands attention
and possibly a bug search if a non-bug explanation is not found.

## What this study does not claim

Part A prints a fitted Cd next to the value the tables predict, and
those two numbers invite a conclusion this study cannot support. An
orbit residual constrains only the product of density, Cd and area
over mass. Scale the tables' error and the density model's error by
the same factor and every observable is unchanged, so the absolute
level is not recoverable from orbit data no matter how many
satellites are added.

Accordingly:

- This study makes no claim about the absolute accuracy of the Cd
  tables, and no statement of the form "the tables are off by X %".
- Comparisons between a fitted Cd and a table Cd are read as
  direction and rough size, never as a level.
- The tables are judged by what they do to position error, which is
  what Part A measures and what a user actually experiences.

## One important correction

The v0.7.2 DSMC band, `DSMC_CD_BAND = (2.65, 4.5)` at
`gracefo_common.py:65`, is withdrawn. Its upper edge is mis-sourced:
the 4.5 comes from arXiv 2503.21651 (Leipner et al.), a closed-loop
simulation of deployable panels on GRACE-like satellites, where it is
an assumed *input* Cd for a hypothetical double-panel bus -- not a
DSMC result and not the GRACE geometry. The lower edge traces to a
genuine DSMC study of the GRACE bus (Mehta, McLaughlin & Sutton 2013,
Adv. Space Res. 52(12) 2035-2051), but its values were never checked
against the paper. So the correction is **withdrawn, not refuted**:
it may not claim the tables fall outside a correct band, only that
the credibility claim rested on a bad citation.

Four live claims rest on the band. All are corrected additively, in
prose, with a dated note -- surrounding measured numbers stay:
- `real-world-validation-findings.md:118-120` -- "NRLMSISE-00
  over-predicts deep-solar-minimum density by >= 25 %"
- `real-world-validation-findings.md:125-129` -- the tables are
  physically credible, sphere/box read against the band edges
- `experiments/real-world-validation/README.md:99` -- the
  "both DSMC-credible" summary row
- `CLAUDE.md:47` -- "A-priori Cd tables are DSMC-credible"

The relative lever 1.98 -> 3.32 -> 3.97 does not rest on the band and
is untouched.

Nothing else moves. `gracefo_common.py:65`, `results.txt` (8 lines)
and `run_gracefo.py` are frozen evidence and are never edited -- the
v0.7.3 precedent is that even a genuine code fix did not trigger
regeneration, and a citation error warrants less. `gracefo/README.md`
gets one correction block appended, body text and tables left in
place. `docs/history/` is the archived record of what was concluded
and why, left as written. `features.md:431` and the two
`docs/history/` Tier-B notes mention DSMC only as a generation
*method* and need no action.

## Conventions and constraints

**The earlier experiment is frozen.** `experiments/real-world-validation/`
is read and imported but never edited. No code, constant or results
file in it changes, and its own `run_all.py --verify` must still pass
when this study is finished. The DSMC correction above is the single
sanctioned exception, and it is prose only.

**The environment is frozen for the duration.** The installed
`orekit_jpype` is 13.1.4.0, while conda-forge offers 13.1.7.0 under
the same version pin, so recreating the environment mid-study would
silently change the Orekit build underneath the evidence. Do not
recreate or update it. Every results file records both the propygator
version and the resolved `orekit_jpype` version in its header, so a
later reader can tell what produced a number. Everything runs in the
conda `propygator` env, **not** the throwaway venv of
`docs/experiments_venv.md` -- the locked exception for validation
studies, because propygator is the system under test and so must be
the installed one. That env is what the freeze above refers to.

**Results must be reproducible.** No random draws at runtime, no
`Epoch.now()`, nothing that depends on the wall clock. The window
list is frozen (Part A), and anything that looks like sampling is a
fixed rule rather than a draw. A regenerate that does not reproduce
the committed numbers is the only way to catch a silent break, and
one stray random call retires that check.

**New truth data lands in the new study's own folder.** Extracting
the GNV1B and MAS1B members from a tarball and discarding the rest
cuts storage from about 148 MB per day to about 19 MB per day for
both satellites. GNV1B is the truth ephemeris and MAS1B is the mass
record; MAS1B is tiny (~8 kB per satellite per day) but it is not
optional, because the window mass is read from it rather than
assumed.
The existing parser reads compressed members already, but the
existing file finder only looks for tarballs or plain text, so the
new folder gets its own small finder rather than an edit to the
frozen one.

**Experiment scripts print ASCII only.** Their output is captured
under cp1252 and a single non-ASCII character crashes the run after
the compute has finished.

## Deliverables

1. **Results files**, one per part, under the new study's folder,
   regenerable by a single orchestrator command with per-window
   separability as described above.
2. **A findings document** recording what was measured, which
   benchmarks were met and which were missed, and what is honestly
   caveated. A missed benchmark is written down as missed.
3. **A revised `docs/tle-fitting-playbook.md`.** This study exists
   partly to validate or invalidate that playbook, so if the r/s
   gate misses its bar, the playbook is corrected rather than left
   standing. If the gate passes, the playbook records that its
   thresholds now rest on this study's window set instead of a
   single satellite.
4. **New pinned regression tests**, following the earlier study's
   pattern: measured values with a generous margin, testing
   relationships rather than exact numbers. They exist to catch a
   wiring regression, not to freeze a physical result.
5. **Reconciliation** of anything that quotes these numbers by hand:
   the README validation section, `notebooks/07_tle_fitting.ipynb`
   section 9, and `notebooks/00_showcase.ipynb`. The showcase needs
   a fresh static HTML export if its numbers move.
6. **The DSMC correction** above, applied as prose only.

## Git branching

Everything on this study is on study/extended-validation. Any
bug fixes or API changes must be done on a separate branch.
Upon successful completion of the study, this branch will
be merged with main via a GitHub PR. Should any changes occur
on main during the study (that should be avoided), the whole
study should be re-run to ensure its validity.

Because nothing here touches src/, the expected release is a patch
(`v0.8.1`). Should the fading memory result clear its bar, the
promotion itself is a separate feature branch off main afterwards,
with its own minor release; this study still ships without it.

Commits, CHANGELOG entries, truth data downloads, Space-Track pulls,
build plan progress marks, and the release itself are the
maintainer's. Claude writes scripts, tests and docs, and runs
read-only and test commands.
