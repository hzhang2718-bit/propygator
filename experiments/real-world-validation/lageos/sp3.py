"""Minimal generic SP3 parser for the real-world-validation study (reference-only).

Reads the subset of SP3-c that the study's truth products use (the line-1 layout
is SP3-d compatible): the header version / pos-vel flag / epoch count /
coordinate-system fields, the ``##`` epoch-interval field, the first ``%c``
line's **time-system field**, epoch lines, and P/V records for one satellite.

Conversions at the boundary (build plan "Decisions already locked"):

- Time: ``UTC``-tagged files go into :class:`Epoch` directly; ``GPS`` converts
  leap-second-free as GPS + 19 s = TAI -> ``Epoch.from_iso(..., TimeScale.TAI)``;
  ``TAI`` goes in directly on the TAI route. Anything else raises. Epochs inside
  an inserted leap second (seconds field 60) are not supported.
- Units: positions km -> m, velocities dm/s -> m/s (SI at the boundary).

When a file carries no V-records, velocity comes from
:func:`lagrange_velocities` (central Lagrange differentiation of neighboring
positions); when V-records exist the driver prints both routes and compares.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output rule applies to
the callers; this module only parses.
"""

from __future__ import annotations

import gzip
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import IO

import numpy as np

from propygator import Epoch, TimeScale

# Wall-clock offset (seconds) added to a tagged epoch to obtain the TAI
# wall-clock. GPS runs a constant 19 s behind TAI (both are leap-free scales).
_TO_TAI_OFFSET_S = {"GPS": 19, "TAI": 0}

_EpochFields = tuple[int, int, int, int, int, float]


@dataclass(frozen=True)
class Sp3Ephemeris:
    """One satellite's ephemeris from an SP3 file, in propygator types + SI."""

    sat_id: str
    version: str  # SP3 version character ('c', 'd', ...)
    time_system: str  # the header %c field ("UTC", "GPS", ...)
    coordinate_system: str  # e.g. "SLR08" (an ITRF realization label)
    epoch_interval_s: float
    n_epochs_header: int  # the count the header claims (cross-check vs len)
    epochs: tuple[Epoch, ...]
    epoch_fields: tuple[_EpochFields, ...]  # raw calendar fields, for round-trip checks
    positions_m: np.ndarray  # (N, 3) float64, meters
    velocities_ms: np.ndarray | None  # (N, 3) m/s from V-records, else None


def _open_text(path: Path) -> IO[str]:
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="ascii", errors="replace")
    return open(path, encoding="ascii", errors="replace")


def _epoch_from_fields(fields: _EpochFields, time_system: str) -> Epoch:
    year, month, day, hour, minute, second = fields
    whole = int(math.floor(second))
    frac = second - whole
    # timedelta addition handles any minute/hour carry; a genuine leap second
    # (second == 60 in a UTC file) would be silently shifted, hence unsupported.
    naive = datetime(year, month, day, hour, minute) + timedelta(seconds=whole)
    if time_system == "UTC":
        epoch = Epoch.from_iso(naive.strftime("%Y-%m-%dT%H:%M:%S"), TimeScale.UTC)
    elif time_system in _TO_TAI_OFFSET_S:
        tai = naive + timedelta(seconds=_TO_TAI_OFFSET_S[time_system])
        epoch = Epoch.from_iso(tai.strftime("%Y-%m-%dT%H:%M:%S"), TimeScale.TAI)
    else:
        raise ValueError(
            f"unsupported SP3 time system {time_system!r} "
            f"(supported: UTC, {', '.join(sorted(_TO_TAI_OFFSET_S))})"
        )
    return epoch.shifted_by(frac) if frac != 0.0 else epoch


