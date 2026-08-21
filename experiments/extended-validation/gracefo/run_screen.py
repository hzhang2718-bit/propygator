"""Both maneuver gates over the ten frozen windows -- Chunk 1's committed evidence.

Evidence for ``docs/build-plan-extended-validation-updated.md`` Chunk 1. Every
window is gated BEFORE any compute is spent on it: Part 2 costs roughly 16 h and
Part 3 rides the same truth, so a burn discovered at Chunk 9 would retire a
window after its propagations had already been paid for.

    conda run -n propygator python run_screen.py
    conda run -n propygator python run_screen.py --window storm_2026_01 --parse-only

THE TWO GATES.

- **Tier 1, THR1B** (exact, JVM-free). Clean iff ``accum_dur_orb_ctrl`` never
  moves and every ``on_time_orb_ctrl_1``/``_2`` is zero across all 14 days, for
  both satellites. No threshold to fix, and -- the reason it exists --
  unconfounded by storms, where the polynomial is weakest.
- **Tier 2, the v0.7.2 degree-5 departure test** (the secondary gate). Fit a
  degree-5 polynomial to the along-track residual of a drag-on Cd = 2.3
  propagation over the full 14-day load; clean iff the maximum departure is
  under 10 % of the maximum along-track signal. It stays because it catches what
  a thruster log cannot: safe-mode entries, attitude anomalies and bad truth
  days.

THE TIER-2 THRESHOLD IS PRE-REGISTERED, not tuned. It is carried verbatim from
``real-world-validation/gracefo/run_gracefo.py:575-586`` -- the same rule, the
same 10 %, applied to this study's longer span. The contract requires it to be
fixed before screening begins, so it is stated here and in the output header and
is not revisited after seeing a number. Two consequences, recorded rather than
engineered away: a degree-5 polynomial has less freedom over 14 days than over
the 3 the rule was calibrated on, so tier 2 is a blunter net here than it was
there; and on a storm window a real onset is itself a slope kink, so a tier-2
departure on windows 6, 8 and 10 documents the storm rather than a burn. Tier 1
is the gate that is trusted on those.

Runs every window in one process and closes with a computed ``[summary]``
block -- the cross-window verdict is the chunk's deliverable, so it is computed
here rather than transcribed into a README afterwards. ``--window`` may be
repeated for debugging; it just cannot produce a complete summary.

Reference-only: not shipped, not in CI, outside ``testpaths``. Runs in the
propygator conda env (starts the JVM, needs orekit-data). Stdout is ASCII-only
(captured under cp1252); ``--parse-only`` stops before the JVM-touching steps.
"""

from __future__ import annotations

import argparse
import sys
import time as _time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_STUDY = _HERE.parent
_REPO = _STUDY.parents[1]  # experiments/extended-validation -> repo root
_FROZEN = _STUDY.parent / "real-world-validation"
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_FROZEN))
sys.path.insert(0, str(_FROZEN / "gracefo"))

# Frozen v0.7.2 modules -- imported, never edited (contract, "The earlier
# experiment is frozen"). find_window_files is deliberately NOT imported: it
# does not glob .gz, which is what this study's tree holds. windows.py carries
# this study's own finder.
from common import ric_components  # noqa: E402
from gnv1b import parse_gnv1b  # noqa: E402

from gracefo_ext_common import (  # noqa: E402
    A_REF_M2,
    CD_NOMINAL,
    NORAD_IDS,
    SUBSAMPLE_S,
    force_config,
    sphere_spacecraft,
    window_mass_kg,
)
from mas1b import parse_mas1b  # noqa: E402
from thr1b import format_screen, screen_thr1b  # noqa: E402
from windows import (  # noqa: E402
    DATA_ROOT,
    SAT_IDS,
    WINDOW_DAYS,
    WINDOWS,
    Window,
    check_frozen_table,
    check_window_files,
    cssi_display_name,
    cssi_path,
    cssi_updated,
    find_product_files,
    observed_end,
    read_cssi,
    resolve,
    window_indices,
)

from propygator import (  # noqa: E402
    Epoch,
    Frame,
    IntegratorConfig,
    State,
    propagate_numerical,
)

