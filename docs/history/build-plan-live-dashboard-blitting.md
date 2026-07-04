# Build plan: Live Dashboard Blitting

> **Status: BUILD PLAN (not started).** Derived from the **"Live Dashboard Blitting"**
> section of `docs/general-upgrades-1.md`, which is the **binding contract** for this
> work (as `features.md` §1.4 was for the live-tracker build). Every artist rule,
> invalidation step, wrinkle, and test below traces to that section — cited inline as
> "(contract: <heading>)". Where this plan and the contract disagree, the **contract
> wins**; fix the plan. Status headers are the maintainer's — trust the git log for
> true status.

## Context

The live dashboard (`tracking/live.py`, Feature 1.4, shipped `v0.4.0`) redraws every
panel each tick by calling `ax.clear()` and re-drawing (`live.py` `update()`:
`ax_ground/ax_alt/ax_speed/ax_sky.clear()`). Because `cla()` re-enables autoscale and the
`_draw_*` primitives re-pin the fixed map/sky limits, **any zoom or pan the user sets via
the matplotlib toolbar is destroyed on the next ~1 Hz redraw** — the dashboard is
effectively non-interactive. This upgrade converts the display layer from
*clear-and-redraw* to *build-once / mutate-artists-in-place*, then layers
`FuncAnimation(blit=True)` on top.

**Two separable wins, delivered in that order (contract: *Context*):**
1. **Interactivity** — the mutate-in-place rewrite. Nothing clears or re-autoscales the
   axes, so a user's zoom/pan survives every redraw (and even a buffer rebuild, because
   the axis limits are pinned). This holds *independently of blitting*, at `blit=False`.
2. **Efficiency** — the blit layer on top caches the expensive coastline basemap once
   (instead of re-rasterizing it every second) and per tick restores that cached
   background + redraws only the handful of small *animated* artists: cheaper CPU,
   flicker-free. At `refresh_s=1 s` the fps gain is modest; the payoff is the flicker-free
   redraw plus headroom to lower `refresh_s` later.

**The central design point (contract: *Background invalidation*).** Blit assumes a fixed
background, but this dashboard changes it on two events — a **buffer rebuild** (new static
curves) and a **twilight band change** (new sky-disk tint). FuncAnimation only re-captures
the blit background when an axes' *view* changes, and we deliberately **pin the limits** so
a rebuild can't blow away zoom — so the view never changes on its own and the re-capture
never fires automatically. Each background-changing event is therefore handled by one
**explicit three-step** mechanism inside `update()`: mutate the static artists → force a
**synchronous** `fig.canvas.draw()` (renders new static; skips the `set_animated(True)`
dynamic artists) → **`anim._blit_cache.clear()`** so `_post_draw` re-captures the new
background on the same tick. This is verified against matplotlib 3.10.9 (see *Risks*).

**End state.** `live_track`'s signature, the `_TrackerEngine` state machine, panel content,
and buffer magnitudes are all **unchanged** (contract: *Supercessions* — no signature/
engine change). The only behavioral change: zoom/pan survives redraws, the per-tick redraw
is flicker-free and cheaper, and the readout moves from a figure suptitle to an
axes-anchored `Text`. This is one of several independent general upgrades feeding
**v0.5.0**; the wrap-up **squash-merges to `main` with no version bump and no tag** (v0.5.0
is cut once, after all general upgrades land).

### Source-of-truth docs (do not silently diverge)

- `docs/general-upgrades-1.md` **"Live Dashboard Blitting"** — the binding contract. Key
  sub-headings: *Supercessions*, *Context*, *Details* (Artist split, Background
  invalidation, Fixed axis limits, The four blit wrinkles, Driver shape, Efficiency, Out
  of scope, Blast radius, Build sequence).
- `docs/features.md` §1.4 ("TLE Live Dashboard") — authoritative **except** the spots the
  contract's *Supercessions* list replaces; reconciled in Chunk 5.
- `docs/history/build-plan-feature-1.4.md` — the original live-tracker build (why `update`,
  the `_draw_*` seams, and the precompute arrays are shaped as they are).
- `CLAUDE.md` "tracking/" + "plotting/" — the module map and the JVM-/matplotlib-free
  import invariant for `live.py`'s top level.

### Decisions already locked (do not relitigate)

