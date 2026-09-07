"""Chunk 18 -- adjudication of Part 3's TLE evidence (reference-only).

Scores the study's THREE pre-registered benchmarks over the ten committed
per-window files and writes down what missed. A text pass over committed
evidence: no JVM, no propagation, no re-run, under a second.

    conda run -n propygator python adjudicate_tle.py > results_tle_adjudication.txt

**THIS IS THE ONLY FILE IN THE STUDY THAT SCORES ANYTHING.** The per-window
drivers and ``summarize_tle.py`` deliberately report without scoring, so that
re-scoring the frozen gate is a cheap text pass and there is never a compute
argument for adjusting a threshold. This script is the other half of that split,
and it is why ``summarize_tle.py`` says no benchmark blocks are added there.

**THE PLAYBOOK'S HORIZON QUALIFIERS ARE DELIBERATELY ABSENT.** Rows 2 and 3 of
the r/s table carry scoping the mapping itself drops -- ``B* = 0`` is directed at
"~3 d horizons", a held B* at ">= 4 d", the freshest fit at "horizon <= 1 d" --
so a day-7 miss by ``arm_zero`` may be the playbook working as documented rather
than the gate mispredicting. Separating those two is a READING, and it belongs in
the study README and the findings document. Do not add it here: a scorer that
excuses its own misses is not a scorer.

**WHAT IS FROZEN.** ``r < 0.05`` and ``s < 0.1`` are pre-registered predictions
carried verbatim from ``docs/tle-fitting-playbook.md``. ``[post-hoc]`` below
searches other thresholds; that block is labelled, reported separately, and
revises nothing -- re-fitting the thresholds to this data and then reporting that
they classify correctly is circular and forbidden (contract).

**PARSING.** Machine tokens only -- ``TGATE`` / ``TROW`` / ``TCAT`` / ``TSTATE``
through ``summarize_tle.parse_files``, plus ``TFADE`` here -- with ONE documented
exception. ``CrossTagResult.separation_km`` is computed at
``catalog_tles.py:337`` and printed by ``format_cross_tag``, but never emitted as
a machine field, so the C-D separation range is read from the human ``[catalog]``
line under an exact-count assert that turns an upstream reformat into a loud
failure. It is the fourth of the four provisional cross-tag ranges that both
``catalog_tles.py``'s docstring and the study README promise this chunk
re-derives; the other three come from ``TCAT``.

**KNOWN LIMIT OF ``run_all.py --verify`` ON THE ``tle_bench`` GROUP**, the same
one ``summarize_tle.py`` carries: ``RESULTS_DIR`` is derived from ``__file__``
(imported from ``summarize_tle``), so this always reads the COMMITTED
per-window files. ``--verify`` therefore checks only this script's own parsing
and formatting determinism, never that freshly regenerated windows re-adjudicate
identically.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output.
"""

from __future__ import annotations

import re
import statistics
import sys
from pathlib import Path

_STUDY = Path(__file__).resolve().parent
sys.path.insert(0, str(_STUDY / "gracefo"))

from summarize_tle import RESULTS_DIR, parse_files  # noqa: E402
from tle_fit_common import (  # noqa: E402
    ARM_IDS,
    CONFIG_IDS,
    FADE_TAUS,
    R_THRESHOLD,
    READ_DAYS,
    S_THRESHOLD,
    select_arm,
)
from windows import WINDOWS  # noqa: E402

# --- the frozen scoring constants --------------------------------------------
# Every one is quoted from the contract or the build plan, not chosen here.
# Changing one changes a verdict, so they are named rather than inlined.

TIE = 1.5  # contract: anchor scatter is 2-3x, so under 1.5x is noise
N_CELLS = len(WINDOWS) * len(READ_DAYS)  # 30 = ten windows x three read days
BENCH1_BAR = 21  # >= 70 % of 30

BENCH3_GAIN = 1.5  # median day-3 improvement needed, per band
BENCH3_FLOOR = 0.8  # = 1 / 1.25, the "no band more than 1.25x worse" bar
BENCH3_MIN_BANDS = 2  # bands that must clear BENCH3_GAIN, under ONE tau

BAND_ORDER = ("low", "moderate", "intense", "storm")

# Context for [bench-3]; both are committed literals, not measurements here.
FADE_MAX_ITERATIONS = 800  # run_tle_window.py:181, the fade rows' cap
SHIPPED_MAX_ITERATIONS = 100  # features.md sec 1.2 default, what a user gets

