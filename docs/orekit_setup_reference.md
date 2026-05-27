# Orekit Setup Reference

A working reference for the Orekit Python (`orekit_jpype`) environment on Windows.

## Installed Stack

- **Conda environment name:** `propygator`
- **Python:** 3.11
- **OpenJDK:** 17 (bundled inside the conda environment)
- **Orekit wrapper:** `orekit_jpype` 13.1.4 (JPype-based, modern path)
- **JPype:** 1.5.2
- **NumPy:** 2.4.x

Everything lives inside the conda environment. The system-installed Temurin is **not used** by this project and does not need to be configured.

## Project Layout

```
C:\Users\hzhan\Documents\orekit-project\
├── orekit-data\                  # downloaded data bundle (do not commit)
│   ├── Earth-Orientation-Parameters\
│   ├── Potential\
│   ├── DE-440-ephemerides\
│   ├── MSAFE\
│   ├── CSSI-Space-Weather-Data\
│   ├── tai-utc.dat
│   ├── fes2004_Cnm-Snm.dat
│   └── ...
├── test_orekit.py                # verified smoke test
└── (your code here)
```

## Daily Startup

Open **Anaconda Prompt** and run:

```
conda activate propygator
cd C:\Users\hzhan\Documents\propygator
```

Your prompt should show `(propygator)` at the front. If it doesn't, the environment isn't active and nothing will work correctly.

To exit: `conda deactivate`, or just close the window.

## Where Code Can Run

What matters is that the `propygator` environment is active when Python runs — not which terminal you use.

- **Anaconda Prompt** — simplest, works out of the box.
- **Command Prompt** — works after `conda activate propygator`.
- **PowerShell** — works after a one-time `conda init powershell` and reopen.
- **VS Code / PyCharm** — select the interpreter at `C:\Users\hzhan\miniconda3\envs\propygator\python.exe`. Integrated terminal then auto-activates.
- **Jupyter** — install into the env (`conda install -c conda-forge jupyterlab`), launch from the activated env. Notebooks keep the JVM warm across cells, which is much faster than rerunning scripts.
- **Double-click a .py file in Explorer** — does **not** work. Uses the system Python, not the conda one.

## Required Boilerplate

Every Orekit script starts with these lines, in this exact order:

```python
import orekit_jpype as orekit
orekit.initVM()

from orekit_jpype.pyhelpers import setup_orekit_curdir
setup_orekit_curdir("orekit-data")   # or absolute path
```

Rules:

- `initVM()` must be called **before** any `from org.orekit...` imports. The Java side isn't up yet otherwise.
- `initVM()` runs once per process. Calling it again is a silent no-op in JPype (fine in notebooks).
- `setup_orekit_curdir()` configures the global data context for the entire process. Do it once, near the top.

**Robust data path** (script works regardless of where you launch it from):

```python
from pathlib import Path
data_dir = Path(__file__).parent / "orekit-data"
setup_orekit_curdir(str(data_dir))
```

## The Java/Python Boundary

JPype handles most type conversion transparently, but a few patterns come up constantly.

### Return values are Java objects

A `Vector3D` from Orekit is a Java object, not a NumPy array. Access components with Java-style getters:

```python
import numpy as np
pos_vec = state.getPVCoordinates().getPosition()
pos_np = np.array([pos_vec.getX(), pos_vec.getY(), pos_vec.getZ()])
```

This conversion pattern shows up everywhere. Expect to do it at the boundary of every block of NumPy/SciPy/Matplotlib work.

### Numbers convert automatically

Python `int` and `float` → Java `int`, `long`, `double` as needed. No action required.

### Arrays sometimes need explicit conversion

Python lists usually auto-convert to Java arrays for method args. When constructing explicitly:

```python
import jpype
arr = jpype.JArray(jpype.JDouble)([1.0, 2.0, 3.0])
```

### Exceptions are Java exceptions

```python
from org.orekit.errors import OrekitException
try:
    ...
except OrekitException as e:
    print("Orekit failed:", e.getMessage())
```

Catching plain `Exception` works too but is less specific.

## Conventions Orekit Enforces

- **Units are SI everywhere.** Meters, meters/second, radians, seconds, kilograms. Passing km or degrees gives nonsense, not an error. Convert at your code's boundaries.
- **Frames are explicit.** Every position/velocity exists in a specific frame (ITRF, EME2000, GCRF, ...). There is no implicit default. You always specify which.
- **Dates require a time scale.** UTC, TAI, TT, etc. `AbsoluteDate(2026, 1, 1, 0, 0, 0.0, utc)` — the trailing time scale argument is not optional.

## Performance Notes

- **JVM startup is 2-5 seconds per fresh script run.** Unavoidable. Long-running notebooks pay this cost once; rerun-heavy scripts pay it every time.
- **Default JVM heap is usually fine.** For multi-year high-fidelity batch runs, pass `orekit.initVM(vmargs='-Xmx8g')` for an 8 GB heap.
- **JVM memory is separate from Python memory.** Large Orekit object graphs don't show up in Python memory profilers.

## Limitations to Know Up Front

- **No subclassing Java classes from Python.** The JPype wrapper can't do this (the older JCC wrapper could).
- **Implementing Java interfaces in Python is possible** but uses `@JImplements` / `@JOverride` decorators. Needed for custom force models, event detectors, etc. We'll address this when the build calls for it.
- **IDE autocomplete is limited.** JPype generates stubs at runtime, so static analyzers don't fully understand `org.orekit.*` imports. Red underlines that "work anyway" are normal. `pip install orekit-stubs` improves things but isn't essential.

## Environment Maintenance

- **Don't `conda update` blindly.** The pinned versions (Python 3.11, OpenJDK 17, orekit_jpype 13.1.4) are a tested combination.
- **To upgrade Orekit later:** create a fresh environment with the new version rather than upgrading in place. This is conda-forge's recommended pattern and avoids the kind of version-mismatch fragility that broke previous installation attempts.
- **Don't commit `orekit-data/` to version control.** ~500 MB, updated independently. Add to `.gitignore`. Document that collaborators need to download it separately from https://gitlab.orekit.org/orekit/orekit-data.

## Verified Smoke Test

The `test_orekit.py` that confirmed the install:

```python
import orekit_jpype as orekit
orekit.initVM()

from orekit_jpype.pyhelpers import setup_orekit_curdir
setup_orekit_curdir("orekit-data")
print("Data loaded OK")

from org.orekit.time import AbsoluteDate, TimeScalesFactory
utc = TimeScalesFactory.getUTC()
date = AbsoluteDate(2026, 1, 1, 0, 0, 0.0, utc)
print("Date constructed:", date)

from org.orekit.frames import FramesFactory
from org.orekit.utils import IERSConventions
itrf = FramesFactory.getITRF(IERSConventions.IERS_2010, True)
print("ITRF frame:", itrf)

from org.orekit.forces.gravity.potential import GravityFieldFactory
provider = GravityFieldFactory.getNormalizedProvider(70, 70)
print("Gravity provider, max degree:", provider.getMaxDegree())

print("\nAll three tests passed.")
```

If any future change to the environment breaks things, run this first to localize the failure.

## Mental Model

Think of the `orekit` conda environment as a self-contained appliance: a specific Python, a specific JDK, the wrapper, and the data files all live inside it. You step in with `conda activate orekit`, work, and step out with `conda deactivate`. Nothing inside leaks out; nothing outside contaminates it. That isolation is what makes the setup stable.
