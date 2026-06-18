"""Capture the conservative-profile thermosphere composition for the Kn floor.

The runtime free-molecular **validity floor** (drag-validity & altitude-guards
addendum §6.2/§6.3) is the altitude below which a body of characteristic length
``L`` leaves free-molecular flow (Knudsen number ``Kn = lambda / L`` drops below
10) and the Sentman/DRIA drag coefficient starts to over-predict. The runtime
computes ``floor_altitude(L)`` by re-implementing the §3.4 mean-free-path / Kn
method — but the mean free path needs the **per-species number densities**, which
NRLMSISE-00 supplies and Orekit's public API does **not** expose (it returns only
*total* density). pymsis is also (deliberately) not a runtime dependency.

So this maintainer tool runs NRLMSISE-00 (pymsis) once, at the fixed **conservative
high-activity** profile the addendum specifies (§6.3, §9 — denser ⇒ shorter λ ⇒ a
higher, safer floor; deterministic), over the floor band, and prints the per-species
number densities ``n_i(alt)`` as a **paste-ready Python constant** for
``propygator.propagation.guards``. This is the analogue of
``scripts/generate_sphere_cd_table.py``: an offline NRLMSISE-00 capture that the
shipped code consumes (here as an embedded constant rather than a ``data/*.npz``,
because the floor is computed on *every* drag run — an embedded constant cannot go
missing and keeps the floor computation pure-Python / JVM-free).

**The §5 cross-check.** The runtime re-implements λ/σ/Kn/scan a *third* time (the
experiment + this script being the other two), so the addendum §5 equivalence
obligation extends to it. To make that auditable this tool *also* computes
``floor_altitude(L)`` two ways and prints both: (a) the continuous-MSIS Brent root
find (what ``experiments/.../kn_floor.py`` does — must reproduce the committed
``kn_floor_results.txt`` curve), and (b) the grid-interpolated bisection the runtime
uses (must agree with (a) to well under a km). If (a) reproduces the experiment and
(b) matches (a), the embedded constant + the runtime scan are certified.

**Dependencies / where to run.** A one-time maintainer step requiring ``pymsis``
(+ ``scipy`` for the reference Brent solve) — packages deliberately **not** in the
propygator conda env. Run it in the throwaway venv (``docs/experiments_venv.md``,
the same one Chunks 1-4 used). The heavy imports are deferred inside :func:`capture`
so ``--help`` still works in the bare env. Nothing here is imported by the package;
the σ table is reconstructed from kinetic-theory references (see below), matching
``experiments/.../kn_floor.py`` but not copied from it.

Usage::

    python scripts/generate_kn_floor_composition.py          # default 80-450 km / 10 km
    python scripts/generate_kn_floor_composition.py --alt-step 5.0   # finer grid

Then paste the printed ``_KN_FLOOR_*`` block into ``propagation/guards.py`` and
confirm the reference-body floors match ``kn_floor_results.txt``.
"""

from __future__ import annotations

import argparse
import logging

import numpy as np

logger = logging.getLogger(__name__)

# --- physical constants + the σ table (reconstructed, not imported) --------
# Composition-weighted hard-sphere mean free path
#     lambda = 1 / (sqrt(2) * sum_i n_i * sigma_i),   sigma_i = pi * d_i^2
# over the major NRLMSISE-00 species, with n_i the per-species NUMBER density
# [1/m^3]. Kinetic / collision diameters d_i [m] from standard kinetic-theory
# tables (molecular N2/O2/Ar: gas-kinetic diameter tables, e.g. Breck 1974; He/H:
# same family; atomic O/N: aeronomy values ~3.0e-10 m, Bird 1994 — more uncertain,
# but the floor band is N2/O2/O-dominated where the values are best known, and a
# larger sigma only shortens lambda and raises the floor, i.e. errs conservative).
# These MUST match experiments/.../kn_floor.py and propagation/guards.py exactly.
_KINETIC_DIAMETER_M = {
    "N2": 3.64e-10,
    "O2": 3.46e-10,
    "O": 3.00e-10,
    "HE": 2.18e-10,
    "H": 2.40e-10,
    "AR": 3.40e-10,
    "N": 3.00e-10,
}
_SIGMA = {sp: float(np.pi * d * d) for sp, d in _KINETIC_DIAMETER_M.items()}
_SQRT2 = float(np.sqrt(2.0))
_KN_FREE_MOLECULAR = 10.0  # free-molecular threshold (addendum §3.4)

# pymsis NRLMSISE-00 output column order (Variable enum): total density, the species
# number densities, then temperature. Keyed on the σ-table species names.
_COL = {"N2": 1, "O2": 2, "O": 3, "HE": 4, "H": 5, "AR": 6, "N": 7}

