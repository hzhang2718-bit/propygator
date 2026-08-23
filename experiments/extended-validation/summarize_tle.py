"""Cross-window summary of Part 3's TLE evidence (reference-only).

A pure text parse of the committed per-window results files -- JVM-free, runs in
under a second, and works against PARTIAL evidence, so it is useful from the
first window onward and the tenth closes it for free. The contract asks for one
results file per part; per-window separability (which it asks for twice) is why
Part 3 is ten files instead, and this is what restores the one-file read.

    conda run -n propygator python summarize_tle.py > results_tle_summary.txt

**THE GATE -> ARM MAPPING IS APPLIED HERE, NOT IN THE DRIVER.** Every window
runs all three arms regardless of what its gate selected, so the mapping is a
text-pass decision that can be re-scored in seconds without re-running a fit.
That is also what keeps the frozen thresholds honest: re-scoring is cheap, so
there is never a compute argument for adjusting them.

**NO BENCHMARK BLOCKS, AND NONE ARE ADDED HERE.** ``[bench-1]``, ``[bench-2]``,
``[bench-3]``, ``[misclass]`` and ``[post-hoc]`` are Chunk 18's adjudication.
This script reports what was measured and which arm the frozen gate selected; it
scores nothing and declares no verdict.

It parses only the drivers' ``[machine]`` blocks -- ``TGATE`` / ``TROW`` /
``TCAT`` / ``TSTATE`` -- never the human tables, so reformatting a table
upstream cannot silently change what this reports. ``TFADE`` is emitted by the
driver and deliberately NOT read here: they are weighted quantities, and
scoring them beside r and s is exactly what the conservative default forbids.

**KNOWN LIMIT OF ``run_all.py --verify`` ON THE ``tle_summary`` GROUP**, the
same one ``summarize_drag.py`` carries: ``RESULTS_DIR`` is derived from
``__file__``, so this always reads the COMMITTED per-window files. Under
``--verify`` the orchestrator regenerates windows into a scratch directory and
then diffs a summary built from the committed ones, so the group verifies this
script's parsing and formatting, never that freshly regenerated windows
re-summarize identically.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output.
"""

from __future__ import annotations

import sys
from pathlib import Path

_STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(_STUDY / "gracefo"))

from tle_fit_common import (  # noqa: E402
    ARM_IDS,
    CONFIG_IDS,
    R_THRESHOLD,
    READ_DAYS,
    S_THRESHOLD,
    select_arm,
)
from windows import WINDOWS  # noqa: E402

RESULTS_DIR = _STUDY / "gracefo" / "results_tle"


def parse_files() -> tuple[dict, dict, dict, dict]:
    """Read every committed per-window file into (gates, rows, cats, states)."""
    gates: dict[str, dict] = {}
    rows: dict[tuple[str, str, int], tuple[float, ...]] = {}
    cats: dict[str, dict] = {}
    states: dict[tuple[str, str], tuple[float, float]] = {}
    if not RESULTS_DIR.is_dir():
        return gates, rows, cats, states
    for path in sorted(RESULTS_DIR.glob("*.txt")):
        for raw in path.read_text(encoding="ascii", errors="replace").splitlines():
            p = raw.split()
            if not p:
                continue
            if p[0] == "TGATE" and len(p) == 10:
                gates[p[1]] = {
                    "band": p[2],
                    "r": float(p[3]),
                    "s": float(p[4]),
                    "sigma0": float(p[5]),
                    "sigma_bstar": float(p[6]),
                    "bstar2": float(p[7]),
                    "bstar3": float(p[8]),
                    "arm": p[9],
                }
            elif p[0] == "TROW" and len(p) == 11:
                rows[(p[1], p[3], int(p[4]))] = (
                    float(p[5]),
                    float(p[6]),
                    float(p[7]),
                    float(p[8]),
                    float(p[9]),
                    float(p[10]),
                )
            elif p[0] == "TCAT" and len(p) == 7:
                cats[p[1]] = {
                    "stale_d": float(p[2]),
                    "rms_c": float(p[3]),
                    "rms_d": float(p[4]),
                    "ratio": float(p[5]),
                    "verdict": p[6],
                }
            elif p[0] == "TSTATE" and len(p) == 5:
                states[(p[1], p[2])] = (float(p[3]), float(p[4]))
    return gates, rows, cats, states


