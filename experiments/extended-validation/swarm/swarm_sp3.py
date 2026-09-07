"""Swarm SP3 truth reader for the extended-validation study (reference-only).

THE FORMAT WAS RESOLVED AGAINST A DELIVERED FILE, NOT DOCUMENTATION (contract,
"Swarm truth data is the one part of this study with no existing path", step 1).
What ESA's POD/RN module actually serves for these windows, read off
``SW_OPER_SP3ACOM_2__20191222T235942_20191223T235942_0201.ZIP``:

- **SP3-d**, one satellite per file, ``V`` records present, 8640 epochs per day
  on a **10 s** grid, header epoch count matching the body.
- **Time system GPS** (the ``%c`` field). That is the trap the contract names:
  read as UTC these files sit ~18 s off, which is ~137 km of pure along-track
  error and would read as propygator failing on Swarm. The conversion is the
  locked leap-free route, GPS + 19 s = TAI (``gracefo/gnv1b.py:44-46``), never a
  hand-rolled leap-second table -- and the frozen SP3 parser already implements
  exactly that, which is why it is reused rather than re-written.
- **Coordinate system IGS14**, an ITRF realization -> ``Frame.ITRF``.
- **The V-records are EARTH-FIXED.** Measured, not assumed: differentiating the
  positions reproduces them to 1e-4 m/s, against a 20-500 m/s gap between the
  Earth-fixed and inertial conventions. So velocities go straight in exactly as
  GNV1B's do, and no Lagrange differentiation is needed.
- Swarm A is SP3 id ``L47``, Swarm B ``L48``. **They are not a twin pair** --
  measured here at ~435 km and ~502 km -- so an A-vs-B difference is an altitude
  difference before it is a body difference.

**THE FILES ARE CUT ON GPS-DAY BOUNDARIES, AND NAMED IN UTC.** A file tagged
``20191222T235942_20191223T235942`` holds GPS day 2019-12-23: in 2019 GPS runs
18 s ahead of UTC, so ``23:59:42 UTC`` *is* ``00:00:00 GPS`` of the next day.
Every file therefore starts exactly 86400 s after the previous one (verified at
every seam), and the file for a given window day is found by its **second**
timestamp, never its first. Window truth is 8 days, which is what a 7-day arc
needs with its ``t0 + 7 d`` endpoint sample (contract amendment 2026-08-21).

This module is a THIN WRAPPER over the frozen ``lageos/sp3.py``: it opens the
``.ZIP`` members that parser cannot (it handles ``.gz`` and plain text only),
concatenates the daily files, checks the seams and subsamples to the study's
60 s grid. The frozen module is imported, never edited.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies to
the callers; this module only parses.
"""

from __future__ import annotations

import re
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Sequence

