"""Orchestrator for the real-world-validation study (reference-only).

Regenerates every committed results file from its driver invocations -- the
one-command reproduction of the study's evidence -- or, with ``--verify``,
runs everything into a scratch directory and diffs each output against the
committed evidence with wall-clock timing lines masked (propagation numbers
are deterministic; wall times are not).

    conda run -n propygator python run_all.py --list
    conda run -n propygator python run_all.py                      # regenerate in place
    conda run -n propygator python run_all.py --only fit,sweep     # a subset
    conda run -n propygator python run_all.py --verify             # scratch + diff
    conda run -n propygator python run_all.py --verify --out-dir X # diff, keep outputs in X

Groups (each owns one results file; invocations run in order and concatenate):

    lageos      lageos/results.txt                (Chunks 0 + 1)
    drag        gracefo/results.txt               (Chunks 2 + 2b + 2c, 4 blocks)
    fit         gracefo/results_fit_vs_catalog.txt (Chunk 3 primary + fit-bstar=off)
    sweep       gracefo/results_fit_span_sweep.txt (Chunk 3 fitting-span sweep)
    state-path  gracefo/results_fit_state_path.txt (Chunk 3 state-path + tables)

Each invocation is a separate process (one JVM per process); a full run is
~60-90 min of compute, dominated by the Chunk 2 golden-section Cd fits. Runs
in the propygator conda env; drivers' stderr (fit progress) passes through.
Output files are written CRLF to match the committed evidence. ASCII only.

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

# group -> (results file relative to STUDY, [(script relative to STUDY, [args])])
GROUPS: dict[str, tuple[str, list[tuple[str, list[str]]]]] = {
    "lageos": (
        "lageos/results.txt",
        [
            ("lageos/run_lageos.py", []),
            ("lageos/run_ablations.py", []),
        ],
    ),
    "drag": (
        "gracefo/results.txt",
        [
            ("gracefo/run_gracefo.py", ["quiet_2019"]),
            ("gracefo/run_gracefo.py", ["active_2023"]),
            ("gracefo/run_gracefo.py", ["storm_2024"]),
            # The Chunk 2c onset arc + the storm-surprise fixed-Cd run (the
            # active_2023 Run-3 fitted Cd; see gracefo_common.RUN3_FITTED_CD).
            (
                "gracefo/run_gracefo.py",
                ["storm_2024", "--start-date=2024-05-10", "--fixed-cd=3.405"],
            ),
        ],
    ),
    "fit": (
        "gracefo/results_fit_vs_catalog.txt",
        [
            ("gracefo/run_fit_vs_catalog.py", ["quiet_2019"]),
            ("gracefo/run_fit_vs_catalog.py", ["active_2023"]),
            ("gracefo/run_fit_vs_catalog.py", ["quiet_2019", "--fit-bstar=off"]),
            ("gracefo/run_fit_vs_catalog.py", ["active_2023", "--fit-bstar=off"]),
        ],
    ),
    "sweep": (
        "gracefo/results_fit_span_sweep.txt",
        [
            ("gracefo/run_fit_vs_catalog.py", ["quiet_2019", "--sweep"]),
            ("gracefo/run_fit_vs_catalog.py", ["active_2023", "--sweep"]),
        ],
    ),
    "state-path": (
        "gracefo/results_fit_state_path.txt",
        [
            ("gracefo/run_fit_vs_catalog.py", ["quiet_2019", "--state-path"]),
            ("gracefo/run_fit_vs_catalog.py", ["active_2023", "--state-path"]),
        ],
    ),
}

# Wall-clock timing text masked before any diff (everything else in the
# evidence is deterministic given the same code, truth files, and orekit-data).
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
    # CRLF to match the committed evidence files.
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
            print(f"{name:<11} -> {rel_out}  ({len(invocations)} invocations)")
        return

    names = list(GROUPS) if args.only is None else args.only.split(",")
    for name in names:
        if name not in GROUPS:
            raise SystemExit(f"unknown group {name!r}; choose from {', '.join(GROUPS)}")

    out_root = args.out_dir
    if out_root is None:
        out_root = (
            Path(tempfile.mkdtemp(prefix="rwv-verify-")) if args.verify else STUDY
        )
    out_root = out_root.resolve()
    if args.verify and out_root == STUDY:
        raise SystemExit("--verify must not overwrite the committed files")

    print(f"[run_all] groups: {', '.join(names)}; output root: {out_root}",
          file=sys.stderr)
    total_diff = 0
    for name in names:
        fresh = _run_group(name, out_root)
        if args.verify:
            total_diff += _diff_report(name, fresh, STUDY / GROUPS[name][0])
    if args.verify:
        print(
            f"[verify] overall: "
            + ("CLEAN -- all groups reproduce" if total_diff == 0
               else f"{total_diff} differing lines across groups")
        )
        if total_diff:
            sys.exit(1)


if __name__ == "__main__":
    main()