def parse_sp3(path: Path, sat_id: str | None = None) -> Sp3Ephemeris:
    """Parse ``path`` (plain or ``.gz``) into an :class:`Sp3Ephemeris`.

    ``sat_id`` selects the satellite (3-character SP3 id, e.g. ``"L52"``); when
    ``None`` the file must contain exactly one satellite. A bad-position
    sentinel (all-zero XYZ) raises rather than masking — the study's truth
    weeks are complete, so a hole means the wrong product.
    """
    version: str | None = None
    has_velocity = False
    n_epochs_header = 0
    coordinate_system = ""
    time_system: str | None = None
    interval: float | None = None

    epoch_fields: list[_EpochFields] = []
    pos_rows: list[list[float]] = []
    vel_rows: list[list[float]] = []
    target = sat_id

    with _open_text(path) as f:
        for line in f:
            line = line.rstrip("\r\n")
            if line.startswith("EOF"):
                break
            if line.startswith("##"):
                interval = float(line.split()[3])
            elif line.startswith("#") and version is None:
                version = line[1]
                has_velocity = line[2] == "V"
                n_epochs_header = int(line[32:39])
                coordinate_system = line[46:51].strip()
            elif line.startswith("%c") and time_system is None:
                time_system = line[9:12].strip()
            elif line.startswith("*"):
                p = line.split()
                epoch_fields.append(
                    (int(p[1]), int(p[2]), int(p[3]), int(p[4]), int(p[5]), float(p[6]))
                )
            elif line.startswith(("P", "V")) and len(line) >= 46:
                rec_id = line[1:4]
                if target is None:
                    target = rec_id
                elif rec_id != target:
                    if sat_id is None:
                        raise ValueError(
                            f"multi-satellite SP3 file ({target!r} and {rec_id!r} "
                            "seen); pass sat_id to select one"
                        )
                    continue
                xyz = [float(line[4:18]), float(line[18:32]), float(line[32:46])]
                if all(v == 0.0 for v in xyz):
                    raise ValueError(
                        f"bad-position sentinel (all-zero XYZ) at record "
                        f"{len(pos_rows)} of {path.name}"
                    )
                (pos_rows if line[0] == "P" else vel_rows).append(xyz)

    if version is None or time_system is None or interval is None:
        raise ValueError(f"{path.name}: missing SP3 header line(s)")
    if target is None or not pos_rows:
        raise ValueError(f"{path.name}: no P records found")
    if len(pos_rows) != len(epoch_fields):
        raise ValueError(
            f"{path.name}: {len(epoch_fields)} epochs but {len(pos_rows)} P records"
        )
    if has_velocity and len(vel_rows) != len(epoch_fields):
        raise ValueError(
            f"{path.name}: {len(epoch_fields)} epochs but {len(vel_rows)} V records"
        )

    epochs = tuple(_epoch_from_fields(fld, time_system) for fld in epoch_fields)
    positions_m = np.asarray(pos_rows, dtype=np.float64) * 1000.0  # km -> m
    velocities_ms = (
        np.asarray(vel_rows, dtype=np.float64) * 0.1 if has_velocity else None
    )  # dm/s -> m/s

    return Sp3Ephemeris(
        sat_id=target,
        version=version,
        time_system=time_system,
        coordinate_system=coordinate_system,
        epoch_interval_s=interval,
        n_epochs_header=n_epochs_header,
        epochs=epochs,
        epoch_fields=tuple(epoch_fields),
        positions_m=positions_m,
        velocities_ms=velocities_ms,
    )


# --- velocity from positions (for files without V-records; cross-check here) --


def _lagrange_derivative_weights(offsets: np.ndarray, x0: float) -> np.ndarray:
    """Weights w s.t. f'(x0) ~= w @ f(offsets) for the Lagrange interpolant."""
    n = offsets.size
    w = np.zeros(n)
    for j in range(n):
        acc = 0.0
        for m in range(n):
            if m == j:
                continue
            prod = 1.0 / (offsets[j] - offsets[m])
            for k in range(n):
                if k == j or k == m:
                    continue
                prod *= (x0 - offsets[k]) / (offsets[j] - offsets[k])
            acc += prod
        w[j] = acc
    return w


def lagrange_velocities(
    positions_m: np.ndarray, step_s: float, n_nodes: int = 7
) -> np.ndarray:
    """Velocity at every sample by differentiating a sliding Lagrange interpolant.

    Central ``n_nodes``-point stencil in the interior, one-sided at the edges
    (same polynomial order, shifted window). For LAGEOS-class dynamics at a
    120 s grid the 7-point truncation error is ~1e-6 m/s — far below the
    cm-level truth noise, i.e. sub-mm/s as the build plan expects.
    """
    n = positions_m.shape[0]
    if n < n_nodes:
        raise ValueError(f"need at least {n_nodes} samples, got {n}")
    half = (n_nodes - 1) // 2
    vel = np.empty_like(positions_m)
    weights: dict[int, np.ndarray] = {}
    for i in range(n):
        start = min(max(i - half, 0), n - n_nodes)
        p = i - start  # position of the evaluation point inside the window
        if p not in weights:
            offsets = np.arange(n_nodes, dtype=np.float64) - p
            weights[p] = _lagrange_derivative_weights(offsets, 0.0)
        vel[i] = weights[p] @ positions_m[start : start + n_nodes]
    return vel / step_s
