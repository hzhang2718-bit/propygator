"""The frozen ten-window list, its CSSI re-read, and this study's file finder.

THE WINDOW LIST IS FROZEN EVIDENCE, NOT A CONFIGURATION KNOB. It was drawn once
(``random.Random``, seed 20260814) without reference to how well the propagator
performs on any of it, and recorded in both
``docs/build-plan-extended-validation-updated.md`` and here. The draw is never
repeated at runtime and this table is never re-sorted, re-drawn or extended
without a recorded retirement (contract, "Important: the windows are drawn
once").

WHY THE AGGREGATES ARE RE-READ RATHER THAN TRUSTED. ``FROZEN_INDICES`` below
transcribes the build plan's table so that a transcription error shows up as a
mismatch instead of propagating silently. The drivers call
:func:`window_indices` and print what CSSI actually says; ``check_frozen_table``
diffs the two. The transcribed numbers are a checksum, not an input.

THE 13 -> 14 DAY EXTENSION (2026-08-15). Windows are 14 days. The draw was made
on 13-day candidates and was NOT re-run; every drawn window was re-verified
against the same band rules over its full 14 days, and only window 4
``moderate_2022_04`` moved (-1 day, t0 2022-04-30 -> 2022-04-29, to restore the
F10.7 max/min flatness rule to 1.220 against a cap of 1.35). See the build plan
for the full record, including the two caveats left as drawn: "intense" exists
only in 2024, and the 2,887-candidate count implies a t0 span starting
2018-06-01 rather than the 2018-09-01 stated beside it.

FLUX CONVENTION. CSSI publishes F10.7 twice -- adjusted to 1 AU and observed at
Earth. NRLMSISE-00 is built on the OBSERVED series, which is what Orekit's
``CssiSpaceWeatherData`` feeds it, so ``flux="obs"`` is the default here and is
what the frozen table is checked against. ``flux="adj"`` exists so the check can
report both and the choice is visible rather than assumed.

JVM-free: pure stdlib + numpy, no ``propygator`` import, no Orekit. That is
deliberate -- it lets the whole ten-window table be verified against CSSI before
a single byte of truth data is downloaded.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies to
the callers; this module only parses and reports.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# --- roots --------------------------------------------------------------------
# experiments/extended-validation/gracefo/windows.py -> the study root.
STUDY_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = STUDY_ROOT.parents[1]

# This study's own truth tree (gitignored). Mirrors the frozen study's shape --
# one directory per window, named for the window -- so --data-root behaves
# identically across both trees.
DATA_ROOT = STUDY_ROOT / "data" / "gracefo"
# Transient download staging. Tarballs are deleted as soon as their six members
# are extracted; nothing here is an input to any run.
TARBALL_ROOT = STUDY_ROOT / "data" / "tarballs"

WINDOW_DAYS = 14

# The three products kept out of each 148 MB daily tarball, for both satellites:
# GNV1B is the truth ephemeris, MAS1B the tank-gas mass record, THR1B the
# thruster activation log the tier-1 maneuver screen reads. 19.23 MB/day gzipped
# against 148 MB/day raw (contract, "New truth data lands in the new study's own
# folder").
PRODUCTS = ("GNV1B", "MAS1B", "THR1B")
SAT_IDS = ("C", "D")


@dataclass(frozen=True)
class Window:
    """One frozen 14-day study window."""

    index: int  # 1-10, the table order the chunks run in
    name: str  # also the directory name under DATA_ROOT
    t0: date  # first day (UTC), inclusive
    band: str  # "low" | "moderate" | "intense" | "storm"
    note: str = ""

    @property
    def is_storm(self) -> bool:
        """Storm windows take the raised Cd scan ceiling and are never slid."""
        return self.band == "storm"

    @property
    def days(self) -> tuple[date, ...]:
        """The 14 UTC days this window covers, in order."""
        return tuple(self.t0 + timedelta(days=k) for k in range(WINDOW_DAYS))

    @property
    def end_exclusive(self) -> date:
        return self.t0 + timedelta(days=WINDOW_DAYS)

    @property
    def dir(self) -> Path:
        return DATA_ROOT / self.name


# --- the frozen ten -----------------------------------------------------------
WINDOWS: tuple[Window, ...] = (
    Window(1, "low_2019_12", date(2019, 12, 23), "low"),
    Window(2, "low_2021_04", date(2021, 4, 15), "low"),
    Window(3, "low_2021_06", date(2021, 6, 17), "low"),
    Window(
        4,
        "moderate_2022_04",
        date(2022, 4, 29),
        "moderate",
        note="slid -1 d from 2022-04-30 at the 13->14 day extension (F10.7 "
        "flatness 1.372 -> 1.220 against a 1.35 cap)",
    ),
    Window(
        5,
        "intense_2024_06",
        date(2024, 6, 14),
        "intense",
        note="'intense' exists only in 2024, so the band is confounded with "
        "mission epoch and altitude",
    ),
    Window(
        6,
        "storm_2024_08",
        date(2024, 8, 11),
        "storm",
        note="storm at day 1: storm-contaminated fit arc, calm forecast",
    ),
    Window(
        7,
        "intense_2024_11",
        date(2024, 11, 23),
        "intense",
        note="'intense' exists only in 2024 -- see window 5",
    ),
    Window(
        8,
        "storm_2025_05",
        date(2025, 5, 26),
        "storm",
        note="storm across days 3-8: nonstationarity, the 's' half of the gate",
    ),
    Window(
        9,
        "moderate_2025_07",
        date(2025, 7, 23),
        "moderate",
    ),
    Window(
        10,
        "storm_2026_01",
        date(2026, 1, 13),
        "storm",
        note="storm onset at the day-6 boundary: the contract's mandated "
        "fit-right-before-onset case, clean arc and forecast opening at onset",
    ),
)

WINDOWS_BY_NAME = {w.name: w for w in WINDOWS}

# The build plan's published aggregates, transcribed as a CHECKSUM on the table
# above -- never as an input to a run. 14-day means for f107 and ctr81, 14-day
# maxima for ap/ap3/kp, and the f107 max/min flatness ratio the band rules used.
# f107_lo/f107_hi are the plan's parenthesised range and are integers there, so
# they are checked as rounded values.
FROZEN_INDICES: dict[str, dict[str, float]] = {
    "low_2019_12": {
        "f107": 71.9, "f107_lo": 70, "f107_hi": 73, "ctr81": 71.3,
        "ap_max": 8, "ap3_max": 18, "kp_max": 3.3,
    },
    "low_2021_04": {
        "f107": 77.3, "f107_lo": 75, "f107_hi": 83, "ctr81": 75.0,
        "ap_max": 28, "ap3_max": 48, "kp_max": 5.0,
    },
    "low_2021_06": {
        "f107": 83.1, "f107_lo": 76, "f107_hi": 94, "ctr81": 79.3,
        "ap_max": 13, "ap3_max": 27, "kp_max": 4.0,
    },
    "moderate_2022_04": {
        "f107": 120.2, "f107_lo": 109, "f107_hi": 133, "ctr81": 129.8,
        "ap_max": 15, "ap3_max": 32, "kp_max": 4.3,
    },
    "intense_2024_06": {
        "f107": 187.4, "f107_lo": 167, "f107_hi": 203, "ctr81": 191.3,
        "ap_max": 17, "ap3_max": 39, "kp_max": 4.7,
    },
    "storm_2024_08": {
        "f107": 242.5, "f107_lo": 225, "f107_hi": 282, "ctr81": 218.8,
        "ap_max": 127, "ap3_max": 207, "kp_max": 8.0,
    },
    "intense_2024_11": {
        "f107": 198.6, "f107_lo": 174, "f107_hi": 225, "ctr81": 200.8,
        "ap_max": 11, "ap3_max": 32, "kp_max": 4.3,
    },
    "storm_2025_05": {
        "f107": 137.4, "f107_lo": 115, "f107_hi": 164, "ctr81": 134.7,
        "ap_max": 98, "ap3_max": 179, "kp_max": 7.7,
    },
    "moderate_2025_07": {
        "f107": 147.8, "f107_lo": 143, "f107_hi": 157, "ctr81": 145.8,
        "ap_max": 27, "ap3_max": 39, "kp_max": 4.7,
    },
    "storm_2026_01": {
        "f107": 166.0, "f107_lo": 117, "f107_hi": 232, "ctr81": 145.2,
        "ap_max": 144, "ap3_max": 300, "kp_max": 8.7,
    },
}


# --- the CSSI space-weather file ----------------------------------------------
# orekit-data resolution, architecture sec 3 order, with ONE deliberate change:
# the last fallback is the REPO ROOT rather than Path.cwd(), because experiment
# scripts must be cwd-independent (repo conventions). Set OREKIT_DATA_PATH to
# override; a set-but-missing value raises rather than falling back, exactly as
# _orekit_init._resolve_data_path does.
_CSSI_RELATIVE = Path("CSSI-Space-Weather-Data") / "SpaceWeather-All-v1.2.txt"


def resolve_orekit_data() -> Path:
    """The orekit-data directory, JVM-free (architecture sec 3 search order)."""
    import os

    env_value = os.environ.get("OREKIT_DATA_PATH")
    if env_value:
        env_path = Path(env_value)
        if env_path.is_dir():
            return env_path
        raise SystemExit(
            f"OREKIT_DATA_PATH is set to {env_path} but that is not a directory"
        )
    for candidate in (
        Path.home() / ".propygator" / "orekit-data",
        REPO_ROOT / "orekit-data",
    ):
        if candidate.is_dir():
            return candidate
    raise SystemExit(
        "orekit-data not found. Looked at OREKIT_DATA_PATH, "
        "~/.propygator/orekit-data/ and "
        f"{REPO_ROOT / 'orekit-data'}. Fetch it with "
        "scripts/download_orekit_data.py"
    )


def cssi_path() -> Path:
    path = resolve_orekit_data() / _CSSI_RELATIVE
    if not path.is_file():
        raise SystemExit(f"CSSI space-weather file not found at {path}")
    return path


def cssi_display_name() -> str:
    """The CSSI file named relative to orekit-data -- machine-independent.

    orekit-data resolves to ``~/.propygator/orekit-data/`` on this machine, which
    is OUTSIDE the repo, so printing the resolved path into a committed results
    file would both leak a home directory and red ``run_all.py --verify``
    anywhere else. The provenance that actually matters is the file's own
    UPDATED stamp, which :func:`cssi_updated` reads.
    """
    return f"<orekit-data>/{_CSSI_RELATIVE.as_posix()}"


def cssi_updated(path: Path | None = None) -> str:
    """The CSSI file's own ``UPDATED`` stamp -- the version of the input, not a path.

    This is the one line that pins WHICH space-weather file produced a number.
    orekit-data is an external dependency that moves (the OBSERVED boundary moves
    with it), so a results file that does not record this cannot be re-verified
    after a refresh.
    """
    src = path if path is not None else cssi_path()
    with open(src, encoding="ascii", errors="replace") as fh:
        for _ in range(20):
            line = fh.readline()
            if not line:
                break
            if line.startswith("UPDATED"):
                return line.split(None, 1)[1].strip()
    return "unknown"


@dataclass(frozen=True)
class CssiDay:
    """One daily CSSI record, only the fields this study reads."""

    day: date
    kp: tuple[float, ...]  # 8 three-hourly Kp, already divided by 10
    ap: tuple[int, ...]  # 8 three-hourly ap
    ap_avg: int  # the daily Ap the default NRLMSISE-00 switches actually use
    f107_adj: float  # adjusted to 1 AU
    ctr81_adj: float
    f107_obs: float  # observed at Earth -- what NRLMSISE-00 is built on
    ctr81_obs: float
    observed: bool  # False once past the OBSERVED block (flat placeholder ap/kp)


# Column layout from the file's own FORMAT line and header, verified against a
# delivered file (2026-01-19: kp_max 8.7, ap3_max 300, both matching the frozen
# table). Zero-based token indices:
#   0-2 yy mm dd | 3 BSRN | 4 ND | 5-12 Kp*10 | 13 KpSum | 14-21 ap | 22 Ap avg
#   23 Cp | 24 C9 | 25 ISN | 26 F10.7 adj | 27 Q | 28 Ctr81 adj | 29 Lst81 adj
#   30 F10.7 obs | 31 Ctr81 obs | 32 Lst81 obs
_N_TOKENS = 33


def read_cssi(path: Path | None = None) -> dict[date, CssiDay]:
    """Parse the CSSI daily records into a date -> :class:`CssiDay` map.

    Both the OBSERVED and DAILY_PREDICTED blocks are read, flagged by
    ``observed``. The distinction matters: past the OBSERVED boundary the
    daily-predicted rows carry a FLAT PLACEHOLDER ap/Kp, so a storm window there
    would contain no storm in the model at all and would read as a propagator
    failure (contract, "No window may extend past 2026-05-09").
    """
    src = path if path is not None else cssi_path()
    out: dict[date, CssiDay] = {}
    block: str | None = None
    for raw in src.read_text(encoding="ascii", errors="replace").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("BEGIN "):
            block = line.split(None, 1)[1].strip()
            continue
        if line.startswith("END "):
            block = None
            continue
        if block not in ("OBSERVED", "DAILY_PREDICTED"):
            continue
        parts = line.split()
        if len(parts) < _N_TOKENS:
            raise ValueError(
                f"{src.name}: expected >= {_N_TOKENS} columns in the {block} "
                f"block, got {len(parts)}: {line!r}"
            )
        day = date(int(parts[0]), int(parts[1]), int(parts[2]))
        out[day] = CssiDay(
            day=day,
            kp=tuple(int(p) / 10.0 for p in parts[5:13]),
            ap=tuple(int(p) for p in parts[14:22]),
            ap_avg=int(parts[22]),
            f107_adj=float(parts[26]),
            ctr81_adj=float(parts[28]),
            f107_obs=float(parts[30]),
            ctr81_obs=float(parts[31]),
            observed=(block == "OBSERVED"),
        )
    if not out:
        raise ValueError(f"{src.name}: no CSSI daily records parsed")
    return out


def observed_end(cssi: dict[date, CssiDay]) -> date:
    """Last day inside the OBSERVED block -- the study's hard window boundary."""
    return max(d for d, rec in cssi.items() if rec.observed)