# The provisional cross-tag figures this chunk re-derives, as literals so the
# output can say which moved. They live in catalog_tles.py's docstring and the
# study README, and both name Chunk 18 as the re-derivation.
#
# ``(lo, hi, decimals)``. The decimals are the precision the figure was WRITTEN
# at, and that is also what a re-derivation is judged against: a range quoted as
# "664 - 1004" is not contradicted by 664.0 - 1003.7, so the test is agreement
# within half of the provisional's own last digit, never string equality.
PROVISIONAL = {
    "vs C (m)": (664.0, 1004.0, 0),
    "vs D (km)": (173.6, 221.8, 1),
    "ratio (x)": (195.0, 301.0, 0),
    "C-D separation (km)": (173.0, 222.3, 1),
}

_SEP_RE = re.compile(r"C-D separation over that day: ([0-9]+\.[0-9]+) km")
_FILE_RE = re.compile(r"^window_(\d{2})_(.+)\.txt$")


# --- parsing -----------------------------------------------------------------


def parse_extras() -> tuple[dict, dict]:
    """``TFADE`` rows, plus the one human line carrying C-D separation.

    Returns ``(fades, seps)``. ``fades[(window, cfg_id)] = (iters, evals,
    sigma0, sigma_bstar)``; ``seps[window] = km``. Both are keyed by the window
    name taken from the FILENAME and cross-checked against ``WINDOWS``, so a
    stray file cannot contribute rows under a name nobody notices.
    """
    fades: dict[tuple[str, str], tuple[int, int, float, float]] = {}
    seps: dict[str, float] = {}
    known = {w.name for w in WINDOWS}
    for path in sorted(RESULTS_DIR.glob("*.txt")):
        m = _FILE_RE.match(path.name)
        if not m:
            raise SystemExit(f"{path.name}: not a window results file")
        name = m.group(2)
        if name not in known:
            raise SystemExit(f"{path.name}: window {name!r} is not in WINDOWS")
        text = path.read_text(encoding="ascii", errors="replace")
        found = _SEP_RE.findall(text)
        if len(found) != 1:
            raise SystemExit(
                f"{path.name}: expected exactly 1 'C-D separation' line, found "
                f"{len(found)} -- format_cross_tag's line has changed shape and "
                f"this is the study's one human-text parse; fix it here"
            )
        seps[name] = float(found[0])
        for raw in text.splitlines():
            p = raw.split()
            if p and p[0] == "TFADE" and len(p) == 7:
                fades[(p[1], p[2])] = (int(p[3]), int(p[4]), float(p[5]), float(p[6]))
    return fades, seps


# --- the shared primitives ---------------------------------------------------


def arm_for(r: float, s: float, r_thr: float, s_thr: float) -> str:
    """The playbook mapping with the thresholds left free, for ``[post-hoc]``.

    Asserted equal to :func:`select_arm` at the frozen thresholds, so the
    post-hoc search cannot silently drift from the function under test.
    """
    if not (r < r_thr):
        return "arm_zero"
    return "arm_transplant" if s < s_thr else "arm_fresh"


def correct_at(rows: dict, w: str, d: int) -> tuple[set[str], dict[str, float], float]:
    """``(correct set, arm -> RMS, best RMS)`` at one window and day.

    The correct set is every arm within ``TIE`` of the best arm there, so the
    argmin is always a member and the set is never empty.
    """
    vals = {a: rows[(w, a, d)][3] for a in ARM_IDS}
    best = min(vals.values())
    return {a for a, v in vals.items() if v <= TIE * best}, vals, best


def rate(hits: int) -> str:
    return f"{hits:>2}/{N_CELLS} = {100.0 * hits / N_CELLS:5.1f} %"


# --- the blocks --------------------------------------------------------------


