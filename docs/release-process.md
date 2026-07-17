# Cutting a release

A keep-it-around record of how a finished feature branch becomes a tagged release
on `main`. It generalizes the steps used for `v0.3.0` (Feature 1.3, the TLE
propagator), updated for the GitHub Pull Request flow adopted at `v0.7.2`.
Distribution is **GitHub-only** — there is no PyPI publish step; a release is a
squash-merge to `main` (through a PR from `v0.7.2` on) plus an annotated tag
(project_meta §3).

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

## 3. Open a pull request and squash-merge it on GitHub

Push the branch, then merge it through a PR (the flow adopted at `v0.7.2`; before
that, this step was a local `git merge --squash`).

```bash
git push -u origin <branch>
```

1. On GitHub, open a PR with **base `main`** and **compare `<branch>`** (use the
   "Compare & pull request" banner after the push, or **Pull requests → New**).
   Title it like the release commit — `Feature N.M: <short title>`, matching the
   existing `main` history; the finalized `CHANGELOG` section is a ready-made body.
2. Let CI finish green, then self-review the **Files changed** diff.
3. Merge with **"Squash and merge"** (not a merge commit — this keeps the
   one-commit-per-release history). Edit the squash message to the release title;
   optionally tick **Delete branch**.

GitHub creates the single feature-titled squash commit on `main`. It is a
**brand-new commit with a new SHA** — not any commit in your local repo — so the
next step pulls it before anything else touches it.

## 4. Pull `main`, then tag it (annotated, matching the existing tags)

Fetch GitHub's squash commit **first** — tagging before the pull would point the
tag at the wrong commit (the classic first-timer mistake):

```bash
git switch main
git pull origin main
git tag -a vX.Y.Z -m "vX.Y.Z - <one-line summary>"
```

All existing tags are **annotated** (`git cat-file -t vX.Y.Z` → `tag`); keep that
consistent. The message mirrors `v0.2.0`'s style, e.g. `v0.3.0 - TLE propagator
(SGP4/SDP4) and CelesTrak TLE fetch`.

## 5. Verify before pushing the tag

```bash
git log --oneline --decorate -3            # main HEAD is the new squash commit, tagged
git diff --stat <branch> main              # empty == squash captured everything
git rev-parse main vX.Y.Z^{commit}         # both SHAs identical -> tag points at HEAD
git tag -l vX.Y.Z -n99                      # annotated message reads right
```

`git diff --stat <branch> main` returning nothing is the key check that the squash
captured the entire branch (no file was missed).

## 6. Push the tag and clean up (the outward-facing step)

`main` is already on GitHub (the PR merge pushed it, step 4 pulled it), so only
the tag remains to push:

```bash
git push origin vX.Y.Z                      # GitHub does not create the tag; you do
git branch -D <branch>                       # local branch: -D, not -d (see note)
git push origin --delete <branch>            # only if the PR merge did not auto-delete it
```

> [!NOTE]
> **Use `git branch -D`, not `-d`, to delete a squash-merged branch.** A squash
> merge does not create a merge-parent link, so git does not consider the branch
> "merged" and `-d` refuses. The empty `git diff --stat <branch> main` in step 5 is
> your proof the content is safe to force-delete.

Optionally, publish a **GitHub Release** from the tag (Releases → Draft a new
release → choose `vX.Y.Z`, paste the `CHANGELOG` section) so the release surfaces
on the repo's front page.

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
- [ ] branch pushed; PR opened (base `main`), CI green, **Squash and merge** with the `Feature N.M: …` title
- [ ] `git pull origin main`, then annotated `vX.Y.Z` tag pointing at `main` HEAD
- [ ] local verification (empty branch↔main diff, tag peels to HEAD)
- [ ] pushed the tag; feature branch deleted (`-D` locally, and on `origin` if not auto-deleted)
- [ ] remote verified (`origin/main` matches, remote tag peels to HEAD)
