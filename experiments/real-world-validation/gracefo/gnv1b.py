"""Minimal GNV1B parser for the real-world-validation study (reference-only).

Reads the GRACE-FO Level-1B GPS navigation product (``GNV1B_<date>_<C|D>_04.txt``):
1 Hz Earth-fixed position + velocity states from precise orbit determination, the
cm-level GPS-determined truth this study's drag leg measures against. The daily
files ship inside the PO.DAAC ``gracefo_1B_<date>_RL04.ascii.noLRI.tgz`` tarballs;
this parser extracts the one ``GNV1B`` member it needs in memory (raw truth files
are never committed -- the ``data/`` directory is gitignored).

Conversions at the boundary (build plan "Decisions already locked"):

- Time: the ``gps_time`` column is continuous seconds past the GPS epoch
  ``2000-01-01 12:00:00 GPS``. That instant is ``2000-01-01 12:00:19`` on the TAI
  clock (GPS runs a constant 19 s behind TAI, both leap-free), so an absolute epoch
  is ``Epoch.from_iso("2000-01-01T12:00:19", TimeScale.TAI).shifted_by(gps_time)`` --
  the locked +19 s route, no hand-rolled leap-second table.
- Frame: the ``coord_ref`` column must be ``E`` (Earth-Centered Earth-Fixed) -> an
  ITRF realization (``Frame.ITRF``); an ``I`` (inertial) file is rejected.
- Units: position and velocity are already SI (m, m/s) in the product -- no scaling.

Quality flags (``qualflg``, the 16th column, an 8-bit string) are honored: any
record whose flag is not all-zero is dropped and counted. The 1 Hz stream is
subsampled to a coarser grid (default 60 s) selected by ``gps_time`` modulo, so the
kept epochs land exactly on ``t0 + k * subsample_s`` (the exact-grid diff the driver
relies on) regardless of any dropped record. Consecutive daily files concatenate
into one continuous ephemeris; the seam continuity is verified.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies to
the callers; this module only parses.
"""

from __future__ import annotations

import gzip
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Iterator, Sequence

import numpy as np

from propygator import Epoch, TimeScale

# The GPS epoch (2000-01-01 12:00:00 GPS) expressed on the TAI clock: GPS = TAI - 19 s
# (both leap-free), so this base + gps_time seconds is the absolute epoch in TAI.
_GPS_EPOCH_TAI_ISO = "2000-01-01T12:00:19"

# GNV1B satellite id -> human name (from the product's value_meanings).
_SAT_NAMES = {"C": "GRACE-FO 1 (GRACE C)", "D": "GRACE-FO 2 (GRACE D)"}

_HEADER_END = "End of YAML header"


@dataclass(frozen=True)
class Gnv1bEphemeris:
    """One GRACE-FO satellite's GNV1B ephemeris in propygator types + SI."""

    sat_id: str  # "C" or "D"
    sat_name: str  # e.g. "GRACE-FO 1 (GRACE C)"
    frame_flag: str  # the coord_ref column, always "E" (Earth-fixed) here
    platform: str  # header global attribute, e.g. "GRACE C"
    product_version: str  # header global attribute, e.g. "04"
    subsample_s: float  # the kept grid spacing (seconds)
    n_raw_records: int  # 1 Hz records read for this satellite (pre-subsample)
    n_dropped_qc: int  # records dropped for a non-zero quality flag
    source_files: tuple[str, ...]  # file names parsed, in order
    epochs: tuple[Epoch, ...]  # (N,) TAI epochs on the subsample grid
    positions_m: np.ndarray  # (N, 3) float64, meters, ITRF
    velocities_ms: np.ndarray  # (N, 3) float64, m/s, ITRF (Earth-fixed)


def _epoch_from_gps_seconds(gps_time: float) -> Epoch:
    """Absolute epoch (TAI) for a GNV1B ``gps_time`` value (the locked +19 s route)."""
    return Epoch.from_iso(_GPS_EPOCH_TAI_ISO, TimeScale.TAI).shifted_by(float(gps_time))