def window_indices(
    window: Window,
    cssi: dict[date, CssiDay],
    *,
    flux: str = "obs",
) -> dict[str, float]:
    """The window's aggregate space-weather indices, computed from CSSI.

    Means over the 14 days for F10.7 and Ctr81, maxima for daily Ap, 3-hourly ap
    and Kp, plus the F10.7 max/min flatness ratio the non-storm band rules used.
    ``flux`` selects the observed (default, what NRLMSISE-00 consumes) or the
    1 AU-adjusted series.
    """
    if flux not in ("obs", "adj"):
        raise ValueError(f"flux must be 'obs' or 'adj', got {flux!r}")
    days = window.days
    missing = [d for d in days if d not in cssi]
    if missing:
        raise ValueError(
            f"{window.name}: CSSI has no record for {missing[0]} "
            f"({len(missing)} of {len(days)} days missing)"
        )
    recs = [cssi[d] for d in days]
    f107 = [getattr(r, f"f107_{flux}") for r in recs]
    ctr81 = [getattr(r, f"ctr81_{flux}") for r in recs]
    return {
        "f107": sum(f107) / len(f107),
        "f107_lo": min(f107),
        "f107_hi": max(f107),
        "f107_flatness": max(f107) / min(f107),
        "ctr81": sum(ctr81) / len(ctr81),
        "ap_max": float(max(r.ap_avg for r in recs)),
        "ap3_max": float(max(max(r.ap) for r in recs)),
        "kp_max": max(max(r.kp) for r in recs),
        "n_predicted": float(sum(1 for r in recs if not r.observed)),
    }


