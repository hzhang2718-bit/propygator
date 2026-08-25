"""Probe 3: does the playbook's auto-rule replicate across anchors?

Part of the **TLE fit strategy** experiment (2026-07-19; see README.md). The
rule under test (from probe 1's single-anchor evidence; now
``tle-fitting-playbook.md``, same folder):

  1. Fit 2 d with B* free. Read r = sigma0*sigma(B*)/|B*|.
  2. r < 0.05  -> B* is real: transplant it (hold) into a fresh 1 d element
                 refit ("selfcal 2d->1d").
     r >= 0.05 -> B* untrustworthy: hold an external prior (catalog B*) on a
                 fresh 1 d refit; with no prior, hold 0 (short horizons only).

Evaluated at anchors day-4/5/6/7 x both windows (public API only, one parse
per window). Rows per anchor: fitted-2d, selfcal 2d->1d, held-cat 1d,
held-zero 1d; forecast = 3 days past the anchor. Measured outcome: the r-gate
classified every anchor correctly (quiet r = 0.15-1.14, never certified;
active r = 0.020-0.024, always certified), and in quiet the surprise was
held-zero beating held-cat at +3 d on 3 of 4 anchors.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data + the study's GNV1B
data); cwd-independent. Stdout is ASCII-only (captured under cp1252):

    cd experiments/tle-fit-strategy
    conda run -n propygator python probe3_rule_replication.py quiet_2019  >  results_probe3_rule_replication.txt
    conda run -n propygator python probe3_rule_replication.py active_2023 >> results_probe3_rule_replication.txt
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

CATALOG_TLES: dict[str, tuple[str, str]] = {
    "quiet_2019": (
        "1 43476U 18047A   19317.74687279 +.00000271 +00000-0 +98502-5 0  9994",
        "2 43476 088.9970 166.9377 0018420 022.3999 337.8049 15.23932987082211",
    ),
    "active_2023": (
        "1 43476U 18047A   23353.82590425  .00004407  00000-0  16167-3 0  9994",
        "2 43476  88.9824 323.8854 0015957  51.6909 308.5772 15.27615336310325",
    ),
}

LOAD_DAYS = 10
ANCHOR_DAYS = (4, 5, 6, 7)  # fit arcs end at each day-N start
FC_DAYS = 3
RATIO_THRESHOLD = 0.05


def _parse_bstar(line1: str) -> float:
    field = line1[53:61]
    sign = -1.0 if field[0] == "-" else 1.0
    return sign * (int(field[1:6]) / 1.0e5) * 10.0 ** int(field[6:8])


def main() -> None:
    window = sys.argv[1] if len(sys.argv) > 1 else "quiet_2019"
    t_wall = time.time()

    files = find_window_files(DATA_ROOT / window, GRACEFO_SAT_ID)
    eph = parse_gnv1b(
        files[:LOAD_DAYS], sat_id=GRACEFO_SAT_ID, subsample_s=SUBSAMPLE_S
    )
    n_per_day = int(86400.0 / SUBSAMPLE_S)
    catalog = TLE.from_strings(*CATALOG_TLES[window], name=SAT_NAME)
    cat_bstar = _parse_bstar(catalog.line1)

    print(f"Probe 3: auto-rule replication across anchors -- {window}")
    print("=" * 78)
    print(f"  rule: fit 2d free; r = sigma0*sig(B*)/|B*| < {RATIO_THRESHOLD} -> "
          f"selfcal 2d->1d; else held-cat 1d")
    print(f"  catalog B* = {cat_bstar:.3e}; forecast horizon {FC_DAYS} d per anchor")
    print()
    print(f"  {'anchor':>7}{'config':<17}{'+1 d':>9}{'+2 d':>9}{'+3 d':>9}"
          f"{'B*':>11}{'r':>8}{'rule picks':>12}")

    for anchor_day in ANCHOR_DAYS:
        k_end = (anchor_day - 1) * n_per_day
        t_end = eph.epochs[k_end]
        span_fc = FC_DAYS * 86400.0
        truth_fc = eph.positions_m[k_end : k_end + FC_DAYS * n_per_day]

        def forecast(tle: TLE) -> list[float]:
            traj = propagate_tle(tle, span_fc, output_step=SUBSAMPLE_S, start=t_end)
            pos = traj.to_frame(Frame.ITRF).positions
            d = np.linalg.norm(pos[: len(truth_fc)] - truth_fc, axis=1)
            return [
                _rms(d[j * n_per_day : (j + 1) * n_per_day]) for j in range(FC_DAYS)
            ]

        def ref_for(span_d: int) -> Trajectory:
            k0 = k_end - span_d * n_per_day
            return Trajectory.from_arrays(
                list(eph.epochs[k0 : k_end + 1]),
                eph.positions_m[k0 : k_end + 1],
                eph.velocities_ms[k0 : k_end + 1],
                Frame.ITRF,
            )

        def fit(span_d: int, guess: TLE | None, fit_bstar: bool):
            return fit_tle_detailed(
                ref_for(span_d),
                fitting_span=span_d * 86400.0,
                initial_guess=guess,
                fit_bstar=fit_bstar,
                norad_id=NORAD_ID,
                name=SAT_NAME,
                progress=False,
            )

        # Stage 1: the 2 d free fit + the trust ratio.
        f2 = fit(2, None, True)
        b2 = _parse_bstar(f2.tle.line1)
        i = f2.parameter_names.index("BSTAR")
        r = (f2.sigma0 * float(f2.sigmas[i])) / abs(b2) if b2 != 0.0 else float("inf")
        pick = "selfcal" if r < RATIO_THRESHOLD else "held-cat"

        rows = [
            ("fitted 2d", forecast(f2.tle), b2, f"{r:.3f}", pick),
            ("selfcal 2d->1d",
             forecast(fit(1, f2.tle, False).tle), b2, "", ""),
            ("held-cat 1d",
             forecast(fit(1, catalog, False).tle), cat_bstar, "", ""),
            ("held-zero 1d",
             forecast(fit(1, None, False).tle), 0.0, "", ""),
        ]
        for label, fc, bstar, r_txt, pick_txt in rows:
            # rstrip: rows without r/pick columns must not carry trailing
            # whitespace (the pre-commit trailing-whitespace hook would fight
            # every regeneration of the committed results file).
            print((f"  {f'day {anchor_day}':>7} {label:<16}"
                   + "".join(f"{v:>9.1f}" for v in fc)
                   + f"{bstar:>11.3e}{r_txt:>8}{pick_txt:>12}").rstrip())
        print(f"  [{time.time() - t_wall:6.0f} s] anchor day {anchor_day} done",
              file=sys.stderr)

    print()
    print(f"  wall time {time.time() - t_wall:.0f} s")


if __name__ == "__main__":
    main()