def _open_member_text(path: Path, sat_id: str) -> IO[str]:
    """Open the GNV1B text stream for ``sat_id`` from a ``.tgz`` / ``.gz`` / ``.txt``.

    A PO.DAAC daily tarball bundles every L1B product; the one member wanted is
    ``GNV1B_<date>_<sat_id>_<ver>.txt``. Plain ``.txt`` (already extracted) and
    ``.gz`` are handled too so the driver works whether or not the maintainer
    unpacked the tarballs.
    """
    suffixes = path.suffixes
    if ".tgz" in suffixes or suffixes[-2:] == [".tar", ".gz"] or path.suffix == ".tar":
        tar = tarfile.open(path, "r:*")
        member = next(
            (
                m
                for m in tar.getmembers()
                if Path(m.name).name.startswith("GNV1B_")
                and f"_{sat_id}_" in Path(m.name).name
                and m.name.endswith(".txt")
            ),
            None,
        )
        if member is None:
            tar.close()
            raise ValueError(
                f"{path.name}: no GNV1B_*_{sat_id}_*.txt member in the tarball"
            )
        extracted = tar.extractfile(member)
        if extracted is None:
            tar.close()
            raise ValueError(f"{path.name}: could not extract {member.name}")
        # Wrap so closing the text stream also closes the tar handle.
        return _TarTextWrapper(extracted, tar)
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="ascii", errors="replace")
    return open(path, encoding="ascii", errors="replace")


class _TarTextWrapper:
    """Iterate a tar member as decoded ASCII text; close the tar on exit."""

    def __init__(self, raw: IO[bytes], tar: tarfile.TarFile) -> None:
        self._raw = raw
        self._tar = tar

    def __iter__(self) -> Iterator[str]:
        for raw_line in self._raw:
            yield raw_line.decode("ascii", errors="replace")

    def __enter__(self) -> "_TarTextWrapper":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._raw.close()
        self._tar.close()


def _parse_one_file(
    path: Path, sat_id: str
) -> tuple[list[float], list[list[float]], list[list[float]], dict[str, str], int]:
    """Parse one GNV1B file: kept (gps_time, pos, vel) plus header facts + QC drops.

    Returns records for ``sat_id`` only, quality-screened (non-zero ``qualflg``
    dropped). ``header`` carries a few global attributes for provenance; the QC
    drop count is returned so the caller can total it across files.
    """
    header: dict[str, str] = {}
    gps: list[float] = []
    pos: list[list[float]] = []
    vel: list[list[float]] = []
    dropped = 0
    in_header = True

    with _open_member_text(path, sat_id) as stream:
        for line in stream:
            line = line.rstrip("\r\n")
            if in_header:
                stripped = line.strip()
                if stripped.endswith(_HEADER_END):
                    in_header = False
                    continue
                # Light key: value capture for a handful of provenance attributes.
                for key in ("platform", "product_version", "time_coverage_start"):
                    if stripped.startswith(f"{key}:") and key not in header:
                        header[key] = stripped.split(":", 1)[1].strip()
                continue
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) < 16:
                raise ValueError(
                    f"{path.name}: expected >= 16 columns, got {len(parts)}: {line!r}"
                )
            if parts[1] != sat_id:
                continue
            frame_flag = parts[2]
            if frame_flag != "E":
                raise ValueError(
                    f"{path.name}: coord_ref {frame_flag!r} is not 'E' (Earth-fixed); "
                    "an inertial GNV1B file is not supported by this study"
                )
            if parts[15] != "00000000":  # honor the quality flag
                dropped += 1
                continue
            gps.append(float(parts[0]))
            pos.append([float(parts[3]), float(parts[4]), float(parts[5])])
            vel.append([float(parts[9]), float(parts[10]), float(parts[11])])

    return gps, pos, vel, header, dropped