# Conservative high-activity profile (addendum §6.3/§9; matches kn_floor.py
# CONSERVATIVE_HIGH): solar-max era, summer noon, equatorial dayside (densest),
# disturbed geomagnetic. Fixed and deterministic — the floor does NOT track the
# run's epoch/space weather (it is a conservative worst case).
_PROFILE = {
    "date": np.datetime64("2002-07-01T12:00"),
    "lon": 0.0,
    "lat": 0.0,
    "f107": 250.0,
    "f107a": 250.0,
    "ap": 45.0,
    "label": "conservative high-activity (F10.7=250, Ap=45, equatorial dayside)",
}

# Reference bodies for the printed self-check, matching kn_floor.py REFERENCE_BODIES
# so the output is directly comparable to the committed kn_floor_results.txt.
_REFERENCE_BODIES = (
    ("1U CubeSat", 0.10),
    ("3U CubeSat", 0.34),
    ("smallsat", 1.00),
    ("small bus", 3.00),
    ("large bus", 5.00),
    ("ISS module", 10.00),
    ("station", 30.00),
)


def _mean_free_path_from_row(row: np.ndarray) -> float:
    """Composition-weighted mean free path λ [m] from one MSIS row (§3.4)."""
    total = 0.0
    for sp, col in _COL.items():
        n = float(row[col])
        if not np.isfinite(n) or n <= 0.0:
            continue
        total += n * _SIGMA[sp]
    return float("inf") if total <= 0.0 else 1.0 / (_SQRT2 * total)


def _floor_continuous(msis_run, length_m: float) -> float:
    """``floor_altitude(L)`` [km] via continuous-MSIS Brent solve (the §3.4 reference).

    Mirrors ``experiments/.../kn_floor.py``: the Kn = 10 crossing of
    ``Kn(alt) = lambda(alt) / L``, found with ``scipy.optimize.brentq`` over a
    [85, 450] km bracket. This is the number that must reproduce the committed
    ``kn_floor_results.txt`` curve.
    """
    from scipy.optimize import brentq

    def f(alt_km: float) -> float:
        row = np.asarray(
            msis_run(
                [_PROFILE["date"]],
                [_PROFILE["lon"]],
                [_PROFILE["lat"]],
                [alt_km],
                [_PROFILE["f107"]],
                [_PROFILE["f107a"]],
                [[_PROFILE["ap"]] * 7],
                version=0,
            )
        ).reshape(-1, 11)[0]
        return _mean_free_path_from_row(row) / length_m - _KN_FREE_MOLECULAR

    return float(brentq(f, 85.0, 450.0, xtol=1.0e-3))


def _floor_on_grid(
    altitudes_km: np.ndarray, densities: dict[str, np.ndarray], length_m: float
) -> float:
    """``floor_altitude(L)`` [km] via the *runtime* method: log-linear-interpolated
    composition on ``altitudes_km`` + a hand-rolled bisection (no scipy).

    A faithful preview of ``propagation.guards._floor_altitude_km`` so the printed
    output proves the embedded grid + bisection reproduce the continuous solve.
    """
    log_n = {sp: np.log(np.clip(d, 1e-300, None)) for sp, d in densities.items()}

    def lam(alt_km: float) -> float:
        total = 0.0
        for sp, ln in log_n.items():
            n = float(np.exp(np.interp(alt_km, altitudes_km, ln)))
            total += n * _SIGMA[sp]
        return float("inf") if total <= 0.0 else 1.0 / (_SQRT2 * total)

    def f(alt_km: float) -> float:
        return lam(alt_km) / length_m - _KN_FREE_MOLECULAR

    lo, hi = float(altitudes_km[0]), float(altitudes_km[-1])
    if f(lo) > 0.0 or f(hi) < 0.0:
        return float("nan")  # crossing outside the captured band
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if f(mid) < 0.0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1.0e-3:
            break
    return 0.5 * (lo + hi)


