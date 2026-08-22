"""Cross-window summary of Part 2's drag evidence (reference-only).

A pure text parse of the committed per-window results files -- JVM-free, runs in
seconds, and works against PARTIAL evidence, so it is useful from the first
window onward and the tenth closes it for free. The contract asks for one
results file per part; per-window separability (which it asks for twice) is why
Part 2 is twenty files instead, and this is what restores the one-file read.

    conda run -n propygator python summarize_drag.py > results_drag_summary.txt

**NO VERDICT COLUMN, AND NONE IS ADDED.** Part 2 has no benchmark: the contract
states an expectation, not a requirement, and the evidence exists to be
analysed. This script reports what was measured and the fraction of the drag-off
signal each option removed, beside the frozen v0.7.2 figures for context. It
never scores a row.

It parses only the drivers' ``[machine]`` blocks -- ``MROW`` / ``MFIT`` /
``MSCREEN`` -- never the human tables, so reformatting a table upstream cannot
silently change what this reports.

**KNOWN LIMIT OF ``run_all.py --verify`` ON THE ``drag_summary`` GROUP.**
``RESULTS_DIRS`` below is derived from ``__file__``, so this script always reads
the COMMITTED per-window files. Under ``--verify`` the orchestrator regenerates
those windows into a scratch directory and then diffs a summary built from the
committed ones -- so the group verifies this script's own parsing and
formatting, never that freshly regenerated windows re-summarize identically.
Verifying the full chain means running ``--only part2`` without ``--verify``
into an ``--out-dir`` and summarizing there by hand. Left as documentation
rather than fixed: routing a per-group output root through ``_run_group`` is
more machinery than a 20-of-21 coverage gap earns.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output.
"""

from __future__ import annotations

import sys
from pathlib import Path

_STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(_STUDY / "gracefo"))

from windows import WINDOWS  # noqa: E402

LEGS = ("gracefo", "swarm")
RESULTS_DIRS = {
    "gracefo": _STUDY / "gracefo" / "results_drag",
    "swarm": _STUDY / "swarm" / "results_drag",
}
CONFIGS = ("drag_off", "cd_2p3", "cd_fit", "sphere", "box")
CONFIG_LABELS = {
    "drag_off": "drag off",
    "cd_2p3": "Cd = 2.3",
    "cd_fit": "Cd fit (in-arc)",
    "sphere": "sphere table",
    "box": "box table",
}
READ_DAYS = (1, 3, 7)

# The frozen v0.7.2 reading, quoted for context only (contract, "Qualifications"
# -- an expectation, never a bar). Those figures were built from 1-day results,
# so it is the DAY-1 column that compares to them; day 1 is identical under both
# RMS conventions, which is what makes the comparison survive the per-day rule.
# Reading day 3 or day 7 against them would not be like-for-like.
V072_REMOVED = {
    "cd_2p3": {"quiet": 86, "active": 67, "storm": 56},
    "sphere": {"quiet": 53, "active": 80, "storm": 63},
    "box": {"quiet": -24, "active": 79, "storm": 96},
}


def parse_files() -> tuple[dict, dict, dict]:
    """Read every committed per-window file into (rows, fits, screens)."""
    rows: dict[tuple[str, str, str, str, int], tuple[float, ...]] = {}
    fits: dict[tuple[str, str, str], tuple[float, float, float, float]] = {}
    screens: dict[tuple[str, str], tuple[float, float, str]] = {}
    for leg, directory in RESULTS_DIRS.items():
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.txt")):
            for raw in path.read_text(encoding="ascii", errors="replace").splitlines():
                parts = raw.split()
                if not parts:
                    continue
                if parts[0] == "MROW" and len(parts) == 11:
                    # band is carried in the row for self-description but keyed
                    # off here -- the canonical band comes from windows.py.
                    _, lg, win, _band, sat, cfg, day, rad, alo, crs, d3 = parts
                    rows[(lg, win, sat, cfg, int(day))] = (
                        float(rad), float(alo), float(crs), float(d3)
                    )
                elif parts[0] == "MFIT" and len(parts) == 8:
                    _, lg, win, sat, cd, b, mass, cd_hi = parts
                    fits[(lg, win, sat)] = (
                        float(cd), float(b), float(mass), float(cd_hi)
                    )
                elif parts[0] == "MSCREEN" and len(parts) == 7:
                    _, lg, win, sat, sig, dep, verdict = parts
                    screens[(win, sat)] = (float(sig), float(dep), verdict)
    return rows, fits, screens


def sats_present(rows: dict, leg: str, window: str) -> list[str]:
    return sorted({k[2] for k in rows if len(k) == 5 and k[0] == leg and k[1] == window})