def parse_gnv1b(
    paths: Path | Sequence[Path],
    *,
    sat_id: str = "C",
    subsample_s: float = 60.0,
) -> Gnv1bEphemeris:
    """Parse one or more consecutive daily GNV1B files into a :class:`Gnv1bEphemeris`.

    ``sat_id`` selects the satellite (``"C"`` = GRACE-FO 1, NORAD 43476; ``"D"`` =
    GRACE-FO 2). Multiple ``paths`` are concatenated in the order given and must be
    time-contiguous (verified at the seams). The 1 Hz stream is quality-screened and
    then subsampled to ``subsample_s`` by selecting records whose ``gps_time`` offset
    from the first kept record is an exact multiple of ``subsample_s`` -- so the kept
    epochs land on ``t0 + k * subsample_s`` regardless of any dropped record.
    """
    file_list: list[Path] = [paths] if isinstance(paths, Path) else list(paths)
    if not file_list:
        raise ValueError("no GNV1B files given")
    if sat_id not in _SAT_NAMES:
        raise ValueError(f"sat_id must be one of {sorted(_SAT_NAMES)}, got {sat_id!r}")

    all_gps: list[float] = []
    all_pos: list[list[float]] = []
    all_vel: list[list[float]] = []
    header: dict[str, str] = {}
    n_dropped = 0
    for path in file_list:
        gps, pos, vel, hdr, dropped = _parse_one_file(path, sat_id)
        if not gps:
            raise ValueError(f"{path.name}: no records for satellite {sat_id!r}")
        if all_gps and gps[0] <= all_gps[-1]:
            raise ValueError(
                f"{path.name}: gps_time {gps[0]:.0f} not after the previous file's "
                f"last {all_gps[-1]:.0f} -- files out of order or overlapping"
            )
        all_gps.extend(gps)
        all_pos.extend(pos)
        all_vel.extend(vel)
        n_dropped += dropped
        for k, v in hdr.items():
            header.setdefault(k, v)

    gps_arr = np.asarray(all_gps, dtype=np.float64)
    if not np.all(np.diff(gps_arr) > 0.0):
        raise ValueError("gps_time not strictly increasing across the concatenation")
    # A raw 1 Hz stream steps by 1 s; a gap > 1 s means a QC drop or missing data.
    gaps = np.diff(gps_arr)
    n_gaps = int(np.sum(gaps > 1.5))
    max_gap = float(np.max(gaps)) if gaps.size else 0.0

    n_raw = gps_arr.size
    # Subsample on the gps_time grid so kept epochs are exactly t0 + k*subsample_s.
    offsets = gps_arr - gps_arr[0]
    keep = np.isclose(np.remainder(offsets, subsample_s), 0.0) | np.isclose(
        np.remainder(offsets, subsample_s), subsample_s
    )
    idx = np.flatnonzero(keep)

    epochs = tuple(_epoch_from_gps_seconds(gps_arr[i]) for i in idx)
    positions_m = np.asarray(all_pos, dtype=np.float64)[idx]
    velocities_ms = np.asarray(all_vel, dtype=np.float64)[idx]

    eph = Gnv1bEphemeris(
        sat_id=sat_id,
        sat_name=_SAT_NAMES[sat_id],
        frame_flag="E",
        platform=header.get("platform", "?"),
        product_version=header.get("product_version", "?"),
        subsample_s=subsample_s,
        n_raw_records=n_raw,
        n_dropped_qc=n_dropped,
        source_files=tuple(p.name for p in file_list),
        epochs=epochs,
        positions_m=positions_m,
        velocities_ms=velocities_ms,
    )
    # Attach the seam-gap diagnostics as attributes read by the driver's report
    # (kept off the frozen field set to keep the dataclass a clean value type).
    object.__setattr__(eph, "_n_gaps", n_gaps)
    object.__setattr__(eph, "_max_gap_s", max_gap)
    return eph


def find_window_files(window_dir: Path, sat_id: str = "C") -> list[Path]:
    """Sorted list of the daily GNV1B source files (tarballs or extracted) in a window.

    Prefers the PO.DAAC ``.tgz`` daily tarballs; falls back to already-extracted
    ``GNV1B_*_<sat_id>_*.txt`` files if the maintainer unpacked them. Sorted by name
    so the ISO date in each file name orders them chronologically.
    """
    tarballs = sorted(window_dir.glob("gracefo_1B_*_RL04.ascii*.tgz"))
    if tarballs:
        return tarballs
    return sorted(window_dir.glob(f"GNV1B_*_{sat_id}_*.txt"))
