"""The ten catalogue TLEs for Part 3's ``catalog`` row, as frozen literals.

NORAD **43476** (GRACE-FO C / "GRACE-FO 1"), Space-Track ``gp_history``, pulled
by hand from the browser by the maintainer (2026-08-22). **There is no committed
fetcher and none is wanted**: the build plan specifies frozen literals and no
runtime network, because a results file that re-pulls is not reproducible.

PROVENANCE, kept here because ``data/`` is gitignored and this module is
therefore the only committed record of the pull. The raw paste lives at
``data/gracefo/catalog/catalog_pull_43476.txt`` and the derived per-window
resolution at ``catalog_selected_43476.txt`` beside it.

- **Selection rule (contract):** the LATEST epoch at or before the forecast
  start ``T``. A later epoch carries information no other method has, and
  comparing against it would be meaningless.
- **151 raw candidates** over ``[T - 5 d, T + 1 d]`` across the ten windows,
  **148** after dropping 3 byte-identical duplicate records (none of them a
  winner). ``n_candidates`` below stores the **post-dedup** count, so the ten
  sum to 148, not 151. Every candidate was constructed through
  ``TLE.from_strings``, which enforces the fixed-column layout and both mod-10
  checksums; NORAD id and object name were checked on every row. **10/10
  windows resolved.**
- **Staleness** is recorded on every row -- it is the known confounder in any
  catalogue comparison. Range 0.0655-0.4259 d.
- Both bookkeeping fields are checked against the sets themselves at import
  (:func:`_check_catalog`), and a post-``T`` epoch is a hard error at both
  import and read, since it would make the cross-tag check PASS more easily.

**THE WINDOW 9 CAVEAT.** ``moderate_2025_07`` is the one stale outlier at
0.4259 d (10.22 h) against 1.57-3.39 h everywhere else -- a catalogue gap, whose
next set sits only 3.86 h PAST T and is ineligible by the rule. A weak
``catalog`` row there is a staleness result before it is a method result.

**THE 18 SECOND OFFSET.** The staleness figures below were computed against
``T = t0 + 6 d 00:00:00 UTC``. The driver's T is the truth sample at index
``K_T``, which sits 18 s earlier (GNV1B days start at GPS midnight), so runtime
staleness is 0.0002 d smaller. No candidate in any window lies within 18 s of T
-- the closest margins are 1.57 h before and 3.86 h after -- so the SELECTION is
unaffected. :func:`entry_for` recomputes staleness against the T it is given and
the driver prints both.

**THE CROSS-TAG CHECK: 10/10 PASS (2026-08-22).** Cross-tagging between
close-flying objects is a known catalogue failure mode, and GRACE-FO C and D are
exactly that case -- a set tagged 43476 that described 43477 would carry the
right inclination, the right mean motion and valid checksums, and would quietly
turn Part 3's ``catalog`` row into a measurement of the wrong satellite.
:func:`cross_tag_check` propagates each row into ``[T, T + 1 d]`` and requires
the residual against C truth to beat the residual against D truth by
:data:`CROSS_TAG_MIN_RATIO`. Measured over the ten windows -- **provisional
figures**, from a one-time uncommitted sweep, re-derived from committed window
files at Chunk 18:

- residual **vs C 664-1004 m**, **vs D 173.6-221.8 km**, ratio **195-301x**
  against the 5x bar -- every window clears it by ~40x, so no verdict is
  marginal;
- the twins are **173.0-222.3 km** apart on forecast day 1, which is what a
  cross-tagged set would show and what staleness cannot manufacture. That is
  what makes this a TAG test rather than a quality test;
- window 9, the 10.22 h staleness outlier, scores **738 m vs C** -- mid-pack
  among the ten, not degraded. Read as one day's evidence, not as a verdict on
  its ``catalog`` row; Chunk 18 adjudicates staleness against outcome.

The sweep was one-time and is not committed as a script. Its permanent guard is
``run_tle_window.py``, which re-runs this check in every window's ``[catalog]``
block and hard-exits on a miss, so every committed window file from Chunk 15 on
carries its own cross-tag verdict.

JVM-free at import. Not shipped, not in CI, outside ``testpaths``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
_FROZEN = _STUDY.parent / "real-world-validation"
for _p in (str(_HERE), str(_STUDY), str(_FROZEN), str(_FROZEN / "gracefo")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from common import rms as _rms  # noqa: E402

from propygator import TLE, Epoch, Frame, propagate_tle  # noqa: E402

# The cross-tag margin. NOT a quality bar -- a tag discriminator. See the module
# docstring: separation is 173-222 km, a correct row is km-class at day 1, so
# the measured ratio should be ~100x. Pre-registered before the check ran.
CROSS_TAG_MIN_RATIO = 5.0

# Truth-file name used for the C-vs-D comparison, for the report line.
_CROSS_TAG_READ_DAY = 1


@dataclass(frozen=True)
class CatalogEntry:
    """One window's selected catalogue set, with the pull's own bookkeeping."""

    window: str
    line1: str
    line2: str
    epoch_iso: str  # UTC, as the pull reported it -- a transcription checksum
    staleness_d_utc: float  # vs T at UTC midnight; see the 18 s note
    n_candidates: int  # candidates in [T - 5 d, T + 1 d], after dedup

    @property
    def tle(self) -> TLE:
        """Constructed through ``from_strings``, so both checksums re-validate."""
        return TLE.from_strings(self.line1, self.line2, name="GRACE-FO 1")


# --- the ten, in table order --------------------------------------------------
CATALOG: dict[str, CatalogEntry] = {
    e.window: e
    for e in (
        CatalogEntry(
            "low_2019_12",
            "1 43476U 18047A   19362.85875694  .00000243  00000-0  87155-5 0  9997",
            "2 43476  88.9957 160.8870 0016702 191.8784 168.2072 15.23953506 89086",
            "2019-12-28T20:36:36.599616",
            0.1412,
            10,
        ),
        CatalogEntry(
            "low_2021_04",
            "1 43476U 18047A   21110.91039612  .00000559  00000-0  21537-4 0  9991",
            "2 43476  88.9768  96.0390 0018215 158.4834 201.7184 15.24235070162044",
            "2021-04-20T21:50:58.224768",
            0.0896,
            17,
        ),
        CatalogEntry(
            "low_2021_06",
            "1 43476U 18047A   21173.87000853  .00000364  00000-0  13596-4 0  9990",
            "2 43476  88.9823  87.4536 0014570 290.0557  69.9122 15.24285959171639",
            "2021-06-22T20:52:48.736992",
            0.1300,
            11,
        ),
        CatalogEntry(
            "moderate_2022_04",
            "1 43476U 18047A   22124.88501851  .00002093  00000-0  82880-4 0  9995",
            "2 43476  88.9905  44.3890 0018008 148.9992 211.2322 15.24783755219778",
            "2022-05-04T21:14:25.599264",
            0.1150,
            16,
        ),
        CatalogEntry(
            "intense_2024_06",
            "1 43476U 18047A   24171.87692316  .00003600  00000-0  12458-3 0  9993",
            "2 43476  88.9771 298.7170 0015380  64.2921 295.9915 15.29479453338284",
            "2024-06-19T21:02:46.161024",
            0.1231,
            14,
        ),
        CatalogEntry(
            "storm_2024_08",
            "1 43476U 18047A   24229.90021219  .00008699  00000-0  29677-3 0  9993",
            "2 43476  88.9758 290.7130 0012653 180.8994 179.2237 15.30141710347153",
            "2024-08-16T21:36:18.333216",
            0.0998,
            17,
        ),
        CatalogEntry(
            "intense_2024_11",
            "1 43476U 18047A   24333.89176096  .00009011  00000-0  29037-3 0  9990",
            "2 43476  88.9736 276.2497 0014136 139.0970 221.1345 15.31963005363067",
            "2024-11-28T21:24:08.146944",
            0.1082,
            15,
        ),
        CatalogEntry(
            "storm_2025_05",
            "1 43476U 18047A   25151.93448321  .00004178  00000-0  12362-3 0  9999",
            "2 43476  88.9783 250.6288 0013389 144.9232 215.2906 15.34553906391266",
            "2025-05-31T22:25:39.349344",
            0.0655,
            14,
        ),
        CatalogEntry(
            "moderate_2025_07",
            "1 43476U 18047A   25209.57406459  .00003208  00000-0  93765-4 0  9999",
            "2 43476  88.9755 242.6267 0008821 299.2170  60.8200 15.34919707400103",
            "2025-07-28T13:46:39.180576",
            0.4259,
            14,
        ),
        CatalogEntry(
            "storm_2026_01",
            "1 43476U 18047A   26018.93139222  .00004074  00000-0  11213-3 0  9998",
            "2 43476  88.9834 218.4869 0010359 348.3527  11.7486 15.36856099426869",
            "2026-01-18T22:21:12.287808",
            0.0686,
            20,
        ),
    )
}

# --- transcription guards, run once at import ---------------------------------
# THE TEN ENTRIES ABOVE ARE HAND-TRANSCRIBED from a browser paste, and they are
# the only hand-typed data table in the study. So the two bookkeeping fields are
# wired up as the checksums they claim to be rather than left decorative:
# `epoch_iso` must reproduce the set's OWN epoch (catches a two-line set pasted
# under the wrong window's metadata), and `staleness_d_utc` must reproduce
# T = t0 + 6 d at UTC midnight for the window it is keyed under (catches a whole
# entry landing on the wrong window, which the epoch check alone cannot see).
_N_WINDOWS = 10
_ARC_END_DAY_UTC = 6  # T = t0 + 6 d 00:00:00 UTC, the basis these were computed on
_STALENESS_TOL_D = 1e-4  # the recorded value carries 4 decimals; worst seen 4.3e-5


def _check_catalog() -> None:
    """Assert the bookkeeping agrees with the sets themselves. JVM-free."""
    from datetime import datetime, timedelta

    from windows import resolve

    from propygator import TimeScale

    if len(CATALOG) != _N_WINDOWS:
        raise SystemExit(
            f"catalog_tles: {len(CATALOG)} entries, expected {_N_WINDOWS} -- a "
            f"duplicate window key silently drops an entry from the dict"
        )
    for name, entry in CATALOG.items():
        got = entry.tle.epoch.in_scale(TimeScale.UTC).to_iso()
        if got != entry.epoch_iso:
            raise SystemExit(
                f"catalog_tles[{name}]: the set's own epoch {got} does not match "
                f"the recorded epoch_iso {entry.epoch_iso} -- the two-line set and "
                f"its bookkeeping disagree, so one of them was transcribed wrong"
            )
        t_utc = datetime.combine(
            resolve(name).t0 + timedelta(days=_ARC_END_DAY_UTC), datetime.min.time()
        )
        expect = (
            t_utc - datetime.fromisoformat(entry.epoch_iso)
        ).total_seconds() / 86400.0
        if abs(expect - entry.staleness_d_utc) > _STALENESS_TOL_D:
            raise SystemExit(
                f"catalog_tles[{name}]: recorded staleness "
                f"{entry.staleness_d_utc:.4f} d but this set sits {expect:.4f} d "
                f"before T = {t_utc.isoformat()} -- the entry is keyed under a "
                f"window it does not belong to"
            )
        if expect <= 0.0:
            raise SystemExit(
                f"catalog_tles[{name}]: epoch {entry.epoch_iso} is AFTER "
                f"T = {t_utc.isoformat()}; the contract selects the latest epoch "
                f"at or before T"
            )


_check_catalog()


def entry_for(window_name: str) -> CatalogEntry:
    try:
        return CATALOG[window_name]
    except KeyError:
        raise SystemExit(
            f"no catalogue TLE recorded for window {window_name!r}; "
            f"have: {', '.join(sorted(CATALOG))}"
        ) from None


def staleness_days(entry: CatalogEntry, t: Epoch) -> float:
    """``T`` minus the TLE epoch, in days, against the T actually used.

    NEGATIVE IS A HARD ERROR, not a warning. The contract's rule is the latest
    epoch at or BEFORE ``T``; a set from after ``T`` carries information no
    other configuration has, and because a fresher epoch tracks C better it
    would make :func:`cross_tag_check` score HIGHER and PASS. The failure would
    therefore be silent, and the ``catalog`` row quietly unfair to every other
    row.
    """
    staleness = t.seconds_since(entry.tle.epoch) / 86400.0
    if staleness < 0.0:
        raise SystemExit(
            f"catalog_tles[{entry.window}]: TLE epoch {entry.tle.epoch.to_iso()} "
            f"is {-staleness:.4f} d AFTER T {t.to_iso()} -- the contract selects "
            f"the latest epoch at or before T. A post-T set beats every other "
            f"configuration on information it should not have."
        )
    return staleness


@dataclass(frozen=True)
class CrossTagResult:
    """One window's cross-tag verdict, with both residuals that produced it."""

    rms_c_m: float
    rms_d_m: float
    ratio: float
    separation_km: float
    passed: bool

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"


