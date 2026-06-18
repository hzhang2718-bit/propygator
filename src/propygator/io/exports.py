"""Tabular and bundled export of a :class:`~propygator.core.states.Trajectory`.

``export_csv`` writes a wide CSV with a fixed set of 16 default columns plus
opt-in column groups (osculating Keplerian elements, Sun position/direction),
and a ``# key: value`` metadata header carrying the trajectory's reproducibility
record (features.md §1.1 "Outputs"). ``export_all`` is the convenience aggregator
that bundles the common case — a summary figure, one or more 3-D HTML views, and a
CSV — into an output directory.

Design notes (architecture §7):

- **Dependency rule.** ``io/`` depends only on ``core/`` — every CSV column is built
  from data reachable from the core data model (frame conversions, geodetic
  projection, Keplerian conversion, the Sun body). An eclipse flag is *not*
  offered: it would force a dependency on ``tracking/`` (architecture §7).
- **``export_all`` and ``plotting/``.** ``export_all`` is the one function here that
  needs ``plotting/``; it imports ``plot_summary`` / ``plot_3d`` **lazily inside the
  function body**, never at module top. So importing ``propygator.io`` (and the
  headless core that leans on it) never pulls matplotlib/plotly — the real intent of
  the "io depends only on core" rule — while ``export_all`` still lives alongside
  ``export_csv`` where the build plan places it. Same lazy-import escape hatch the
  package uses for the JVM.
- **Column registry (extensibility hook).** Each opt-in group is a builder function
  keyed by its token; the dict the builder returns is the single source of both the
  column names and their order. Adding a future group is one registry entry (token →
  builder), provided the value is derivable from ``core/`` data (so no signature
  change, no caller change).
- **Additive ``columns`` semantics.** ``columns=None`` yields the 16 defaults;
  passing a list of group tokens (``["keplerian", "sun"]``) *appends* those groups
  to the defaults in a fixed canonical order, so the leading schema is stable.
- **Units at the boundary.** Internally SI; the CSV reports angles in degrees and
  keeps positions/velocities in metres / m·s⁻¹ (the column names carry the unit).
"""

from __future__ import annotations

import logging
import math
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ..core.bodies import _sun
from ..core.frames import Frame, geodetic_track
from ..core.states import Trajectory, _vector3d_to_array
from ..core.time import _abs_date

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence


logger = logging.getLogger(__name__)


# --- column constants -------------------------------------------------------

# The 16 default columns (features.md §1.1) are built — in output order — by
# ``_build_default_columns``, whose returned dict is the single source of their names
# and order: epoch_utc, epoch_mjd_utc, x/y/z_eme2000_m, vx/vy/vz_eme2000_mps,
# x/y/z_itrf_m, latitude_deg, longitude_deg, altitude_m, speed_inertial_mps
# (EME2000-relative), speed_itrf_mps (ground-relative). Positions/velocities are
# reported in EME2000 (the native output frame) and ITRF; geodetic lat/lon/alt are
# WGS84; each speed is the velocity magnitude in its frame.

# MJD epoch (1858-11-17 00:00 UTC): MJD = days since this instant.
_MJD_ORIGIN_ISO = "1858-11-17"

# ISO-8601 format for the ``epoch_utc`` column (UTC wall-clock, 'T' separator,
# microsecond precision; UTC is implied by the column name, so no offset suffix).
_EPOCH_UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%f"


def _build_keplerian_columns(eme: Trajectory) -> dict[str, np.ndarray]:
    """Osculating classical elements per sample, computed in EME2000.

    ``eme`` is the trajectory already converted to EME2000 (the frame the opt-in
    Keplerian and Sun columns are computed in). Angles are converted to degrees at the
    boundary. Near-circular / near-equatorial orbits make ω, Ω, ν individually
    ill-conditioned (architecture §6); the values stay finite but go erratic —
    documented, not corrected here.
    """
    n = len(eme)
    sma = np.empty(n, dtype=np.float64)
    ecc = np.empty(n, dtype=np.float64)
    inc = np.empty(n, dtype=np.float64)
    raan = np.empty(n, dtype=np.float64)
    argp = np.empty(n, dtype=np.float64)
    nu = np.empty(n, dtype=np.float64)
    for i, state in enumerate(eme):
        k = state.to_keplerian()
        sma[i] = k.semi_major_axis_m
        ecc[i] = k.eccentricity
        inc[i] = math.degrees(k.inclination_rad)
        raan[i] = math.degrees(k.raan_rad)
        argp[i] = math.degrees(k.arg_perigee_rad)
        nu[i] = math.degrees(k.true_anomaly_rad)
    return {
        "semi_major_axis_m": sma,
        "eccentricity": ecc,
        "inclination_deg": inc,
        "raan_deg": raan,
        "arg_perigee_deg": argp,
        "true_anomaly_deg": nu,
    }


