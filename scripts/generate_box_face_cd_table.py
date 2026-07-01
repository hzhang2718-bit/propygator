"""Generate the shipped ``BoxFaceCd.default`` per-face drag table (maintainer tool).

``BoxFaceCd.default()`` loads a small committed array, ``data/box_face_cd_default.npz``,
that maps ``(geocentric radius, total density, face-flow angle theta)`` to a single
**box face's** free-molecular drag coefficient (referenced to that face's *full* area).
At runtime ``propagate_numerical`` looks the table up once per face (six faces of a
convex box) and sums ``CdA = sum_i Cd_i(theta_i) * A_i`` -- the exact convex
free-molecular drag (``general-upgrades-1.md`` "Tier B Drag"). This script produces
that array once; end users compute nothing.

**What it does.** It is the per-face twin of ``scripts/generate_sphere_cd_table.py``.
It reuses that script's Tier-A model wholesale -- the SESAM/Langmuir energy
accommodation (anchored alpha = 0.90 at 400 km / solar max), the geocentric-radius and
atmosphere-relative-speed maps, the NRLMSISE-00 condition sweep, and the
``(radius, density)`` validated band -- so the box table shares the sphere table's
gas-surface assumptions exactly (cross-table coherence). The genuinely **new** part is
the per-face coefficient: an *independent* reconstruction of the **Schaaf-Chambre /
Sentman DRIA** flat-face closed form (normal pressure **and** tangential shear, diffuse
re-emission at the DRIA reflected temperature), evaluated over the full face-flow angle
``theta in [0, pi]`` (theta = 0 head-on, pi/2 edge-on, pi fully leeward). The axis is
**theta, not cos theta**: the shear's ``sin theta`` factor is smooth in theta but
becomes ``sqrt(1 - cos^2 theta)`` -- with an infinite-derivative cusp at the poles -- in
cos-theta space, so linear interpolation only converges cleanly on the theta axis
(``general-upgrades-1.md`` "Tier B Drag"; Chunk-1 convergence study).

Because the per-face Cd collapses onto a single ``(radius, density)`` surface at each
incidence (de-risked at fixed attitude in the ``drag-coefficient-verification``
experiment), the scattered cloud is regridded -- one ``(radius, density)`` regrid per
incidence node, since the incidence is sampled exactly at every node -- onto a clean
``(radius, density, incidence)`` mesh and saved.

**Independence / cross-validation.** Like the sphere generator, the per-face *physics*
here is reconstructed from the standard literature, **not** copied from the experiment
``cd_box.py`` kernel. The Tier-A pieces are imported from ``generate_sphere_cd_table``
(they are a shared, already-validated dependency, exactly as the experiment's
``cross_validate_models.py`` imports it). The §5-equivalence invariant -- that this
generator and the experiment kernel are the same physics -- is proven separately by the
Chunk-3 cross-validator on the force-relevant assembled ``CdA``.

**Dependencies / where to run.** A one-time maintainer step requiring ``pymsis`` +
``scipy`` (see ``scripts/requirements-generate.txt``) -- packages deliberately **not**
in the propygator conda env. Run it in the throwaway venv
(``experiments/drag-coefficient-verification/.venv-experiments``;
``docs/experiments_venv.md``). The heavy imports are deferred inside :func:`generate` so
``--help`` still works in the bare propygator env. Nothing here is imported by the
package; end users load the committed ``.npz``.

Examples
--------
Regenerate the committed table with the default grid::

    python scripts/generate_box_face_cd_table.py

Custom incidence resolution and a different output path::

    python scripts/generate_box_face_cd_table.py --incidence-points 49 \
        --output /tmp/box_face.npz
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

# The sphere generator is a sibling maintainer script (scripts/), not the package.
# Importing its Tier-A internals is exactly the cross-table-coherence reuse the build
# plan calls for (the box table must share the sphere's accommodation model, radius/
# speed maps, and condition sweep). Its heavy imports (pymsis, scipy) are deferred
# inside generate(), so this top-level import is cheap and keeps --help JVM/scipy-free.
import generate_sphere_cd_table as gen

logger = logging.getLogger(__name__)

# --- per-face axis defaults ------------------------------------------------
# The (radius, density) axes reuse the Tier-A validated band wholesale (the sphere
# generator's defaults). The incidence axis is the new dimension: a uniform grid over
# the FULL face-flow range [0, pi] (theta = 0 head-on, pi/2 edge-on, pi leeward).
#
# 65 nodes (~2.8 deg spacing) is the maintainer-signed-off resolution (build-plan
# Chunk-2 sign-off, 2026-06-27). The Chunk-1 convergence study
# (cd_box_incidence_convergence.py) showed linear interpolation over the theta axis
# converges at clean ~2nd order with no special node placement: 33 nodes already give
# < 0.4% max / < 0.1% RMS error vs the kernel, and 65 nodes give < 0.1% max -- a safe
# margin at trivial table size. The incidence range is FIXED at [0, pi] by contract
# (general-upgrades-1.md "Tier B Drag"): a real face-flow angle never falls outside it,
# so there is no incidence clamp/wrap/seam and no reason to make the bounds tunable.
DEFAULT_INCIDENCE_POINTS = 65
INCIDENCE_MIN_RAD = 0.0
INCIDENCE_MAX_RAD = float(np.pi)

# Experiment-vs-generator per-face cross-validation agreement on the force-relevant
# assembled CdA = sum_i Cd_i * A_i (Chunk 3, cross_validate_box_face.py), measured over
# a convex box + plate swept over attitude x radius x density. Recorded in the table
# metadata for provenance only (the generator does not run the cross-validation). The
# shared per-face closed form is bit-identical (8.9e-16); this end-to-end CdA figure is
# dominated by the documented spherical-vs-geocentric relative-speed convention (the
# same sub-1% effect the sphere table records). UPDATE whenever the per-face physics
# (closed form, anchor ANCHOR_ALPHA, or the relative-speed formula) changes and the
# cross-validation is re-run, so the shipped table never claims a stale agreement
# (mirrors generate_sphere_cd_table.CROSS_VALIDATION_MAX_REL_PCT).
CROSS_VALIDATION_MAX_REL_PCT = 0.1193

_DEFAULT_OUTPUT = (
    Path(__file__).resolve().parents[1] / "data" / "box_face_cd_default.npz"
)


# --- free-molecular per-face Cd (Schaaf-Chambre / Sentman DRIA) ------------


def _face_cd_species(
    theta: NDArray[np.float64],
    speed: NDArray[np.float64],
    temperature: NDArray[np.float64],
    mass: float,
    alpha: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Closed-form per-face Cd (ref. *full* face area) for one gas species.

    Schaaf-Chambre / Sentman flat-face result with DRIA re-emission (diffuse,
    incomplete energy accommodation ``alpha``, re-emitted flux at the reflected
    temperature ``Tr``): a normal-pressure coefficient ``Cp`` plus a tangential-shear
    coefficient ``Ctau``, each projected onto the drag (incoming-flow) direction --
    ``Cd = Cp * cos theta + Ctau * sin theta``. The pressure term falls off as
    ``cos theta`` (-> 0 edge-on) but the shear term does **not** vanish edge-on
    (``general-upgrades-1.md`` "Tier B Drag"), so the table spans the leeward half too.

    ``theta`` is the face-flow angle ``[0, pi]`` (axis, shape ``(n_theta,)``); the
    state arrays ``speed`` / ``temperature`` / ``alpha`` are per cloud sample (shape
    ``(N,)``). Returns shape ``(N, n_theta)``. The ``sin theta`` is written as
    ``sqrt(max(0, 1 - cos^2 theta))`` -- bit-faithful to the experiment kernel's
    ``cos theta`` evaluation and harmless at the poles -- so the Chunk-3 cross-
    validation stays tight.
    """
    from scipy.special import erf  # generation-only dependency (see requirements)

    boltzmann = gen.BOLTZMANN
    s = speed * np.sqrt(mass / (2.0 * boltzmann * temperature))  # speed ratio, (N,)
    reflected_t = (1.0 - alpha) * mass * speed * speed / (
        3.0 * boltzmann
    ) + alpha * gen.WALL_TEMPERATURE
    tr = reflected_t / temperature  # reflected/ambient temperature ratio, (N,)

    cos_t = np.cos(theta)  # gamma = cos theta, (n_theta,)
    sin_t = np.sqrt(np.maximum(0.0, 1.0 - cos_t * cos_t))  # sin theta >= 0 on [0, pi]

    s_col = s[:, None]
    a = s_col * cos_t[None, :]  # S * cos theta, (N, n_theta)
    e = np.exp(-a * a)
    zp = 1.0 + erf(a)

    cp_incident = (a / np.sqrt(np.pi) * e + (a * a + 0.5) * zp) / (s_col * s_col)
    cp_reemit = (np.sqrt(tr)[:, None] / (2.0 * s_col * s_col)) * (
        e + np.sqrt(np.pi) * a * zp
    )
    cp = cp_incident + cp_reemit  # normal-pressure coefficient
    c_shear = (sin_t[None, :] / (np.sqrt(np.pi) * s_col)) * (
        e + np.sqrt(np.pi) * a * zp
    )
    return cp * cos_t[None, :] + c_shear * sin_t[None, :]