- **Full blit, with a go/no-go gate at Checkpoint A** (maintainer's call). Interactivity
  ships at `blit=False` first; the blit layer is a *separable increment* proceeded-to only
  after the gate (contract: *Efficiency* — "a legitimate place to stop").
- **Refactor confined to `tracking/live.py`'s display layer** + small *additive,
  output-preserving* seams on the private `_draw_*` primitives. The pure `_TrackerEngine`,
  `live_track`'s §1.4 signature, and every public `plot_*` verb are untouched (contract:
  *Details*, *Blast radius*).
- **Fixed axis limits, never autoscale** — ground (−180..180 / −90..90) and sky (rlim
  0..90) are already fixed; altitude/speed get stable y-ranges from the first buffer, held
  across rebuilds (contract: *Fixed axis limits*; the LEO near-circular caveat stays out of
  scope).
- **Explicit background invalidation** — the three-step (mutate → synchronous `draw()` →
  `anim._blit_cache.clear()`); the "`draw_idle` re-caches automatically" model is wrong
  (contract: *Background invalidation*).
- **Off-thread rebuild stays deferred** (contract: *Out of scope*) — a rebuild/refetch is
  still a synchronous stall; blitting does not change that.
- **Bundle into v0.5.0** — no tag/version bump in this plan.

### Decisions to confirm (defaults chosen; "You provide" flags them)

- **Branch:** `feature/live-dashboard-blitting`, off `main`. Confirmed.
- **The Checkpoint A go/no-go** (proceed to the blit layer, or stop at interactivity) —
  the maintainer's call after Chunk 2 lands.
- **Manual GUI smoke check** — the felt interactivity (real toolbar zoom surviving a
  redraw) can only be confirmed with a GUI backend, not by the headless test suite; the
  maintainer runs it once (see Chunk 2 *You run*).

### Architecture invariants to honor (CLAUDE.md / architecture §4, §7, §10)

`live.py`'s module top stays **JVM- and matplotlib-free** — every matplotlib / `plotting`
import stays inside `live_track`'s body (the `export_all` precedent, pinned by an AST
test). No Orekit type appears on any signature. SI internally; `logging`, never `print`;
`tracking/` → `tle/`/`core/` stays the only inward edge (no new `plotting/` import at
module top). The `plotting/` primitives stay a leaf (nothing imports back).

---

## How to use this plan

- **5 numbered chunks**, each sized for one Claude Code session and independently
  verifiable, plus a git section and two checkpoints. All chunks are **shipped runtime
  code** in the `propygator` conda env (pytest, with JVM-touching tests acquiring the
  `orekit` fixture — the dashboard buffer is a real SGP4 propagation).
- Each chunk lists **Goal / Create-Edit / Reuse / You provide / You run / Verify**.
  **You provide** is called out every chunk (often "nothing") so a session always knows
  whether it needs input.
- **One go/no-go gate:** Checkpoint A (after Chunk 2) — interactivity has shipped; decide
  whether the blit layer is worth its four wrinkles + the private-`_blit_cache` matplotlib
  coupling. If "no", jump to a trimmed Chunk 5 (docs the interactivity-only outcome).
- **`/code-review` + `/simplify` checkpoints** are marked after the two riskiest landings
  (the mutate-in-place rewrite; the full blit path) and again in the wrap-up — regular,
  not after every chunk.
- **Commits, CHANGELOG entries, chunk-header "done" marks, and the merge are the
  maintainer's.** Claude writes code and runs read-only/test commands; the maintainer
  commits, pushes, runs the GUI smoke check, and merges. Claude won't push or open a PR
  unasked.
- **Mergeable chunks:** Chunk 1 (additive primitive seams) can fold into the front of
  Chunk 2 if a session is short; Chunks 3+4 (the two blit wrinkles) can merge in a big
  session. Split for safety.

---

## Git: branch strategy (read once, before Chunk 1)

`main` carries 1.1 / 1.3 / 1.4 and Tier B drag; branch straight off it:

```powershell
conda activate propygator
git switch main
git pull
git switch -c feature/live-dashboard-blitting
git push -u origin feature/live-dashboard-blitting
```

Per-chunk rhythm: `git status` → `git add -A` →
`git commit -m "blitting chunk N: <summary>"` → `git push` (CI runs on the branch).
**Do NOT** bump `pyproject.toml` version or tag — v0.5.0 is cut once, after all general
upgrades land.

