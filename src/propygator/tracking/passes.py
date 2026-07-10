"""``find_passes`` — the Feature 1.5 pass-search engine (features.md §1.5).

The headline verb: given a TLE, a :class:`GroundStation`, and a time window,
find the satellite's passes — **visible** ones by default — with refined
rise/culmination/set epochs, azimuths, and a peak visual magnitude. Pure
composition over shipped primitives (contract: "Search algorithm"):

- **Coarse scan:** one :func:`propagate_tle` over the window on an even ~30 s
  grid whose last sample lands exactly on the window end, plus one batched
  :func:`look_angles_track` (a single ``TopocentricFrame`` build).
- **Bracket:** maximal above-gate sample runs, padded one sample each side,
  **plus** near-miss local maxima within ``_GRAZE_MARGIN_DEG`` below the gate —
  so a pass shorter than one coarse step still gets a candidate; candidates
  whose refined arc never reaches the gate are discarded.
- **Refine:** per candidate, a fine batched grid (~1 s) + sub-sample
  interpolation — linear at the threshold crossings, parabolic at the
  culmination — comfortably under the contract's ~0.5 s target.
- **Lighting only inside passes:** the ``tracking/visibility.py`` kernel
  (conical umbra, phase-law magnitude) plus the observer-darkness gate
  (station Sun elevation ≤ ``_TWILIGHT_SUN_EL_DEG``), evaluated on each pass's
  own samples — never as an O(window) sweep.

The scan constants below are **tunable placeholders, not contract** (the §1.4
buffer-magnitudes precedent). Pre-flight validation and ``Pass`` assembly are
pure Python; JVM contact happens only inside ``find_passes``'s reported region
(propagation, look angles, lighting), so the ``ValueError`` table raises with
no JVM and the progress ``start`` line prints before JVM boot (the §1.1
convention).
"""

from __future__ import annotations

import logging
import math
import warnings
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from ..core.catalogs import _standard_magnitude
from ..core.exceptions import StaleTLEWarning
from ..core.frames import Frame
from ..core.observation import (
    Pass,
    _body_azel,
    _station_topocentric_frame,
    look_angles_track,
)
from ..core.progress import ProgressCallback, _ProgressReporter
from ..core.states import _vector3d_to_array
from ..core.time import Epoch, USTimeZone, _resolve_tz
from ..tle.propagator import propagate_tle
from .visibility import (
    _is_sunlit,
    _magnitudes,
    _phase_angle_rad,
    _sun_positions_eme2000,
)

if TYPE_CHECKING:
    from datetime import tzinfo

    # Type-only; the org.orekit namespace is a runtime JPype stub with no
    # importable module at type-check time (mypy: ignore_missing_imports).
    import org.orekit.frames  # noqa: F401
    import pandas as pd  # noqa: F401

    from ..core.observation import GroundStation
    from ..core.states import Trajectory
    from ..core.tle import TLE

logger = logging.getLogger(__name__)

# Scan constants (tunable placeholders, not contract — features.md §1.5 "Still
# open"). The coarse step bounds how short a pass can be and still show an
# above-gate sample; the graze margin catches the rest (a local maximum within
# this band below the gate is refined, then kept only if the fine arc actually
# crosses the gate). The fine step sets the pre-interpolation event resolution.
_COARSE_STEP_S = 30.0
_FINE_STEP_S = 1.0
_GRAZE_MARGIN_DEG = 2.0

# End of civil twilight — the standard satellite-spotting "observer in
# darkness" threshold (contract: "Lighting model"; fixed for v1, not a
# parameter).
_TWILIGHT_SUN_EL_DEG = -6.0

# Per-candidate cap on the fine grid. A multi-hour above-gate arc (deep-space
# orbits seen from mid-latitudes) would otherwise request span/1 s samples;
# above the cap the fine step degrades gracefully to span/(cap-1) and the
# sub-sample interpolation still refines the events.
_MAX_FINE_SAMPLES = 10_000


