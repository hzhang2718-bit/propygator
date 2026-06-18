"""Generate the shipped ``sphere_default`` variable-Cd table (maintainer tool).

``VariableCd.sphere_default()`` loads a small committed array,
``data/sphere_cd_default.npz``, that maps ``(geocentric radius, total density)`` to a
free-molecular sphere drag coefficient. This script produces that array once; end
users compute nothing (features.md §1.1 "Where the table comes from").

**What it does.** It evaluates a closed-form **Sentman / DRIA** sphere Cd — the
standard free-molecular result (Sentman 1961; Schaaf & Chambre; Moe & Moe 2005),
with per-species mass-flux weighting and a SESAM-style energy-accommodation model
keyed on atomic-oxygen surface coverage (Pilinski et al. 2013) — over a broad sweep
of genuinely different thermospheric conditions (epoch, local solar time, latitude,
F10.7, Ap) drawn from **NRLMSISE-00** (the same atmosphere model the propagator feeds
this table at runtime). Because the sphere Cd collapses onto a single
``(radius, density)`` surface across those conditions (de-risked in
``experiments/drag-coefficient-verification/``), the scattered cloud is then
**regridded** onto a clean ``(radius, density)`` mesh and saved.

**Dependencies / where to run.** This is a one-time maintainer step requiring
``pymsis`` + ``scipy`` (see ``scripts/requirements-generate.txt``) — packages that are
deliberately **not** in the propygator conda env. Run it in a throwaway venv or a
clone of the conda env. The heavy imports are deferred inside :func:`generate` so
``--help`` still works in the bare propygator env. Nothing here is imported by the
package; the physics is reconstructed from the standard literature, not copied from
the ``experiments/`` reference code.

Examples
--------
Regenerate the committed table with the default grid::

    python scripts/generate_sphere_cd_table.py

Custom grid extents / resolution and a different output path::

    python scripts/generate_sphere_cd_table.py --radius-points 30 \
        --density-min 1e-15 --density-max 3e-9 --output /tmp/table.npz
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

logger = logging.getLogger(__name__)

# --- physical constants (SI) -----------------------------------------------
BOLTZMANN = 1.380649e-23  # J/K
AMU = 1.66053906660e-27  # kg
MU_EARTH = 3.986004418e14  # m^3/s^2 (gravitational parameter)
WGS84_A = 6378137.0  # m, equatorial radius
WGS84_F = 1.0 / 298.257223563  # flattening
EARTH_ROTATION_RATE = 7.2921159e-5  # rad/s
WALL_TEMPERATURE = 300.0  # K, assumed spacecraft surface temperature

# --- default grid extents (drag-validity addendum, signed off 2026-06-15):
#     geocentric radius 6,528-7,778 km (~150-1,400 km altitude), total density
#     1e-15 .. 3e-9 kg/m^3 log-spaced. The GRID AXES are exactly the validated band
#     (addendum sec. 4/5.3): lower edge ~150 km retained; upper edge extended from
#     the old 1,200 km to the full green-validated ~1,400 km sweep so high /
#     elliptical LEO no longer trips nuisance clamp warnings. ---
DEFAULT_RADIUS_MIN_M = 6_528_000.0  # ~150 km altitude (lower edge, retained)
DEFAULT_RADIUS_MAX_M = 7_778_000.0  # ~1,400 km altitude (validated upper edge)
DEFAULT_RADIUS_POINTS = 26  # ~50 km radius spacing across the wider band
DEFAULT_DENSITY_MIN = 1e-15
DEFAULT_DENSITY_MAX = 3e-9
DEFAULT_DENSITY_POINTS = 25

# Internal MSIS altitude sampling: spans a margin WIDER than the grid so the regrid
# interpolant covers the mesh corners rather than nearest-filling them (addendum
# sec. 5.3 -- the internal sampling is NOT a coverage claim, only the grid axes are).
# This is the full range the two C_D models were cross-validated over (addendum
# sec. 5, Chunk 3: experiment vs generator agree to 0.0191% across 130-1450 km).
DEFAULT_INTERNAL_ALT_MIN_KM = 130.0
DEFAULT_INTERNAL_ALT_MAX_KM = 1450.0
DEFAULT_INTERNAL_ALT_POINTS = 56  # ~24 km spacing (matches the prior sampling density)

# Storm cohort: a fraction of the sampled conditions reach the validated storm tails
# (addendum sec. 3.3) so the regridded cloud spans the same certified extremes the
# experiment validated, rather than interpolating Cd over a narrower cloud than was
# certified (addendum sec. 5 "same condition coverage").
DEFAULT_STORM_FRACTION = 0.18  # ~ the experiment's 12/67 storm epochs
QUIET_F107_RANGE = (65.0, 250.0)
QUIET_AP_RANGE = (2.0, 80.0)
STORM_F107_RANGE = (200.0, 320.0)
STORM_AP_RANGE = (100.0, 400.0)

# Accommodation anchor: energy accommodation at 400 km / solar maximum.
# 0.90 is a commonly-accepted value there: Pilinski, Argrow & Palo (2010,
# J. Spacecraft & Rockets 47(6), 951-956) SESAM lands ~0.85-0.93, and CHAMP-
# derived values (Moe & Moe 2005, Planet. Space Sci. 53(8), 793-801) are
# ~0.86-0.89. Matched to the experiment's cd_core.calibrate_K anchor (reconciled
# to 0.90 per the Feature 1.1 drag-validity addendum, section 5). The *collapse*
# onto (radius, density) is a property of the mechanism, not this value.
ANCHOR_ALPHA = 0.90

# Experiment-vs-generator C_D model cross-validation agreement (addendum sec. 5,
# Chunk 3), measured by cross_validate_models.py over the full generation range.
# Recorded in the table metadata for provenance only (the generator does not run the
# cross-validation). UPDATE whenever the C_D model (physics, anchor ANCHOR_ALPHA, or
# the relative-speed formula) changes and the cross-validation is re-run, so the
# shipped table never claims a stale agreement.
CROSS_VALIDATION_MAX_REL_PCT = 0.0191

#: pymsis NRLMSISE-00 output column order (Variable enum): total density, the
#: species number densities, then temperature. Reconstructed here, not imported.
_COL = {
    "rho": 0,
    "N2": 1,
    "O2": 2,
    "O": 3,
    "He": 4,
    "H": 5,
    "Ar": 6,
    "N": 7,
    "AnomO": 8,
    "NO": 9,
    "T": 10,
}
#: (column, molecular mass [kg]) for the species carried into the Cd weighting.
_SPECIES = {
    "N2": (_COL["N2"], 28.0134 * AMU),
    "O2": (_COL["O2"], 31.9988 * AMU),
    "O": (_COL["O"], 15.9994 * AMU),
    "He": (_COL["He"], 4.002602 * AMU),
    "H": (_COL["H"], 1.008 * AMU),
    "Ar": (_COL["Ar"], 39.948 * AMU),
    "N": (_COL["N"], 14.0067 * AMU),
}

_DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "sphere_cd_default.npz"


# --- free-molecular sphere Cd (Sentman / DRIA) -----------------------------


def _geocentric_radius(
    altitude_m: NDArray[np.float64], lat_rad: float
) -> NDArray[np.float64]:
    """Geocentric radius [m] of a WGS84 geodetic point (height, geodetic latitude)."""
    e2 = WGS84_F * (2.0 - WGS84_F)
    sin_lat = np.sin(lat_rad)
    prime_vertical = WGS84_A / np.sqrt(1.0 - e2 * sin_lat * sin_lat)
    x = (prime_vertical + altitude_m) * np.cos(lat_rad)
    z = (prime_vertical * (1.0 - e2) + altitude_m) * sin_lat
    return np.sqrt(x * x + z * z)


def _relative_speed(
    radius_m: NDArray[np.float64], lat_rad: float
) -> NDArray[np.float64]:
    """Atmosphere-relative speed [m/s] for a prograde circular orbit at ``radius``.

    Circular orbital speed minus the corotating-atmosphere speed at the sub-satellite
    latitude — a scalar approximation adequate for a representative table (corotation
    is a few percent of orbital speed, and the table collapses chiefly on radius).
    """
    orbital = np.sqrt(MU_EARTH / radius_m)
    corotation = EARTH_ROTATION_RATE * radius_m * np.cos(lat_rad)
    return orbital - corotation


def _sphere_cd_species(
    speed: NDArray[np.float64],
    temperature: NDArray[np.float64],
    mass: float,
    alpha: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Closed-form Sentman sphere Cd (ref. projected area) for one gas species.

    DRIA: diffuse re-emission with incomplete energy accommodation ``alpha``; the
    re-emitted flux leaves at the reflected temperature ``Tr``. Standard sphere result
    (incident + re-emission terms) — see module docstring for references.
    """
    from scipy.special import erf  # generation-only dependency (see requirements)

    s = speed * np.sqrt(mass / (2.0 * BOLTZMANN * temperature))  # molecular speed ratio
    reflected_t = (1.0 - alpha) * mass * speed * speed / (
        3.0 * BOLTZMANN
    ) + alpha * WALL_TEMPERATURE
    incident = (2.0 * s**2 + 1.0) / (np.sqrt(np.pi) * s**3) * np.exp(-(s**2)) + (
        4.0 * s**4 + 4.0 * s**2 - 1.0
    ) / (2.0 * s**4) * erf(s)
    re_emission = (2.0 * np.sqrt(np.pi) / (3.0 * s)) * np.sqrt(
        reflected_t / temperature
    )
    return incident + re_emission


