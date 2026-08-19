"""Minimal THR1B parser -- the tier-1 maneuver screen (reference-only).

Reads the GRACE-FO Level-1B thruster activation product
(``THR1B_<date>_<C|D>_04.txt``, ~95 kB/day) out of the same daily tarballs the
GNV1B truth comes from, and reduces it to the one question the study asks: did
either orbit-control thruster fire inside this window?

WHY THIS EXISTS. GRACE-FO performs orbit maintenance, and a burn inside a window
destroys the drag measurement the study is trying to make. The earlier study's
only gate was a degree-5 polynomial fit to the along-track truth signal, which is
weakest exactly where this study needs it most: a geomagnetic storm's onset is
itself a slope kink, so on the three storm windows a burn and a storm look
alike. THR1B gives an EXACT primary gate with no threshold to fix and no
confounding with a storm -- the accumulator either moved or it did not. The
polynomial stays as tier 2 because it also catches what a thruster log cannot:
safe-mode entries, attitude anomalies and bad truth days (contract, "The
polynomial screen is the secondary gate, not the only one").

THE SCREEN. A window is CLEAN for a satellite iff, across all 14 days:
  * every per-record ``on_time_orb_ctrl_1`` and ``on_time_orb_ctrl_2`` is zero,
  * and ``accum_dur_orb_ctrl`` never changes.
The two are redundant by construction, which is the point -- they are read from
different columns and disagreeing is itself a signal.

FORMAT, resolved by inspecting a delivered file rather than from documentation
(2026-08-17, against the frozen quiet_2019 tarballs). 47 whitespace-separated
columns after the YAML header. Zero-based indices of the four this module reads:

    30  on_time_orb_ctrl_1     milliseconds
    31  on_time_orb_ctrl_2     milliseconds
    44  accum_dur_orb_ctrl     milliseconds, monotonic, wraps past 4294967295
    46  qualflg                8-bit string

Columns 4-29 are the TWELVE ATTITUDE-CONTROL thrusters (two branches of six) and
their on-times. They fire constantly -- 463 records on a quiet day -- and are
deliberately not read: attitude control is not orbit maintenance.

TRAP, and the reason this is spelled out. THR1B's ``qualflg`` is ``00001100`` on
known-clean data, NOT all-zero. The GNV1B parser drops any record whose flag is
not ``00000000``; applying that rule here would drop every record and the screen
would report CLEAN on an empty set. The flag is recorded for reporting and is
never used to drop a record.

QUALFLG BITS, from the Handbook's THR1B section (p. 55). Rightmost is bit 0, and
per-product bit meanings differ -- never carry another product's table across:

    0    on-time not calculated
    1    multiple unaccounted thrusts prior to current record
    2    '1' = branch 1 is active
    3    '1' = branch 2 is active
    4-5  not defined
    6    no OBC-to-receiver time mapping
    7    no clock correction available

So ``00001100`` is bits 2 and 3 -- both thruster branches active, i.e. normal
operating status. That is precisely why demanding an all-zero flag here would be
wrong.

BITS 0 AND 1 ARE THE GATE'S BLIND SPOT, which is why they are decoded and named
rather than left inside a raw 8-character string. Bit 0 means the on-time columns
were not populated, so a record reading zero is *unknown*, not quiet; bit 1 means
the accumulator moved with thrusts unaccounted for. Either undermines a column
the verdict is built on. The contract defines CLEAN as "the accumulator is flat
and both on-times are zero", so neither is folded into :attr:`Thr1bScreen.clean`
-- widening the gate is a contract amendment and the maintainer's call. Measured
across window 1 and the three frozen v0.7.2 windows (16,248 records,
2026-08-19): neither bit is ever set. Bit 6 occurs 3 times, always on D, and
affects a burn's reported TIME rather than its detection.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies to
the callers; this module only parses.
"""

from __future__ import annotations

import gzip
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_HEADER_END = "End of YAML header"

_N_COLUMNS = 47
_IDX_TIME_INTG = 0
_IDX_SAT = 3
_IDX_ON_TIME_1 = 30
_IDX_ON_TIME_2 = 31
_IDX_ACCUM = 44
_IDX_QUALFLG = 46

# Handbook p. 55: the two qualflg bits that invalidate a column the tier-1
# verdict is read from. Rightmost character of the flag is bit 0. Reported by
# name, deliberately NOT folded into `clean` -- see the module docstring.
_GATE_CRITICAL_BITS = {
    0: "bit 0, on-time not calculated -- a zero on-time is UNKNOWN, not quiet",
    1: "bit 1, multiple unaccounted thrusts prior to record",
}


