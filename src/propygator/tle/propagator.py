"""``propagate_tle`` — the SGP4/SDP4 TLE propagator (Feature 1.3).

The headline verb of Feature 1.3: analytic SGP4/SDP4 propagation of a :class:`TLE`
to a TEME :class:`~propygator.core.states.Trajectory`, reusing Feature 1.1's output
surface (the ``plot_*`` verbs, ``export_csv`` / ``export_all``) wholesale. The
propagation core is Orekit's ``TLEPropagator.selectExtrapolator(tle)``, which picks
the near-Earth (SGP4, period < 225 min) or deep-space (SDP4) branch automatically —
there is no user-facing knob (features.md §1.3).

What 1.3 deliberately does **not** carry, relative to ``propagate_numerical``: no
force/spacecraft/attitude/integrator inputs (SGP4 is self-contained — its drag rides
in the TLE's B* term and the theory is fixed); no altitude-guard family or ``limits=``
(SGP4 is a closed-form evaluation with none of numerical integration's failure modes,
and a TLE encodes a bound orbit so escape is structurally moot); and **no
stop-and-report** — a decay raises :class:`TLEPropagationError` cleanly rather than
returning a partial trajectory, because SGP4 is least reliable precisely as it
approaches decay (features.md §1.3). The one runtime warning is the warn-once
**stale-TLE** notice when the propagated span reaches far from the TLE epoch.

**Architecture invariants** (CLAUDE.md / architecture §10): no Orekit type appears on
the public signature (``tle`` and the returned ``Trajectory`` are propygator types);
``jpype`` / ``org.orekit.*`` are imported lazily *inside* the JVM section behind
``_ensure_started()``; SI units throughout; the output ``Trajectory`` is **TEME** with
no silent conversion (the native SGP4 frame); the propygator-side pre-flight (sampling
validation + the stale-TLE check) is pure-Python and runs before the JVM starts.
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import numpy as np

from .._orekit_init import _ensure_started, _orekit_version
from ..core.frames import Frame
from ..core.sampling import _output_offsets, _validate_sampling
from ..core.states import Trajectory, _propygator_version
from ..core.time import TimeScale

if TYPE_CHECKING:
    from ..core.states import TrajectoryMetadata
    from ..core.time import Epoch
    from ..core.tle import TLE

logger = logging.getLogger(__name__)

# Stale-TLE threshold (features.md §1.3): SGP4 accuracy degrades with time from the
# TLE epoch, so a span whose worst-case age exceeds this emits a one-time warning (it
# never raises — SGP4 can evaluate anywhere, it is merely inaccurate there).
_STALE_TLE_THRESHOLD_S = 30.0 * 86400.0


def propagate_tle(
    tle: "TLE",
    duration: float,
    *,
    output_step: float,
    start: "Epoch | None" = None,
    name: str | None = None,
) -> Trajectory:
    """Propagate a TLE with SGP4/SDP4 to a TEME ``Trajectory`` (features.md §1.3).

    ``duration`` and ``output_step`` are in seconds and share ``propagate_numerical``'s
    sampling contract exactly: ``output_step`` is required and keyword-only, and the
    output grid is ``floor(duration/output_step + tol) + 1`` samples, the first at
    ``start`` and spaced by ``output_step`` — so a TLE and a numerical run with the same
    ``duration`` / ``output_step`` produce identically-gridded trajectories.

    ``start`` defaults to the TLE's own epoch (``tle.epoch``), where SGP4 is most
    accurate; it may legally precede the epoch (SGP4 evaluates backwards). ``name``
    defaults to ``tle.name`` (so a fetched ``"ISS (ZARYA)"`` carries its identity into
    the metadata) and an explicit ``name=`` always wins.

    The returned ``Trajectory`` is in :data:`Frame.TEME`, the native SGP4 frame — no
    silent conversion (architecture §10); call ``.to_frame(...)`` to convert. Its
    ``epoch_scale`` inherits the scale of ``start``.

    Raises ``ValueError`` (before any Orekit call) for a non-positive / mis-ordered
    ``duration`` / ``output_step`` or an over-cap sample count, and
    :class:`TLEPropagationError` if SGP4/SDP4 leaves its validity envelope during the
    span (a decay / out-of-range eccentricity) — whether Orekit signals that by raising
    (out-of-range eccentricity) or by returning a non-finite state (a sub-surface
    decay), both surface as ``TLEPropagationError`` with **no** partial trajectory
    (features.md §1.3). A span reaching more than 30 days from the TLE epoch emits a
    one-time ``warnings.warn`` (never an error).
    """
    # --- propygator-side pre-flight (pure-Python, before any JVM) -----------
    # tle.epoch / tle.norad_id are parsed properties; evaluate each once and reuse.
    tle_epoch = tle.epoch
    norad_id = tle.norad_id
    resolved_start = start if start is not None else tle_epoch
    n_samples = _validate_sampling(duration, output_step)
    resolved_name = name if name is not None else tle.name

    # Stale-TLE warn-once (features.md §1.3): the worst-case age over the whole span,
    # checking BOTH ends because `start` may precede `tle.epoch` (a backward look).
    age_s = max(
        abs(resolved_start.seconds_since(tle_epoch)),
        abs(resolved_start.shifted_by(duration).seconds_since(tle_epoch)),
    )
    if age_s > _STALE_TLE_THRESHOLD_S:
        warnings.warn(
            f"propagating {age_s / 86400.0:.1f} days from the TLE epoch "
            f"({tle_epoch.in_scale(TimeScale.UTC).to_iso()}Z); SGP4/SDP4 accuracy "
            "degrades with time from epoch (roughly 1 km near epoch to many km over "
            "days to weeks). Use a TLE closer to the propagation span for accuracy.",
            # warn -> propagate_tle -> user: stacklevel 2 surfaces the warning at the
            # caller's propagate_tle(...) line, not this internal frame.
            stacklevel=2,
        )

    logger.info(
        "propagate_tle: norad_id=%d duration=%.1fs output_step=%.1fs samples=%d",
        norad_id,
        duration,
        output_step,
        n_samples,
    )

    # --- JVM section --------------------------------------------------------
    _ensure_started()
    import jpype
    from org.orekit.propagation.analytical.tle import TLEPropagator

    from ..core.exceptions import TLEPropagationError

    # selectExtrapolator picks SGP4 (near-Earth) vs SDP4 (deep-space) from the TLE's
    # mean motion automatically — no user knob (features.md §1.3).
    propagator = TLEPropagator.selectExtrapolator(tle.to_orekit())
    # Pin the output frame explicitly to TEME by requesting PV in it, rather than
    # relying on the propagator's implicit frame (architecture §10 explicit-frame rule).
    teme = Frame.TEME.to_orekit()
    start_date = resolved_start.to_orekit()

    offsets = _output_offsets(n_samples, output_step)
    positions = np.empty((n_samples, 3), dtype=np.float64)
    velocities = np.empty((n_samples, 3), dtype=np.float64)
    epochs: list[Epoch] = []
    try:
        for k, offset in enumerate(offsets):
            pv = propagator.propagate(start_date.shiftedBy(offset)).getPVCoordinates(
                teme
            )
            p = pv.getPosition()
            v = pv.getVelocity()
            positions[k, 0], positions[k, 1], positions[k, 2] = (
                p.getX(),
                p.getY(),
                p.getZ(),
            )
            velocities[k, 0], velocities[k, 1], velocities[k, 2] = (
                v.getX(),
                v.getY(),
                v.getZ(),
            )
            # Epoch built pure-Python from `start`, inheriting its scale; the Orekit
            # lookup date and this Epoch share the same offset, so they denote one
            # instant.
            epochs.append(resolved_start.shifted_by(offset))
    except jpype.JException as exc:  # type: ignore[attr-defined]
        # SGP4/SDP4 left its validity envelope (decay / out-of-range eccentricity).
        # Capture the Java *message* only (no raw stack trace; architecture §3) and
        # raise cleanly with no partial trajectory (features.md §1.3, no partial).
        raise TLEPropagationError(
            f"TLE propagation failed: {exc.getMessage()}"
        ) from None

    # SGP4/SDP4 can leave its validity envelope *without* throwing: a sub-surface
    # decay surfaces as a non-finite PV rather than an exception. Surface that as the
    # same TLEPropagationError as a thrown decay (features.md §1.3) — using the exact
    # finiteness idiom Trajectory itself enforces — rather than letting the generic
    # "must be finite" ValueError leak out of trajectory assembly.
    if not (np.isfinite(positions).all() and np.isfinite(velocities).all()):
        raise TLEPropagationError(
            "TLE propagation failed: the propagator produced a non-finite state; "
            "the orbit has likely decayed (left the SGP4/SDP4 validity envelope)."
        )

    metadata = _build_sgp4_metadata(
        tle,
        resolved_start,
        output_step,
        resolved_name,
        tle_epoch=tle_epoch,
        norad_id=norad_id,
    )
    traj = Trajectory.from_arrays(
        epochs,
        positions,
        velocities,
        Frame.TEME,
        metadata=metadata,
    )
    logger.info("propagate_tle: done — %d samples", len(epochs))
    return traj


def _build_sgp4_metadata(
    tle: "TLE",
    start: "Epoch",
    output_step: float,
    name: str | None,
    *,
    tle_epoch: "Epoch",
    norad_id: int,
) -> "TrajectoryMetadata":
    """Assemble the SGP4 trajectory metadata for this run (features.md §1.3).

    Simpler than ``numerical._build_metadata``: no force/integrator/termination keys —
    SGP4 has none. The source TLE lines make the run exactly reproducible, and
    ``propagator`` is always ``"sgp4"`` (that single token also covers the auto-selected
    SDP4 branch, since the TLE lines record which branch ``selectExtrapolator`` picks).
    ``tle_epoch`` and ``norad_id`` are passed in already-parsed (the caller evaluates
    each ``tle`` property once) rather than re-read here.

    The epoch-valued keys are **forced to UTC** before formatting: ``tle_epoch`` is
    already UTC, but ``start`` may be supplied in any scale, and ``Epoch.to_iso()``
    emits no zone suffix — so ``in_scale(TimeScale.UTC)`` guarantees the recorded ISO
    instant is genuinely UTC (Note "Metadata timestamps must be forced to UTC").
    ``name`` is written only when set, reusing 1.1's optional ``name`` field.
    """
    metadata: TrajectoryMetadata = {
        "propygator_version": _propygator_version(),
        "orekit_version": _orekit_version(),
        "propagator": "sgp4",
        "tle_line1": tle.line1,
        "tle_line2": tle.line2,
        "norad_id": norad_id,
        "tle_epoch": tle_epoch.in_scale(TimeScale.UTC).to_iso(),
        "start": start.in_scale(TimeScale.UTC).to_iso(),
        "output_step_s": float(output_step),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if name is not None:
        metadata["name"] = name
    return metadata