# THE PRE-REGISTERED TIER-2 RULE. v0.7.2 run_gracefo.py:586, carried verbatim.
TIER2_FRACTION = 0.10
TIER2_POLY_DEGREE = 5
# v0.7.2's reference reading, quoted so the bar has a scale: a 186.6 m
# along-track signal with a 6.7 m degree-5 departure was called clean (3.6 %).
V072_REFERENCE = (186.6, 6.7)

# t0 round-trip bound, RAISED from the build plan's original 5e-9 m (2026-08-18,
# maintainer). ITRF -> EME2000 -> ITRF is a pure float round-trip through two
# rotations, so its floor is set by double precision at |r|: one ulp at
# 6.8746e6 m is 9.3e-10 m. Measured hourly across all three frozen v0.7.2
# windows, both satellites (1,152 epochs, 2026-08-19): median 5.6e-9 m
# (~6 ulps), worst 2.99e-8 m (~32 ulps, active_2023 D). The old 5e-9 m bound is
# ~5.4 ulps and rejects most valid epochs -- it had been set just above the
# frozen study's single observed 4.2e-9 m, which was one draw from this same
# distribution. 5e-8 m clears the measured worst case by 1.7x -- quote that, not
# the handful of t0 readings, if the bound is ever re-argued. This is a WIRING
# check (did the conversion round-trip at all), never a physical measurement.
T0_ROUNDTRIP_TOL_M = 5e-8

# Truth-grid continuity bound. _tier2 aligns propagated samples to truth BY
# ARRAY INDEX against a uniform t0 + k*SUBSAMPLE_S grid, so one missing truth
# epoch shifts every later comparison by a full step (~456 km of along-track) --
# a false REVIEW retiring a clean window. parse_gnv1b drops non-zero-qualflg
# records BEFORE subsampling, so one flagged record on a grid point does it.
# A short TAIL is harmless and deliberately not checked: _tier2 clips to
# min(len(positions), len(eph.epochs)) and t0 always aligns. The bar only has to
# sit far below one step. Measured on window 1, both satellites: exactly 0.0 s.
GRID_CONTINUITY_TOL_S = 1e-6


def _pkg_version(name: str) -> str:
    try:
        return version(name)
    except PackageNotFoundError:
        return "unknown"


def _display_path(path: Path) -> str:
    """Repo-relative, forward-slashed, so the evidence is machine-independent."""
    try:
        return path.relative_to(_REPO).as_posix()
    except ValueError:
        return str(path)


def _print_header(data_root: Path) -> None:
    print("=" * 78)
    print("Extended validation -- Chunk 1: maneuver screening, ten windows")
    print("=" * 78)
    print(
        f"[versions] propygator {_pkg_version('propygator')}, "
        f"orekit_jpype {_pkg_version('orekit_jpype')}, numpy {np.__version__}"
    )
    print(f"[data root] {_display_path(data_root)}")
    print(
        f"[convention] A_ref = {A_REF_M2:.7f} m^2, Cd = {CD_NOMINAL}, "
        f"mass = MAS1B dry + tank gas, PER SATELLITE"
    )
    print(
        f"[pre-registered] tier-2: degree-{TIER2_POLY_DEGREE} fit to the "
        f"{WINDOW_DAYS}-day along-track residual, CLEAN iff max departure < "
        f"{TIER2_FRACTION:.0%} of max |along-track|."
    )
    print(
        f"                 carried verbatim from v0.7.2 run_gracefo.py:586, whose "
        f"reference reading was {V072_REFERENCE[0]:.1f} m signal / "
        f"{V072_REFERENCE[1]:.1f} m departure "
        f"({100.0 * V072_REFERENCE[1] / V072_REFERENCE[0]:.1f}%)."
    )
    print(
        "                 Fixed before screening began; not revisited after "
        "seeing a number."
    )
    print()