def check_frozen_table(
    cssi: dict[date, CssiDay], *, flux: str = "obs"
) -> list[tuple[str, str, float, float]]:
    """Diff the transcribed table against CSSI; returns the mismatching cells.

    Each mismatch is ``(window_name, field, transcribed, measured)``. Means are
    compared at the table's own one-decimal precision, maxima exactly, and the
    parenthesised F10.7 range as rounded integers. An empty list means the
    transcription is clean -- the point of the exercise.
    """
    bad: list[tuple[str, str, float, float]] = []
    for window in WINDOWS:
        want = FROZEN_INDICES[window.name]
        got = window_indices(window, cssi, flux=flux)
        for field, tol in (
            ("f107", 0.05),
            ("ctr81", 0.05),
            ("kp_max", 0.001),
            ("ap_max", 0.001),
            ("ap3_max", 0.001),
        ):
            if abs(float(want[field]) - got[field]) > tol:
                bad.append((window.name, field, float(want[field]), got[field]))
        for field in ("f107_lo", "f107_hi"):
            if round(got[field]) != round(float(want[field])):
                bad.append((window.name, field, float(want[field]), got[field]))
    return bad


# --- this study's file finder -------------------------------------------------
def find_product_files(
    window_dir: Path, product: str, sat_id: str, *, days: int | None = None
) -> list[Path]:
    """Sorted daily files of one product for one satellite in a window directory.

    THIS STUDY'S OWN FINDER, and the reason it exists: the frozen study's
    ``gnv1b.find_window_files`` globs ``.tgz`` tarballs or plain ``.txt`` and
    does NOT glob ``.gz``, so it cannot see this tree's extracted-and-compressed
    products. The frozen module is imported, never edited (contract, "The
    earlier experiment is frozen"), so the new folder gets this instead.

    Sorted by name, which orders the ISO date in each product file name
    chronologically. ``days`` asserts the expected count -- pass it wherever a
    short window would silently shorten an RMS span.
    """
    if product not in PRODUCTS:
        raise ValueError(f"product must be one of {PRODUCTS}, got {product!r}")
    if sat_id not in SAT_IDS:
        raise ValueError(f"sat_id must be one of {SAT_IDS}, got {sat_id!r}")
    found = sorted(window_dir.glob(f"{product}_*_{sat_id}_*.txt.gz"))
    if not found:
        found = sorted(window_dir.glob(f"{product}_*_{sat_id}_*.txt"))
    if days is not None and len(found) != days:
        raise SystemExit(
            f"{window_dir.name}: expected {days} {product} files for satellite "
            f"{sat_id}, found {len(found)}. Run fetch_windows.py for this window."
        )
    return found


