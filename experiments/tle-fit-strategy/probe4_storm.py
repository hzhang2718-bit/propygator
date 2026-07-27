"""Probe 4: the auto-rule's behavior under the Gannon storm (storm_2024).

Part of the **TLE fit strategy** experiment (2026-07-19; see README.md).
Measured outcome, exactly as feared: the 2 d free fit's trust ratio r reads
SMALL (0.011 — B* very observable under storm drag) while the forecast still
degrades 3.4x vs the freshest 1 d fit; the 3 d fit reads r = 0.005 (the
smallest of the whole experiment) with the WORST forecast. r certifies
in-arc observability, not forward stationarity. The cross-span consistency
signal s = |B*(3d)-B*(2d)|/B*(2d) = 0.323 (vs 0.014 active, 1.65 quiet) is
the internal signal that catches it — the playbook's s-gate.

4 days on disk (May 10-13, 2024; onset May 10 ~17 UT): anchor = day-4 start
(May 13, recovery), fit arcs inside days 1-3, forecast = day 4 (1 day). No
storm catalog TLE in the study -> catalog-free rows only.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data + the study's GNV1B
data); cwd-independent. Stdout is ASCII-only (captured under cp1252):

    cd experiments/tle-fit-strategy
    conda run -n propygator python probe4_storm.py > results_probe4_storm.txt
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np

_EXP = Path(__file__).resolve().parents[1] / "real-world-validation"
sys.path.insert(0, str(_EXP / "gracefo"))
sys.path.insert(0, str(_EXP))

from common import rms as _rms  # noqa: E402
from gnv1b import find_window_files, parse_gnv1b  # noqa: E402
from gracefo_common import (  # noqa: E402
    DATA_ROOT,
    GRACEFO_SAT_ID,
    NORAD_ID,
    SAT_NAME,
    SUBSAMPLE_S,
)

from propygator import TLE, Frame, Trajectory, fit_tle_detailed, propagate_tle  # noqa: E402

WINDOW = "storm_2024"
LOAD_DAYS = 4
ANCHOR_DAY = 4  # fit arcs end at the day-4 start; forecast = day 4
FC_DAYS = 1


def _parse_bstar(line1: str) -> float:
    field = line1[53:61]
    sign = -1.0 if field[0] == "-" else 1.0
    return sign * (int(field[1:6]) / 1.0e5) * 10.0 ** int(field[6:8])


def main() -> None:
    t_wall = time.time()
    files = find_window_files(DATA_ROOT / WINDOW, GRACEFO_SAT_ID)
    eph = parse_gnv1b(
        files[:LOAD_DAYS], sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S
    )
    n_per_day = int(86400.0 / SUBSAMPLE_S)
    k_end = (ANCHOR_DAY - 1) * n_per_day
    t_end = eph.epochs[k_end]
    truth_fc = eph.positions_m[k_end : k_end + FC_DAYS * n_per_day]

    print(f"Probe 4: storm window -- {WINDOW} (Gannon, May 2024)")
    print("=" * 78)
    print(f"  anchor = day-{ANCHOR_DAY} start {t_end.to_iso()} {t_end.scale.value} "
          f"(recovery); forecast = {FC_DAYS} d; catalog-free rows only")

    def forecast(tle: TLE) -> list[float]:
        traj = propagate_tle(
            tle, FC_DAYS * 86400.0, output_step=SUBSAMPLE_S, start=t_end
        )
        pos = traj.to_frame(Frame.ITRF).positions
        d = np.linalg.norm(pos[: len(truth_fc)] - truth_fc, axis=1)
        return [_rms(d[j * n_per_day : (j + 1) * n_per_day]) for j in range(FC_DAYS)]

    def fit(span_d: int, guess: TLE | None, fit_bstar: bool):
        k0 = k_end - span_d * n_per_day
        ref = Trajectory.from_arrays(
            list(eph.epochs[k0 : k_end + 1]),
            eph.positions_m[k0 : k_end + 1],
            eph.velocities_ms[k0 : k_end + 1],
            Frame.ITRF,
        )
        return fit_tle_detailed(
            ref,
            fitting_span=span_d * 86400.0,
            initial_guess=guess,
            fit_bstar=fit_bstar,
            norad_id=NORAD_ID,
            name=SAT_NAME,
            progress=False,
        )

    print()
    print(f"  {'config':<17}{'in-arc':>8}{'+1 d':>9}{'B*':>11}{'r':>8}")

    f2 = fit(2, None, True)
    b2 = _parse_bstar(f2.tle.line1)
    i = f2.parameter_names.index("BSTAR")
    r2 = (f2.sigma0 * float(f2.sigmas[i])) / abs(b2) if b2 != 0.0 else float("inf")
    print(f"  {'fitted 2d':<17}{f2.rms_m:>8.1f}{forecast(f2.tle)[0]:>9.1f}"
          f"{b2:>11.3e}{r2:>8.3f}")

    f1 = fit(1, None, True)
    b1 = _parse_bstar(f1.tle.line1)
    i = f1.parameter_names.index("BSTAR")
    r1 = (f1.sigma0 * float(f1.sigmas[i])) / abs(b1) if b1 != 0.0 else float("inf")
    print(f"  {'fitted 1d':<17}{f1.rms_m:>8.1f}{forecast(f1.tle)[0]:>9.1f}"
          f"{b1:>11.3e}{r1:>8.3f}")

    f3 = fit(3, None, True)
    b3 = _parse_bstar(f3.tle.line1)
    i = f3.parameter_names.index("BSTAR")
    r3 = (f3.sigma0 * float(f3.sigmas[i])) / abs(b3) if b3 != 0.0 else float("inf")
    print(f"  {'fitted 3d':<17}{f3.rms_m:>8.1f}{forecast(f3.tle)[0]:>9.1f}"
          f"{b3:>11.3e}{r3:>8.3f}")
    print(f"  cross-span B* consistency s = |B*(3d)-B*(2d)|/B*(2d) = "
          f"{abs(b3 - b2) / abs(b2):.3f}")

    sc = fit(1, f2.tle, False)
    print(f"  {'selfcal 2d->1d':<17}{sc.rms_m:>8.1f}{forecast(sc.tle)[0]:>9.1f}"
          f"{_parse_bstar(sc.tle.line1):>11.3e}")

    hz = fit(1, None, False)
    print(f"  {'held-zero 1d':<17}{hz.rms_m:>8.1f}{forecast(hz.tle)[0]:>9.1f}"
          f"{0.0:>11.3e}")

    print()
    print(f"  wall time {time.time() - t_wall:.0f} s")


if __name__ == "__main__":
    main()
