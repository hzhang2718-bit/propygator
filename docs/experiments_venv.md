# Experiment virtual environment — setup & hygiene

Recordkeeping note for the throwaway Python **venv** that runs the reference
experiments under `experiments/` (currently the drag-coefficient verification).
These experiments are **not** part of the propygator package and intentionally do
**not** share the `propygator` conda env.

## Why a venv, not the conda env

- The experiments need `scipy` + `pymsis`, which are **not** in the propygator
  conda env. That env is a pinned, tested trio (Python 3.11 / OpenJDK 17 /
  orekit_jpype 13.1.x); adding packages risks perturbing it.
- A venv is fully isolated, disposable (it is just a folder), and its numpy/scipy
  come from PyPI wheels bundling **OpenBLAS** rather than conda's **MKL** — which
  sidesteps the Windows MKL-DLL crash documented in CLAUDE.md ("Environment &
  running": NumPy linear algebra hard-crashes outside the activated conda env).
- The experiments are self-contained (they never import `propygator`), so they
  gain nothing from the conda env's JDK. If that ever changes, switch to a clone
  of the conda env instead — the JDK is already handled there.

## Setup

Run from `experiments/drag-coefficient-verification/` (PowerShell):

```powershell
python -m venv .venv-experiments              # once
.\.venv-experiments\Scripts\Activate.ps1      # each new terminal
pip install -r requirements.txt               # once, after the first activate
```

The canonical run steps (and the PowerShell execution-policy note) live in that
directory's `README.md`. Leave the environment with `deactivate`.

## Verified install (2026-06-11)

Created from Python **3.13** (`python -m venv`) on Windows 11. `pip install -r
requirements.txt` resolved entirely to prebuilt `cp313` `win_amd64` wheels — no
compiler was invoked:

| Direct dependency | Version |
|-------------------|---------|
| numpy | 2.4.6 |
| scipy | 1.17.1 |
| matplotlib | 3.10.9 |
| pymsis | 0.12.0 |

Transitive (pulled by matplotlib): contourpy 1.3.3, cycler 0.12.1,
fonttools 4.63.0, kiwisolver 1.5.0, packaging 26.2, pillow 12.2.0,
pyparsing 3.3.2, python-dateutil 2.9.0.post0, six 1.17.0.

> The `WARNING: Cache entry deserialization failed, entry ignored` line seen during
> install is a benign pip wheel-cache hiccup — pip simply re-downloads. The install
> still succeeds.

## Hygiene

- **Never commit the venv.** `.venv*/` is gitignored; the folder stays local-only.
- **Re-activate per terminal.** Each new shell starts deactivated; the prompt shows
  a `(.venv-experiments)` prefix when active.
- **Reset by deleting the folder.** `Remove-Item -Recurse -Force .venv-experiments`,
  then recreate — no other cleanup needed.
- **Keep it separate from conda.** Do not expect propygator's packages inside the
  venv or vice-versa; use one environment at a time.
- **Different numpy build than propygator** (OpenBLAS vs MKL) — expected, and the
  reason this route avoids the MKL crash.
- **Run scripts from the experiment directory** — the imports are flat (`cd_core`
  must be importable as a sibling), not a package.

## See also

- `experiments/drag-coefficient-verification/README.md` — the experiments and how
  to run them.
- `docs/verified_environments/2026-06.txt` — the main dev-env snapshot (the conda
  env, for contrast).