def main() -> None:
    gates, rows, cats, states = parse_files()
    landed = [w for w in WINDOWS if w.name in gates]

    print("=" * 78)
    print("Extended validation -- Part 3 TLE fitting, cross-window summary")
    print("=" * 78)
    print(f"  source: {RESULTS_DIR.name}/ -- {len(landed)}/10 windows landed")
    if not landed:
        print("  no committed Part 3 evidence yet; run --only tle_01 first")
        return
    print(
        "  every RMS below is PER-DAY: day N is the RMS over [N-1 d, N d] past "
        "T alone, never accumulated from T"
    )
    print("  nothing here is scored -- the three benchmarks are Chunk 18's")

    # --- the gate ------------------------------------------------------------
    print()
    print(f"[gate]  frozen thresholds r < {R_THRESHOLD}, s < {S_THRESHOLD}")
    print(
        f"  {'win':>3}  {'window':<18}{'band':<10}{'r':>12}{'s':>12}"
        f"{'B*(fit2)':>12}  arm"
    )
    for w in landed:
        g = gates[w.name]
        print(
            f"  {w.index:>3}  {w.name:<18}{g['band']:<10}{g['r']:>12.4g}"
            f"{g['s']:>12.4g}{g['bstar2']:>12.3e}  {g['arm']}"
        )
        if g["arm"] != select_arm(g["r"], g["s"]):
            raise SystemExit(
                f"{w.name}: recorded arm {g['arm']!r} does not match the mapping "
                f"applied to its own r/s -- the driver and this script disagree"
            )
    counts = {a: sum(1 for w in landed if gates[w.name]["arm"] == a) for a in ARM_IDS}
    print("  selected: " + ", ".join(f"{a} {counts[a]}" for a in ARM_IDS))

    # The third mapping row's free-vs-held ambiguity, reported as a labelled
    # sensitivity rather than resolved here -- both configurations are measured
    # in every window either way (build plan, Part 3 preamble).
    swapped = [w.name for w in landed if gates[w.name]["arm"] == "arm_fresh"]
    print(
        f"  SENSITIVITY, not a result: the playbook's third row ('freshest 1 d "
        f"fit') is read as arm_fresh (free B*). Substituting arm_zero would "
        f"change {len(swapped)} window(s): "
        + (", ".join(swapped) if swapped else "none")
    )

    # --- the rows ------------------------------------------------------------
    print()
    print("[rows]  forecast 3D RMS (m) vs truth, per day past T")
    for day in READ_DAYS:
        present = [c for c in CONFIG_IDS if any((w.name, c, day) in rows for w in landed)]
        if not present:
            continue
        print(f"  day {day}")
        print("    " + f"{'window':<18}" + "".join(f"{c:>15}" for c in present))
        for w in landed:
            cells = ""
            for c in present:
                v = rows.get((w.name, c, day))
                cells += f"{v[3]:>15.1f}" if v else f"{'-':>15}"
            print(f"    {w.name:<18}{cells}")

    # --- the catalogue rows --------------------------------------------------
    if cats:
        print()
        print("[catalog]  staleness is the known confounder; the cross-tag is a tag test")
        print(
            f"  {'window':<18}{'stale h':>9}{'vs C (m)':>11}{'vs D (km)':>11}"
            f"{'ratio':>9}  verdict"
        )
        for w in landed:
            c = cats.get(w.name)
            if not c:
                continue
            print(
                f"  {w.name:<18}{24.0 * c['stale_d']:>9.2f}{c['rms_c']:>11.1f}"
                f"{c['rms_d'] / 1e3:>11.1f}{c['ratio']:>9.1f}  {c['verdict']}"
            )

    # --- the state rows' reference drift -------------------------------------
    if states:
        print()
        print("[state]  numerical reference drift vs truth over the fitted 2 d arc")
        print(
            "  the number that explains any degradation in the two state rows -- "
            "the a-priori tables cannot meet sec 1.2's calibration bar, so this is "
            "an expectation, never a bar"
        )
        print(f"  {'window':<18}{'sphere RMS':>13}{'sphere end':>13}"
              f"{'box RMS':>13}{'box end':>13}")
        for w in landed:
            sph = states.get((w.name, "state_sphere"))
            box = states.get((w.name, "state_box"))
            if not (sph or box):
                continue
            def _c(v, i):
                return f"{v[i]:>13.1f}" if v else f"{'-':>13}"
            print(
                f"  {w.name:<18}{_c(sph, 0)}{_c(sph, 1)}{_c(box, 0)}{_c(box, 1)}"
            )

    print()
    print(f"  {len(landed)}/10 windows summarized")


if __name__ == "__main__":
    main()
