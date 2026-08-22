"""Orchestrator for the extended-validation study (reference-only).

Regenerates every committed results file from its driver invocations -- the
one-command reproduction of the study's evidence -- or, with ``--verify``, runs
everything into a scratch directory and diffs each output against the committed
evidence with wall-clock timing lines masked.

    conda run -n propygator python run_all.py --list
    conda run -n propygator python run_all.py --only noise
    conda run -n propygator python run_all.py --verify --only noise

``--list`` is the authoritative group listing; groups are registered below by
the chunk that creates them, so a group routinely exists here before its
evidence does.

PER-GROUP --verify IS THE DOCUMENTED DEFAULT. A whole-study regenerate is a
multi-hour, deliberately scheduled act, not a pre-commit check.

Each invocation is a separate process (one JVM per process). Runs in the
propygator conda env; drivers' stderr (fit progress) passes through. Output
files are written CRLF to match the committed evidence. ASCII only.

Not shipped, not in CI, outside ``testpaths``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

STUDY = Path(__file__).resolve().parent

# The table-noise windows live in the FROZEN v0.7.2 truth tree. Its parsers and
# file finder all take arbitrary Paths, so this is a READ of that tree, never an
# edit (contract, "The earlier experiment is frozen"). Stated here rather than
# left to the driver's default so the provenance is visible in the orchestrator.
_FROZEN_ROOT = "--data-root=../../real-world-validation/data/gracefo"

# group -> (results file relative to STUDY, [(script relative to STUDY, [args])])
#
# Each group is ONE invocation covering every window it owns, because each
# driver closes with a cross-window summary block that is part of the chunk's
# deliverable: computing it in a process that has seen every window beats
# transcribing it afterwards, and it saves the extra JVM boots.
GROUPS: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {
    "noise": (  # Chunk 2 -- three inherited windows, both satellites
        "gracefo/results_table_noise.txt",
        [("gracefo/run_table_noise.py", [_FROZEN_ROOT])],
    ),
    "screen": (  # Chunk 1 -- both maneuver gates over the ten frozen windows
        "gracefo/results_screen.txt",
        # --data-root left at the driver's default, THIS study's own truth tree.
        [("gracefo/run_screen.py", [])],
    ),
}

# --- Part 2 (Chunks 3-13) -----------------------------------------------------
# One group per window per leg. `--only drag_04` is a complete unit of work, and
# per-window separability is the ONLY mitigation that matters for a part whose
# 7-day Cd fits are ~80 % of the study's compute (contract, stated twice).
# Registered by the chunk that CREATES them, so these exist here before their
# evidence does; --verify says so rather than running for hours to find out.
_TABLE_ORDER = (
    "low_2019_12",
    "low_2021_04",
    "low_2021_06",
    "moderate_2022_04",
    "intense_2024_06",
    "storm_2024_08",
    "intense_2024_11",
    "storm_2025_05",
    "moderate_2025_07",
    "storm_2026_01",
)
for _i, _name in enumerate(_TABLE_ORDER, start=1):
    GROUPS[f"drag_{_i:02d}"] = (
        f"gracefo/results_drag/window_{_i:02d}_{_name}.txt",
        [("gracefo/run_drag_window.py", [_name])],
    )
    GROUPS[f"swarm_{_i:02d}"] = (
        f"swarm/results_drag/window_{_i:02d}_{_name}.txt",
        [("swarm/run_drag_window.py", [_name])],
    )
GROUPS["drag_summary"] = (
    "results_drag_summary.txt",
    [("summarize_drag.py", [])],
)

# Twenty bare names in --only is unusable, so a few aliases expand to them.
ALIASES: dict[str, list[str]] = {
    "drag": [f"drag_{i:02d}" for i in range(1, 11)],
    "swarm": [f"swarm_{i:02d}" for i in range(1, 11)],
    "part2": [f"drag_{i:02d}" for i in range(1, 11)]
    + [f"swarm_{i:02d}" for i in range(1, 11)]
    + ["drag_summary"],
}


def _expand(names: list[str]) -> list[str]:
    """Expand any aliases, preserving order and dropping duplicates."""
    out: list[str] = []
    for name in names:
        for expanded in ALIASES.get(name, [name]):
            if expanded not in out:
                out.append(expanded)
    return out

# Wall-clock timing text masked before any diff (everything else in the evidence
# is deterministic given the same code, truth files, and orekit-data).
_TIME_PATTERNS = [
    (re.compile(r"\b\d+(?:\.\d+)? s wall\b"), "<T> s wall"),
    (re.compile(r"wall time: \d+(?:\.\d+)? s"), "wall time: <T> s"),
]


def _mask_times(line: str) -> str:
    for pattern, repl in _TIME_PATTERNS:
        line = pattern.sub(repl, line)
    return line


def _run_group(name: str, out_root: Path) -> Path:
    """Run one group's invocations, concatenating stdout into its results file."""
    rel_out, invocations = GROUPS[name]
    out_path = out_root / rel_out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for script, args in invocations:
        script_path = STUDY / script
        cmd = [sys.executable, str(script_path), *args]
        print(f"[run_all] {name}: {script} {' '.join(args)}".rstrip(), file=sys.stderr)
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=script_path.parent,
            stdout=subprocess.PIPE,
            stderr=None,  # driver progress passes through
            check=False,
        )
        dt = time.perf_counter() - t0
        if proc.returncode != 0:
            raise SystemExit(
                f"[run_all] FAILED ({proc.returncode}) after {dt:.0f} s: "
                f"{script} {' '.join(args)}"
            )
        lines.extend(proc.stdout.decode("ascii", errors="replace").splitlines())
        print(f"[run_all]   done in {dt:.0f} s", file=sys.stderr)
    out_path.write_bytes(("\r\n".join(lines) + "\r\n").encode("ascii"))
    return out_path