@dataclass(frozen=True)
class Thr1bScreen:
    """One satellite's orbit-control thruster history across a window."""

    sat_id: str
    n_records: int
    n_files: int
    source_files: tuple[str, ...]
    accum_first_ms: int  # accum_dur_orb_ctrl at the first record
    accum_last_ms: int  # ... and at the last
    accum_values: tuple[int, ...]  # every DISTINCT value seen, in first-seen order
    on_time_max_1_ms: int
    on_time_max_2_ms: int
    n_firing_records: int  # records with either on-time non-zero
    first_firing_file: str | None  # where the first non-zero on-time appears
    first_firing_gps_s: float | None  # ... and its time_intg, for locating the burn
    qualflg_values: tuple[str, ...]  # distinct quality flags seen (reported only)

    @property
    def accum_moved_ms(self) -> int:
        """Total accumulator movement across the window; 0 on a clean window."""
        return self.accum_last_ms - self.accum_first_ms

    @property
    def clean(self) -> bool:
        """Both halves of the tier-1 gate: no on-time, and a flat accumulator."""
        return (
            self.n_firing_records == 0
            and len(self.accum_values) == 1
            and self.accum_moved_ms == 0
        )

    @property
    def verdict(self) -> str:
        return "CLEAN" if self.clean else "BURN"


def _read_member_lines(path: Path, sat_id: str) -> list[str]:
    """Text lines of the THR1B member for ``sat_id`` from .tgz / .gz / .txt.

    Mirrors ``mas1b._read_member_lines`` -- the daily tarball is the delivery
    unit, but this study extracts and gzips the three products it keeps, so the
    ``.gz`` branch is the one its own tree actually exercises.
    """
    suffixes = path.suffixes
    if ".tgz" in suffixes or suffixes[-2:] == [".tar", ".gz"] or path.suffix == ".tar":
        with tarfile.open(path, "r:*") as tar:
            member = next(
                (
                    m
                    for m in tar.getmembers()
                    if Path(m.name).name.startswith("THR1B_")
                    and f"_{sat_id}_" in Path(m.name).name
                    and m.name.endswith(".txt")
                ),
                None,
            )
            if member is None:
                raise ValueError(
                    f"{path.name}: no THR1B_*_{sat_id}_*.txt member in the tarball"
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"{path.name}: could not extract {member.name}")
            return extracted.read().decode("ascii", errors="replace").splitlines()
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="ascii", errors="replace") as fh:
            return fh.read().splitlines()
    return path.read_text(encoding="ascii", errors="replace").splitlines()


def _parse_one_file(
    path: Path, sat_id: str
) -> list[tuple[float, int, int, int, str]]:
    """One file's records as (gps_time, on_time_1, on_time_2, accum, qualflg)."""
    records: list[tuple[float, int, int, int, str]] = []
    in_header = True
    for line in _read_member_lines(path, sat_id):
        if in_header:
            if line.strip().endswith(_HEADER_END):
                in_header = False
            continue
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != _N_COLUMNS:
            raise ValueError(
                f"{path.name}: expected {_N_COLUMNS} columns, got {len(parts)}. "
                f"The THR1B record format changed -- re-inspect before trusting "
                f"a screen verdict from it: {line[:120]!r}"
            )
        if parts[_IDX_SAT] != sat_id:
            continue
        records.append(
            (
                float(parts[_IDX_TIME_INTG]),
                int(parts[_IDX_ON_TIME_1]),
                int(parts[_IDX_ON_TIME_2]),
                int(parts[_IDX_ACCUM]),
                parts[_IDX_QUALFLG],
            )
        )
    return records


