# Maintaining `CHANGELOG.md`

A keep-it-around record of how this project's changelog is maintained. The format
is [Keep a Changelog 1.1.0](https://keepachangelog.com/en/1.1.0/) and the project
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html) (currently on
`0.x`).

## The rhythm

- **Keep an `## [Unreleased]` section at the top.** Accumulate entries there as you
  work on a branch. At release, rename it to `## [X.Y.Z] - YYYY-MM-DD` and open a
  fresh, empty `## [Unreleased]` above it.
- **Edit the changelog in the same change that introduces the behavior** — not in a
  batch at the end. It's far easier to describe a feature while it's fresh.

## Grouping

Use the standard headings, in this order, omitting any that are empty:

1. `Added` — new features.
2. `Changed` — changes to existing behavior.
3. `Deprecated` — soon-to-be-removed features.
4. `Removed` — features removed in this release.
5. `Fixed` — bug fixes.
6. `Security` — vulnerability fixes.

## How to write entries

- **Write for humans, not for git.** Describe user-visible capability, not
  file-by-file churn. One bullet per meaningful capability.
  - Good: `Numerical propagator: propagate_numerical(...) with configurable force
    models, seven attitude modes, and CSV + plot exports.`
  - Avoid: `Edited numerical.py, added 4 functions to exports.py.`
- **Imperative, present-ish, terse.** Lead with the capability.
- **Backtick the public verbs/types** (`propagate_numerical`, `export_all`,
  `VariableCd`) so they stay greppable.
- **Reference, don't reproduce.** Point at `docs/features.md §1.1` rather than
  re-listing every preset, signature, or validation rule.

## SemVer (while on 0.x)

- New, backward-compatible features → **minor** bump (`0.1.0` → `0.2.0`).
- Bug fixes only → **patch** bump (`0.2.0` → `0.2.1`).
- On `0.x`, breaking changes are allowed in a minor bump, but call them out clearly
  under `Changed`/`Removed`.
- The version is single-sourced in `pyproject.toml` and read back via
  `importlib.metadata`; bump it there when you tag.

## At release / tag time

- Rename `[Unreleased]` → `[X.Y.Z] - YYYY-MM-DD`; open a new empty `[Unreleased]`.
- Add comparison links at the bottom of the file, e.g.:

  ```
  [Unreleased]: https://github.com/<org>/propygator/compare/v0.2.0...HEAD
  [0.2.0]: https://github.com/<org>/propygator/compare/v0.1.0...v0.2.0
  ```

- Tag `main` (`git tag v0.2.0 && git push --tags`) so the release is reproducible
  (project_meta §3).

## Example skeleton

```markdown
## [Unreleased]

## [0.2.0] - 2026-06-13

### Added

- Numerical propagator: `propagate_numerical(...)` with configurable force models
  (gravity, third-body, drag, SRP, tides, relativity), seven attitude modes, and
  sphere / box-and-panels geometry. See `docs/features.md §1.1`.
- Orekit conversion layer on the core data model: `State.to_orekit` / `to_frame` /
  `to_keplerian`, `Trajectory.to_frame` / `at`, `to_geodetic`,
  `KeplerianElements` round-trips, `Orientation.to_orekit`.
- Variable drag coefficient `VariableCd` (Tier A, sphere + box) with the shipped
  `sphere_default()` table.
- Output surface: `plot_summary` / `plot_ground_track` / `plot_3d` /
  `plot_altitude` / `plot_speed`, and `export_csv` / `export_all`.
- Top-level re-exports of the Feature 1.1 surface (`import propygator as pgr`).
```