def integrity(gates: dict, rows: dict, fades: dict, seps: dict) -> None:
    """Hard-exit on anything that would make a verdict below meaningless."""
    names = [w.name for w in WINDOWS]
    missing = [n for n in names if n not in gates]
    if missing:
        raise SystemExit(
            "adjudication needs 10/10 windows; missing: " + ", ".join(missing)
        )
    want = len(names) * len(CONFIG_IDS) * len(READ_DAYS)
    absent = [
        (n, c, d)
        for n in names
        for c in CONFIG_IDS
        for d in READ_DAYS
        if (n, c, d) not in rows
    ]
    if absent:
        raise SystemExit(f"expected {want} TROW rows, {len(absent)} missing")
    for n in names:
        g = gates[n]
        if g["arm"] != select_arm(g["r"], g["s"]):
            raise SystemExit(f"{n}: recorded arm disagrees with select_arm(r, s)")
        if arm_for(g["r"], g["s"], R_THRESHOLD, S_THRESHOLD) != g["arm"]:
            raise SystemExit(f"{n}: arm_for disagrees with select_arm at frozen (R,S)")
    if (R_THRESHOLD, S_THRESHOLD) != (0.05, 0.1):
        raise SystemExit(
            f"frozen thresholds moved: r < {R_THRESHOLD}, s < {S_THRESHOLD} -- the "
            f"playbook's literals are 0.05 and 0.1 and are never re-fitted"
        )
    counts = {b: sum(1 for w in WINDOWS if w.band == b) for b in BAND_ORDER}
    if sum(counts.values()) != len(WINDOWS) or set(counts) != set(BAND_ORDER):
        raise SystemExit(f"bands do not partition the ten windows: {counts}")
    if len(fades) != len(names) * len(FADE_TAUS):
        raise SystemExit(f"expected {len(names) * len(FADE_TAUS)} TFADE rows")
    if len(seps) != len(names):
        raise SystemExit(f"expected {len(names)} C-D separation lines")

    print()
    print("[integrity]  asserted, not assumed -- each one hard-exits on failure")
    print(f"  {want} TROW rows present, 13 configurations x 3 days x 10 windows")
    print("  every recorded arm reproduces select_arm(r, s), and arm_for agrees at (R,S)")
    print(
        f"  thresholds are the playbook's literals: r < {R_THRESHOLD}, s < {S_THRESHOLD}"
    )
    print(
        "  bands partition the ten windows: "
        + ", ".join(f"{b} {counts[b]}" for b in BAND_ORDER)
    )
    print(f"  {len(fades)} TFADE rows, {len(seps)} C-D separation lines")


def bench1(
    rows: dict, arm_of: dict[str, str], *, quiet: bool = False
) -> tuple[int, int]:
    """Gate-selected arm against ``naive_2d`` over the 30 cells."""
    strict = tie = 0
    lines: list[str] = []
    for d in READ_DAYS:
        for w in WINDOWS:
            a = arm_of[w.name]
            g = rows[(w.name, a, d)][3]
            n = rows[(w.name, "naive_2d", d)][3]
            s_ok, t_ok = g < n, g <= TIE * n
            strict += s_ok
            tie += t_ok
            lines.append(
                f"  {d:>3}  {w.name:<18}{w.band:<10}{a:<16}{g:>10.1f}{n:>11.1f}"
                f"{g / n:>8.3f}   {'WIN' if s_ok else 'LOSS':<8}"
                f"{'OK' if t_ok else 'MISS'}"
            )
    if quiet:
        return strict, tie

    print()
    print("[bench-1]  the gate + playbook beat the naive fit")
    print(
        f"  bar: >= 70 % ({BENCH1_BAR}/{N_CELLS}). Gate-selected arm vs naive_2d, "
        f"days 1/3/7, ten windows."
    )
    print(
        "  these are ten independent runs read on three disjoint days, NOT 30 "
        "independent trials"
    )
    print(
        f"  'tie' passes when the gate is within {TIE}x of naive_2d -- the "
        f"contract's own scoring"
    )
    print(
        f"  {'day':>3}  {'window':<18}{'band':<10}{'gate arm':<16}{'gate':>10}"
        f"{'naive_2d':>11}{'ratio':>8}   {'strict':<8}tie"
    )
    for line in lines:
        print(line)
    print(f"  strict  : {rate(strict)}  -> {'HIT' if strict >= BENCH1_BAR else 'MISS'}")
    print(f"  tie rule: {rate(tie)}  -> {'HIT' if tie >= BENCH1_BAR else 'MISS'}")
    print(
        f"  VERDICT [bench-1]: {'HIT' if tie >= BENCH1_BAR else 'MISS'}  (scored "
        f"under the tie rule, which the contract states is how this bar is meant "
        f"to be read)"
    )
    hinges = (tie >= BENCH1_BAR) != (strict >= BENCH1_BAR)
    print(
        "  the verdict HINGES on the tie rule -- strict and tie disagree"
        if hinges
        else "  the verdict does not hinge on the tie rule -- strict and tie agree"
    )
    return strict, tie