def _interp_azimuth_deg(az0: float, az1: float, frac: float) -> float:
    """Interpolate between two compass azimuths along the short way around.

    Plain linear interpolation breaks at the 0/360 seam (359° → 1° must move
    +2°, not −358°); this maps the difference into (−180°, 180°] first and
    normalizes the result back to [0, 360).
    """
    delta = (az1 - az0 + 180.0) % 360.0 - 180.0
    return (az0 + frac * delta) % 360.0


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Inclusive ``(start, end)`` index pairs of the maximal True runs."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return [(int(s), int(e) - 1) for s, e in zip(edges[0::2], edges[1::2])]


def _candidate_brackets(
    elevation_deg: np.ndarray, min_elevation_deg: float
) -> list[tuple[int, int]]:
    """Coarse-grid index brackets (inclusive) that may contain passes.

    Above-gate runs padded one sample each side (so the fine grid brackets the
    threshold crossings), plus the grazing candidates: interior local maxima
    below the gate by at most ``_GRAZE_MARGIN_DEG`` (a pass shorter than one
    coarse step peeks above the gate *between* samples — contract: "Search
    algorithm"; the ≥ comparisons keep a flat-topped maximum). Overlapping or
    touching brackets are merged, so each returned bracket is refined once.
    """
    n = elevation_deg.shape[0]
    above = elevation_deg >= min_elevation_deg
    brackets = [(max(j0 - 1, 0), min(j1 + 1, n - 1)) for j0, j1 in _true_runs(above)]

    el = elevation_deg
    graze = (
        ~above[1:-1]
        & (el[1:-1] >= min_elevation_deg - _GRAZE_MARGIN_DEG)
        & (el[1:-1] >= el[:-2])
        & (el[1:-1] >= el[2:])
    )
    # flatnonzero indexes the interior slice: interior index i corresponds to
    # grid index i+1, so the (i-1, i+1) bracket around the maximum is (i, i+2).
    brackets += [(int(i), int(i) + 2) for i in np.flatnonzero(graze)]

    brackets.sort()
    merged: list[tuple[int, int]] = []
    for lo, hi in brackets:
        if merged and lo <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return merged


def _fine_sample_count(span_s: float) -> int:
    """Fine-grid sample count for a bracket span (capped — see the constant)."""
    return min(int(math.ceil(span_s / _FINE_STEP_S)) + 1, _MAX_FINE_SAMPLES)


@dataclass(frozen=True, eq=False)
class _SkyGrid:
    """One evenly-stepped scan grid projected into the station's sky.

    ``trajectory`` (TEME, straight from :func:`propagate_tle`) and the three
    parallel :func:`look_angles_track` arrays, with the grid's start epoch and
    exact step. Sample ``k`` is at ``start.shifted_by(k * step_s)`` — the same
    instants the trajectory holds, by the shared sampling contract.
    """

    trajectory: "Trajectory"
    azimuth_deg: np.ndarray
    elevation_deg: np.ndarray
    range_m: np.ndarray
    start: Epoch
    step_s: float


def _scan_grid(
    tle: "TLE",
    station: "GroundStation",
    start: Epoch,
    span_s: float,
    n_samples: int,
    *,
    suppress_stale_warning: bool = False,
) -> _SkyGrid:
    """Propagate an even ``n_samples`` grid over ``[start, start + span_s]``.

    The step is ``span_s / (n_samples - 1)``, so the last sample lands exactly
    on the span end (no uncovered tail; ``propagate_tle``'s floor-based sample
    count reproduces ``n_samples`` because the division round-trips within its
    1e-9 tolerance). ``suppress_stale_warning`` silences ``StaleTLEWarning``
    for the fine grids — each is a sub-span of the coarse scan, whose single
    warning already reported the worst-case TLE age (warn-once, contract:
    "Failure modes").
    """
    step_s = span_s / (n_samples - 1)
    if suppress_stale_warning:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", StaleTLEWarning)
            trajectory = propagate_tle(tle, span_s, output_step=step_s, start=start)
    else:
        trajectory = propagate_tle(tle, span_s, output_step=step_s, start=start)
    azimuth_deg, elevation_deg, range_m = look_angles_track(station, trajectory)
    return _SkyGrid(trajectory, azimuth_deg, elevation_deg, range_m, start, step_s)


