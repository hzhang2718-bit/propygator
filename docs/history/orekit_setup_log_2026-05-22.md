# Orekit Setup Log — May 22, 2026

Record of the successful Orekit installation session, for future context.

## Outcome

Orekit Python wrapper is installed and verified working on Windows. All three smoke tests pass: data loading, frame construction, and gravity field reading.

## What Was Installed

Inside a dedicated conda environment named `propygator`:

| Component        | Version    | Notes                                      |
|------------------|------------|--------------------------------------------|
| Python           | 3.11.15    | pinned for binary coverage stability       |
| OpenJDK          | 17.0.18    | bundled by conda, isolated from Temurin    |
| orekit_jpype     | 13.1.4.0   | JPype-based wrapper (modern path)          |
| jpype1           | 1.5.2      | Java/Python bridge                         |
| NumPy            | 2.4.6      | for computation at the boundary            |
| jupyterlab       | 4.5.7      | for user interfaces                        |

All packages installed from the `conda-forge` channel.

## Project Location

```
C:\Users\hzhan\Documents\propygator\
├── orekit-data\          # extracted from orekit-data GitLab zip
└── test_orekit.py        # working smoke test
```

## Why This Approach Worked

Previous attempts failed because of one or more of:

- **JCC wrapper + OpenJDK 8** — the legacy combination, fragile on modern Windows
- **System JDK mixed with conda's bundled JDK** — caused JVM DLL loading failures
- **`orekit` package pulling OpenJDK 8 implicitly** — Orekit 13 needs Java 11+; the mismatch caused class-loading errors

This setup avoids all three by:

- Using `orekit_jpype` (the JPype-based wrapper, actively maintained) instead of the JCC-based `orekit`
- Pinning `openjdk=17` explicitly in the install command so the solver can't pick an older version
- Keeping everything inside one conda environment; Temurin on the system is unused

## Key Decisions

1. **Path B (JPype) over Path A (JCC).** The previous chat surfaced both as options. JPype is the community's current direction and avoids the openjdk-8 pin that the JCC build forces.
2. **Underscore, not hyphen.** The conda-forge package is `orekit_jpype`, not `orekit-jpype`. The first install attempt failed because of this naming mismatch.
3. **Anaconda Prompt, not PowerShell.** PowerShell needs a one-time `conda init` to make activation work; Anaconda Prompt works out of the box. Switched to Anaconda Prompt when `conda activate propygator` silently failed in PowerShell.
4. **Data zip extracted with no nesting.** The extracted folder is `orekit-data/` directly under the project root, containing `Earth-Orientation-Parameters/`, `Potential/`, `tai-utc.dat`, etc. at the top level — not nested inside another `orekit-data/`.

## Verification

The smoke test in `test_orekit.py` confirmed:

- JVM starts and reports Java 17.0.18
- Orekit data loads from `orekit-data/`
- UTC date construction works (leap-second file readable)
- ITRF frame builds with IERS 2010 conventions (EOP files readable)
- 70×70 gravity field provider loads (Potential/ files readable)

Output:
```
Data loaded OK
Date constructed: 2026-01-01T00:00:00.000Z
ITRF frame: CIO/2010-based ITRF simple EOP
Gravity provider, max degree: 70
All three tests passed.
```

## Install Commands Used (for reproducibility)

```
conda create -n propygator -c conda-forge python=3.11 openjdk=17 orekit_jpype numpy
conda activate propygator
```

Then downloaded `orekit-data` zip from https://gitlab.orekit.org/orekit/orekit-data, extracted to `C:\Users\hzhan\Documents\propygator\orekit-data\`.

## Next Steps

Resume work on the original solar sail simulation build (Direction B in the conversation). Starting point: minimal Keplerian propagation as a propagator sanity check, then incrementally adding force models per the original build doc.

See `orekit_setup_reference.md` for ongoing operational reference (boilerplate, conventions, gotchas).