def expected_file_names(window: Window) -> set[str]:
    """The 84 gzipped product file names a fully landed window holds."""
    return {
        f"{product}_{day.isoformat()}_{sat}_04.txt.gz"
        for day in window.days
        for product in PRODUCTS
        for sat in SAT_IDS
    }


def check_window_files(window: Window, window_dir: Path | None = None) -> None:
    """Assert the landed files are EXACTLY this window's 14 days.

    WHY THIS IS SEPARATE FROM THE FINDER. :func:`find_product_files` matches on
    product and satellite and asserts only a COUNT, so a window re-fetched after
    a t0 slide can hold days from the old t0 alongside the new ones -- window 4
    has already slid once, and the build plan's failure rule slides more on a
    burn. An off-by-a-day pair leaves the count at 14 and the parse would
    silently concatenate a window that is not the frozen window, putting every
    RMS and screen verdict on the wrong epochs. Checked once per window here
    rather than inside the finder, which stays untouched.
    """
    directory = window_dir if window_dir is not None else window.dir
    want = expected_file_names(window)
    have = {p.name for p in directory.glob("*.txt.gz")}
    if not have:  # mirror the finder's uncompressed fallback
        have = {p.name for p in directory.glob("*.txt")}
        want = {name[: -len(".gz")] for name in want}
    missing = sorted(want - have)
    extra = sorted(have - want)
    if missing or extra:
        raise SystemExit(
            f"{window.name}: landed files do not match the frozen window "
            f"({window.t0} .. {window.days[-1]}).\n"
            f"  missing {len(missing)}: {missing[:4]}\n"
            f"  unexpected {len(extra)}: {extra[:4]}\n"
            f"  A window re-fetched after a t0 slide keeps the old days. Clear "
            f"{directory} and re-run fetch_windows.py for this window."
        )


def window_is_complete(window: Window) -> bool:
    """True iff all 14 days of all three products are present for both satellites."""
    if not window.dir.is_dir():
        return False
    return all(
        len(find_product_files(window.dir, product, sat)) == WINDOW_DAYS
        for product in PRODUCTS
        for sat in SAT_IDS
    )


def resolve(name: str) -> Window:
    """Look up a window by name, with a usable error listing the ten."""
    try:
        return WINDOWS_BY_NAME[name]
    except KeyError:
        raise SystemExit(
            f"unknown window {name!r}; choose from: "
            + ", ".join(w.name for w in WINDOWS)
        ) from None