def _station_sun_geometry(
    topo: "org.orekit.frames.TopocentricFrame", epochs: list[Epoch]
) -> tuple[np.ndarray, np.ndarray]:
    """Station EME2000 positions (N, 3) + station Sun elevations (N,) in degrees.

    The per-pass observer-side batch: the station position feeds the phase
    angle, the Sun elevation the observer-darkness gate. One thin JVM loop —
    fine at per-pass scale (contract: "Search algorithm" step 3). The caller
    built ``topo`` and started the JVM.
    """
    from ..core.bodies import _sun

    sun = _sun()
    eme_frame = Frame.EME2000.to_orekit()
    n = len(epochs)
    positions = np.empty((n, 3), dtype=np.float64)
    sun_elevation_deg = np.empty(n, dtype=np.float64)
    for i, epoch in enumerate(epochs):
        positions[i] = _vector3d_to_array(
            topo.getPVCoordinates(epoch.to_orekit(), eme_frame).getPosition()
        )
        sun_elevation_deg[i] = _body_azel(topo, sun, epoch).elevation_deg
    return positions, sun_elevation_deg


def _assemble_pass(
    grid: _SkyGrid,
    eme_positions_m: np.ndarray,
    j0: int,
    j1: int,
    topo: "org.orekit.frames.TopocentricFrame",
    min_elevation_deg: float,
    standard_magnitude: float | None,
) -> tuple[Pass, bool]:
    """Build one annotated ``(Pass, visible)`` from grid run ``[j0, j1]``.

    Geometry first — sub-sample refinement of the two threshold crossings
    (linear in elevation between the bracketing samples) and the culmination
    (parabola through the maximum sample and its neighbors). A run touching
    the grid edge has no crossing there: the endpoint is **clamped** to the
    grid edge (which, by construction, is the search-window edge — contract:
    "Pass semantics") and its azimuth read off that sample.

    Then lighting, on the run's own samples: sunlit (conical umbra), observer
    dark (Sun elevation ≤ the twilight constant), and — when a standard
    magnitude is available and the pass has a visible portion — the phase-law
    magnitudes, whose minimum over the visible samples is ``peak_magnitude``
    (contract: "Pass semantics"; ``None`` otherwise).
    """
    el = grid.elevation_deg
    az = grid.azimuth_deg
    step = grid.step_s
    n = el.shape[0]

    # -- rise ---------------------------------------------------------------
    if j0 == 0:
        rise_t = 0.0
        rise_az = float(az[0])
    else:
        e0, e1 = float(el[j0 - 1]), float(el[j0])
        frac = (min_elevation_deg - e0) / (e1 - e0)
        rise_t = (j0 - 1 + frac) * step
        rise_az = _interp_azimuth_deg(float(az[j0 - 1]), float(az[j0]), frac)

    # -- set ----------------------------------------------------------------
    if j1 == n - 1:
        set_t = (n - 1) * step
        set_az = float(az[n - 1])
    else:
        e0, e1 = float(el[j1]), float(el[j1 + 1])
        frac = (e0 - min_elevation_deg) / (e0 - e1)
        set_t = (j1 + frac) * step
        set_az = _interp_azimuth_deg(float(az[j1]), float(az[j1 + 1]), frac)

    # -- culmination ----------------------------------------------------------
    jmax = j0 + int(np.argmax(el[j0 : j1 + 1]))
    culm_t = jmax * step
    max_el = float(el[jmax])
    culm_az = float(az[jmax])
    if 0 < jmax < n - 1:
        e_prev, e_next = float(el[jmax - 1]), float(el[jmax + 1])
        denom = e_prev - 2.0 * max_el + e_next
        if denom < 0.0:  # a proper (concave) maximum; flat triples keep the sample
            delta = min(max(0.5 * (e_prev - e_next) / denom, -0.5), 0.5)
            culm_t = (jmax + delta) * step
            max_el = max_el - 0.25 * (e_prev - e_next) * delta
            neighbor = jmax + 1 if delta >= 0.0 else jmax - 1
            culm_az = _interp_azimuth_deg(
                float(az[jmax]), float(az[neighbor]), abs(delta)
            )

    # -- lighting (the run's own samples only) --------------------------------
    run = slice(j0, j1 + 1)
    epochs = [grid.start.shifted_by(k * step) for k in range(j0, j1 + 1)]
    sat_positions = eme_positions_m[run]
    sun_positions = _sun_positions_eme2000(epochs)
    lit = _is_sunlit(sat_positions, sun_positions)
    station_positions, sun_elevation_deg = _station_sun_geometry(topo, epochs)
    visible_mask = lit & (sun_elevation_deg <= _TWILIGHT_SUN_EL_DEG)
    visible = bool(visible_mask.any())

    peak_magnitude: float | None = None
    if standard_magnitude is not None and visible:
        phi = _phase_angle_rad(sat_positions, sun_positions, station_positions)
        mags = _magnitudes(standard_magnitude, grid.range_m[run], phi)
        peak_magnitude = float(np.min(mags[visible_mask]))

    return (
        Pass(
            rise=grid.start.shifted_by(rise_t),
            culmination=grid.start.shifted_by(culm_t),
            set=grid.start.shifted_by(set_t),
            max_elevation_deg=max_el,
            peak_magnitude=peak_magnitude,
            sunlit_at_culmination=bool(lit[jmax - j0]),
            rise_azimuth_deg=rise_az,
            culmination_azimuth_deg=culm_az,
            set_azimuth_deg=set_az,
        ),
        visible,
    )