def _face_cd_total(
    msis_rows: NDArray[np.float64],
    speed: NDArray[np.float64],
    alpha: NDArray[np.float64],
    incidence_axis: NDArray[np.float64],
) -> NDArray[np.float64]:
    """Mass-flux-weighted per-face Cd over the species, for every incidence node.

    Same per-species mass-density weighting as the sphere (``_sphere_cd_total``), but
    the per-species coefficient is the per-*face* closed form evaluated across the
    whole incidence axis. ``msis_rows`` is ``(N, 11)``; returns ``(N, n_theta)``.
    """
    temperature = msis_rows[:, gen._COL["T"]]
    numerator = np.zeros((speed.size, incidence_axis.size))
    denominator = np.zeros(speed.size)
    for column, mass in gen._SPECIES.values():
        number_density = msis_rows[:, column]
        valid = np.isfinite(number_density) & (number_density > 0.0)
        partial_density = np.where(valid, number_density * mass, 0.0)
        cd = _face_cd_species(incidence_axis, speed, temperature, mass, alpha)
        numerator += partial_density[:, None] * np.where(valid[:, None], cd, 0.0)
        denominator += partial_density
    # Every row already passed the total-density rho>0 filter in generate(), so a
    # weighted species is present and the denominator is positive. Guard anyway: a zero
    # denominator yields a NaN row that LinearNDInterpolator silently spreads across the
    # shipped grid (the Chunk-3 cross-validation hazard), so fail loudly here instead.
    if not np.all(denominator > 0.0):
        n_bad = int(np.count_nonzero(denominator <= 0.0))
        raise ValueError(
            f"mass-flux denominator is non-positive for {n_bad} cloud row(s): no "
            "weighted species present though total density passed the rho>0 filter; "
            "refusing to emit NaN into the table"
        )
    return numerator / denominator[:, None]


