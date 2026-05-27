# propygator — Project Meta Reference

Repository and project-structure decisions for `propygator`. Sits alongside the architecture doc; covers governance/distribution/maintenance rather than what the code does.

**Project tier:** (a) — personal portfolio, public repo, not actively soliciting contributors. Recommendations bias toward minimalism. Decisions can be revisited if the project's audience changes.

---

## 1. License

**MIT.** Maximum adoption, minimum friction. Composes cleanly with Orekit's Apache 2.0 license (an MIT project can depend on Apache 2.0 code; users get the union of obligations, which for runtime-only use of `orekit_jpype` is essentially just attribution).

**Files:**
- `LICENSE` — standard MIT text with copyright line.

**README requirement:**
- An `Acknowledgments` section names Orekit (Apache 2.0) and `orekit_jpype` maintainers. Not strictly required by Apache 2.0 since we don't redistribute Orekit source, but it's the right citizenship.

---

## 2. Versioning

**SemVer (`MAJOR.MINOR.PATCH`), starting at `0.1.0`.**

Conventions:
- `MAJOR` stays at `0` indefinitely. Tier (a) doesn't promise API stability; staying on `0.x` is the right signal. No rush to `1.0.0`.
- `MINOR` bumps for new features or breaking changes (which are free while on `0.x`).
- `PATCH` bumps for bug fixes that don't change the API.

**Version string location:** single source of truth in `pyproject.toml` under `[project]`. `src/propygator/__init__.py` reads it back via `importlib.metadata.version("propygator")` — no duplication.

---

## 3. Branching

**GitHub Flow + tagged releases.**

- `main` is the integration branch. Aim to keep it green (CI passing) but no enforcement.
- Feature work on short-lived branches: `feature/numerical-propagator`, `fix/tle-checksum`, etc.
- Solo workflow tolerates direct commits to `main` for small fixes (typos, doc tweaks). Use feature branches + PRs for anything substantive — gives CI feedback and a written record in the PR description.
- Tag releases on `main`: `v0.1.0`, `v0.2.0`, etc.
- **No branch protection on `main`.** Solo project; no team to break things for.

---

## 4. Distribution

**GitHub only.** No PyPI, no conda-forge.

Rationale:
- Tier-(a) audience reads code; they don't expect to `pip install` a portfolio project.
- PyPI publishing is forever — namespace can't be reclaimed once used.
- conda-forge submission requires interaction with the maintainer team and a feedstock repo.

**Install story (documented in README):**
```bash
git clone https://github.com/<user>/propygator.git
cd propygator
conda env create -f environment.yml
conda activate propygator
```

If publishing makes sense later, it's a non-breaking addition. No need to design for it now.

---

## 5. Hosting

**GitHub.** Largest discovery surface for Python projects; best CI integration (GitHub Actions); standard for the audience this project targets.

---

## 6. Issue and PR templates

**Skip.** Tier (a) doesn't actively curate contributions. Cost of occasional low-information issues < cost of maintaining templates that mostly go unused.

Add later if issue volume warrants it.

---

## 7. CI matrix

**Minimal:**

- **OS:** Linux only (Ubuntu latest)
- **Python:** 3.11 only (matches the pin)
- **Triggers:** every push to any branch, every PR
- **Steps:** install env, run `pytest`, run `pre-commit run --all-files`

**Key optimization:** orekit-data (~500 MB) is cached across runs using GitHub Actions' `cache` action keyed on a version string. Without this, every CI run re-downloads half a gigabyte.

**Setup pattern:** `mamba-org/setup-micromamba@v1` action to provision the conda environment from `environment.yml`. Faster than full conda.

**Tier-(a) interpretation:** a green CI badge means "the author set up CI and the tests pass right now." Not a compatibility guarantee across Pythons/OSes.

---

## 8. Documentation hosting

**No Read the Docs.** Documentation lives in three places:

1. **README** (repo root) — install, quick example, feature list, links to the other surfaces.
2. **`docs/architecture.md`** (this repo) — the architecture reference doc; readable directly on GitHub, no build pipeline.
3. **Rendered notebooks** on the personal projects page — narrative tutorials and demos, one per feature.

Docstrings in code serve anyone reading the source. MkDocs can be added later if a fuller reference site becomes valuable; nothing in this setup blocks that.

---

## 9. README structure

Sections, in order:

1. **One-sentence what-it-is** — taken from the architecture doc §1.
2. **Status badges** — CI status, license. (No PyPI/RTD badges since we're not publishing/hosting on those.)
3. **Install** — the three-line conda incantation from §4. Most important section; first thing visitors evaluate.
4. **Quick example** — the §9 example from the architecture doc, basically as-is.
5. **Features** — bullet list of the v1 features (mirrors architecture §1).
6. **Notebooks** — link to rendered notebooks on the personal projects page.
7. **Architecture** — link to `docs/architecture.md`.
8. **Acknowledgments** — Orekit (Apache 2.0), `orekit_jpype` maintainers.
9. **License** — one line: "MIT — see LICENSE."

Explicitly **not** in the README:
- Detailed install troubleshooting (link to docs if needed)
- Full API reference (docstrings + source)
- Roadmap (GitHub Projects or skip)

---

## 10. CHANGELOG

**`CHANGELOG.md` in Keep-a-Changelog format**, hand-maintained.

Pattern:
- Top of file has an `[Unreleased]` section; add entries as you go.
- On release: rename `[Unreleased]` to `[v0.2.0] - 2026-06-15`, start a new `[Unreleased]`.
- Categories: Added / Changed / Deprecated / Removed / Fixed / Security.

Looser cadence than tier (b) — tag versions when you hit milestones you care about, not on a schedule.

Auto-generation from commit messages (conventional commits + `git-cliff`) is not worth the discipline overhead for solo work.

---

## 11. Code of Conduct + Contributing

**Skip both.**

A CoC for a project with no outside contributors is theater. A CONTRIBUTING.md for a project not soliciting PRs is misleading.

If a substantive PR ever arrives, respond with a short personal note rather than a process document.

---

## 12. Security policy

**Skip.** Realistic security surface for tier (a) is minimal. Anyone finding a real issue can email or file an issue.

---

## Summary table

| # | Topic | Decision |
|---|-------|----------|
| 1 | License | MIT |
| 2 | Versioning | SemVer from 0.1.0, stay on 0.x |
| 3 | Branching | GitHub Flow + tags, no branch protection |
| 4 | Distribution | GitHub only |
| 5 | Hosting | GitHub |
| 6 | Issue/PR templates | Skip |
| 7 | CI | Linux + Python 3.11, cached orekit-data |
| 8 | Docs hosting | README + `docs/` + personal-site notebooks |
| 9 | README | 9-section structure, trimmed badges |
| 10 | CHANGELOG | Hand-maintained Keep-a-Changelog |
| 11 | CoC + Contributing | Skip both |
| 12 | Security policy | Skip |

---

## When to revisit

The tier-(a) framing drives most of these decisions. If the project's audience shifts — for example, if you start fielding issues, accepting PRs, or wanting an easy install path for non-clone users — the relevant items to reopen are:

- **#4 Distribution** → PyPI + conda-forge publishing
- **#6 Issue templates** → minimal Issue Forms
- **#7 CI** → add Windows, possibly more Python versions
- **#8 Docs hosting** → Read the Docs for reference docs
- **#11 CoC + Contributing** → Contributor Covenant + short guide
- **#12 Security** → minimal SECURITY.md

The architecture doc (§5 "even minimal CI signals 'maintained project'") and (§3 "TLE data sources") were written with a tier-(b) lean. This doc supersedes those framings; the architecture itself doesn't need editing.