def _passes_on_grid(
    grid: _SkyGrid,
    topo: "org.orekit.frames.TopocentricFrame",
    min_elevation_deg: float,
    standard_magnitude: float | None,
) -> list[tuple[Pass, bool]]:
    """Assemble every above-gate run on ``grid`` into an annotated pass.

    Shared by the two grid shapes: a candidate's fine grid (the normal path —
    usually one run; a refined graze that never reaches the gate yields no runs
    and is thereby discarded) and, for the always-up case, the coarse grid
    itself (whose single window-spanning run needs no refinement). The EME2000
    conversion for the lighting evaluation happens once per grid, only when a
    run exists.
    """
    runs = _true_runs(grid.elevation_deg >= min_elevation_deg)
    if not runs:
        return []
    eme_positions = grid.trajectory.to_frame(Frame.EME2000).positions
    return [
        _assemble_pass(
            grid, eme_positions, j0, j1, topo, min_elevation_deg, standard_magnitude
        )
        for j0, j1 in runs
    ]


def find_passes(
    tle: "TLE",
    station: "GroundStation",
    duration: float,
    *,
    start: Epoch | None = None,
    min_elevation_deg: float = 10.0,
    visible_only: bool = True,
    standard_magnitude: float | None = None,
    progress: bool | ProgressCallback = True,
) -> list[Pass]:
    """Find ``tle``'s passes over ``station`` in the next ``duration`` seconds.

    The Feature 1.5 headline verb (features.md §1.5, the binding contract). A
    **pass** is a maximal interval with elevation ≥ ``min_elevation_deg``
    (default 10°, the customary visual-observing threshold) — so the reported
    ``rise`` / ``set`` are crossings of *that gate*, not of the 0° horizon;
    pass ``min_elevation_deg=0.0`` for true horizon-to-horizon passes. The
    horizon is geometric (refraction out of scope). A pass is **visible** if at
    some point during it the satellite is sunlit (conical umbra; penumbra
    counts as lit) *and* the station is in darkness (Sun elevation ≤ −6°, end
    of civil twilight). ``visible_only=True`` (default) returns visible passes
    only; ``False`` returns every geometric pass, annotated — the same
    computation, filtered differently.

    ``start=None`` means :meth:`Epoch.now` (the "tonight" default).
    ``standard_magnitude`` resolves: explicit argument → the ``core/catalogs``
    registry by ``tle.norad_id`` → ``None`` (passes still found, magnitude-less).
    ``progress`` drives the shared reporter with a determinate scanned/total
    fraction (``True`` prints throttled stderr lines, ``False`` is silent, a
    callable receives the 0→1 fraction).

    Returns a list of :class:`Pass` sorted by rise time — possibly empty (a
    normal answer). Each pass carries refined rise/culmination/set epochs
    (~sub-second), the three azimuths, ``max_elevation_deg``,
    ``sunlit_at_culmination`` (which can be ``False`` on a visible pass — the
    classic evening pass entering shadow mid-arc), and ``peak_magnitude`` (the
    brightest magnitude over the visible portion; ``None`` without a standard
    magnitude or a visible portion). A pass straddling the window boundary is
    **clamped and included** — its clamped endpoint is not a true rise/set. A
    satellite continuously above the gate all window yields one window-spanning
    clamped pass plus a warn-once; one that never rises yields ``[]``.

    Raises ``ValueError`` (before any JVM work) for a non-positive or
    non-finite ``duration``, ``min_elevation_deg`` outside ``[0, 90)``, or a
    non-finite ``standard_magnitude``. The internal :func:`propagate_tle` calls
    contribute their own behavior unchanged (contract: "Failure modes"): the
    shared sample-grid cap ``ValueError``, ``TLEPropagationError`` on decay (no
    partial pass list), and the warn-once ``StaleTLEWarning`` for windows
    reaching > 30 days from the TLE epoch.
    """
    # --- pre-flight (pure Python, before the reporter and any JVM) ----------
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError(f"duration must be finite and > 0 seconds, got {duration!r}")
    if not (math.isfinite(min_elevation_deg) and 0.0 <= min_elevation_deg < 90.0):
        raise ValueError(
            f"min_elevation_deg must be in [0, 90), got {min_elevation_deg!r}"
        )
    if standard_magnitude is not None and not math.isfinite(standard_magnitude):
        raise ValueError(
            f"standard_magnitude must be finite or None, got {standard_magnitude!r}"
        )
    resolved_start = start if start is not None else Epoch.now()
    std_mag = (
        standard_magnitude
        if standard_magnitude is not None
        else _standard_magnitude(tle.norad_id)
    )
    # Even coarse grid whose last sample lands exactly on the window end (no
    # uncovered tail), step ≤ _COARSE_STEP_S. Deliberately uncapped: an absurd
    # window inherits propagate_tle's shared sample-grid ValueError (contract).
    n_coarse = int(math.ceil(duration / _COARSE_STEP_S)) + 1

    logger.info(
        "find_passes: norad_id=%d window=%.1f h min_el=%.1f deg visible_only=%s",
        tle.norad_id,
        duration / 3600.0,
        min_elevation_deg,
        visible_only,
    )
    reporter = _ProgressReporter("find_passes", progress)
    reporter.start(
        f"{duration / 3600.0:.1f} h window | min el {min_elevation_deg:.1f} deg"
    )
    try:
        # --- coarse scan (JVM starts here) -----------------------------------
        coarse = _scan_grid(tle, station, resolved_start, duration, n_coarse)
        topo = _station_topocentric_frame(station)

        annotated: list[tuple[Pass, bool]]
        if bool((coarse.elevation_deg >= min_elevation_deg).all()):
            # Always above the gate: the whole window is one clamped pass; the
            # coarse grid itself is the pass grid (re-sampling a window-long
            # "pass" at the fine step would be pointless work — contract:
            # "Pass semantics").
            warnings.warn(
                f"satellite is continuously above the {min_elevation_deg:.1f} deg "
                "elevation gate for the whole search window; returning one "
                "window-spanning pass with clamped endpoints (not true rise/set "
                "times).",
                stacklevel=2,
            )
            reporter.update(0.5)
            annotated = _passes_on_grid(coarse, topo, min_elevation_deg, std_mag)
        else:
            # --- bracket & refine --------------------------------------------
            brackets = _candidate_brackets(coarse.elevation_deg, min_elevation_deg)
            fine_counts = [
                _fine_sample_count((i1 - i0) * coarse.step_s) for i0, i1 in brackets
            ]
            # Determinate progress over samples evaluated: the coarse scan is
            # done, each refinement contributes its fine-grid share.
            total = n_coarse + sum(fine_counts)
            done = n_coarse
            reporter.update(done / total)
            annotated = []
            for (i0, i1), n_fine in zip(brackets, fine_counts):
                span_s = (i1 - i0) * coarse.step_s
                fine = _scan_grid(
                    tle,
                    station,
                    resolved_start.shifted_by(i0 * coarse.step_s),
                    span_s,
                    n_fine,
                    suppress_stale_warning=True,
                )
                annotated.extend(
                    _passes_on_grid(fine, topo, min_elevation_deg, std_mag)
                )
                done += n_fine
                reporter.update(done / total)

        passes = [p for p, visible in annotated if visible or not visible_only]
        passes.sort(key=lambda p: p.rise.seconds_since(resolved_start))
        reporter.finish(f"done | {len(passes)} passes | {reporter.elapsed_s:.1f} s")
        return passes
    finally:
        # Every exit path ends with one honest final line (the §1.1 pattern):
        # finish() ran on the clean path (close() is then a no-op); an escaping
        # error gets the 'failed at NN%' fallback.
        reporter.close()