def bench2(
    rows: dict, arm_of: dict[str, str], *, quiet: bool = False
) -> tuple[int, dict]:
    """The gate against each always-one-arm policy, on correct-set membership."""
    gate_hits = 0
    fixed = {a: 0 for a in ARM_IDS}
    degenerate = 0
    lines: list[str] = []
    for w in WINDOWS:
        for d in READ_DAYS:
            ok, vals, _ = correct_at(rows, w.name, d)
            a = arm_of[w.name]
            gate_hits += a in ok
            for arm in ARM_IDS:
                fixed[arm] += arm in ok
            degenerate += len(ok) == len(ARM_IDS)
            cells = "".join(
                f"{vals[arm]:>10.1f}{'*' if arm in ok else ' '}" for arm in ARM_IDS
            )
            lines.append(
                f"  {w.index:>3}  {w.name:<18}{d:>2}{cells}  {a:<16}"
                f"{'yes' if a in ok else 'NO'}"
            )
    if quiet:
        return gate_hits, fixed

    print()
    print("[bench-2]  the gate beats any fixed arm")
    print(
        f"  correct set at a cell = every arm within {TIE}x of the best arm THERE "
        f"('*' below)"
    )
    print(
        "  bar: the gate's rate must be STRICTLY higher than all three "
        "always-one-arm rates"
    )
    print(
        f"  {'win':>3}  {'window':<18}{'d':>2}"
        + "".join(f"{a.replace('arm_', ''):>11}" for a in ARM_IDS)
        + f"  {'gate picked':<16}hit"
    )
    for line in lines:
        print(line)
    print(f"  gate                 : {rate(gate_hits)}")
    for a in ARM_IDS:
        print(f"  always {a:<14}: {rate(fixed[a])}")
    beat = all(gate_hits > fixed[a] for a in ARM_IDS)
    print(f"  VERDICT [bench-2]: {'HIT' if beat else 'MISS'}")
    print(
        f"  degenerate cells (all three arms within {TIE}x, so every policy "
        f"scores): {degenerate}/{N_CELLS} -- these separate nothing"
    )
    print(
        "  STRUCTURAL: the gate picks one arm per WINDOW and applies it at all "
        "three days, while the correct set varies BY DAY"
    )
    print(
        "  a MISS here means the gate is REDUNDANT, not wrong (contract) -- one arm "
        "did the job everywhere, which revises the playbook TOWARD that arm"
    )
    return gate_hits, fixed