**You provide (git):** the branch name (confirmed: `feature/live-dashboard-blitting`);
`gh` authenticated before Chunk 5; the final merge-to-main go-ahead (an outward action).

---

## Chunk 1 — Additive, output-preserving plotting-primitive seams - Done

**Goal:** give `live.py` stable handles to the static artists it will mutate on rebuild,
without changing any standalone `plot_*` output. Today only `_draw_ground_track` returns
its artist (the `LineCollection` mappable); the altitude/speed/sky primitives return
`None`, and the ground-track **start marker** is created inside `_draw_ground_track` and
never surfaced (contract: *Blast radius* — "additive, output-preserving seams").

**Create / edit:**
- `src/propygator/plotting/timeseries.py` — `_draw_altitude` returns the altitude `Line2D`
  it creates; `_draw_speed` returns the speed `Line2D` (both the default and the
  `speeds_kms=` precomputed-seam branches). Signatures widen only their **return type**
  (`None` → `Line2D`); the drawing is byte-identical.
- `src/propygator/plotting/trajectories.py` — `_draw_sky_track` returns the track `Line2D`
  (return type `None` → `Line2D`). **Leave `_draw_ground_track`'s return as the mappable**
  (`plot_ground_track`/`plot_summary` depend on it for the colorbar); the start-marker
  handle is captured off the axes by `live.py` in Chunk 2 — document that the start marker
  is the *sole scatter `PathCollection`* `_draw_ground_track` adds (the track and coastline
  are `LineCollection`s), created before `live.py` adds its own live/station scatters.