def _sphere_cd_total(
    msis_rows: NDArray[np.float64],
    speed: NDArray[np.float64],
    alpha: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Mass-flux-weighted total sphere Cd over the per-species number densities."""
    temperature = msis_rows[:, _COL["T"]]
    numerator = np.zeros_like(speed)
    denominator = np.zeros_like(speed)
    for column, mass in _SPECIES.values():
        number_density = msis_rows[:, column]
        valid = np.isfinite(number_density) & (number_density > 0.0)
        partial_density = np.where(valid, number_density * mass, 0.0)
        cd = _sphere_cd_species(speed, temperature, mass, alpha)
        numerator += partial_density * np.where(valid, cd, 0.0)
        denominator += partial_density
    return numerator / denominator


def _calibrate_accommodation_K(msis_run, anchor_alpha: float) -> float:
    """Pick the Langmuir K so accommodation hits ``anchor_alpha`` at 400 km / solar max.

    Derives the anchor's atomic-O number density and temperature live from NRLMSISE-00
    (rather than hardcoding reference numbers), then inverts the Langmuir isotherm
    ``theta = K P /(1 + K P)`` at the chosen coverage.
    """
    anchor = np.asarray(
        msis_run(
            [np.datetime64("2002-07-01T12:00")],
            [0.0],
            [0.0],
            [400.0],
            [200.0],
            [200.0],
            [[15.0] * 7],
            version=0,
        )
    ).reshape(-1, 11)[0]
    partial_pressure_O = anchor[_COL["O"]] * BOLTZMANN * anchor[_COL["T"]]
    return float((anchor_alpha / (1.0 - anchor_alpha)) / partial_pressure_O)


def _accommodation(
    n_atomic_O: NDArray[np.float64], temperature: NDArray[np.float64], langmuir_K: float
) -> NDArray[np.float64]:
    """SESAM-style energy accommodation from atomic-oxygen Langmuir surface coverage."""
    partial_pressure_O = n_atomic_O * BOLTZMANN * temperature
    return langmuir_K * partial_pressure_O / (1.0 + langmuir_K * partial_pressure_O)


# --- condition sweep + regrid ----------------------------------------------


def _sample_conditions(
    n_conditions: int,
    rng: np.random.Generator,
    storm_fraction: float = DEFAULT_STORM_FRACTION,
) -> list[dict[str, object]]:
    """Draw genuinely different thermospheric conditions across a solar cycle.

    A ``storm_fraction`` of the conditions are drawn from the validated storm tails
    (F10.7 / Ap reaching the experiment's certified extremes; addendum sec. 3.3) so
    the regridded cloud spans the same range the experiment validated -- otherwise
    the table would interpolate Cd over a narrower cloud than was certified
    (addendum sec. 5 "same condition coverage"). Each condition carries a ``storm``
    flag for the metadata coverage record.
    """
    epochs = [
        "2002-07-01T12:00",
        "2003-01-15T03:00",
        "2005-04-10T09:00",
        "2008-07-21T18:00",
        "2011-06-01T15:00",
        "2014-10-05T21:00",
        "2017-03-20T06:00",
        "2019-12-30T00:00",
    ]
    n_storm = int(round(n_conditions * storm_fraction))
    conditions: list[dict[str, object]] = []
    for i in range(n_conditions):
        storm = i < n_storm
        f107_lo, f107_hi = STORM_F107_RANGE if storm else QUIET_F107_RANGE
        ap_lo, ap_hi = STORM_AP_RANGE if storm else QUIET_AP_RANGE
        conditions.append(
            {
                "date": np.datetime64(str(rng.choice(epochs))),
                "lon": float(rng.uniform(0.0, 360.0)),  # varies local solar time
                "lat": float(rng.uniform(-80.0, 80.0)),  # varies latitude
                "f107": float(rng.uniform(f107_lo, f107_hi)),  # solar-cycle / storm
                "f107a": float(rng.uniform(f107_lo, f107_hi)),
                "ap": float(rng.uniform(ap_lo, ap_hi)),  # geomagnetic activity
                "storm": storm,
            }
        )
    return conditions


def generate(
    *,
    radius_axis: NDArray[np.float64],
    density_axis: NDArray[np.float64],
    n_conditions: int,
    seed: int,
    internal_alt_min_km: float = DEFAULT_INTERNAL_ALT_MIN_KM,
    internal_alt_max_km: float = DEFAULT_INTERNAL_ALT_MAX_KM,
    internal_alt_points: int = DEFAULT_INTERNAL_ALT_POINTS,
    storm_fraction: float = DEFAULT_STORM_FRACTION,
) -> tuple[NDArray[np.float64], dict[str, object]]:
    """Build the ``(radius, density) -> Cd`` grid; return it plus provenance metadata.

    Heavy, generation-only imports (``pymsis``, ``scipy``) happen here so ``--help``
    runs in the bare propygator env.
    """
    from pymsis import msis  # generation-only dependency (see requirements)
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

    rng = np.random.default_rng(seed)
    conditions = _sample_conditions(n_conditions, rng, storm_fraction)
    langmuir_K = _calibrate_accommodation_K(msis.run, ANCHOR_ALPHA)
    logger.info(
        "Calibrated Langmuir K = %.3e 1/Pa (anchor alpha=%.2f)",
        langmuir_K,
        ANCHOR_ALPHA,
    )

    # Sample geodetic altitudes spanning the radius grid with edge margin, so the
    # regrid interpolant covers the mesh corners rather than relying on nearest-fill.
    altitudes_km = np.linspace(
        internal_alt_min_km, internal_alt_max_km, internal_alt_points
    )

    radii: list[NDArray[np.float64]] = []
    densities: list[NDArray[np.float64]] = []
    cds: list[NDArray[np.float64]] = []
    for cond in conditions:
        lat = float(cond["lat"])  # type: ignore[arg-type]
        rows = np.asarray(
            msis.run(
                [cond["date"]],
                [cond["lon"]],
                [lat],
                altitudes_km,
                [cond["f107"]],
                [cond["f107a"]],
                [[cond["ap"]] * 7],
                version=0,
            )
        ).reshape(-1, 11)
        rho = rows[:, _COL["rho"]]
        finite = np.isfinite(rho) & (rho > 0.0)
        rows = rows[finite]
        radius_m = _geocentric_radius(altitudes_km[finite] * 1e3, np.radians(lat))
        speed = _relative_speed(radius_m, np.radians(lat))
        alpha = _accommodation(rows[:, _COL["O"]], rows[:, _COL["T"]], langmuir_K)
        cd = _sphere_cd_total(rows, speed, alpha)
        radii.append(radius_m)
        densities.append(rows[:, _COL["rho"]])
        cds.append(cd)

    radius_cloud = np.concatenate(radii)
    density_cloud = np.concatenate(densities)
    cd_cloud = np.concatenate(cds)
    logger.info(
        "Built %d (radius, density, Cd) samples; Cd in [%.3f, %.3f]",
        cd_cloud.size,
        float(cd_cloud.min()),
        float(cd_cloud.max()),
    )

    # Regrid the cloud onto the clean mesh. Cd is smooth in log-density, so the
    # interpolation (and the shipped density axis) live in log10(density) space.
    points = np.column_stack([radius_cloud, np.log10(density_cloud)])
    linear = LinearNDInterpolator(points, cd_cloud)
    nearest = NearestNDInterpolator(points, cd_cloud)
    mesh_r, mesh_logd = np.meshgrid(radius_axis, np.log10(density_axis), indexing="ij")
    grid = linear(mesh_r, mesh_logd)
    outside = ~np.isfinite(grid)
    grid[outside] = nearest(mesh_r[outside], mesh_logd[outside])
    n_outside = int(outside.sum())
    logger.info(
        "Regridded onto %dx%d mesh; %d edge cell(s) filled by nearest-neighbour",
        radius_axis.size,
        density_axis.size,
        n_outside,
    )

    n_storm = sum(bool(c["storm"]) for c in conditions)
    metadata: dict[str, object] = {
        "model": "Sentman/DRIA sphere Cd, mass-flux weighted over NRLMSISE-00 species",
        "accommodation": "SESAM Langmuir on atomic-O coverage",
        "anchor_alpha": ANCHOR_ALPHA,
        "atmosphere": "NRLMSISE-00 (pymsis)",
        "axes": "radius_axis [m] (geocentric), density_axis [kg/m^3] (total)",
        # The GRID AXES are the validated-band coverage claim (addendum sec. 4/5.3):
        # what the table asserts. The INTERNAL SAMPLING is deliberately wider (a
        # margin so the regrid interpolates the mesh corners) and is NOT a claim --
        # both are recorded so the distinction is auditable.
        "grid_band": {
            "radius_m": [float(radius_axis[0]), float(radius_axis[-1])],
            "altitude_km_equatorial": [
                float(radius_axis[0] - WGS84_A) / 1e3,
                float(radius_axis[-1] - WGS84_A) / 1e3,
            ],
            "density_kgm3": [float(density_axis[0]), float(density_axis[-1])],
        },
        "internal_sampling_band": {
            "altitude_km": [float(altitudes_km[0]), float(altitudes_km[-1])],
            "n_points": int(altitudes_km.size),
            "note": "wider-than-grid margin for regrid corner coverage; not a claim",
        },
        # The actual extent of the sampled (radius, density) cloud, plus how many mesh
        # cells fell OUTSIDE it and were filled by nearest-neighbour rather than
        # interpolated. Lets a reader audit whether a grid corner the axes CLAIM was
        # genuinely interpolated or edge-extrapolated (addendum sec. 5.3: nearest-fill
        # regions are recorded, not silently presented as validated).
        "sampled_cloud": {
            "radius_m": [float(radius_cloud.min()), float(radius_cloud.max())],
            "density_kgm3": [float(density_cloud.min()), float(density_cloud.max())],
            "n_mesh_cells_nearest_filled": n_outside,
            "n_mesh_cells_total": int(grid.size),
        },
        "condition_coverage": {
            "n_conditions": n_conditions,
            "n_storm": n_storm,
            "quiet_f107": list(QUIET_F107_RANGE),
            "quiet_ap": list(QUIET_AP_RANGE),
            "storm_f107": list(STORM_F107_RANGE),
            "storm_ap": list(STORM_AP_RANGE),
        },
        "confidence": {
            "green_rms_pct": 5.0,
            # Derived from the grid upper edge (not hardcoded) so it tracks the band
            # on regeneration; the whole grid is green-validated.
            "green_validated_through_km": float(radius_axis[-1] - WGS84_A) / 1e3,
            "reduced_confidence_above_km": None,
            "cross_validation_max_rel_pct": CROSS_VALIDATION_MAX_REL_PCT,
            "note": (
                "Collapse RMS stays <= 5% (green) across the full validated sweep "
                "(overall 0.490%, storm 0.672%; addendum Chunk 1), so there is no "
                "reduced-confidence region within the grid. The high-altitude end is "
                "non-binding (drag ~ rho -> 0). Experiment-vs-generator model cross-"
                "validation (addendum sec. 5, Chunk 3): the two C_D models' physics "
                f"agree to {CROSS_VALIDATION_MAX_REL_PCT}% over the generation range "
                "(see grid_band / internal_sampling_band for the exact extents)."
            ),
        },
        "seed": seed,
        "n_samples": int(cd_cloud.size),
        "cd_range": [float(cd_cloud.min()), float(cd_cloud.max())],
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return grid.astype(np.float64), metadata


def _build_axes(
    args: argparse.Namespace,
) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    radius_axis = np.linspace(args.radius_min, args.radius_max, args.radius_points)
    density_axis = np.logspace(
        np.log10(args.density_min), np.log10(args.density_max), args.density_points
    )
    return radius_axis, density_axis


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: parse args, run the sweep+regrid, write the ``.npz``."""
    parser = argparse.ArgumentParser(
        description="Generate the shipped sphere_default variable-Cd table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT, help="Output .npz path."
    )
    parser.add_argument(
        "--radius-min", type=float, default=DEFAULT_RADIUS_MIN_M, dest="radius_min"
    )
    parser.add_argument(
        "--radius-max", type=float, default=DEFAULT_RADIUS_MAX_M, dest="radius_max"
    )
    parser.add_argument(
        "--radius-points", type=int, default=DEFAULT_RADIUS_POINTS, dest="radius_points"
    )
    parser.add_argument(
        "--density-min", type=float, default=DEFAULT_DENSITY_MIN, dest="density_min"
    )
    parser.add_argument(
        "--density-max", type=float, default=DEFAULT_DENSITY_MAX, dest="density_max"
    )
    parser.add_argument(
        "--density-points",
        type=int,
        default=DEFAULT_DENSITY_POINTS,
        dest="density_points",
    )
    parser.add_argument(
        "--conditions",
        type=int,
        default=80,
        dest="n_conditions",
        help="Number of thermospheric conditions sampled for the cloud.",
    )
    parser.add_argument(
        "--storm-fraction",
        type=float,
        default=DEFAULT_STORM_FRACTION,
        dest="storm_fraction",
        help="Fraction of conditions drawn from the validated storm tails.",
    )
    parser.add_argument(
        "--internal-alt-min",
        type=float,
        default=DEFAULT_INTERNAL_ALT_MIN_KM,
        dest="internal_alt_min_km",
        help="Internal MSIS altitude sampling floor [km] (wider than the grid).",
    )
    parser.add_argument(
        "--internal-alt-max",
        type=float,
        default=DEFAULT_INTERNAL_ALT_MAX_KM,
        dest="internal_alt_max_km",
        help="Internal MSIS altitude sampling ceiling [km] (wider than the grid).",
    )
    parser.add_argument(
        "--internal-alt-points",
        type=int,
        default=DEFAULT_INTERNAL_ALT_POINTS,
        dest="internal_alt_points",
    )
    parser.add_argument(
        "--seed", type=int, default=20260611, help="RNG seed (reproducible output)."
    )
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing output file."
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true", help="Debug-level logging."
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    output: Path = args.output
    if output.exists() and not args.force:
        logger.error("%s already exists; pass --force to overwrite.", output)
        raise SystemExit(1)

    radius_axis, density_axis = _build_axes(args)
    grid, metadata = generate(
        radius_axis=radius_axis,
        density_axis=density_axis,
        n_conditions=args.n_conditions,
        seed=args.seed,
        internal_alt_min_km=args.internal_alt_min_km,
        internal_alt_max_km=args.internal_alt_max_km,
        internal_alt_points=args.internal_alt_points,
        storm_fraction=args.storm_fraction,
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        output,
        grid=grid,
        radius_axis=radius_axis,
        density_axis=density_axis,
        metadata_json=np.asarray(json.dumps(metadata)),
    )
    logger.info("Wrote %s (grid shape %s)", output, grid.shape)


if __name__ == "__main__":
    main()