def _preflight(flux: str = "obs") -> None:
    """Verify the frozen ten-window table against CSSI. JVM-free, seconds.

    Runs before anything expensive because a transcription error in the window
    table would otherwise propagate into every downstream chunk. The transcribed
    aggregates are a checksum on the table, never an input to a run.
    """
    print("[pre-flight] frozen window table vs CSSI (JVM-free)")
    path = cssi_path()
    cssi = read_cssi(path)
    end = observed_end(cssi)
    # Named relative to orekit-data, never resolved: orekit-data lives outside
    # the repo on this machine, so an absolute path would leak a home directory
    # and red --verify elsewhere. The UPDATED stamp is the provenance that
    # matters, and it moves when orekit-data is refreshed.
    print(f"  source: {cssi_display_name()}  (UPDATED {cssi_updated(path)})")
    print(f"  {len(cssi)} daily records; OBSERVED block ends {end}")
    print(
        f"  flux convention: {flux} "
        f"(NRLMSISE-00 is built on the observed series, which is what Orekit's "
        f"CssiSpaceWeatherData feeds it)"
    )

    bad = check_frozen_table(cssi, flux=flux)
    print(
        f"  table check: {len(bad)} mismatching cell(s) across "
        f"{len(WINDOWS)} windows x 7 fields -> {'CLEAN' if not bad else 'MISMATCH'}"
    )
    for name, field, want, got in bad:
        print(f"    {name:18s} {field:14s} table {want:8.2f}  measured {got:8.2f}")

    print(
        f"  {'window':18s} {'f107':>7s} {'lo':>6s} {'hi':>6s} {'flat':>6s} "
        f"{'ctr81':>7s} {'Ap':>5s} {'ap3':>5s} {'Kp':>5s} {'pred':>5s}"
    )
    n_predicted = 0
    for window in WINDOWS:
        g = window_indices(window, cssi, flux=flux)
        n_predicted += int(g["n_predicted"])
        print(
            f"  {window.name:18s} {g['f107']:7.1f} {g['f107_lo']:6.1f} "
            f"{g['f107_hi']:6.1f} {g['f107_flatness']:6.3f} {g['ctr81']:7.1f} "
            f"{g['ap_max']:5.0f} {g['ap3_max']:5.0f} {g['kp_max']:5.1f} "
            f"{g['n_predicted']:5.0f}"
        )
    print(
        f"  days on daily-PREDICTED rows: {n_predicted} "
        f"(must be 0 -- predicted rows carry a flat placeholder ap/Kp, so a "
        f"storm there would contain no storm in the model)"
    )
    if bad or n_predicted:
        raise SystemExit(
            "  pre-flight FAILED -- resolve before screening; the window list is "
            "frozen evidence and a mismatch is a bug report, not an amendment"
        )
    print()


def _load(window: Window, data_root: Path) -> tuple[dict, dict]:
    """Parse GNV1B + MAS1B for both satellites over the window's full 14 days."""
    window_dir = data_root / window.name
    eph: dict[str, object] = {}
    mas: dict[str, object] = {}
    for sat in SAT_IDS:
        gnv = find_product_files(window_dir, "GNV1B", sat, days=WINDOW_DAYS)
        mass = find_product_files(window_dir, "MAS1B", sat, days=WINDOW_DAYS)
        eph[sat] = parse_gnv1b(gnv, sat_id=sat, subsample_s=SUBSAMPLE_S)
        mas[sat] = parse_mas1b(mass, sat_id=sat)
    return eph, mas


def _tier2(
    state0: State, span_s: float, eph, mass_kg: float
) -> tuple[float, float, bool, float, bool]:
    """The degree-5 departure test. Returns (signal, departure, clean, wall, term)."""
    t_wall = _time.perf_counter()
    traj = propagate_numerical(
        state0,
        span_s,
        output_step=SUBSAMPLE_S,
        force_models=force_config(True),
        spacecraft=sphere_spacecraft(CD_NOMINAL, mass_kg=mass_kg),
        integrator=IntegratorConfig.high_precision(),
        progress=False,
    )
    dt = _time.perf_counter() - t_wall
    # A guard trip would silently shorten the screened span, which is the one
    # way this gate could report CLEAN on a window it never fully examined.
    terminated = bool(traj.metadata.get("terminated"))
    positions = traj.to_frame(Frame.ITRF).positions

    n = min(len(positions), len(eph.epochs))
    diff = positions[:n] - eph.positions_m[:n]
    along = ric_components(
        diff, eph.positions_m[:n], eph.velocities_ms[:n], earth_fixed=True
    )[:, 1]
    t_rel = np.arange(n) * SUBSAMPLE_S
    coef = np.polyfit(t_rel, along, TIER2_POLY_DEGREE)
    departure = float(np.max(np.abs(along - np.polyval(coef, t_rel))))
    signal = float(np.max(np.abs(along)))
    clean = departure < TIER2_FRACTION * max(signal, 1.0)
    return signal, departure, clean, dt, terminated


