# Propygator - Extended validation study involving additional drag-significant propagations, TLE fitting tests, and table noise

> Status: drafted and open to revisions

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
The lengths of these windows and which ones are selected is yet to be
decided.
The aim is to have ~10 windows. [WE NEED TO RESOLVE THIS] For
each window, the drag test will be the same as the one for the earlier
real world validation experiment. Each window will get propagations
with drag off, drag on (Cd=2.3), drag on (Cd fit), sphere table, and
box table. Propagations will cover 1D, 3D, and 7D. For each propagation,
the results will be recorded as radial, along, cross, and 3D rms.

Window length follows from the propagations rather than being a free
choice. A window has to hold the longest propagation plus the TLE
fitting arc that precedes it, so a 7 day propagation behind a 3 day
arc needs 10 days. At roughly 19 MB per day for both satellites once
extracted and compressed, ten 10 day windows is about 1.9 GB.

The box mass and dimensions for this part are to be specified.
However, dimensions will come from the authoritative GRACE-FO handbook,
and the masses, which vary, will be extracted from the data during
runtime [WE NEED TO RESOLVE THIS].

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
> storage stress. Attempt to reuse parser code from the earlier
> real world validation experiment.

> Important: an attempt should be made while constructing the build
> plan to make the run for each window separable. This allows for
> shorter shell run times.

### Part B: additional drag-significant propagations, Swarm A, B

This study will also run the identical drag propagations on Swarm
A and B. These are more stress-test cases because the Swarms do
not conform to a very rectangular shape, and their masses are not
known well. The purpose of having these as test cases is to help
understand propygator's accuracy on a different and more
irregularly shaped satellite. The Swarms will use the same
set of windows as above.

The box mass and dimensions for this part are to be specified
[WE NEED TO RESOLVE THIS].

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

> [DECIDE: Swarm A and C are the side-by-side pair at matched
> altitude; B flies roughly 50 km higher in a different plane.
> Either pairing works for a shape stress test, but A/C keeps the
> two bodies comparable to each other in the way C and D are.]

> These runs should also be made separable for each window to
> ensure reasonable shell run times.

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
- A naive, one-time fitting (1)
- A fitting for each of the 3 playbook decisions (3)
- Catalogue fitting (pulled from Space-Track by maintainer) (1)
- State fits with sphere and box tables (2)
- Fading memory fits with tau = τ ∈ {0.5, 0.75, 1, 1.5, 2, 3} (6)
That's 13 different fittings, propagations, and results in total.

> These runs should also be made separable for each window to
> ensure reasonable shell run times.

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

### Qualifications

This part does have benchmarks, outlined below:
- In order for the r/s gate and the TLE playbook to be validated,
the playbook and gate must beat the naive, one-time fit ≥ 80% of
the time. In addition, the success rate of the r/s gate must be
higher than the success rate of sticking point-blank to any of the
3 gated options.
- In order for the fading memory to be promoted, it requires a
≥ 1.5× improvement than the playbook and no regime > 1.25× worse.
The default for fading memory is to defer.

Anchor-to-anchor scatter in comparisons of this kind runs 2-3×, so
differences under 1.5× are not meaningful. Where two options land
within 1.5× of each other at the same anchor, both count as correct.
Without this rule the gate is scored on choices it had no way to get
right, and the bar above becomes harder than it is meant to be.

In addition, it is expected that the TLE fitting trials will
all converge and give reasonably close values to reality. If that
is not the case, a search for bugs is warranted.

## The design - table noise

GRACE-FO C and D are essentially the same body flying through
the same atmosphere. For each of the three windows of the earlier real world
validation study (2019 quiet, 2023 active,
and 2024 storm), a Cd will be fitted to the true trajectory of each
GRACE-FO body, and the two propagations of [DECIDE LENGTH] will
be done on each GRACE-FO body, using the sphere and box tables. The
following metrics will be computed:
- Cd_fit(C)/Cd_fit(D)
- RMS_sphere(C)/RMS_sphere(D)
- RMS_box(C)/RMS_box(D)

All of the three metrics above should be close to 1.0. Orbits
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

> Caveat: the lattice used to obtain Cd_fit during each window
> should be small. Otherwise, the resolution of the fitted Cd
> is limited, which lead to confound.

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
and possibly a bug search.

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

The DSMC band for v0.7.2 experiment needs to be withdrawn
because it currently cannot be matched to a fully credible source.
[Insert locations and blast radius here]. These corrections should
be entirely restricted to doc edits.

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
later reader can tell what produced a number.

**Results must be reproducible.** No random draws at runtime, no
`Epoch.now()`, nothing that depends on the wall clock. The window
list is frozen (Part A), and anything that looks like sampling is a
fixed rule rather than a draw. A regenerate that does not reproduce
the committed numbers is the only way to catch a silent break, and
one stray random call retires that check.

**New truth data lands in the new study's own folder.** Extracting
the GNV1B members from a tarball and discarding the rest cuts storage
from about 148 MB per day to about 19 MB per day for both satellites.
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
be merged with main via a GitHub PR.

Because nothing here touches src/, the expected release is a patch
(`v0.8.1`). Should the fading memory result clear its bar, the
promotion itself is a separate feature branch off main afterwards,
with its own minor release; this study still ships without it.

Commits, CHANGELOG entries, truth data downloads, Space-Track pulls,
build plan progress marks, and the release itself are the
maintainer's. Claude writes scripts, tests and docs, and runs
read-only and test commands.