def screen_thr1b(
    paths: Path | Sequence[Path], *, sat_id: str = "C"
) -> Thr1bScreen:
    """Run the tier-1 orbit-control screen over one or more daily THR1B files.

    ``paths`` are read in the order given, which the finders produce
    chronologically. A day with no records for ``sat_id`` raises rather than
    being skipped: a silently missing day is a hole in the screen, and the whole
    value of this gate is that it covers every day of the window.
    """
    file_list: list[Path] = [paths] if isinstance(paths, Path) else list(paths)
    if not file_list:
        raise ValueError("no THR1B files given")

    accum_values: list[int] = []
    qualflgs: list[str] = []
    n_records = 0
    n_firing = 0
    max_1 = 0
    max_2 = 0
    accum_first: int | None = None
    accum_last: int | None = None
    first_firing_file: str | None = None
    first_firing_gps: float | None = None

    for path in file_list:
        day = _parse_one_file(path, sat_id)
        if not day:
            raise ValueError(f"{path.name}: no THR1B records for satellite {sat_id!r}")
        for gps, on1, on2, accum, qualflg in day:
            n_records += 1
            if accum_first is None:
                accum_first = accum
            accum_last = accum
            if accum not in accum_values:
                accum_values.append(accum)
            if qualflg not in qualflgs:
                qualflgs.append(qualflg)
            max_1 = max(max_1, on1)
            max_2 = max(max_2, on2)
            if on1 != 0 or on2 != 0:
                n_firing += 1
                if first_firing_file is None:
                    first_firing_file = path.name
                    first_firing_gps = gps

    assert accum_first is not None and accum_last is not None  # non-empty by now
    return Thr1bScreen(
        sat_id=sat_id,
        n_records=n_records,
        n_files=len(file_list),
        source_files=tuple(p.name for p in file_list),
        accum_first_ms=accum_first,
        accum_last_ms=accum_last,
        accum_values=tuple(accum_values),
        on_time_max_1_ms=max_1,
        on_time_max_2_ms=max_2,
        n_firing_records=n_firing,
        first_firing_file=first_firing_file,
        first_firing_gps_s=first_firing_gps,
        qualflg_values=tuple(qualflgs),
    )


def format_screen(screen: Thr1bScreen, *, indent: str = "  ") -> list[str]:
    """The screen as ASCII report lines, carrying the values that justify the call.

    Every driver that consumes a window re-prints this in its results header, so
    a results file can be checked standalone without trusting another file
    (build plan Chunk 1, "it keeps every results file verifiable standalone").
    """
    lines = [
        f"{indent}[screen tier-1 THR1B] sat {screen.sat_id}: {screen.verdict}",
        f"{indent}  {screen.n_records} records over {screen.n_files} daily files; "
        f"qualflg seen {','.join(screen.qualflg_values)} (reported, never a drop rule)",
        f"{indent}  accum_dur_orb_ctrl: first {screen.accum_first_ms} ms, "
        f"last {screen.accum_last_ms} ms, moved {screen.accum_moved_ms} ms, "
        f"{len(screen.accum_values)} distinct value(s)",
        f"{indent}  max on_time_orb_ctrl_1/_2: "
        f"{screen.on_time_max_1_ms} / {screen.on_time_max_2_ms} ms over "
        f"{screen.n_firing_records} firing record(s)",
    ]
    # Silent unless a gate-critical bit is set (never, on any data held as of
    # 2026-08-19). A raw flag string in the line above is easy to skim past, and
    # skimming past one of these means accepting a CLEAN built on a column that
    # was never populated.
    suspect = sorted(
        {
            bit
            for flag in screen.qualflg_values
            for bit in _GATE_CRITICAL_BITS
            if len(flag) == 8 and flag[7 - bit] == "1"
        }
    )
    if suspect:
        lines.append(
            f"{indent}  QUALFLG GATE-CRITICAL BIT SET -- "
            + "; ".join(_GATE_CRITICAL_BITS[bit] for bit in suspect)
            + f". The {screen.verdict} above rests on columns these bits "
            f"invalidate; the contract's two-condition test cannot see them. "
            f"Escalate before using this window."
        )
    if not screen.clean:
        if screen.first_firing_gps_s is not None:
            where = (
                f"first firing in {screen.first_firing_file} at gps_time "
                f"{screen.first_firing_gps_s:.0f}"
            )
        else:
            # The accumulator moved but no record carries a non-zero on-time.
            # This is a REAL failure mode, not a contradiction: the burn fell
            # between two records or inside a data gap, so only the cumulative
            # column saw it. The two columns are read independently precisely so
            # that they can disagree -- the disagreement IS the signal, so it has
            # to print rather than trip over a None.
            where = (
                "no record carries a non-zero on-time -- the burn fell between "
                "records or inside a data gap"
            )
        lines.append(
            f"{indent}  BURN DETECTED -- {where}; accumulator values "
            f"{screen.accum_values[:6]}"
        )
        lines.append(
            f"{indent}  This window is retired or slid per the build plan's "
            f"failure rule; the retirement is recorded."
        )
    return lines