def run_window(
    window: Window, data_root: Path, *, parse_only: bool
) -> dict[str, dict[str, bool]]:
    """Screen one window on both gates and both satellites."""
    print("=" * 78)
    print(
        f"=== window {window.index:02d}  {window.name}  "
        f"({window.band}, {window.t0} .. {window.days[-1]}) ==="
    )
    print("=" * 78)
    if window.note:
        print(f"[note] {window.note}")

    window_dir = data_root / window.name
    check_window_files(window, window_dir)
    eph, mas = _load(window, data_root)

    print("[parse]")
    for sat in SAT_IDS:
        e = eph[sat]
        print(
            f"  {sat} = {e.sat_name} (NORAD {NORAD_IDS[sat]}), platform "
            f"{e.platform!r} v{e.product_version}, {len(e.source_files)} daily files"
        )
        print(
            f"    1 Hz records {e.n_raw_records} (QC-dropped {e.n_dropped_qc}); "
            f"subsampled to {SUBSAMPLE_S:.0f} s -> {len(e.epochs)} epochs"
        )
        print(f"    seam gaps > 1.5 s: {e._n_gaps} (max gap {e._max_gap_s:.1f} s)")
        print(
            f"    span: {e.epochs[0].to_iso()} -> {e.epochs[-1].to_iso()} "
            f"{e.epochs[0].scale.value}"
        )

    print("[mass]  MAS1B tank gas, both tanks (L1 Handbook sec 4.2.17)")
    mass_kg: dict[str, float] = {}
    for sat in SAT_IDS:
        m = mas[sat]
        mass_kg[sat] = window_mass_kg(m.gas_mean_kg)
        print(
            f"  {sat}: gas mean {m.gas_mean_kg:.4f} kg over {m.n_records} records "
            f"(range {m.gas_min_kg:.4f}..{m.gas_max_kg:.4f}) "
            f"-> total {mass_kg[sat]:.3f} kg"
        )
        if m.empty_files:
            # MAS1B is periodic, so a zero-record day is an OUTAGE, not a quiet
            # day. Named, with the bound it puts on the mean, so the reader can
            # see the gap is immaterial instead of being told it is.
            bound = m.mean_shift_bound_kg
            print(
                f"     {len(m.empty_files)} day(s) declare num_records: 0 "
                f"({', '.join(m.empty_files)}) -- telemetry outage, not a "
                f"truncated file (header cross-checked)"
            )
            print(
                f"     the mean is over the {m.n_records} records that exist; "
                f"the missing days can move it by at most {bound:.4f} kg "
                f"({100.0 * bound / mass_kg[sat]:.4f}% of total mass), against a "
                f"CD_FIT_TOL resolution of ~0.05-0.1% in Cd"
            )

    print("[parser checks]")
    for sat in SAT_IDS:
        e = eph[sat]
        n = len(e.epochs)
        exact = all(Epoch.from_iso(ep.to_iso(), ep.scale) == ep for ep in e.epochs)
        dts = np.array(
            [e.epochs[i + 1].seconds_since(e.epochs[i]) for i in range(n - 1)]
        )
        r0 = float(np.linalg.norm(e.positions_m[0]))
        max_dt_error = float(np.max(np.abs(dts - SUBSAMPLE_S)))
        print(
            f"  {sat}: from_iso(to_iso()) == epoch for all {n}: {exact}; "
            f"max |dt - {SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s"
        )
        print(f"     |r0| = {r0 / 1e3:.1f} km (altitude ~ {r0 / 1e3 - 6378.1:.0f} km)")
        if not exact:
            raise SystemExit(
                f"{sat}: epoch round trip not exact -- fix before reading on"
            )
        if max_dt_error > GRID_CONTINUITY_TOL_S:
            raise SystemExit(
                f"{sat}: truth grid has an interior hole -- max |dt - "
                f"{SUBSAMPLE_S:.0f} s| = {max_dt_error:.3e} s. The tier-2 diff "
                f"aligns by array index, so every sample after the hole would be "
                f"compared against truth one step later (~456 km of along-track) "
                f"and the window would read as a false REVIEW. Resolve the "
                f"dropped record before screening this window."
            )

    # TIER 1 RUNS BEFORE THE --parse-only RETURN, AND BEFORE ANYTHING THAT
    # TOUCHES THE JVM -- the t0 round-trip below is the first JVM-touching step,
    # matching the frozen Chunk 0 driver's convention.
    #
    # --parse-only is a JVM-FREE DEBUGGING GATE OVER A LANDED WINDOW, not a
    # check to run while windows are still coming down: _load above already
    # needs all 14 days of GNV1B and MAS1B for both satellites, so it costs
    # ~15 s per window and raises on any window not fully landed. The
    # while-landing check is fetch_windows.py, which screens each window as its
    # fourteenth day lands.
    verdicts: dict[str, dict[str, bool]] = {}
    print("[screen tier-1 THR1B]  exact gate, no threshold, storm-proof")
    for sat in SAT_IDS:
        files = find_product_files(window_dir, "THR1B", sat, days=WINDOW_DAYS)
        screen = screen_thr1b(files, sat_id=sat)
        for line in format_screen(screen):
            print(line)
        verdicts[sat] = {"tier1": screen.clean}

    if parse_only:
        print("[parse-only] stopping before JVM-touching steps")
        print()
        return verdicts

    print("[t0 sanity]  ITRF -> EME2000 -> ITRF, isolated from dynamics")
    state0: dict[str, State] = {}
    for sat in SAT_IDS:
        e = eph[sat]
        s0 = State(
            e.epochs[0], e.positions_m[0], e.velocities_ms[0], Frame.ITRF
        ).to_frame(Frame.EME2000)
        state0[sat] = s0
        back = s0.to_frame(Frame.ITRF)
        dr = float(np.linalg.norm(back.position - e.positions_m[0]))
        dv = float(np.linalg.norm(back.velocity - e.velocities_ms[0]))
        print(
            f"  {sat}: |dr| = {dr:.3e} m, |dv| = {dv:.3e} m/s "
            f"(bound {T0_ROUNDTRIP_TOL_M:.0e} m)"
        )
        if dr > T0_ROUNDTRIP_TOL_M:
            raise SystemExit(
                f"{sat}: t0 round trip {dr:.3e} m exceeds "
                f"{T0_ROUNDTRIP_TOL_M:.0e} m"
            )

    print(
        f"[screen tier-2 deg-{TIER2_POLY_DEGREE}]  drag-on Cd = {CD_NOMINAL} over "
        f"the full {WINDOW_DAYS}-day load"
    )
    for sat in SAT_IDS:
        e = eph[sat]
        span_s = e.epochs[-1].seconds_since(e.epochs[0])
        signal, departure, clean, wall, terminated = _tier2(
            state0[sat], span_s, e, mass_kg[sat]
        )
        # The printed call must be the RECORDED verdict, not the departure test
        # alone -- a terminated trajectory is not clean however small its
        # departure, and a body line saying CLEAN under a [summary] row saying
        # REVIEW would break the standalone-readability rule this chunk is built
        # on.
        verdict = clean and not terminated
        verdicts[sat]["tier2"] = verdict
        if verdict:
            call = "CLEAN"
        elif not clean:
            call = "REVIEW -- kink"
        else:
            call = "REVIEW -- terminated"
        print(
            f"  {sat}: signal {signal:.1f} m, departure {departure:.1f} m "
            f"({100.0 * departure / max(signal, 1.0):.1f}%) -> "
            f"{call}  ({wall:.0f} s wall)"
        )
        if terminated:
            print(
                f"     TERMINATED trajectory ({e.sat_name}) -- a guard tripped, so "
                f"the screened span is short of {span_s / 86400.0:.1f} d. Treated "
                f"as NOT CLEAN regardless of the departure."
            )
        # THE ONLY TRUE-POSITIVE TEST TIER 2 GETS. Swarm has no THR1B analogue,
        # so the polynomial is its ONLY maneuver gate -- and nothing else in this
        # study exercises it against a maneuver known to be real. A tier-1 BURN
        # is exactly that known positive, so record whether tier 2 saw it. A MISS
        # here is a finding about the Swarm screen, not about this window.
        if not verdicts[sat]["tier1"]:
            print(
                f"     TIER-2 TRUE-POSITIVE CHECK -- tier 1 reports a burn on "
                f"{sat}, and tier 2 {'CAUGHT' if not clean else 'MISSED'} it "
                f"({100.0 * departure / max(signal, 1.0):.1f}% departure against "
                f"the {TIER2_FRACTION:.0%} bar). Swarm is screened by tier 2 "
                f"alone, so this is the only calibration of that gate against a "
                f"maneuver known to be real."
            )
        if window.is_storm and not clean:
            print(
                "     storm window: a real onset is itself a slope kink, so this "
                "departure documents the storm, not a burn. Tier 1 is the gate "
                "that is trusted here."
            )
    print()
    return verdicts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--window",
        action="append",
        default=None,
        metavar="NAME",
        help="screen only this window; repeatable (debugging -- no full summary)",
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument(
        "--parse-only",
        action="store_true",
        help="tier 1 only, JVM-free: stops before the t0 round-trip and tier 2 "
        "(still needs the window fully landed)",
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="skip the CSSI table check (it is cheap; this is for debugging only)",
    )
    args = parser.parse_args()

    selected = [resolve(name) for name in args.window] if args.window else list(WINDOWS)
    data_root = args.data_root.resolve()

    t0 = _time.perf_counter()
    _print_header(data_root)
    if not args.skip_preflight:
        _preflight()

    results: dict[str, dict[str, dict[str, bool]]] = {}
    for window in selected:
        results[window.name] = run_window(window, data_root, parse_only=args.parse_only)

    print("=" * 78)
    print("[summary]")
    print("=" * 78)
    gates = ("tier1",) if args.parse_only else ("tier1", "tier2")
    header = f"  {'window':18s} {'band':9s}"
    for gate in gates:
        for sat in SAT_IDS:
            header += f" {gate + ' ' + sat:>9s}"
    print(header + "  verdict")

    # THE VERDICT NAMES WHAT FLAGGED, and is derived rather than judged: the
    # summary states which gate fired on which satellite and stops there. The
    # disposition -- retire, slide, or record and keep -- is the maintainer's,
    # per the build plan's failure rule, and is not inferred here. In particular
    # this table never resolves a flag by deciding some satellite does not count.
    n_clean = 0
    d_only = False
    for window in selected:
        row = f"  {window.name:18s} {window.band:9s}"
        for gate in gates:
            for sat in SAT_IDS:
                value = results[window.name][sat].get(gate)
                # tier 1 has no threshold, so its failure IS a burn -- say so,
                # rather than flattening both gates onto one word.
                bad = "BURN" if gate == "tier1" else "REVIEW"
                row += f" {'CLEAN' if value else bad:>9s}"
        # One reason per satellite: where tier 1 fires, tier 2 firing too is the
        # expected consequence, not a second finding.
        reasons = []
        for sat in SAT_IDS:
            if not results[window.name][sat].get("tier1", True):
                reasons.append(f"burn on {sat}")
            elif not results[window.name][sat].get("tier2", True):
                reasons.append(f"kink on {sat}")
        n_clean += int(not reasons)
        if reasons and all(r.endswith(f" {SAT_IDS[-1]}") for r in reasons):
            d_only = True
        verdict = "CLEAN" if not reasons else "REVIEW -- " + ", ".join(reasons)
        print(row + f"  {verdict}")

    print()
    print(
        f"  {n_clean}/{len(selected)} window(s) CLEAN on "
        f"{' and '.join(gates)} for both satellites"
    )
    if n_clean != len(selected):
        print(
            "  A window that is not CLEAN is retired or slid per the build plan's "
            "failure rule -- level-band windows slide by the fewest whole days that "
            "clears the burn by >= 1 day (up to +/-10 d, staying in band), storm "
            "windows are never slid but replaced from the census. Every retirement "
            "is recorded."
        )
    if d_only:
        print(
            f"  Where the only flag is on {SAT_IDS[-1]}, applying that rule is a "
            f"judgement the maintainer records rather than one this script makes. "
            f"The contract runs every window on {SAT_IDS[0]} ('all the runs will "
            f"be conducted on GRACE-FO C'); {SAT_IDS[-1]} is read on the ten "
            f"windows only as Chunk 14's cross-tag discriminator, which a burn "
            f"makes easier rather than harder, and the table-noise part that does "
            f"need it runs on the three frozen v0.7.2 windows."
        )
    print(f"  wall time: {_time.perf_counter() - t0:.0f} s")


if __name__ == "__main__":
    main()
