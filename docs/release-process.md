# Cutting a release

A keep-it-around record of how a finished feature branch becomes a tagged release
on `main`. It generalizes the steps used for `v0.3.0` (Feature 1.3, the TLE
propagator). Distribution is **GitHub-only** — there is no PyPI publish step; a
release is simply a squash-merge to `main` plus an annotated tag (project_meta §3).

Conventions assumed here:

- One feature (or addendum) per release branch, squash-merged into `main` as a
  single feature-titled commit. See `git log main` — `Feature 1.1: numerical
  propagator`, `Feature 1.1 addendum: …`, `Feature 1.3: TLE propagator`.
- SemVer on `0.x`; backward-compatible feature → **minor** bump, fixes → **patch**
  (`docs/changelog-guidelines.md`).
- All Python commands run in the `propygator` conda env. Use `conda run -n
  propygator <cmd>` (or activate first); a bare interpreter path crashes NumPy on
  this machine (MKL DLLs only resolve in the activated env).

Throughout, `X.Y.Z` is the outgoing version and `<branch>` the feature branch.

---

## 1. Get the branch release-ready (still on the feature branch)

Bring the branch fully green and finalize the release metadata **before** touching
`main`:

1. **Tests green:** `conda run -n propygator pytest`
2. **Hooks green:** `conda run -n propygator pre-commit run --all-files`
   (ruff check + format, mypy, nbstripout, file hygiene — the same hooks CI runs).
3. **Finalize the changelog** per `docs/changelog-guidelines.md`: rename the
   `## [Unreleased]` section to `## [X.Y.Z] - YYYY-MM-DD` and open a fresh empty
   `## [Unreleased]` above it. Proof-read it (it is the public release note).
4. **Bump the version** in `pyproject.toml` (`version = "X.Y.Z"`). This is the
   single source of truth.
5. **Refresh the installed metadata** — see the gotcha below — and confirm:

   ```bash
   conda run -n propygator pip install -e .[dev]
   conda run -n propygator python -c "import importlib.metadata as m; print(m.version('propygator'))"
   ```

   The second command must print `X.Y.Z`.

> [!IMPORTANT]
> **A version bump is not live until you reinstall.** The version is read at
> runtime via `importlib.metadata` from the *installed* dist metadata, which is
> baked in at install time — editing `pyproject.toml` alone does **not** update it.
> The propagators stamp `propygator_version` into every `Trajectory`'s metadata and
> the CSV/export header, so a release built without the reinstall would emit
> trajectories tagged with the **old** version. Always reinstall and verify.

## 2. Commit the release prep on the branch

```bash
git add CHANGELOG.md pyproject.toml
git commit -m "Set vX.Y.Z version and changelog date"
git status        # expect a clean tree
```

This commit is folded into the squash in step 3, so its message is throwaway — it
will not appear in `main`'s history.

## 3. Squash-merge into `main`

```bash
git switch main
git merge --squash <branch>
git commit -m "Feature N.M: <short title>"
```

`--squash` stages the whole branch diff without committing or recording a merge
parent; your `git commit` creates the single feature-titled release commit
(matching the existing `main` history).

## 4. Tag it (annotated, matching the existing tags)

```bash
git tag -a vX.Y.Z -m "vX.Y.Z - <one-line summary>"
```

All existing tags are **annotated** (`git cat-file -t vX.Y.Z` → `tag`); keep that
consistent. The message mirrors `v0.2.0`'s style, e.g. `v0.3.0 - TLE propagator
(SGP4/SDP4) and CelesTrak TLE fetch`.

## 5. Verify locally before pushing

```bash
git log --oneline --decorate -3            # main HEAD is the new feature commit, tagged
git diff --stat <branch> main              # empty == squash captured everything
git rev-parse main vX.Y.Z^{commit}         # both SHAs identical -> tag points at HEAD
git tag -l vX.Y.Z -n99                      # annotated message reads right
```

`git diff --stat <branch> main` returning nothing is the key check that the squash
captured the entire branch (no file was missed).

## 6. Push and clean up (the outward-facing step)

```bash
git push origin main --follow-tags         # pushes main + reachable annotated tags in one shot
git branch -D <branch>                      # see note: -D, not -d
git push origin --delete <branch>           # optional: drop the remote branch too
```

> [!NOTE]
> **Use `git branch -D`, not `-d`, to delete a squash-merged branch.** A squash
> merge does not create a merge-parent link, so git does not consider the branch
> "merged" and `-d` refuses. The empty `git diff --stat <branch> main` in step 5 is
> your proof the content is safe to force-delete.

If you prefer two explicit pushes over `--follow-tags`:

```bash
git push origin main
git push origin vX.Y.Z
```

## 7. Verify the remote

```bash
git fetch --prune --tags origin
git rev-parse main origin/main             # identical
git ls-remote --tags origin vX.Y.Z         # tag present; the refs/tags/vX.Y.Z^{} line peels to main HEAD
git ls-remote --heads origin <branch>      # empty == remote branch gone
```

When `main` and `origin/main` match, the remote `vX.Y.Z^{}` peeled ref equals
`main`'s HEAD commit, and the remote branch is gone, the release is live.

---

## Quick checklist

- [ ] `pytest` and `pre-commit run --all-files` green on the branch
- [ ] `CHANGELOG.md` `[Unreleased]` renamed to `[X.Y.Z] - YYYY-MM-DD`, new empty `[Unreleased]` opened
- [ ] `pyproject.toml` version bumped **and** editable reinstall done (`importlib.metadata` reports `X.Y.Z`)
- [ ] release prep committed, tree clean
- [ ] `git merge --squash` + single `Feature N.M: …` commit on `main`
- [ ] annotated `vX.Y.Z` tag pointing at `main` HEAD
- [ ] local verification (empty branch↔main diff, tag peels to HEAD)
- [ ] pushed `main` + tag; feature branch deleted (`-D`) locally and on `origin`
- [ ] remote verified (`origin/main` matches, remote tag peels to HEAD)