# Column order for the pass table / CSV — one source of truth so the DataFrame
# and the ``io/`` CSV exporter stay aligned (features.md §1.5 "Outputs"). The
# three epoch columns come first, then the derived duration and the scalar
# ``Pass`` fields.
_PASS_TABLE_COLUMNS: tuple[str, ...] = (
    "rise",
    "culmination",
    "set",
    "duration_s",
    "max_elevation_deg",
    "rise_azimuth_deg",
    "culmination_azimuth_deg",
    "set_azimuth_deg",
    "peak_magnitude",
    "sunlit_at_culmination",
)


def passes_to_dataframe(
    passes: list[Pass], *, tz: "USTimeZone | tzinfo | None" = None
) -> "pd.DataFrame":
    """Tabulate ``find_passes`` output as a pandas ``DataFrame``, one row per pass.

    The JVM-free formatter of the Feature 1.5 output surface (features.md §1.5
    "Outputs"; the :meth:`Trajectory.to_dataframe` idiom). Columns, in order:
    ``rise`` / ``culmination`` / ``set`` (**tz-aware** ``datetime64[ns]`` — UTC
    by default, converted to ``tz`` when given, a real datetime dtype rather than
    formatted text), ``duration_s`` (``set − rise``), ``max_elevation_deg``, the
    three ``*_azimuth_deg`` fields, ``peak_magnitude``, and
    ``sunlit_at_culmination``.

    ``tz`` lowers through the shared :func:`core.time._resolve_tz`: ``None`` keeps
    UTC, a :class:`USTimeZone` member renders DST-correct US civil time, and a
    raw ``datetime.tzinfo`` is the non-US escape hatch. Only the three datetime
    columns are localized; ``duration_s`` and the scalars are tz-independent.

    Pure Python — no JVM (a ``Pass`` carries only scalar fields and ``Epoch``
    objects, and ``Epoch.to_datetime`` / :meth:`Epoch.seconds_since` are
    pure-Python). ``peak_magnitude`` and any unset azimuth become ``NaN`` in a
    ``float64`` column; an empty ``passes`` list yields a zero-row frame with the
    same columns and dtypes.
    """
    import pandas as pd

    target_tz = _resolve_tz(tz)

    def _times(attr: str) -> "pd.DatetimeIndex":
        # tz-aware UTC first (Epoch.to_datetime is always UTC), then convert:
        # tz_convert onto timezone.utc is a no-op, onto a ZoneInfo it localizes.
        utc = pd.to_datetime(
            [getattr(p, attr).to_datetime() for p in passes], utc=True
        ).as_unit("ns")
        return utc.tz_convert(target_tz)

    def _floats(values: list) -> np.ndarray:
        # dtype=float coerces None -> NaN and keeps an empty list float64.
        return np.array(values, dtype=np.float64)

    data = {
        "rise": _times("rise"),
        "culmination": _times("culmination"),
        "set": _times("set"),
        "duration_s": _floats([p.set.seconds_since(p.rise) for p in passes]),
        "max_elevation_deg": _floats([p.max_elevation_deg for p in passes]),
        "rise_azimuth_deg": _floats([p.rise_azimuth_deg for p in passes]),
        "culmination_azimuth_deg": _floats([p.culmination_azimuth_deg for p in passes]),
        "set_azimuth_deg": _floats([p.set_azimuth_deg for p in passes]),
        "peak_magnitude": _floats([p.peak_magnitude for p in passes]),
        "sunlit_at_culmination": np.array(
            [p.sunlit_at_culmination for p in passes], dtype=bool
        ),
    }
    return pd.DataFrame(data, columns=list(_PASS_TABLE_COLUMNS))