def _build_sun_columns(eme: Trajectory) -> dict[str, np.ndarray]:
    """Geocentric Sun position (EME2000) plus the unit satellite→Sun direction.

    ``eme`` is the trajectory already in EME2000. The direction is computed from the
    spacecraft (``Sun − satellite``, normalised), which is the physically correct
    lighting direction at the satellite — the geocentric Sun direction differs by
    ~9 arcsec and is the common foot-gun.
    """
    from .._orekit_init import _ensure_started

    _ensure_started()

    sun = _sun()
    eme_frame = Frame.EME2000.to_orekit()
    n = len(eme)
    sat = eme.positions
    pos = np.empty((n, 3), dtype=np.float64)
    direction = np.empty((n, 3), dtype=np.float64)
    for i in range(n):
        # Build the AbsoluteDate straight from the two-part TAI count (the
        # Trajectory.to_frame pattern) — no throwaway Epoch per sample.
        date = _abs_date(int(eme._epochs_int[i]), float(eme._epochs_frac[i]))
        p = sun.getPVCoordinates(date, eme_frame).getPosition()
        sun_pos = _vector3d_to_array(p)
        pos[i] = sun_pos
        d = sun_pos - sat[i]
        direction[i] = d / np.linalg.norm(d)
    return {
        "sun_x_eme2000_m": pos[:, 0],
        "sun_y_eme2000_m": pos[:, 1],
        "sun_z_eme2000_m": pos[:, 2],
        "sun_dir_x_eme2000": direction[:, 0],
        "sun_dir_y_eme2000": direction[:, 1],
        "sun_dir_z_eme2000": direction[:, 2],
    }


# Opt-in column groups: token -> builder. The builder's returned dict supplies the
# column names and their order, so adding a future group is one entry here plus its
# builder (extensibility hook; module docstring).
_OPTIONAL_GROUPS: dict[str, Callable[[Trajectory], dict[str, np.ndarray]]] = {
    "keplerian": _build_keplerian_columns,
    "sun": _build_sun_columns,
}

# Canonical order opt-in groups are appended in, regardless of the order tokens are
# passed in ``columns`` — keeps the output schema deterministic.
_GROUP_ORDER: tuple[str, ...] = ("keplerian", "sun")


# --- assembly ---------------------------------------------------------------


def _resolve_groups(columns: list[str] | None) -> tuple[str, ...]:
    """Resolve ``columns`` to the requested opt-in groups, in canonical order.

    ``None`` → no opt-in groups (the 16 defaults only). A list of group tokens selects
    those groups in canonical order (duplicates collapsed). An unknown token raises
    ``ValueError`` listing the valid groups.
    """
    if columns is None:
        return ()

    requested: set[str] = set()
    for token in columns:
        if token not in _OPTIONAL_GROUPS:
            valid = ", ".join(sorted(_OPTIONAL_GROUPS))
            raise ValueError(
                f"unknown column group {token!r}; valid opt-in groups are: {valid}. "
                "Pass columns=None for the 16 default columns."
            )
        requested.add(token)
    return tuple(g for g in _GROUP_ORDER if g in requested)


def _build_default_columns(
    traj: Trajectory,
) -> tuple[dict[str, np.ndarray], Trajectory]:
    """Build the 16 default columns; return (data, the EME2000 trajectory).

    The EME2000 trajectory is returned so the opt-in builders can reuse it as their
    context rather than re-converting. EME2000 conversion is vectorised
    (``Trajectory.to_frame``); the ITRF trajectory and per-sample geodetic lat/lon/alt
    come from the shared :func:`~propygator.core.frames.geodetic_track`.
    """
    import pandas as pd

    eme = traj.to_frame(Frame.EME2000)
    itrf, lat, lon, alt = geodetic_track(traj)

    # Reuse Trajectory.to_dataframe for the vectorised epoch → UTC datetime path.
    epoch_utc = eme.to_dataframe()["epoch_utc"]
    epoch_iso = epoch_utc.dt.strftime(_EPOCH_UTC_FORMAT).to_numpy()
    epoch_mjd = (
        (epoch_utc - pd.Timestamp(_MJD_ORIGIN_ISO, tz="UTC")) / pd.Timedelta(days=1)
    ).to_numpy()

    data: dict[str, np.ndarray] = {
        "epoch_utc": epoch_iso,
        "epoch_mjd_utc": epoch_mjd,
        "x_eme2000_m": eme.positions[:, 0],
        "y_eme2000_m": eme.positions[:, 1],
        "z_eme2000_m": eme.positions[:, 2],
        "vx_eme2000_mps": eme.velocities[:, 0],
        "vy_eme2000_mps": eme.velocities[:, 1],
        "vz_eme2000_mps": eme.velocities[:, 2],
        "x_itrf_m": itrf.positions[:, 0],
        "y_itrf_m": itrf.positions[:, 1],
        "z_itrf_m": itrf.positions[:, 2],
        "latitude_deg": lat,
        "longitude_deg": lon,
        "altitude_m": alt,
        "speed_inertial_mps": np.linalg.norm(eme.velocities, axis=1),
        "speed_itrf_mps": np.linalg.norm(itrf.velocities, axis=1),
    }
    return data, eme