def bench3(rows: dict, arm_of: dict[str, str], fades: dict) -> None:
    """Fading memory's pre-registered promotion bar, per band, at day 3."""
    tau_ids = [c for c in CONFIG_IDS if c.startswith("fade_tau_")]
    bands = {b: [w for w in WINDOWS if w.band == b] for b in BAND_ORDER}

    print()
    print("[bench-3]  fading memory -- the pre-registered promotion bar")
    print(
        "  per band, the MEDIAN over that band's windows of  day-3 RMS(gate arm) / "
        "day-3 RMS(fade tau)"
    )
    print("  a ratio ABOVE 1 means fading memory is BETTER")
    print(
        f"  promotion needs a SINGLE tau at >= {BENCH3_GAIN}x in at least "
        f"{BENCH3_MIN_BANDS} bands, with NO band below {BENCH3_FLOOR}x "
        f"(= none more than 1.25x worse)"
    )
    print("  default: DEFER")
    print(
        "  band sizes: "
        + ", ".join(f"{b} {len(bands[b])}" for b in BAND_ORDER)
        + " -- the two 2-window medians are means of two, and are read as such"
    )

    print("  per-window day-3 ratios, the inputs to every median below")
    print(
        "  "
        + f"{'window':<18}{'band':<10}"
        + "".join(f"{t.replace('fade_tau_', 'tau '):>12}" for t in tau_ids)
    )
    for w in WINDOWS:
        g = rows[(w.name, arm_of[w.name], 3)][3]
        cells = "".join(f"{g / rows[(w.name, t, 3)][3]:>12.3f}" for t in tau_ids)
        print(f"  {w.name:<18}{w.band:<10}{cells}")

    print("  band medians")
    print(
        "  "
        + f"{'tau':<8}"
        + "".join(f"{b:>11}" for b in BAND_ORDER)
        + f"{'bands >= ' + str(BENCH3_GAIN) + 'x':>16}{'min band':>10}  verdict"
    )
    promoted: list[str] = []
    for t in tau_ids:
        meds = {
            b: statistics.median(
                [
                    rows[(w.name, arm_of[w.name], 3)][3] / rows[(w.name, t, 3)][3]
                    for w in bands[b]
                ]
            )
            for b in BAND_ORDER
        }
        n_gain = sum(1 for b in BAND_ORDER if meds[b] >= BENCH3_GAIN)
        worst = min(meds.values())
        ok = n_gain >= BENCH3_MIN_BANDS and worst >= BENCH3_FLOOR
        if ok:
            promoted.append(t)
        print(
            f"  {t.replace('fade_tau_', ''):<8}"
            + "".join(f"{meds[b]:>11.3f}" for b in BAND_ORDER)
            + f"{n_gain:>16}{worst:>10.3f}  {'CLEARS' if ok else 'no'}"
        )
    if promoted:
        print(f"  VERDICT [bench-3]: PROMOTE -- {', '.join(promoted)} clears the bar")
    else:
        print(
            "  VERDICT [bench-3]: DEFER -- no single tau clears the bar "
            "(the pre-registered default)"
        )

    worst_key = max(fades, key=lambda k: fades[k][1])
    print(
        f"  the fade rows alone run at max_iterations {FADE_MAX_ITERATIONS} "
        f"(run_tle_window.py:181), which caps EVALUATIONS as well as iterations"
    )
    print(
        f"  worst demand over the {len(fades)} weighted fits: {fades[worst_key][1]} "
        f"evaluations ({worst_key[0]}, "
        f"{worst_key[1].replace('fade_tau_', 'tau ')})"
    )
    print(
        f"  a promotion to sec 1.2 would therefore have to raise the shipped "
        f"max_iterations {SHIPPED_MAX_ITERATIONS} past that maximum -- the cost of "
        f"promoting"
    )


def sensitivity(rows: dict, arm_of: dict[str, str]) -> None:
    """Re-score bench-1 and bench-2 with the third mapping row read as arm_zero."""
    alt = {
        w.name: ("arm_zero" if arm_of[w.name] == "arm_fresh" else arm_of[w.name])
        for w in WINDOWS
    }
    changed = [w.name for w in WINDOWS if alt[w.name] != arm_of[w.name]]
    _, tie_a = bench1(rows, arm_of, quiet=True)
    _, tie_b = bench1(rows, alt, quiet=True)
    g_a, _ = bench2(rows, arm_of, quiet=True)
    g_b, _ = bench2(rows, alt, quiet=True)

    print()
    print("[sensitivity]  NOT a result -- the third mapping row's free-vs-held ambiguity")
    print(
        "  the playbook's third row ('freshest 1 d fit') is read as arm_fresh "
        "(free B*); substituting arm_zero gives:"
    )
    print(
        f"  windows whose selected arm changes: {len(changed)}"
        + (f" ({', '.join(changed)})" if changed else " (none)")
    )
    print(f"  bench-1 tie rule: {rate(tie_a)}  ->  {rate(tie_b)}")
    print(f"  bench-2 gate    : {rate(g_a)}  ->  {rate(g_b)}")
    print(
        "  both configurations are measured in every window either way, so neither "
        "reading loses evidence"
    )


def misclass(gates: dict, rows: dict, arm_of: dict[str, str]) -> None:
    """Every cell whose gate-selected arm was not in the correct set."""
    print()
    print("[misclass]  every cell whose gate-selected arm was NOT in the correct set")
    print(
        "  a misclassification IS the finding (contract), so these are listed, not "
        "explained away"
    )
    print(
        f"  severity = RMS(gate arm) / RMS(best arm) at that cell; {TIE} is the tie "
        f"boundary"
    )
    print(
        "  NO horizon reading here: the playbook's <= 1 d / ~3 d / >= 4 d scoping is "
        "interpreted in the README, never in this file"
    )
    n_cells = n_windows = 0
    for w in WINDOWS:
        g = gates[w.name]
        a = arm_of[w.name]
        bad = []
        for d in READ_DAYS:
            ok, vals, best = correct_at(rows, w.name, d)
            if a not in ok:
                bad.append((d, min(vals, key=lambda k: vals[k]), vals[a] / best))
        if not bad:
            continue
        n_windows += 1
        n_cells += len(bad)
        print(
            f"  {w.index:>3}  {w.name:<18}{w.band:<10}r {g['r']:>9.4g}  "
            f"s {g['s']:>9.4g}  gate {a}"
        )
        for d, winner, sev in bad:
            print(f"       day {d}: won by {winner:<16}severity {sev:>7.2f}x")
    if n_cells == 0:
        print("  none -- the gate's arm was in the correct set at all 30 cells")
    else:
        print(
            f"  {n_cells} of {N_CELLS} cells misclassified, across {n_windows} of "
            f"{len(WINDOWS)} windows"
        )