def _diff_report(name: str, fresh: Path, committed: Path, max_show: int = 80) -> int:
    """Unified diff after timing masks; returns the number of +/- diff lines."""
    import difflib

    if not committed.exists():
        print(f"[verify] {name}: no committed file at {committed}")
        return 1
    a = [_mask_times(ln) for ln in committed.read_text(encoding="ascii").splitlines()]
    b = [_mask_times(ln) for ln in fresh.read_text(encoding="ascii").splitlines()]
    diff = list(
        difflib.unified_diff(a, b, fromfile="committed", tofile="fresh", lineterm="")
    )
    n_diff = sum(
        1
        for ln in diff
        if (ln.startswith("+") or ln.startswith("-"))
        and not ln.startswith(("+++", "---"))
    )
    for ln in diff[: max_show + 4]:
        print(f"  {ln}")
    if len(diff) > max_show + 4:
        print(f"  ... ({len(diff) - max_show - 4} more diff lines)")
    status = "IDENTICAL (timing masked)" if n_diff == 0 else f"{n_diff} +/- diff lines"
    print(f"[verify] {name}: {status}")
    return n_diff


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--only",
        default=None,
        help=f"comma-separated group subset (of: {', '.join(GROUPS)})",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=None,
        help="write outputs under this directory instead of in place",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="run into a scratch dir (or --out-dir) and diff vs the committed files",
    )
    parser.add_argument("--list", action="store_true", help="list groups and exit")
    args = parser.parse_args()

    if args.list:
        for name, (rel_out, invocations) in GROUPS.items():
            print(f"{name:<14} -> {rel_out}  ({len(invocations)} invocations)")
        print()
        for alias, expansion in ALIASES.items():
            print(f"{alias:<14} => {', '.join(expansion)}")
        return

    names = _expand(list(GROUPS) if args.only is None else args.only.split(","))
    for name in names:
        if name not in GROUPS:
            raise SystemExit(f"unknown group {name!r}; choose from {', '.join(GROUPS)}")

    # Groups are registered by the chunk that CREATES them, so a group routinely
    # exists here before its evidence does. Catch that now rather than after the
    # multi-hour run it would otherwise take to reach the diff.
    if args.verify:
        pending = [n for n in names if not (STUDY / GROUPS[n][0]).exists()]
        if pending:
            raise SystemExit(
                "[verify] no committed evidence yet for: "
                + ", ".join(f"{n} -> {GROUPS[n][0]}" for n in pending)
                + "\n  Regenerate it first (drop --verify), or --only the groups "
                "that have evidence."
            )

    out_root = args.out_dir
    if out_root is None:
        # mkdtemp CREATES the directory, so it is called only when verifying --
        # a plain regenerate writes in place and must not leave a stray temp dir.
        out_root = (
            Path(tempfile.mkdtemp(prefix="extval-verify-")) if args.verify else STUDY
        )
    out_root = out_root.resolve()
    if args.verify and out_root == STUDY:
        raise SystemExit("--verify must not overwrite the committed files")

    print(
        f"[run_all] groups: {', '.join(names)}; output root: {out_root}",
        file=sys.stderr,
    )
    total_diff = 0
    for name in names:
        fresh = _run_group(name, out_root)
        if args.verify:
            total_diff += _diff_report(name, fresh, STUDY / GROUPS[name][0])
    if args.verify:
        print(
            "[verify] overall: "
            + (
                "CLEAN -- all groups reproduce"
                if total_diff == 0
                else f"{total_diff} differing lines across groups"
            )
        )
        if total_diff:
            sys.exit(1)


if __name__ == "__main__":
    main()
