# Pass verification — the Feature 1.5 Skyfield cross-check fixture

Reference data for `find_passes` (Feature 1.5, `docs/history/build-plan-feature-1.5.md`
Chunk 3 → Checkpoint A): the same fixed pass search that
`tests/tracking/test_passes.py` runs through propygator, computed independently
with **Skyfield** — python-sgp4 propagation, Skyfield's own TEME→ITRS frame
chain, topocentric geometry, and the DE421 solar ephemeris. No Orekit anywhere
in the stack, so agreement is a genuine independent-implementation check (the
Feature 1.4 self-sourced + cross-checked reference-data precedent).

## The fixture

| | |
|---|---|
| Satellite | ISS (ZARYA), the fixed historical TLE used across the 1.3/1.4/1.5 tests (epoch 2026-06-20.41) |
| Station | Durham: 35.99°N, 78.90°W, 130 m |
| Window | 2026-06-23T00:00:00 UTC + 2 days |
| Gate | 10° elevation, geometric (no refraction — both stacks) |

## How to run (throwaway venv, `docs/experiments_venv.md` hygiene)

From this directory, in PowerShell:

```powershell
python -m venv .venv-passes            # once
.\.venv-passes\Scripts\Activate.ps1    # each new terminal
pip install -r requirements.txt        # once, after the first activate
python generate_reference.py
```

The first run downloads `de421.bsp` (~17 MB) into this directory (gitignored).
The script writes `results.txt` here (ASCII only) and echoes it to stdout.
Never commit the venv or the `.bsp`; **do** commit `results.txt`.

## How the numbers are consumed

- `results.txt` is the committed provenance record (tool versions, TLE lines,
  station, and the full event table: rise/culmination/set UTC times, azimuths,
  culmination elevation, `sunlit_at_culmination`, station Sun altitude).
- The pass table is pinned into `tests/tracking/test_passes.py`'s cross-check
  as cited constants; expected agreement: **rise/set within a few seconds, max
  elevation and azimuths within ~1°** (in practice much tighter — the stacks
  share SGP4 and differ only in frame-chain details).
- Known convention gap: Skyfield's `is_sunlit` shadow model is not propygator's
  conical umbra, so a lighting flag may legitimately differ for a culmination
  within seconds of a shadow crossing; times/angles are the authoritative
  comparison.
- The sanity leg (maintainer, Checkpoint A): a near-future window with a
  *current* TLE eyeballed against Heavens-Above predictions for the same
  station — the check that ties both stacks to reality rather than to each
  other.