def main() -> None:
    rows, fits, screens = parse_files()
    print("=" * 78)
    print("Extended validation -- Part 2 drag propagations, cross-window summary")
    print("=" * 78)
    print(
        "  A text parse of the committed per-window files. Part 2 has NO "
        "benchmark, so nothing here is scored and no verdict column exists."
    )
    print(
        "  Every RMS is a PER-DAY value: day N is the RMS over [N-1 d, N d] "
        "alone, never accumulated from t0."
    )

    for leg in LEGS:
        done = [w for w in WINDOWS if sats_present(rows, leg, w.name)]
        print()
        print("=" * 78)
        print(f"[{leg}]  {len(done)}/{len(WINDOWS)} windows")
        print("=" * 78)
        if not done:
            print("  no committed evidence yet")
            continue

        print("  3D RMS (m) by configuration and day")
        header = f"  {'window':<18}{'band':<10}{'sat':<5}{'config':<18}"
        header += "".join(f"{f'day {d}':>12}" for d in READ_DAYS)
        print(header)
        for window in done:
            for sat in sats_present(rows, leg, window.name):
                for cfg in CONFIGS:
                    cells = ""
                    for day in READ_DAYS:
                        val = rows.get((leg, window.name, sat, cfg, day))
                        cells += f"{val[3]:>12.1f}" if val else f"{'-':>12}"
                    print(
                        f"  {window.name:<18}{window.band:<10}{sat:<5}"
                        f"{CONFIG_LABELS[cfg]:<18}{cells}"
                    )

        print()
        print(
            "  removed fraction of the drag-off signal (%), per day -- context "
            "only, no verdict"
        )
        header = f"  {'window':<18}{'band':<10}{'sat':<5}{'config':<18}"
        header += "".join(f"{f'day {d}':>12}" for d in READ_DAYS)
        print(header)
        for window in done:
            for sat in sats_present(rows, leg, window.name):
                for cfg in ("cd_2p3", "sphere", "box"):
                    cells = ""
                    for day in READ_DAYS:
                        off = rows.get((leg, window.name, sat, "drag_off", day))
                        val = rows.get((leg, window.name, sat, cfg, day))
                        if off and val and off[3] > 0:
                            cells += f"{100.0 * (off[3] - val[3]) / off[3]:>11.0f}%"
                        else:
                            cells += f"{'-':>12}"
                    print(
                        f"  {window.name:<18}{window.band:<10}{sat:<5}"
                        f"{CONFIG_LABELS[cfg]:<18}{cells}"
                    )

        print()
        print("  fitted Cd, with the convention-free B = Cd*A/m beside it")
        print(
            f"  {'window':<18}{'sat':<5}{'Cd':>10}{'B (m^2/kg)':>16}"
            f"{'mass (kg)':>12}{'ceiling':>10}"
        )
        for window in done:
            for sat in sats_present(rows, leg, window.name):
                fit = fits.get((leg, window.name, sat))
                if not fit:
                    continue
                railed = " RAILED" if fit[0] >= fit[3] - 0.05 else ""
                print(
                    f"  {window.name:<18}{sat:<5}{fit[0]:>10.4f}{fit[1]:>16.6e}"
                    f"{fit[2]:>12.3f}{fit[3]:>10.1f}{railed}"
                )

        if leg == "swarm" and screens:
            print()
            print(
                "  degree-5 maneuver screen -- the ONLY gate on this leg, and a "
                "CLEAN is weak evidence rather than a quiet window"
            )
            print(f"  {'window':<18}{'sat':<5}{'signal (m)':>14}{'departure (m)':>16}{'call':>10}")
            for window in done:
                for sat in sats_present(rows, leg, window.name):
                    s = screens.get((window.name, sat))
                    if s:
                        print(
                            f"  {window.name:<18}{sat:<5}{s[0]:>14.1f}"
                            f"{s[1]:>16.1f}{s[2]:>10}"
                        )

    # --- the v0.7.2 context table --------------------------------------------
    print()
    print("=" * 78)
    print("[context]  the frozen v0.7.2 removed-fraction reading, for comparison")
    print("=" * 78)
    print(f"  {'removed':<18}{'quiet':>10}{'active':>10}{'storm':>10}")
    for cfg, vals in V072_REMOVED.items():
        print(
            f"  {CONFIG_LABELS[cfg]:<18}{vals['quiet']:>9}%{vals['active']:>9}%"
            f"{vals['storm']:>9}%"
        )
    print(
        "  Those figures were built from 1-day results, so it is the DAY-1 column "
        "above that compares to them. Day 1 is identical under both RMS "
        "conventions, which is what makes the comparison survive the per-day rule "
        "exactly; reading day 3 or day 7 against them would not be like-for-like."
    )
    print(
        "  The contract expects a bounded loss where drag is weak alongside a "
        "large gain where drag is strong. An INVERSION -- a table run losing "
        "badly where drag is strong -- is what warrants a bug search, and is "
        "written into the findings as what it is."
    )


if __name__ == "__main__":
    main()