def posthoc(gates: dict, rows: dict) -> None:
    """Exhaustive search over every REACHABLE (R, S), labelled post-hoc."""
    print()
    print("[post-hoc]  POST-HOC AND SEPARATE -- NOT a claim that the frozen gate passed")
    print(
        "  the frozen thresholds are pre-registered predictions and are NOT revised "
        "by this block."
    )
    print(
        "  Re-fitting them to this data and reporting that they classify correctly "
        "would be"
    )
    print("  circular, and the contract forbids it. This is an observation, not a result.")
    print(
        "  objective: the [bench-2] correct-set hit rate over the same 30 cells, "
        "with (R,S) substituted into the same mapping"
    )
    print(
        "  search: EXHAUSTIVE, not a sweep -- the classification depends on (R,S) "
        "only through (r < R, s < S)"
    )
    print("  across the ten windows, so the reachable thresholds form a finite grid")

    rv = sorted({gates[w.name]["r"] for w in WINDOWS})
    sv = sorted({gates[w.name]["s"] for w in WINDOWS})

    def rep(vals: list[float], j: int) -> float:
        """A representative threshold admitting exactly the j smallest values."""
        return vals[j] if j < len(vals) else float("inf")

    def interval(vals: list[float], j: int, sym: str) -> str:
        if j == 0:
            return f"{sym} <= {vals[0]:.4g}"
        if j == len(vals):
            return f"{sym} > {vals[-1]:.4g}"
        return f"{vals[j - 1]:.4g} < {sym} <= {vals[j]:.4g}"

    correct = {
        (w.name, d): correct_at(rows, w.name, d)[0] for w in WINDOWS for d in READ_DAYS
    }

    def score(r_thr: float, s_thr: float) -> int:
        hits = 0
        for w in WINDOWS:
            g = gates[w.name]
            a = arm_for(g["r"], g["s"], r_thr, s_thr)
            hits += sum(a in correct[(w.name, d)] for d in READ_DAYS)
        return hits

    results = {
        (jr, js): score(rep(rv, jr), rep(sv, js))
        for jr in range(len(rv) + 1)
        for js in range(len(sv) + 1)
    }
    print(
        f"  {len(results)} distinct partitions enumerated "
        f"({len(rv) + 1} x {len(sv) + 1})"
    )

    frozen = (
        sum(1 for v in rv if v < R_THRESHOLD),
        sum(1 for v in sv if v < S_THRESHOLD),
    )
    best = max(results.values())
    winners = sorted(k for k, v in results.items() if v == best)

    print(f"  frozen  r < {R_THRESHOLD}, s < {S_THRESHOLD} : {rate(results[frozen])}")
    print(
        f"  best reachable                : {rate(best)}, attained by "
        f"{len(winners)} of {len(results)} regions"
    )
    if best == results[frozen]:
        print(
            "  the frozen thresholds are already among the best-scoring regions on "
            "this data"
        )
    shown = winners[:12]
    for jr, js in shown:
        arms = [
            arm_for(gates[w.name]["r"], gates[w.name]["s"], rep(rv, jr), rep(sv, js))
            for w in WINDOWS
        ]
        counts = ", ".join(f"{a.replace('arm_', '')} {arms.count(a)}" for a in ARM_IDS)
        star = "  <- contains the frozen (0.05, 0.1)" if (jr, js) == frozen else ""
        print(
            f"    {interval(rv, jr, 'R'):<30}{interval(sv, js, 'S'):<30}"
            f"[{counts}]{star}"
        )
    if len(winners) > len(shown):
        print(f"    ... {len(winners) - len(shown)} more region(s) at the same rate")


