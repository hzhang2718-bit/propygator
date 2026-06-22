"""Shared output-sample grid for the propagators (Feature 1.3 Chunk 1).

The propagator-agnostic sampling contract — the sample-count formula, the
memory-guard cap, the pre-flight duration/output-step validation, and the on-grid
offset list — lives here so that every propagator (``propagate_numerical``,
``propagate_tle``) produces an identically-gridded
:class:`~propygator.core.states.Trajectory` from one source of truth. It previously
lived inside ``propagation.numerical``'s
``_validate_inputs``; it was promoted here because the dependency rule forbids
``tle/`` importing ``propagation/`` (architecture §7).

Pure-Python and **safe before init**: no JVM, no Orekit import. SI units throughout
(seconds). Epochs are built per-propagator from :func:`_output_offsets` via
``start.shifted_by(offset)``; this module only produces the float offsets.
"""

from __future__ import annotations

import math

# Sample-count round-off tolerance (features.md §1.1): absorbs float error so a
# duration that is an exact multiple of output_step yields the deterministic count.
_SAMPLE_COUNT_TOL = 1e-9

# Upper bound on the output-sample count. With no cap, a tiny output_step against a
# long duration (e.g. 1 ms over a year -> ~3e10 samples) would pre-allocate multi-GB
# position/velocity arrays plus that many per-sample propagator evaluations and exhaust
# memory before any useful work. 1e7 covers ~19 years at a 60 s step; beyond it,
# raise and tell the caller to coarsen output_step.
_MAX_OUTPUT_SAMPLES = 10_000_000


def _sample_count(duration: float, output_step: float) -> int:
    """Number of output samples: ``floor(duration/output_step + tol) + 1``.

    First sample at ``initial.epoch``, last at ``initial.epoch + (n-1)*output_step``
    (features.md §1.1). The small relative ``tol`` makes divisible cases
    deterministic. ``output_step <= duration`` (validated upstream) guarantees
    ``n >= 2``.
    """
    return int(math.floor(duration / output_step + _SAMPLE_COUNT_TOL)) + 1


def _validate_sampling(duration: float, output_step: float) -> int:
    """Validate the sampling request and return the planned sample count.

    The propagator-agnostic pre-flight shared by every propagator: ``duration`` and
    ``output_step`` finite and positive, ``output_step <= duration``, and the
    sample-count :data:`_MAX_OUTPUT_SAMPLES` cap (which guards against an accidental
    enormous allocation from a tiny ``output_step`` over a long ``duration``). Each
    failure raises ``ValueError`` with an actionable message; the cap message keeps the
    ``"output samples"`` substring that callers pin. Pure-Python (no JVM).
    """
    if not math.isfinite(duration) or duration <= 0.0:
        raise ValueError(f"duration must be finite and > 0 seconds, got {duration!r}")
    if not math.isfinite(output_step) or output_step <= 0.0:
        raise ValueError(
            f"output_step must be finite and > 0 seconds, got {output_step!r}"
        )
    if output_step > duration:
        raise ValueError(
            f"output_step must be <= duration; got output_step={output_step!r} > "
            f"duration={duration!r}"
        )
    n_samples = _sample_count(duration, output_step)
    if n_samples > _MAX_OUTPUT_SAMPLES:
        raise ValueError(
            f"duration/output_step requests {n_samples} output samples, exceeding the "
            f"{_MAX_OUTPUT_SAMPLES} cap; increase output_step or shorten duration "
            "(each sample allocates a position+velocity row and one propagator "
            "evaluation, so a much larger count would exhaust memory)."
        )
    return n_samples


def _output_offsets(n_samples: int, output_step: float) -> list[float]:
    """On-grid output offsets in seconds: ``[0, output_step, ..., (n-1)*output_step]``.

    The single place both propagators build the sample grid (features.md §1.1); each
    converts an offset to an epoch with ``start.shifted_by(offset)``.
    """
    return [k * output_step for k in range(n_samples)]