def capture(alt_min_km: float, alt_max_km: float, alt_step_km: float) -> None:
    """Run NRLMSISE-00 at the conservative profile and print the paste-ready block."""
    from pymsis import msis  # capture-only dependency (throwaway venv)

    altitudes_km = np.arange(alt_min_km, alt_max_km + 0.5 * alt_step_km, alt_step_km)
    result = np.asarray(
        msis.run(
            [_PROFILE["date"]],
            [_PROFILE["lon"]],
            [_PROFILE["lat"]],
            altitudes_km,
            [_PROFILE["f107"]],
            [_PROFILE["f107a"]],
            [[_PROFILE["ap"]] * 7],
            version=0,
        )
    )
    # pymsis version=0 (NRLMSISE-00) returns 11 variables per point in the fixed
    # Variable-enum order _COL assumes (total density, the 7 species number densities,
    # then temperature). Assert the column count so a future pymsis layout change fails
    # loudly here instead of silently mis-keying the embedded composition. (A reorder
    # that keeps 11 columns would still slip past this, but then the self-check floor
    # values below diverge wildly from kn_floor_results.txt — the secondary backstop.)
    if result.shape[-1] != 11:
        raise RuntimeError(
            f"expected 11 NRLMSISE-00 output columns, got {result.shape[-1]}; the "
            "pymsis Variable enum/layout may have changed — re-check _COL before "
            "trusting output."
        )
    rows = result.reshape(-1, 11)
    densities = {sp: rows[:, col].astype(np.float64) for sp, col in _COL.items()}

    # Per-species share of the collision term Σ n σ across the band — so a maintainer
    # can see which species actually set the floor (and that none was dropped wrongly).
    sigma_term = {sp: densities[sp] * _SIGMA[sp] for sp in _COL}
    total_term = np.sum(list(sigma_term.values()), axis=0)
    logger.info("Per-species max share of the collision term sum(n*sigma) over band:")
    for sp in _COL:
        share = np.nanmax(sigma_term[sp] / total_term)
        logger.info("    %-3s  max share %.4f", sp, float(share))

    # --- the paste-ready constant ---------------------------------------------
    print("\n# ==== paste into propagation/guards.py ============================")
    print("# Conservative high-activity NRLMSISE-00 per-species NUMBER densities")
    print("# [1/m^3] vs geodetic altitude [km], captured by")
    print("# scripts/generate_kn_floor_composition.py at the fixed profile:")
    print(f"#   {_PROFILE['label']}, {_PROFILE['date']}.")
    print("# See that script + experiments/.../kn_floor.py for the sigma table and")
    print("# the section 5 cross-check. Deterministic (not the run's space weather).")
    alt_str = ", ".join(f"{a:.1f}" for a in altitudes_km)
    print(f"_KN_FLOOR_ALTITUDE_KM = ({alt_str})")
    print("_KN_FLOOR_NUMBER_DENSITY_M3 = {")
    for sp in _COL:
        vals = ", ".join(f"{n:.6e}" for n in densities[sp])
        print(f'    "{sp}": ({vals}),')
    print("}")
    print("# ==================================================================\n")

    # --- self-check: continuous (experiment) vs grid (runtime) floor ----------
    print(f"floor_altitude(L) self-check  [{_PROFILE['label']}]")
    print(
        f"  grid: {altitudes_km[0]:.0f}-{altitudes_km[-1]:.0f} km, "
        f"{alt_step_km:.0f} km step, {altitudes_km.size} points"
    )
    print(
        f"  {'body':>11s} {'L m':>7s} {'continuous km':>14s} {'grid km':>9s} "
        f"{'delta m':>8s}"
    )
    max_delta_m = 0.0
    for name, length_m in _REFERENCE_BODIES:
        cont = _floor_continuous(msis.run, length_m)
        grid = _floor_on_grid(altitudes_km, densities, length_m)
        delta_m = abs(cont - grid) * 1000.0
        max_delta_m = max(max_delta_m, delta_m)
        print(f"  {name:>11s} {length_m:7.2f} {cont:14.1f} {grid:9.1f} {delta_m:8.1f}")
    verdict = "OK < 1 km" if max_delta_m < 1000.0 else "WIDEN GRID (use --alt-step 5)"
    print(f"  max continuous-vs-grid delta = {max_delta_m:.1f} m  ({verdict})")
    print("  (the 'continuous km' column must match committed kn_floor_results.txt)")


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: capture the composition + print the constant and self-check."""
    parser = argparse.ArgumentParser(
        description="Capture conservative-profile thermosphere composition for the "
        "runtime Kn floor (maintainer tool; needs pymsis + scipy in the throwaway "
        "venv).",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--alt-min", type=float, default=80.0, dest="alt_min_km")
    parser.add_argument("--alt-max", type=float, default=450.0, dest="alt_max_km")
    parser.add_argument(
        "--alt-step",
        type=float,
        default=10.0,
        dest="alt_step_km",
        help="Altitude grid spacing [km]; drop to 5.0 if the self-check exceeds 1 km.",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    capture(args.alt_min_km, args.alt_max_km, args.alt_step_km)


if __name__ == "__main__":
    main()