# Leading characters a spreadsheet may interpret as a formula/command (CSV
# injection). '-' is deliberately excluded: it is almost always a legitimate
# negative number, and neutralizing it would corrupt numeric metadata.
_CSV_FORMULA_TRIGGERS = frozenset({"=", "+", "@", "\t"})


def _format_metadata_value(value: object) -> str:
    """Render a metadata value as a single parseable string for a header line.

    Carriage returns and newlines are collapsed to spaces so a value can never
    break out of its ``# key: value`` comment line into a forged second line — which
    would not carry the ``#`` prefix and would corrupt the documented
    ``pandas.read_csv(path, comment="#")`` reload (e.g. a multi-line ``name``).

    A value beginning with a spreadsheet formula trigger (``=`` / ``+`` / ``@`` /
    tab) is prefixed with a single quote so a consumer that re-emits it into a cell
    treats it as text (CSV-injection defense-in-depth; the values live in ``#``
    comment lines, so the common spreadsheet import is already safe).
    """
    if isinstance(value, (list, tuple)):
        rendered = ", ".join(str(v) for v in value)
    elif isinstance(value, dict):
        rendered = ", ".join(f"{k}={v}" for k, v in value.items())
    else:
        rendered = str(value)
    rendered = rendered.replace("\r", " ").replace("\n", " ")
    if rendered[:1] in _CSV_FORMULA_TRIGGERS:
        rendered = "'" + rendered
    return rendered


def _metadata_header_lines(metadata: dict) -> list[str]:
    """The trajectory metadata as ``# key: value`` comment lines (insertion order)."""
    return [
        f"# {key}: {_format_metadata_value(value)}" for key, value in metadata.items()
    ]


def export_csv(
    traj: Trajectory, path: str | Path, *, columns: list[str] | None = None
) -> None:
    """Write ``traj`` to ``path`` as CSV with a metadata header (features.md §1.1).

    Parameters
    ----------
    traj
        The trajectory to export. Positions/velocities are written in both EME2000
        and ITRF; opt-in Keplerian elements are computed in EME2000.
    path
        Destination file (``str`` or ``Path``); the parent directory is created if
        missing. An existing file at ``path`` is overwritten.
    columns
        ``None`` (default) writes the 16 default columns. A list of opt-in group
        tokens appends those groups to the defaults: ``"keplerian"`` adds the six
        osculating classical elements, ``"sun"`` adds geocentric Sun position and
        the unit satellite→Sun direction. Groups are appended in a fixed canonical
        order; an unknown token raises ``ValueError``.

    Notes
    -----
    The trajectory's :class:`~propygator.core.states.TrajectoryMetadata` is written
    as ``# key: value`` comment lines above the table; reload with
    ``pandas.read_csv(path, comment="#")``. The JVM starts lazily on first call
    (frame conversions / geodetic projection).
    """
    import pandas as pd

    groups = _resolve_groups(columns)
    data, eme = _build_default_columns(traj)
    for group in groups:
        data.update(_OPTIONAL_GROUPS[group](eme))

    frame = pd.DataFrame(data)

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)  # match export_all's behavior
    header = _metadata_header_lines(dict(traj.metadata))
    # newline="" lets pandas control line terminators (no doubled newlines on
    # Windows); comment lines are written first, then the table body.
    with out.open("w", newline="", encoding="utf-8") as fh:
        if header:
            fh.write("\n".join(header) + "\n")
        frame.to_csv(fh, index=False)

    logger.info("Exported %d samples to %s (%d columns)", len(traj), out, len(data))


