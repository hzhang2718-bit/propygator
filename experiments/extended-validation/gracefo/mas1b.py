"""Minimal MAS1B parser for the extended-validation study (reference-only).

Reads the GRACE-FO Level-1B spacecraft/tank mass product
(``MAS1B_<date>_<C|D>_04.txt``, ~8 kB, 24 records/day) out of the same PO.DAAC
daily tarballs the GNV1B truth comes from. It is already on disk for every
window this study uses, so the per-window spacecraft mass costs zero downloads.

WHY THIS EXISTS. The v0.7.2 study assumed a round 600.0 kg launch mass. T
scales exactly as 1/m (docs/extended-validation.md sec 2.2), so the mass is
part of the measurement. MAS1B turns it from an assumption into a reading, and
turns the third term of A1's mandatory three-term label -- "any true A/m
difference between the twins" -- from a propellant-load bound of ~5.5% into a
measured ~0.1%.

FORMAT (L1 Data Product User Handbook sec 4.2.17). Whitespace-separated after
the YAML header::

    time_intg time_frac time_ref GRACEFO_id qualflg prod_flag <values...>

``prod_flag`` is an 8-character string read **from position 0 at the right to
position 7 at the left**, selecting which optional values are present, in
ascending field order:

    0 mass_thr        1 mass_thr_err    2 mass_tnk       3 mass_tnk_err
    4 gas_mass_thr1   5 gas_mass_thr2   6 gas_mass_tnk1  7 gas_mass_tnk2

Every file this study touches carries ``11000000`` -- bits 6 and 7 -- i.e. the
two tanks' gas masses from tank observations. The handbook marks ``mass_tnk``
(total spacecraft mass) "Not available", which is why total mass is
reconstructed as dry + gas rather than read directly.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies
to the callers; this module only parses.
"""

from __future__ import annotations

import gzip
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

_HEADER_END = "End of YAML header"

# prod_flag bit index -> field name, in ascending index order.
_FIELDS = (
    "mass_thr",
    "mass_thr_err",
    "mass_tnk",
    "mass_tnk_err",
    "gas_mass_thr1",
    "gas_mass_thr2",
    "gas_mass_tnk1",
    "gas_mass_tnk2",
)
# The only flag this study expects: tank-observed gas mass for both tanks.
_EXPECTED_BITS = frozenset({6, 7})


@dataclass(frozen=True)
class Mas1bMass:
    """One satellite's tank-gas mass over a window."""

    sat_id: str
    n_records: int
    source_files: tuple[str, ...]
    gas_first_kg: float  # tank1 + tank2 at the first record
    gas_last_kg: float  # tank1 + tank2 at the last record
    gas_mean_kg: float  # mean over all records -- the window's assumed value


def _read_member_lines(path: Path, sat_id: str) -> list[str]:
    """Text lines of the MAS1B member for ``sat_id`` from .tgz / .gz / .txt."""
    suffixes = path.suffixes
    if ".tgz" in suffixes or suffixes[-2:] == [".tar", ".gz"] or path.suffix == ".tar":
        with tarfile.open(path, "r:*") as tar:
            member = next(
                (
                    m
                    for m in tar.getmembers()
                    if Path(m.name).name.startswith("MAS1B_")
                    and f"_{sat_id}_" in Path(m.name).name
                    and m.name.endswith(".txt")
                ),
                None,
            )
            if member is None:
                raise ValueError(
                    f"{path.name}: no MAS1B_*_{sat_id}_*.txt member in the tarball"
                )
            extracted = tar.extractfile(member)
            if extracted is None:
                raise ValueError(f"{path.name}: could not extract {member.name}")
            return extracted.read().decode("ascii", errors="replace").splitlines()
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="ascii", errors="replace") as fh:
            return fh.read().splitlines()
    return path.read_text(encoding="ascii", errors="replace").splitlines()


def _parse_one_file(path: Path, sat_id: str) -> list[float]:
    """Total tank gas mass (tank1 + tank2) per record, for ``sat_id``."""
    totals: list[float] = []
    in_header = True
    for line in _read_member_lines(path, sat_id):
        if in_header:
            if line.strip().endswith(_HEADER_END):
                in_header = False
            continue
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) < 6:
            raise ValueError(
                f"{path.name}: expected >= 6 columns, got {len(parts)}: {line!r}"
            )
        if parts[3] != sat_id:
            continue
        prod_flag = parts[5]
        if len(prod_flag) != 8:
            raise ValueError(f"{path.name}: prod_flag {prod_flag!r} is not 8 chars")
        # Position 0 is the RIGHTMOST character (handbook sec 4.2.17).
        present = {i for i in range(8) if prod_flag[7 - i] == "1"}
        if present != _EXPECTED_BITS:
            named = sorted(_FIELDS[i] for i in present)
            raise ValueError(
                f"{path.name}: prod_flag {prod_flag!r} selects {named}; this parser "
                f"expects exactly gas_mass_tnk1 + gas_mass_tnk2 -- inspect the file "
                f"before trusting a mass from it"
            )
        values = parts[6:]
        if len(values) != len(present):
            raise ValueError(
                f"{path.name}: prod_flag {prod_flag!r} implies {len(present)} values, "
                f"found {len(values)}: {line!r}"
            )
        # Values appear in ascending field order: tnk1 then tnk2.
        totals.append(float(values[0]) + float(values[1]))
    return totals


def parse_mas1b(paths: Path | Sequence[Path], *, sat_id: str = "C") -> Mas1bMass:
    """Tank gas mass across one or more consecutive daily MAS1B files."""
    file_list: list[Path] = [paths] if isinstance(paths, Path) else list(paths)
    if not file_list:
        raise ValueError("no MAS1B files given")

    totals: list[float] = []
    for path in file_list:
        day = _parse_one_file(path, sat_id)
        if not day:
            raise ValueError(f"{path.name}: no MAS1B records for satellite {sat_id!r}")
        totals.extend(day)

    return Mas1bMass(
        sat_id=sat_id,
        n_records=len(totals),
        source_files=tuple(p.name for p in file_list),
        gas_first_kg=totals[0],
        gas_last_kg=totals[-1],
        gas_mean_kg=sum(totals) / len(totals),
    )