def also_recorded(
    gates: dict, rows: dict, cats: dict, states: dict, seps: dict
) -> None:
    """Staleness vs outcome, the re-derived ranges, state drift, convergence."""
    print()
    print("[also-recorded]")

    print("  catalogue staleness against its own row's outcome, sorted by staleness")
    print(
        "  n = 10, so no correlation is computed or claimed -- this is the table, "
        "read it as one"
    )
    print(
        f"  {'window':<18}{'stale h':>9}{'day 1':>10}{'day 3':>10}{'day 7':>10}"
        f"{'vs naive d7':>13}"
    )
    for w in sorted(WINDOWS, key=lambda w: cats[w.name]["stale_d"]):
        d1, d3, d7 = (rows[(w.name, "catalog", d)][3] for d in READ_DAYS)
        print(
            f"  {w.name:<18}{24.0 * cats[w.name]['stale_d']:>9.2f}{d1:>10.1f}"
            f"{d3:>10.1f}{d7:>10.1f}"
            f"{d7 / rows[(w.name, 'naive_2d', 7)][3]:>13.3f}"
        )

    print("  cross-tag ranges RE-DERIVED from the ten committed window files")
    print(
        "  checked against the provisional figures in catalog_tles.py's docstring "
        "and the study README; where they differ, the re-derivation is authoritative"
    )
    measured = {
        "vs C (m)": (
            min(cats[w.name]["rms_c"] for w in WINDOWS),
            max(cats[w.name]["rms_c"] for w in WINDOWS),
            1.0,
        ),
        "vs D (km)": (
            min(cats[w.name]["rms_d"] for w in WINDOWS),
            max(cats[w.name]["rms_d"] for w in WINDOWS),
            1e3,
        ),
        "ratio (x)": (
            min(cats[w.name]["ratio"] for w in WINDOWS),
            max(cats[w.name]["ratio"] for w in WINDOWS),
            1.0,
        ),
        "C-D separation (km)": (min(seps.values()), max(seps.values()), 1.0),
    }
    print(
        f"  {'quantity':<22}{'re-derived':<20}{'provisional':<18}{'worst delta':>12}"
        f"  status"
    )
    for key, (lo, hi, scale) in measured.items():
        lo, hi = lo / scale, hi / scale
        was_lo, was_hi, dec = PROVISIONAL[key]
        delta = max(abs(lo - was_lo), abs(hi - was_hi))
        tol = 0.5 * 10.0 ** (-dec)  # half the provisional's own last digit
        print(
            f"  {key:<22}{f'{lo:.1f} - {hi:.1f}':<20}"
            f"{f'{was_lo:.{dec}f} - {was_hi:.{dec}f}':<18}{delta:>12.2f}"
            f"  {'unchanged' if delta <= tol else 'SUPERSEDED'}"
        )
    print(
        "  'unchanged' means the re-derivation agrees within half of the "
        "provisional's own last digit -- not that the digits match as text"
    )
    print(
        "  C-D separation is a PER-DAY RMS of |r_C - r_D| over forecast day 1 "
        "(catalog_tles.py:337), printed to 0.1 km"
    )
    print(
        "  the provisional figures came from a one-time uncommitted sweep whose "
        "output is not retained, so a disagreement is recorded and its cause is not "
        "guessed at here"
    )

    print("  state rows: forecast degradation against the measured reference drift")
    print(
        "  drift = TSTATE arc RMS (m); dN = that row's day-N RMS / naive_2d's "
        "day-N RMS"
    )
    print(
        f"  {'window':<18}{'sphere drift':>13}{'d1':>7}{'d3':>7}{'d7':>7}"
        f"{'box drift':>12}{'d1':>7}{'d3':>7}{'d7':>7}"
    )
    for w in WINDOWS:
        cells = ""
        for cfg, width in (("state_sphere", 13), ("state_box", 12)):
            cells += f"{states[(w.name, cfg)][0]:>{width}.1f}"
            for d in READ_DAYS:
                cells += (
                    f"{rows[(w.name, cfg, d)][3] / rows[(w.name, 'naive_2d', d)][3]:>7.2f}"
                )
        print(f"  {w.name:<18}{cells}")
    print(
        "  degradation roughly the size of the reference drift is EXPECTED and is "
        "not a bar -- the a-priori tables cannot meet sec 1.2's single-digit-% bar"
    )

    print("  convergence and in-arc RMS class over the ten windows")
    print(
        "  every fit in every window converged: run_tle_window.py hard-exits on "
        "TLEFitError, so ten committed files ARE the convergence record"
    )
    print(f"  {'configuration':<16}{'min in-arc':>12}{'max in-arc':>12}  past 2 km")
    for c in CONFIG_IDS:
        vals = [rows[(w.name, c, READ_DAYS[0])][4] for w in WINDOWS]
        if all(v < 0 for v in vals):
            print(f"  {c:<16}{'-':>12}{'-':>12}  n/a -- this row fits nothing")
            continue
        over = [w.name for w in WINDOWS if rows[(w.name, c, READ_DAYS[0])][4] > 2000.0]
        # Named while the list stays short; past that the count is the reading
        # and the per-window files carry the names.
        if not over:
            note = "0"
        elif len(over) <= 4:
            note = f"{len(over)}: " + ", ".join(over)
        else:
            note = f"{len(over)} of {len(WINDOWS)}"
        print(f"  {c:<16}{min(vals):>12.1f}{max(vals):>12.1f}  {note}")
    print(
        "  the SGP4 representation floor on a GNV1B arc is ~500-700 m; the short-tau "
        "fade rows sit above 2 km by construction, because age weighting stops "
        "fitting the old half of the arc"
    )