- Docstrings updated to note the returned handle is the live dashboard's mutate-in-place
  seam (mirroring `_draw_ground_track`'s existing "returns the colorbar mappable" note).

**Reuse:** the existing primitive/wrapper split; `composite.py` / `plot_summary` call these
and **ignore** the return, so no caller change is needed.

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/plotting -v` green — the snapshot tests
prove the standalone outputs are byte-unchanged. The three primitives now return the
`Line2D`(s) they create; `_draw_ground_track` is unchanged. `plot_summary` still renders.

---

## Chunk 2 — Mutate-in-place rewrite at `blit=False` (interactivity ships), both layouts - Done

**Goal:** build the scene once, mutate persistent artists in place, drop every
`ax.clear()`, pin all axis limits — so a user's zoom/pan survives every redraw *and* a
buffer rebuild. Wrinkle 1 (the rotated heading marker) lands here. Stay at `blit=False`;
keep the `fig.suptitle` readout for now. **This delivers the entire interactivity
headline** (contract: *Build sequence* step 1) before any blit risk.

**Create / edit (`src/propygator/tracking/live.py`, the `live_track` body):**
- **`_init_scene(...)`** (built once, inside `live_track` after the figure/axes exist):
  create every artist once and return the **dynamic** set (blit's animated artists),
  keeping **static** handles in the closure. Classification (contract: *Artist split*):
  - *Static (mutated only on rebuild):* the ground gradient `LineCollection` + start marker
    (captured off `ax_ground.collections` per Chunk 1) + station marker + legend; the
    altitude `Line2D`; both speed `Line2D`s + legend; the sky disk/grids/track/legend.
  - *Dynamic (mutated every frame):* the heading-marked sub-satellite marker; the two
    now-cursors; the sky Sun/Moon/satellite glyphs; the live readout (still the suptitle in
    this chunk). Created **once**, thereafter **only mutated, never recreated**.
- **`_draw_static(buffer)`** — idempotent, **mutate-in-place** (never `ax.clear()`; contract
  spells out the three reasons it must not clear): recompute `_geodetic_lonlat(buffer)` →
  `_dateline_segments(lon, lat, hours)` and `set_segments(list(segments))` / `set_array` /
  `set_clim(0, hours[-1])` on the ground `LineCollection` (segment count varies with
  dateline crossings, so recompute segments + colour array together); `set_offsets` the
  start marker (the centred buffer re-centres each rebuild); `set_data` the altitude, both
  speed, and sky-track lines. Idempotent because FuncAnimation's `init_func` re-runs it on
  every window resize — re-setting existing artists' data is a safe no-op.
- **Wrinkle 1 — rotated heading marker** (contract: wrinkle 1): a single persistent
  `Line2D` (one point) for the sub-satellite marker; each frame
  `set_marker(_heading_marker(heading))` + `set_data([lon], [lat])`. Translate the
  `_LIVE_MARKER` scatter kwargs to `Line2D` equivalents (`c`→`markerfacecolor`,
  `edgecolors`→`markeredgecolor`, `s`→`markersize=√s`, `zorder` direct) — the same mapping
  `_marker_legend_handle` already encodes.
- **Cursors** — create the two `axvline` `Line2D`s once; each frame
  `set_xdata([elapsed_h, elapsed_h])`.
- **Sky glyphs** — create three persistent `PathCollection`s once (via `_plot_sky_glyph`
  factored to build-once); each frame `set_offsets` with `(azimuth_rad, 90 − elevation)`
  (a below-horizon body lands outside `rlim` and clips, unchanged).
- **Fixed limits** (contract: *Fixed axis limits*): altitude + speed y-ranges from the first
  buffer (min/max + a small margin over both speed arrays), x from the buffer span; set
  **once**, never autoscale. Ground/sky are already fixed by their primitives.
- **`update()`** rewritten: `now = Epoch.now()`; `if engine.maybe_rebuild(now):
  _draw_static(engine.buffer)`; mutate the dynamic artists from the O(1) precomputed seam
  (`engine.inertial_speed_kms` / `ground_speed_kms` / `azel`, memoized `geodetic_track`) +
  the per-frame `observer_snapshot` (4-panel); keep `fig.suptitle(...)`; **return the
  dynamic set** (unused at `blit=False`, but ready for Chunk 3).
- **`init_func`** — `_draw_static(engine.buffer)`; return the dynamic set. Pass
  `init_func=init` to `FuncAnimation`; keep `blit=False`, keep `cache_frame_data=False`.

**Reuse:** the Chunk-1 primitive return handles; `_heading_marker` / `_marker_legend_handle`
(`style.py`); `_dateline_segments` / `_geodetic_lonlat` / `_track_heading_deg`
(`trajectories.py`); the engine's precompute arrays; `observer_snapshot`. The panel content
and colours (`_LIVE_MARKER`, `_CURSOR_STYLE`, the twilight/glyph constants) are unchanged.

**You provide:** nothing.

**You run:** the per-chunk git rhythm; **and once, a manual GUI smoke check** — run
`live_track(...)` under a real backend (`%matplotlib qt`/`tk`, or as a script), toolbar-zoom
into the sky panel or an altitude feature, and confirm the zoom **survives** the next
redraw *and* a buffer rebuild (the headless suite cannot assert felt interactivity).

**Verify:** `conda run -n propygator pytest tests/tracking/test_live_dashboard.py -v`
green. New tests:
- **Zoom-survival** — set axis limits, tick a non-rebuild frame under the frozen-now
  fixture, assert the limits are unchanged (3- and 4-panel). Guards the no-autoscale /
  mutate-in-place property; passes at `blit=False`.
- **Rebuild-preserves-zoom** — set limits, advance `now` past the leading edge to force a
  rebuild, assert the limits are unchanged **and** the static curves refreshed
  (`get_segments` / `get_ydata` reflect the new buffer).
- **Artist-mutation / identity** — across two frames the cursor `get_xdata`, the marker
  offsets/data, and the readout text change, and the **same artist objects persist**
  (identity check — not recreated).
- The existing 3-/4-panel build+tick tests stay green (the suptitle readout still updates).

> ### ⛔ Checkpoint A — go/no-go gate for the blit layer (the maintainer's chosen gate)
> 1. **Interactivity has shipped** at `blit=False` — zoom/pan survives redraws and
>    rebuilds. Confirm with the manual GUI smoke check.
> 2. **Decide:** proceed to the blit layer (Chunks 3–4) for the flicker-free redraw +
>    headroom to lower `refresh_s`, at the cost of the four wrinkles' full handling and a
>    coupling to matplotlib's private `_blit_cache` (version-pinned; needs the pixel canary
>    test). At 1 Hz the fps gain is negligible, so this is a real choice.
> 3. `/code-review` + `/simplify` on the mutate-in-place rewrite (the `_init_scene` /
>    `_draw_static` split + persistent-artist handles are the biggest structural change and
>    easy to get subtly wrong — e.g. a static artist accidentally recreated in `update`).
> 4. **If GO** → Chunk 3. **If STOP** → jump to the trimmed Chunk 5 (document
>    interactivity-only; the blit half stays a named later optimization). Commit + push.

---

## Chunk 3 — Flip `blit=True` + explicit background invalidation (buffer rebuild), both layouts

**Goal:** turn on blitting; handle the **buffer-rebuild** background change with the
three-step re-cache; move the readout to an axes-anchored `Text` (wrinkle 3) so blit
actually redraws it (contract: *Build sequence* step 2, wrinkle 3).

**Create / edit (`tracking/live.py`):**
- `blit=True` on `FuncAnimation`; `init_func` returns the animated (dynamic) set so blit
  flags them `set_animated(True)` (which is *why* the synchronous `draw()` in the three-step
  can render new static content without baking the dynamic artists into the captured
  background).
- **Wrinkle 3 — readout** (contract: wrinkle 3): replace `fig.suptitle(...)` with a
  persistent **axes-anchored `Text`** on `ax_ground` (`transform=ax.transAxes`, axes-fraction
  `y≈0.95`, `va="top"`, left-anchored, compact fontsize so the long coords·alt·speeds·UTC
  string does not clip at the panel edge). It must sit **inside** `ax_ground.bbox` — a
  title-style `y>1.0` lands in the margin and, like the old suptitle, would never blit. It is
  a **dynamic** artist: created in `_init_scene`, `set_text(...)` each frame, returned in the
  animated set.
- **Three-step re-cache on buffer rebuild** (contract: *Background invalidation* item 1):
  in `update()`, when `engine.maybe_rebuild(now)` returns `True`, run
  `_draw_static(engine.buffer)` → **`fig.canvas.draw()`** (SYNCHRONOUS — not `draw_idle`,
  which defers past `_post_draw`'s re-capture) → **`anim._blit_cache.clear()`** (drop the
  stale view-keyed background so `_post_draw` re-grabs it this tick). `update` references
  `anim` as a **late-bound closure free variable** — valid because `anim = FuncAnimation(...)`
  is assigned before the first tick and `update` never rebinds it.
- **Robustness:** the three-step touches `anim._blit_cache`, which exists only after
  `_setup_blit` (fires on the first `draw_event`). In real GUI use the buffer is built fresh
  at construction and the first drain is ~`half_window_s` away, so `_setup_blit` has run long
  before any rebuild — safe. The pixel test (below) forces init first, per the contract.

**Reuse:** the Chunk-2 `_draw_static` / dynamic-artist set; the matplotlib blit internals
verified in *Risks*.

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/tracking/test_live_dashboard.py -v`
green. Test changes:
- **Repoint** `test_three_panel_builds_and_ticks` — read the readout off the new
  axes-anchored `Text` on `ax_ground` (locate the `Text` artist) instead of `fig._suptitle`
  (contract: *Blast radius* — this is the one structural test that reads `_suptitle`).
- **Background-invalidation pixel test** (the real regression guard; contract: *Blast
  radius*, and the only case that must **step the actual blit loop**): force `Agg`;
  **initialize the blit machinery first** (`fig.canvas.draw()` or `anim._init_draw()` — else
  `_step` runs with no animated set / empty cache); step `anim._step()` (or
  `_draw_next_frame(..., blit=True)`) across a **forced buffer rebuild**; assert on
  `fig.canvas.buffer_rgba()` that the **new** static content is present **after subsequent
  ticks** (not just the rebuild tick — the pixel check after the *next* tick is the only
  thing that proves the invalidation worked, since without the `_blit_cache.clear()` the
  stale background silently overwrites it one frame later). Keep it one tight case.
- Zoom still survives; `update()` returns the dynamic set; the existing smoke tests (which
  tick via `anim._func(0)` on a fresh, non-draining buffer) stay green.

---

## Chunk 4 — Twilight band-change re-cache (wrinkle 2) under blit, 4-panel

**Goal:** the last background-changing event — the sky-disk twilight tint — handled by the
same three-step, only when the discrete band actually changes (contract: *Background
invalidation* item 2, wrinkle 2). Wrinkle 4 (sky glyphs via `set_offsets`) already landed
in Chunk 2's mutate-in-place rewrite; this chunk completes the sky panel under blit.

**Create / edit (`tracking/live.py`):**
- Recompute the twilight band each tick — a cheap scalar off the per-frame Sun elevation the
  glyph `observer_snapshot` already yields (`_twilight_facecolor`). Track the **stored** band.
- On a **band change** (a few times per day), run the same three-step re-cache
  (`ax_sky.set_facecolor(...)` → synchronous `fig.canvas.draw()` → `anim._blit_cache.clear()`).
  Short-circuit it with the rebuild: `if engine.maybe_rebuild(now) or _band_changed(now):`
  — and on a rebuild frame, refresh the **stored** band there too (per the contract's note,
  so it can't go stale and fire one harmless extra re-cache next tick). The facecolor is an
  axes *background* element, so it can't be an over-the-top blitted artist without covering
  the track — the re-cache is the only correct route.
- Confirm the sky **track / disk / legend** are static (built once in `_init_scene`), and the
  Sun/Moon/satellite glyphs are the persistent `set_offsets` `PathCollection`s from Chunk 2.

**Reuse:** `_twilight_facecolor`; the Chunk-3 three-step; the Chunk-2 persistent sky glyphs.

**You provide:** nothing.

**You run:** the per-chunk git rhythm.

**Verify:** `conda run -n propygator pytest tests/tracking/test_live_dashboard.py -v`
green. Tests:
- **Band-change re-cache pixel check** — force a band change (monkeypatch the Sun elevation
  / snapshot so `_twilight_facecolor` flips), step the blit loop, assert the **new
  facecolor** survives **subsequent** ticks and that exactly **one** re-cache fired for the
  change (not one per tick).
- **Glyph offsets update** — the Sun/Moon/satellite `PathCollection` offsets change across
  frames (and the same objects persist).
- The 4-panel build+tick test stays green.

> ### ✅ Checkpoint B — full blit path complete
> 1. Both build tests + the three behavioral tests (zoom-survival, rebuild-preserves-zoom,
>    artist-mutation) + the two pixel tests (buffer-rebuild, band-change) are green.
> 2. `/code-review` + `/simplify` on the dense re-cache logic and the private-`_blit_cache`
>    coupling (the three-step, the short-circuit, the late-bound `anim` reference).
> 3. Commit + push.

---

## Chunk 5 — Docs + wrap-up (no tag)

**Goal:** land the change — clean diff, the contract's *Supercessions* map folded back into
`features.md` §1.4, and the merge to `main`. **No version bump, no tag** (v0.5.0 is cut
later, after all general upgrades land).

**Create / edit / run:**
- Full local CI parity: `conda run -n propygator pytest` and
  `conda run -n propygator pre-commit run --all-files` both green from the repo root.
- Final `/code-review` + `/simplify` across the whole diff.
- **Reconcile `features.md` §1.4** (contract's *Supercessions* — apply exactly those spots):
  - "The view" paragraph: clear-and-redraw → build-once + mutate-in-place under
    `FuncAnimation(blit=True)` with an `init_func`.
  - "Per-frame work" paragraph: its "keeps the simple clear-and-redraw … blitting stays the
    named later optimization" closing is now realized (the O(1) precompute seam it describes
    is the unchanged precondition).
  - "Resolved decisions → Live rendering": "v1 uses clear-and-redraw, blitting deferred" →
    "blitting shipped in v0.5.0".
  - "Still open / deferred → Performance": the **blitting** half is realized; the
    **off-thread rebuild** half stays deferred.
  - The §1.4 sky-view radial-label refinement is explicitly **not** part of this change.
- Update the `live_track` docstring rendering note (clear-and-redraw → build-once /
  mutate-in-place under blit; zoom/pan now survives; note the pinned-matplotlib-internals
  coupling as the reason the background-invalidation pixel test is the version canary).
- **Leave `general-upgrades-1.md` in place** — it stays the source of truth for the other
  v0.5.0 upgrades; only its Live Dashboard Blitting section is now "built."
- **You** update `CHANGELOG.md` `[Unreleased]` and refresh `CLAUDE.md` "Project state"
  (dashboard blitting shipped on `feature/live-dashboard-blitting`, feeding v0.5.0; the
  narrative artifacts are the maintainer's).
- **Merge:** `gh pr create` against `main`, confirm CI green, then
  `gh pr merge --squash --delete-branch` (`git branch -D` locally for the squash-merged
  branch) — **the maintainer's call**. Do **not** tag v0.5.0 here.

> **If Checkpoint A said STOP (interactivity only):** trim this chunk — document that the
> **mutate-in-place** rewrite shipped (zoom/pan survives) and the **blit layer** stays a
> named later optimization; reconcile only the §1.4 "The view" / "Resolved decisions"
> bullets to that partial state, and leave the blit-specific §1.4 bullets untouched.

**You provide:** `gh` authenticated; the final merge go-ahead; the CHANGELOG + CLAUDE.md
edits; the note that v0.5.0 tagging is deferred to the cross-upgrade step.

**Verify:** full `pytest` + `pre-commit run --all-files` green; `import propygator as pgr`
stays JVM-free and `live_track`'s signature is unchanged; the contract's *Supercessions*
spots are all carried into `features.md` §1.4; `pyproject.toml` version is **unchanged**.

---

## End-state verification (Dashboard blitting shipped → on `main`, untagged)

From the repo root, `conda activate propygator`, on the merged branch:
1. **Interactivity:** a toolbar zoom/pan on any panel survives the next redraw *and* a
   buffer rebuild (manual GUI check + the automated zoom-survival / rebuild-preserves-zoom
   tests).
2. **Blit correctness:** the background-invalidation pixel test (buffer rebuild) and the
   band-change pixel test both prove the new static content / facecolor survives
   *subsequent* ticks — the canaries for the matplotlib-internals coupling.
3. **Artists mutate, never recreate:** cursors/marker/readout/glyphs are the same objects
   across frames (identity test); `update()` returns the animated set.
4. **No signature/engine/content change:** `_TrackerEngine`, `live_track`'s §1.4 signature,
   the buffer magnitudes, and every public `plot_*` verb are unchanged; the `_draw_*`
   primitive outputs and their snapshots are unchanged.
5. **Tests:** the dashboard suite (build + behavioral + pixel) passes via the `orekit`
   fixture; `pre-commit run --all-files` clean; `live.py`'s top stays JVM-/matplotlib-free.
6. **Docs:** the *Supercessions* map is carried into `features.md` §1.4;
   `general-upgrades-1.md` stays alive for the other upgrades; CHANGELOG + CLAUDE.md
   updated; **version unchanged / untagged**.
7. `conda run -n propygator python -c "import propygator, jpype; print(jpype.isJVMStarted())"`
   → `False`.

## Risks & de-risking (verified during planning)

- **matplotlib private internals (the load-bearing coupling).** Verified against the pinned
  **matplotlib 3.10.9**: `FuncAnimation._blit_cache`, `_blit_draw` (re-captures the
  background **only** when `ax._get_view()` differs — animation.py:1208-1212), `_blit_clear`
  (restores the stale bitmap otherwise), `_post_draw`, `_step`, `_init_draw` all exist and
  behave as the contract states. This confirms the explicit `anim._blit_cache.clear()` is
  required with pinned limits, and that the background-invalidation pixel test is the canary
  for a breaking matplotlib bump. **Do not `conda update` matplotlib without re-running that
  test.**
- **`_blit_cache` existence ordering** — safe in real GUI use (init on first draw ≫ before
  the first rebuild); forced in the pixel test per the contract.
- **Start-marker handle** — captured off `ax_ground.collections` (the sole scatter
  `PathCollection` `_draw_ground_track` adds), keeping the shipped primitive's mappable
  return intact.
- **Late-bound `anim` closure reference** — valid: `anim` is assigned before the first tick;
  `update` only reads it.
- **Contract conclusion: SOUND.** No stop-and-report condition found; every wrinkle has a
  verified resolution.

## Notes / deferred (not this plan)

- **Off-thread rebuild** (features.md §1.4 Performance): a rebuild/refetch is still a
  synchronous stall on the draw thread; blitting does not change that. Stays deferred
  (contract: *Out of scope*).
- **Eccentric-orbit / drag-decay envelope widening** — the fixed altitude/speed y-range is a
  first-buffer envelope, valid for near-circular LEO; widening it for GTO/Molniya stays out
  of scope while the target is LEO (contract: *Fixed axis limits* caveat).
- **Sky-view radial-label refinement** (labelling rings in elevation) — a *separate* §1.4
  upgrade, not this section.
- **v0.5.0 tag** — a separate cross-upgrade step once all general upgrades land.