# --- condition sweep + regrid ----------------------------------------------


def generate(
    *,
    radius_axis: NDArray[np.float64],
    density_axis: NDArray[np.float64],
    incidence_axis: NDArray[np.float64],
    n_conditions: int,
    seed: int,
    internal_alt_min_km: float = gen.DEFAULT_INTERNAL_ALT_MIN_KM,
    internal_alt_max_km: float = gen.DEFAULT_INTERNAL_ALT_MAX_KM,
    internal_alt_points: int = gen.DEFAULT_INTERNAL_ALT_POINTS,
    storm_fraction: float = gen.DEFAULT_STORM_FRACTION,
) -> tuple[NDArray[np.float64], dict[str, object]]:
    """Build the ``(radius, density, incidence) -> Cd`` grid plus provenance metadata.

    Heavy, generation-only imports (``pymsis``, ``scipy``) happen here so ``--help``
    runs in the bare propygator env. The condition sweep, accommodation calibration,
    and radius/speed maps are reused from the sphere generator; only the per-face Cd
    and the third (incidence) axis are new.
    """
    from pymsis import msis  # generation-only dependency (see requirements)
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator

    rng = np.random.default_rng(seed)
    conditions = gen._sample_conditions(n_conditions, rng, storm_fraction)
    langmuir_K = gen._calibrate_accommodation_K(msis.run, gen.ANCHOR_ALPHA)
    logger.info(
        "Calibrated Langmuir K = %.3e 1/Pa (anchor alpha=%.2f)",
        langmuir_K,
        gen.ANCHOR_ALPHA,
    )

    # Sample geodetic altitudes spanning the radius grid with edge margin, so the
    # per-slice regrid interpolant covers the mesh corners rather than nearest-filling.
    altitudes_km = np.linspace(
        internal_alt_min_km, internal_alt_max_km, internal_alt_points
    )

    radii: list[NDArray[np.float64]] = []
    densities: list[NDArray[np.float64]] = []
    cds: list[NDArray[np.float64]] = []  # each (n_alt_valid, n_incidence)
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
        rho = rows[:, gen._COL["rho"]]
        finite = np.isfinite(rho) & (rho > 0.0)
        rows = rows[finite]
        radius_m = gen._geocentric_radius(altitudes_km[finite] * 1e3, np.radians(lat))
        speed = gen._relative_speed(radius_m, np.radians(lat))
        alpha = gen._accommodation(
            rows[:, gen._COL["O"]], rows[:, gen._COL["T"]], langmuir_K
        )
        cd = _face_cd_total(rows, speed, alpha, incidence_axis)
        radii.append(radius_m)
        densities.append(rows[:, gen._COL["rho"]])
        cds.append(cd)

    radius_cloud = np.concatenate(radii)
    density_cloud = np.concatenate(densities)
    cd_cloud = np.concatenate(cds, axis=0)  # (N, n_incidence)
    logger.info(
        "Built %d (radius, density) cloud points x %d incidence nodes; "
        "per-face Cd in [%.3f, %.3f]",
        radius_cloud.size,
        incidence_axis.size,
        float(cd_cloud.min()),
        float(cd_cloud.max()),
    )

    # Regrid the cloud onto the clean mesh. The incidence axis is sampled EXACTLY at
    # every node (no interpolation in theta during generation), so the regrid is a
    # per-incidence-slice 2-D (radius, log-density) interpolation -- identical to the
    # sphere generator, just vector-valued across the incidence columns (one shared
    # triangulation). Cd is smooth in log-density, so the interpolation (and the
    # shipped density axis) live in log10(density) space.
    points = np.column_stack([radius_cloud, np.log10(density_cloud)])
    linear = LinearNDInterpolator(points, cd_cloud)
    nearest = NearestNDInterpolator(points, cd_cloud)
    mesh_r, mesh_logd = np.meshgrid(radius_axis, np.log10(density_axis), indexing="ij")
    grid = linear(mesh_r, mesh_logd)  # (n_radius, n_density, n_incidence)
    # A query point is inside or outside the cloud's convex hull regardless of
    # incidence, so finiteness is all-or-nothing across the incidence axis; use the
    # first slice as the inside/outside indicator and fill those columns by nearest.
    outside = ~np.isfinite(grid[..., 0])
    if outside.any():
        grid[outside] = nearest(mesh_r[outside], mesh_logd[outside])
    n_outside = int(outside.sum())
    logger.info(
        "Regridded onto %dx%dx%d mesh; %d edge column(s) filled by nearest-neighbour",
        radius_axis.size,
        density_axis.size,
        incidence_axis.size,
        n_outside,
    )

    # Sanity anchors at a representative mid-grid cell (build-plan Chunk-2 verify: the
    # per-face Cd should floor near ~0.07 at edge-on and taper to ~0 by ~110 deg).
    ri, di = radius_axis.size // 2, density_axis.size // 2
    anchors_deg = (0.0, 90.0, 110.0, 180.0)
    anchor_vals = [
        float(grid[ri, di, int(np.argmin(np.abs(incidence_axis - np.radians(a))))])
        for a in anchors_deg
    ]
    logger.info(
        "Per-face Cd anchors at r=%.0f km, rho=%.2e kg/m^3:  "
        "theta=0 %.4f | 90 %.4f | 110 %.4f | 180 %.4f",
        (radius_axis[ri] - gen.WGS84_A) / 1e3,
        density_axis[di],
        *anchor_vals,
    )

    n_storm = sum(bool(c["storm"]) for c in conditions)
    spacing_deg = float(np.degrees(incidence_axis[1] - incidence_axis[0]))
    metadata: dict[str, object] = {
        "model": (
            "Schaaf-Chambre/Sentman per-face free-molecular Cd (normal pressure + "
            "tangential shear, DRIA), mass-flux weighted over NRLMSISE-00 species; "
            "referenced to full face area, keyed on face-flow angle theta in [0, pi]"
        ),
        "accommodation": (
            "SESAM Langmuir on atomic-O coverage (shared with the sphere table)"
        ),
        "anchor_alpha": gen.ANCHOR_ALPHA,
        "atmosphere": "NRLMSISE-00 (pymsis)",
        "axes": (
            "radius_axis [m] (geocentric), density_axis [kg/m^3] (total), "
            "incidence_axis [rad] (face-flow angle theta in [0, pi])"
        ),
        # The GRID AXES are the coverage claim (the validated (radius, density) band
        # plus the full [0, pi] incidence range). The INTERNAL SAMPLING is wider in
        # altitude (a margin so the regrid interpolates the mesh corners) and is NOT a
        # claim; both recorded so the distinction is auditable.
        "grid_band": {
            "radius_m": [float(radius_axis[0]), float(radius_axis[-1])],
            "altitude_km_equatorial": [
                float(radius_axis[0] - gen.WGS84_A) / 1e3,
                float(radius_axis[-1] - gen.WGS84_A) / 1e3,
            ],
            "density_kgm3": [float(density_axis[0]), float(density_axis[-1])],
            "incidence_rad": [float(incidence_axis[0]), float(incidence_axis[-1])],
            "incidence_deg": [
                float(np.degrees(incidence_axis[0])),
                float(np.degrees(incidence_axis[-1])),
            ],
            "n_incidence": int(incidence_axis.size),
            "incidence_spacing_deg": spacing_deg,
        },
        "internal_sampling_band": {
            "altitude_km": [float(altitudes_km[0]), float(altitudes_km[-1])],
            "n_points": int(altitudes_km.size),
            "note": "wider-than-grid margin for regrid corner coverage; not a claim",
        },
        # The actual extent of the sampled (radius, density) cloud, plus how many mesh
        # columns fell OUTSIDE it and were filled by nearest-neighbour rather than
        # interpolated (one count per (radius, density) cell, shared across incidence).
        "sampled_cloud": {
            "radius_m": [float(radius_cloud.min()), float(radius_cloud.max())],
            "density_kgm3": [float(density_cloud.min()), float(density_cloud.max())],
            "n_mesh_cells_nearest_filled": n_outside,
            "n_mesh_cells_total": int(radius_axis.size * density_axis.size),
        },
        "condition_coverage": {
            "n_conditions": n_conditions,
            "n_storm": n_storm,
            "quiet_f107": list(gen.QUIET_F107_RANGE),
            "quiet_ap": list(gen.QUIET_AP_RANGE),
            "storm_f107": list(gen.STORM_F107_RANGE),
            "storm_ap": list(gen.STORM_AP_RANGE),
        },
        "confidence": {
            "green_rms_pct": 5.0,
            # Per-face collapse onto (radius, density) at fixed attitude is green
            # (<= 5% RMS) across the box experiment (cd_box_experiment.py: all
            # attitudes PASS, <~2% RMS even at an 80 deg grazing plate), so there is no
            # reduced-confidence region within the grid; the high-altitude end is
            # non-binding (drag ~ rho -> 0).
            "green_validated_through_km": float(radius_axis[-1] - gen.WGS84_A) / 1e3,
            "reduced_confidence_above_km": None,
            # Interpolation accuracy on the incidence axis (Chunk-1 convergence study).
            "incidence_interp_max_pct_at_nodes": {"33": 0.35, "65": 0.09},
            "cross_validation_max_rel_pct": CROSS_VALIDATION_MAX_REL_PCT,
            "note": (
                "Per-face Cd is smooth (C-infinity) in theta; the Chunk-1 convergence "
                "study (cd_box_incidence_convergence.py) shows linear interpolation "
                "over the [0, pi] theta axis converges at ~2nd order with no special "
                "node placement (65 nodes: < 0.1% max vs the kernel). The per-face "
                "collapse onto (radius, density) at fixed attitude is green across the "
                "box experiment. Experiment-vs-generator per-face cross-validation on "
                "the assembled CdA (Chunk 3, cross_validate_box_face.py) agrees to "
                "cross_validation_max_rel_pct (<< 1%; the shared closed form is "
                "bit-identical, the residual is the relative-speed radius convention)."
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
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    radius_axis = np.linspace(args.radius_min, args.radius_max, args.radius_points)
    density_axis = np.logspace(
        np.log10(args.density_min), np.log10(args.density_max), args.density_points
    )
    # Incidence axis is fixed to the full [0, pi] face-flow range (contract); only the
    # node count is tunable. Uniform spacing -- the Chunk-1 study needs no clustering.
    incidence_axis = np.linspace(
        INCIDENCE_MIN_RAD, INCIDENCE_MAX_RAD, args.incidence_points
    )
    return radius_axis, density_axis, incidence_axis


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: parse args, run the sweep+regrid, write the ``.npz``."""
    parser = argparse.ArgumentParser(
        description="Generate the shipped BoxFaceCd per-face drag table.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT, help="Output .npz path."
    )
    parser.add_argument(
        "--radius-min", type=float, default=gen.DEFAULT_RADIUS_MIN_M, dest="radius_min"
    )
    parser.add_argument(
        "--radius-max", type=float, default=gen.DEFAULT_RADIUS_MAX_M, dest="radius_max"
    )
    parser.add_argument(
        "--radius-points",
        type=int,
        default=gen.DEFAULT_RADIUS_POINTS,
        dest="radius_points",
    )
    parser.add_argument(
        "--density-min", type=float, default=gen.DEFAULT_DENSITY_MIN, dest="density_min"
    )
    parser.add_argument(
        "--density-max", type=float, default=gen.DEFAULT_DENSITY_MAX, dest="density_max"
    )
    parser.add_argument(
        "--density-points",
        type=int,
        default=gen.DEFAULT_DENSITY_POINTS,
        dest="density_points",
    )
    parser.add_argument(
        "--incidence-points",
        type=int,
        default=DEFAULT_INCIDENCE_POINTS,
        dest="incidence_points",
        help="Uniform nodes over the fixed [0, pi] face-flow angle axis.",
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
        default=gen.DEFAULT_STORM_FRACTION,
        dest="storm_fraction",
        help="Fraction of conditions drawn from the validated storm tails.",
    )
    parser.add_argument(
        "--internal-alt-min",
        type=float,
        default=gen.DEFAULT_INTERNAL_ALT_MIN_KM,
        dest="internal_alt_min_km",
        help="Internal MSIS altitude sampling floor [km] (wider than the grid).",
    )
    parser.add_argument(
        "--internal-alt-max",
        type=float,
        default=gen.DEFAULT_INTERNAL_ALT_MAX_KM,
        dest="internal_alt_max_km",
        help="Internal MSIS altitude sampling ceiling [km] (wider than the grid).",
    )
    parser.add_argument(
        "--internal-alt-points",
        type=int,
        default=gen.DEFAULT_INTERNAL_ALT_POINTS,
        dest="internal_alt_points",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260611,
        help="RNG seed (reproducible output; default matches the sphere table's "
        "condition cloud for cross-table coherence).",
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

    radius_axis, density_axis, incidence_axis = _build_axes(args)
    grid, metadata = generate(
        radius_axis=radius_axis,
        density_axis=density_axis,
        incidence_axis=incidence_axis,
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
        incidence_axis=incidence_axis,
        metadata_json=np.asarray(json.dumps(metadata)),
    )
    logger.info("Wrote %s (grid shape %s)", output, grid.shape)


if __name__ == "__main__":
    main()