def decision(rows: dict, arm_of: dict[str, str]) -> None:
    """The chunk's fourth checklist item: what Chunk 22 inherits."""
    _, tie = bench1(rows, arm_of, quiet=True)
    gate_hits, fixed = bench2(rows, arm_of, quiet=True)
    b1 = tie >= BENCH1_BAR
    b2 = all(gate_hits > fixed[a] for a in ARM_IDS)

    print()
    print(
        "[playbook-revision]  the decision this chunk records; the doc rewrite is "
        "Chunk 22"
    )
    print(
        f"  bench-1 (gate beats naive, >= {BENCH1_BAR}/{N_CELLS}) : "
        f"{'HIT' if b1 else 'MISS'}"
    )
    print(f"  bench-2 (gate beats every fixed arm)  : {'HIT' if b2 else 'MISS'}")
    if b1 and b2:
        print(
            "  -> the gate transfers. The playbook records that its thresholds now "
            "rest on this"
        )
        print(
            "     study's ten-window set rather than a single satellite (contract, "
            "Deliverable 3)."
        )
    elif b1 and not b2:
        best_fixed = max(ARM_IDS, key=lambda a: fixed[a])
        print(
            "  -> the gate beats the naive fit but does NOT beat every fixed arm, so "
            "on this data it is"
        )
        print(
            f"     REDUNDANT rather than wrong: always-{best_fixed} does as well or "
            f"better."
        )
        print(
            "     The playbook is revised TOWARD that arm (contract), not against "
            "the gate."
        )
    else:
        print(
            "  -> bench-1 missed. The playbook is CORRECTED rather than left standing"
        )
        print(
            "     (contract, Deliverable 3), and the miss is written down as a miss."
        )
    print(
        "  the horizon qualifiers on mapping rows 2 and 3 are part of that revision "
        "and are read"
    )
    print("  in the README and the findings document, never scored here")


def main() -> None:
    gates, rows, cats, states = parse_files()
    fades, seps = parse_extras()

    print("=" * 78)
    print("Extended validation -- Part 3 TLE fitting, Chunk 18 adjudication")
    print("=" * 78)
    print(f"  source: {RESULTS_DIR.name}/ -- a text pass over committed evidence")
    print(
        "  no JVM, no propagation, no re-run: every number below derives from a "
        "committed file"
    )
    print(
        "  every RMS is PER-DAY: day N is the RMS over [N-1 d, N d] past T alone, "
        "never accumulated"
    )
    print(
        f"  TIE RULE (contract): anchor scatter runs 2-3x, so differences under "
        f"{TIE}x are noise and both options count as correct"
    )
    print(
        "  the frozen gate is carried verbatim and never re-fitted; see [post-hoc] "
        "for the label"
    )

    integrity(gates, rows, fades, seps)
    arm_of = {w.name: gates[w.name]["arm"] for w in WINDOWS}

    bench1(rows, arm_of)
    bench2(rows, arm_of)
    bench3(rows, arm_of, fades)
    sensitivity(rows, arm_of)
    misclass(gates, rows, arm_of)
    posthoc(gates, rows)
    also_recorded(gates, rows, cats, states, seps)
    decision(rows, arm_of)

    print()
    print(f"  {len(WINDOWS)}/10 windows adjudicated")


if __name__ == "__main__":
    main()