import numpy as np

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
_FROZEN = _STUDY.parent / "real-world-validation"
for _p in (str(_FROZEN / "lageos"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from sp3 import parse_sp3  # noqa: E402

from propygator import Epoch, TimeScale  # noqa: E402

SAT_IDS = ("A", "B")
# The SP3 satellite ids, READ OFF THE DELIVERED FILES and asserted at parse time
# rather than trusted -- a mislabelled download is otherwise invisible.
SP3_IDS = {"A": "L47", "B": "L48"}
SAT_NAMES = {"A": "Swarm A", "B": "Swarm B"}

# GPS runs a constant 19 s behind TAI, both leap-free (the locked route; see
# gracefo/gnv1b.py:44-46). Used ONLY to state the expected GPS-midnight t0 for
# the file-set check; the epoch conversion itself is the frozen parser's.
GPS_TO_TAI_S = 19.0

NATIVE_INTERVAL_S = 10.0  # the delivered grid; asserted per file
_NAME_RE = re.compile(
    r"^SW_OPER_SP3(?P<sat>[AB])COM_2__"
    r"(?P<start>\d{8}T\d{6})_(?P<end>\d{8}T\d{6})_(?P<ver>\d{4})\.ZIP$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SwarmEphemeris:
    """One Swarm satellite's truth ephemeris -- the GNV1B duck type.

    Field names match ``Gnv1bEphemeris`` wherever the drivers read them, so the
    shared Part 2 machinery treats both legs identically.
    """

    sat_id: str  # "A" or "B"
    sat_name: str
    sp3_id: str  # "L47" / "L48"
    time_system: str  # "GPS" -- printed so the resolution is in the evidence
    coordinate_system: str  # "IGS14", an ITRF realization
    version: str  # SP3 version character
    native_interval_s: float
    subsample_s: float
    n_raw_records: int
    source_files: tuple[str, ...]
    epochs: tuple[Epoch, ...]
    positions_m: np.ndarray  # (N, 3) ITRF
    velocities_ms: np.ndarray  # (N, 3) ITRF, Earth-fixed (measured, see above)


def _gps_day(path: Path) -> date:
    """The GPS day a delivered file holds -- from its SECOND timestamp."""
    m = _NAME_RE.match(path.name)
    if m is None:
        raise SystemExit(
            f"{path.name}: not a recognized Swarm SP3 delivery name "
            f"(expected SW_OPER_SP3<A|B>COM_2__<start>_<end>_<ver>.ZIP)"
        )
    return datetime.strptime(m.group("end"), "%Y%m%dT%H%M%S").date()


def find_swarm_files(
    window_dir: Path, sat_id: str, days: Sequence[date]
) -> list[Path]:
    """The delivered files holding exactly ``days``, in order.

    Keyed on each file's GPS day rather than on sort order, so a download that
    is short, duplicated, or left over from a different window fails here by
    name instead of silently shifting every epoch downstream.
    """
    if sat_id not in SAT_IDS:
        raise ValueError(f"sat_id must be one of {SAT_IDS}, got {sat_id!r}")
    found: dict[date, Path] = {}
    for path in sorted(window_dir.glob(f"SW_OPER_SP3{sat_id}COM_2__*.ZIP")):
        day = _gps_day(path)
        if day in found:
            raise SystemExit(
                f"{window_dir.name}: two files claim GPS day {day} for Swarm "
                f"{sat_id} ({found[day].name}, {path.name})"
            )
        found[day] = path
    missing = [d for d in days if d not in found]
    if missing:
        raise SystemExit(
            f"{window_dir.name}: Swarm {sat_id} is missing {len(missing)} of "
            f"{len(days)} day(s), first {missing[0]}. Files are named in UTC for "
            f"the day BEFORE the GPS day they hold, so the file wanted for "
            f"{missing[0]} ends with that date, not starts with it. Present: "
            f"{len(found)} day(s) {min(found) if found else '-'}..{max(found) if found else '-'}"
        )
    return [found[d] for d in days]


def _extract(path: Path, out_dir: Path) -> Path:
    with zipfile.ZipFile(path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith(".sp3")]
        if len(members) != 1:
            raise SystemExit(
                f"{path.name}: expected exactly one .sp3 member, found "
                f"{len(members)}: {members}"
            )
        return Path(archive.extract(members[0], out_dir))


def parse_swarm_sp3(
    paths: Sequence[Path], *, sat_id: str, subsample_s: float = 60.0
) -> SwarmEphemeris:
    """Parse consecutive daily Swarm SP3 deliveries into one ephemeris.

    Delegates every record to the frozen ``parse_sp3`` -- including the GPS ->
    TAI conversion and the km -> m / (dm/s) -> m/s unit scaling -- and adds only
    what that parser does not do: ZIP extraction, day concatenation, seam
    checking and subsampling.
    """
    if not paths:
        raise ValueError("no Swarm SP3 files given")
    stride_f = subsample_s / NATIVE_INTERVAL_S
    if abs(stride_f - round(stride_f)) > 1e-9:
        raise ValueError(
            f"subsample_s {subsample_s} is not a whole multiple of the delivered "
            f"{NATIVE_INTERVAL_S} s grid"
        )
    stride = int(round(stride_f))

    epochs: list[Epoch] = []
    pos: list[np.ndarray] = []
    vel: list[np.ndarray] = []
    meta: dict[str, str] = {}
    prev_last: Epoch | None = None

    with tempfile.TemporaryDirectory(prefix="swarm-sp3-") as tmp:
        tmp_dir = Path(tmp)
        for path in paths:
            eph = parse_sp3(_extract(path, tmp_dir))
            if eph.sat_id != SP3_IDS[sat_id]:
                raise SystemExit(
                    f"{path.name}: holds SP3 satellite {eph.sat_id!r}, expected "
                    f"{SP3_IDS[sat_id]!r} for Swarm {sat_id}"
                )
            if eph.time_system != "GPS":
                raise SystemExit(
                    f"{path.name}: time system {eph.time_system!r}, expected 'GPS'. "
                    f"The whole ephemeris would sit shifted with every magnitude, "
                    f"seam and grid check still clean -- resolve before reading on."
                )
            if abs(eph.epoch_interval_s - NATIVE_INTERVAL_S) > 1e-9:
                raise SystemExit(
                    f"{path.name}: {eph.epoch_interval_s} s grid, expected "
                    f"{NATIVE_INTERVAL_S} s"
                )
            if eph.velocities_ms is None:
                raise SystemExit(f"{path.name}: no V records")
            n = len(eph.epochs)
            span = eph.epochs[-1].seconds_since(eph.epochs[0])
            if abs(span - (n - 1) * NATIVE_INTERVAL_S) > 1e-6:
                raise SystemExit(
                    f"{path.name}: {n} epochs spanning {span:.1f} s, not the "
                    f"{(n - 1) * NATIVE_INTERVAL_S:.1f} s a uniform grid gives"
                )
            if prev_last is not None:
                gap = eph.epochs[0].seconds_since(prev_last)
                if abs(gap - NATIVE_INTERVAL_S) > 1e-6:
                    raise SystemExit(
                        f"{path.name}: seam gap {gap:.3f} s from the previous "
                        f"file, expected {NATIVE_INTERVAL_S} s -- the files are "
                        f"not consecutive GPS days"
                    )
            prev_last = eph.epochs[-1]
            epochs.extend(eph.epochs)
            pos.append(eph.positions_m)
            vel.append(eph.velocities_ms)
            meta.setdefault("version", eph.version)
            meta.setdefault("time_system", eph.time_system)
            meta.setdefault("coordinate_system", eph.coordinate_system)

    n_raw = len(epochs)
    idx = np.arange(0, n_raw, stride)
    return SwarmEphemeris(
        sat_id=sat_id,
        sat_name=SAT_NAMES[sat_id],
        sp3_id=SP3_IDS[sat_id],
        time_system=meta["time_system"],
        coordinate_system=meta["coordinate_system"],
        version=meta["version"],
        native_interval_s=NATIVE_INTERVAL_S,
        subsample_s=subsample_s,
        n_raw_records=n_raw,
        source_files=tuple(p.name for p in paths),
        epochs=tuple(epochs[i] for i in idx),
        positions_m=np.concatenate(pos, axis=0)[idx],
        velocities_ms=np.concatenate(vel, axis=0)[idx],
    )


def expected_t0(day: date) -> Epoch:
    """GPS midnight on ``day``, on the TAI clock -- the expected first epoch."""
    return Epoch.from_iso(f"{day.isoformat()}T00:00:00", TimeScale.TAI).shifted_by(
        GPS_TO_TAI_S
    )