def cross_tag_check(
    entry: CatalogEntry,
    t: Epoch,
    truth_c_pos_m: np.ndarray,
    truth_d_pos_m: np.ndarray,
    *,
    step_s: float = 60.0,
) -> CrossTagResult:
    """Propagate the catalogue set into day 1 and confirm it tracks C, not D.

    ``truth_c_pos_m`` / ``truth_d_pos_m`` are the ITRF truth positions over
    ``[T, T + 1 d]`` inclusive, on the same grid this returns, so the diff
    aligns by array index like every other residual in the study.

    THE CALLER MUST HAVE CHECKED D'S ALIGNMENT. This function cannot: the
    ``min()`` below silently shortens a short array, and a shifted D grid
    inflates ``rms_d``, inflates the ratio and makes the check PASS. The check
    therefore fails OPEN on exactly the input it exists to reject, so
    ``run_tle_window.py`` asserts D's length, start epoch and grid continuity
    before calling this.
    """
    n = min(len(truth_c_pos_m), len(truth_d_pos_m))
    traj = propagate_tle(entry.tle, 86400.0, output_step=step_s, start=t)
    pos = traj.to_frame(Frame.ITRF).positions[:n]
    rms_c = _rms(np.linalg.norm(pos - truth_c_pos_m[:n], axis=1))
    rms_d = _rms(np.linalg.norm(pos - truth_d_pos_m[:n], axis=1))
    separation = _rms(np.linalg.norm(truth_c_pos_m[:n] - truth_d_pos_m[:n], axis=1))
    ratio = rms_d / rms_c if rms_c > 0 else float("inf")
    return CrossTagResult(
        rms_c_m=float(rms_c),
        rms_d_m=float(rms_d),
        ratio=float(ratio),
        separation_km=float(separation / 1e3),
        passed=bool(ratio >= CROSS_TAG_MIN_RATIO),
    )


def format_cross_tag(entry: CatalogEntry, t: Epoch, res: CrossTagResult) -> list[str]:
    """The ``[catalog]`` block's cross-tag lines, shared by driver and sweep."""
    return [
        f"  epoch {entry.tle.epoch.to_iso()} {entry.tle.epoch.scale.value}; "
        f"staleness {staleness_days(entry, t):.4f} d "
        f"({24.0 * staleness_days(entry, t):.2f} h)",
        f"  pull recorded {entry.staleness_d_utc:.4f} d against UTC-midnight T "
        f"(the 18 s GPS/UTC offset; selection unaffected), "
        f"{entry.n_candidates} candidates in [T-5d, T+1d] (after dedup)",
        f"  cross-tag day {_CROSS_TAG_READ_DAY}: RMS vs C {res.rms_c_m:.1f} m, "
        f"vs D {res.rms_d_m / 1e3:.1f} km, ratio {res.ratio:.1f}x "
        f"(bar {CROSS_TAG_MIN_RATIO:.0f}x) -> {res.verdict}",
        f"  C-D separation over that day: {res.separation_km:.1f} km "
        f"-- what a cross-tagged set would show and staleness cannot produce",
    ]