def export_all(
    traj: Trajectory,
    output_dir: str | Path,
    *,
    summary: bool = True,
    plot_3d: bool = True,
    csv: bool = True,
    show_map_overlay: bool = True,
    speed_frames: Sequence[Frame] = (Frame.EME2000,),
    frames_3d: Sequence[Frame] = (Frame.EME2000,),
    csv_columns: list[str] | None = None,
    filename_prefix: str = "trajectory",
) -> dict[str, Path]:
    """Generate the standard outputs for ``traj``; return name → written path.

    Bundles the common case (features.md §1.1): a stacked summary figure, one or
    more interactive 3-D HTML views, and a CSV, all written into ``output_dir``
    (created if missing). Files are named ``{filename_prefix}_{output}.{ext}`` —
    e.g. ``trajectory_summary.png``, ``trajectory.csv``.

    Parameters
    ----------
    traj
        The trajectory to export.
    output_dir
        Destination directory (``str`` or ``Path``); created with parents if it
        does not exist.
    summary, plot_3d, csv
        Toggle each output. Booleans (not a string list) keep IDE autocomplete and
        static checking — a typo'd output name can't become a silent no-op.
    show_map_overlay
        Drape the bundled coastline on the ground track (summary) and the ITRF 3-D
        view. Ignored for inertial 3-D frames (the Earth rotates under the orbit).
    speed_frames
        Frames whose speed panels appear in the summary figure (one panel each).
    frames_3d
        Frames to render in 3-D, one HTML file each. Files are **always**
        frame-suffixed — ``{prefix}_3d_eme2000.html`` / ``{prefix}_3d_itrf.html`` —
        with dict keys ``"3d_eme2000"`` / ``"3d_itrf"`` (``frame.value.lower()``),
        regardless of how many frames are requested. The uniform shape keeps the
        returned dict scriptable across single- and multi-frame calls (there is no
        bare ``"3d"`` key).
    csv_columns
        Forwarded to :func:`export_csv` as its ``columns`` argument.
    filename_prefix
        Leading filename token shared by every written file.

    Returns
    -------
    dict[str, Path]
        Maps each produced output name to the file written. Only enabled outputs
        appear. Keys are ``"summary"``, ``"csv"``, and one ``"3d_<frame>"`` per
        entry in ``frames_3d``.

    Notes
    -----
    ``plot_summary`` / ``plot_3d`` are imported lazily here so that importing
    ``propygator.io`` stays free of matplotlib/plotly (module docstring). The JVM
    starts lazily on the first frame conversion.
    """
    # filename_prefix is interpolated into output paths; require a bare filename
    # component so a prefix with separators / '..' / an absolute root cannot escape
    # output_dir (path traversal). Path(...).name strips any directory part, so a
    # prefix that survives the name check has none; '.'/'..' are excluded explicitly
    # because Path('..').name is '..' (it would otherwise pass the name check).
    if (
        not filename_prefix
        or filename_prefix in {".", ".."}
        or Path(filename_prefix).name != filename_prefix
    ):
        raise ValueError(
            "filename_prefix must be a bare filename component with no path "
            f"separators, no '..', and not absolute; got {filename_prefix!r}."
        )

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    if csv:
        csv_path = out_dir / f"{filename_prefix}.csv"
        export_csv(traj, csv_path, columns=csv_columns)
        written["csv"] = csv_path

    if summary:
        # Lazy, function-local imports keep io/ free of plotting at module load
        # (architecture §7 dependency rule; module docstring).
        import matplotlib.pyplot as plt

        from ..plotting import plot_summary

        fig = plot_summary(
            traj, speed_frames=speed_frames, show_map_overlay=show_map_overlay
        )
        summary_path = out_dir / f"{filename_prefix}_summary.png"
        fig.savefig(summary_path)
        plt.close(fig)  # release the figure (export_all is often called in a loop)
        written["summary"] = summary_path

    if plot_3d:
        from ..plotting import plot_3d as _plot_3d

        # De-duplicate by enum identity (Frame.J2000 is an alias of Frame.EME2000),
        # preserving order, so an aliased/repeated frame doesn't render and silently
        # overwrite the same file twice or collapse two dict entries into one.
        for frame in dict.fromkeys(frames_3d):
            # The coastline overlay is meaningful only on the Earth-fixed ITRF view;
            # gating it here keeps the inertial render from emitting a warning.
            fig3d = _plot_3d(
                traj,
                frame=frame,
                show_map_overlay=show_map_overlay and frame is Frame.ITRF,
            )
            # Always frame-suffix the 3D output so the filename and dict key have a
            # stable, scriptable shape regardless of how many frames are requested.
            token = frame.value.lower()
            path = out_dir / f"{filename_prefix}_3d_{token}.html"
            fig3d.write_html(str(path))
            written[f"3d_{token}"] = path

    logger.info("export_all wrote %d output(s) to %s", len(written), out_dir)
    return written
