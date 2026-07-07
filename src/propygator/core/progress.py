"""Progress reporting for the long-running verbs (general-upgrades-1, Part B).

The repo convention is *logging, never prints* (architecture §Logging). Progress
output is that rule's one **sanctioned, narrow exception** — the same carve-out
``pip``/``git``/``tqdm`` take: it writes plain, ASCII-only status lines to
**stderr only** (never stdout), is **TTY-gated** (a non-TTY stderr — pytest, CI,
``conda run``, a redirect — coarsens to the 25/50/75 milestones so log files stay
clean; Jupyter's captured stderr is non-TTY too, so notebooks still see the
milestones), is **opt-out** (``progress=False``), and is transient (no state, no
root-logger handler). ``logger.info`` milestones are emitted **regardless** of
mode and TTY state, for users who configure logging.

``_ProgressReporter`` is the single reporter behind every consumer's ``progress``
parameter — ``propagate_numerical`` now, ``find_passes`` (1.5, determinate) and
``fit_tle`` (1.2, indeterminate) when they ship — so promoting the rendering to
tqdm later is a zero-API-change swap. The ``stream`` and ``clock`` seams exist
for headless tests (a fake TTY/non-TTY stream, a hand-advanced clock); production
callers pass neither.

Pure-Python and JVM-free: safe on the "before init" surface (architecture §10).
"""

from __future__ import annotations

import logging
import sys
import time
from typing import IO, Callable

logger = logging.getLogger(__name__)

#: The ``progress=<callable>`` seam (re-exported at the top level): called with
#: the 0.0 -> 1.0 completed fraction on each throttled tick; the library then
#: prints nothing (the hook for tqdm, a GUI bar, or a custom log line).
ProgressCallback = Callable[[float], None]

# Cadence (contract: "Reporter behavior"). On a TTY: a line per new 10% or per
# ~5 s of wall clock, whichever first (the heartbeat keeps a slow run visibly
# alive). Off-TTY, prints coarsen to the 25/50/75 milestones. The 10%/~5 s
# numbers are contract; _HEARTBEAT_S may be tuned at Checkpoint A.
_TTY_PERCENT_STEP = 10
_HEARTBEAT_S = 5.0
_COARSE_MILESTONES = (25, 50, 75)


class _ProgressReporter:
    """One run's progress channel: throttled stderr lines / callable / silent.

    Lowered from a verb's ``progress`` argument: ``True`` -> the built-in
    stderr printer, ``False`` -> silent, a callable -> the fraction is forwarded
    on each throttled tick and nothing is printed. Anything else raises
    ``TypeError`` here, so every consumer fails fast with one shared message.

    Determinate consumers drive :meth:`update` with a monotonic 0 -> 1 fraction;
    indeterminate consumers (differential correctors with no honest percentage)
    drive :meth:`step` with a per-iteration text instead. Lifecycle:
    :meth:`start` once, ticks, then :meth:`finish` with the honest final detail
    (``done | ...`` or ``stopped at NN% | ...``); :meth:`close` belongs in a
    ``finally`` — it is idempotent and, when :meth:`finish` never ran (an
    exception escaped), emits a ``failed at NN%`` fallback so no run ends with a
    dangling last line.

    Rendering is ASCII-only (Windows cp1252 stderr), and a broken/closed stream
    is swallowed — a display channel must never kill the physics.
    """

    def __init__(
        self,
        verb: str,
        progress: bool | ProgressCallback,
        *,
        span_s: float | None = None,
        stream: IO[str] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if progress is True:
            self._print, self._callback = True, None
        elif progress is False:
            self._print, self._callback = False, None
        elif callable(progress):
            self._print, self._callback = False, progress
        else:
            raise TypeError(
                "progress must be True (built-in stderr reporter), False "
                "(silent), or a callable taking the 0-1 completed fraction; "
                f"got {type(progress).__name__}"
            )
        self._verb = verb
        self._span_s = span_s
        self._stream = stream
        self._clock = clock
        self._started = False
        self._finished = False
        self._fine = False  # TTY cadence? resolved once, at start()
        self._t_start = 0.0
        self._last_emit_t = 0.0
        self._last_fraction = 0.0
        self._next_fine_pct = _TTY_PERCENT_STEP
        self._coarse_idx = 0  # next _COARSE_MILESTONES print threshold
        self._log_idx = 0  # next _COARSE_MILESTONES logger.info threshold

    @property
    def percent(self) -> int:
        """The last reported whole-percent (for a caller's ``stopped`` line)."""
        return int(self._last_fraction * 100.0)

    @property
    def elapsed_s(self) -> float:
        """Wall-clock seconds since :meth:`start` — the tick lines' time base.

        Callers composing a ``done``/``stopped`` detail should quote this (not
        their own narrower timer) so the final line's wall clock is consistent
        with the progress ticks it follows.
        """
        return self._clock() - self._t_start

    # -- lifecycle -----------------------------------------------------------

    def start(self, detail: str) -> None:
        """Emit the immediate "it began" line (before the first slow step)."""
        self._started = True
        self._t_start = self._last_emit_t = self._clock()
        self._fine = self._isatty()
        logger.info("%s: start | %s", self._verb, detail)
        if self._print:
            self._write(f"{self._verb}: start | {detail}")

    def update(self, fraction: float) -> None:
        """Record a determinate 0 -> 1 fraction; emit if a throttle tick is due."""
        if not self._started or self._finished:
            return
        self._last_fraction = min(max(fraction, 0.0), 1.0)
        percent = self.percent
        self._log_coarse(percent)
        if self._callback is not None:
            # Callable cadence is the fine cadence regardless of TTY (the gate
            # governs printing, not the user's own sink).
            if self._fine_tick_due(percent):
                self._callback(self._last_fraction)
                self._bump_emitted(percent)
        elif self._print:
            due = (
                self._fine_tick_due(percent)
                if self._fine
                else self._coarse_tick_due(percent)
            )
            # Suppress the 100% tick: the finish() line reports completion.
            if due and percent < 100:
                self._write(self._progress_line(percent))
                self._bump_emitted(percent)

    def step(self, text: str) -> None:
        """Emit an indeterminate per-iteration line (e.g. ``iter 3 | rms ...``).

        The 1.2 ``fit_tle`` mode: no fake percentage, one line per iteration
        (differential correction runs a handful, so no throttle is needed).
        """
        if not self._started or self._finished:
            return
        logger.info("%s: %s", self._verb, text)
        if self._callback is None and self._print:
            self._write(f"{self._verb}: {text}")

    def finish(self, detail: str) -> None:
        """Emit the honest final line (``done | ...`` / ``stopped at NN% | ...``)."""
        if self._finished:
            return
        self._finished = True
        logger.info("%s: %s", self._verb, detail)
        if self._print:
            self._write(f"{self._verb}: {detail}")

    def close(self) -> None:
        """Idempotent finalizer for a ``finally``: no-op unless finish() never ran."""
        if self._finished or not self._started:
            self._finished = True
            return
        wall = self._clock() - self._t_start
        self.finish(f"failed at {self.percent}% | {wall:.1f} s")

    # -- internals ------------------------------------------------------------

    def _fine_tick_due(self, percent: int) -> bool:
        if percent >= self._next_fine_pct:
            return True
        return self._clock() - self._last_emit_t >= _HEARTBEAT_S

    def _coarse_tick_due(self, percent: int) -> bool:
        return (
            self._coarse_idx < len(_COARSE_MILESTONES)
            and percent >= _COARSE_MILESTONES[self._coarse_idx]
        )

    def _bump_emitted(self, percent: int) -> None:
        self._last_emit_t = self._clock()
        # One emission per update, however many thresholds a jump crossed.
        self._next_fine_pct = (percent // _TTY_PERCENT_STEP + 1) * _TTY_PERCENT_STEP
        while self._coarse_tick_due(percent):
            self._coarse_idx += 1

    def _log_coarse(self, percent: int) -> None:
        if (
            self._log_idx < len(_COARSE_MILESTONES)
            and percent >= _COARSE_MILESTONES[self._log_idx]
        ):
            logger.info("%s: %d%%", self._verb, percent)
            while self._log_idx < len(_COARSE_MILESTONES) and (
                percent >= _COARSE_MILESTONES[self._log_idx]
            ):
                self._log_idx += 1

    def _progress_line(self, percent: int) -> str:
        wall = self._clock() - self._t_start
        if self._span_s:
            done_h = self._last_fraction * self._span_s / 3600.0
            total_h = self._span_s / 3600.0
            return (
                f"{self._verb}: {percent:3d}% | t+{done_h:.1f}/{total_h:.1f} h "
                f"| {wall:.1f} s"
            )
        return f"{self._verb}: {percent:3d}% | {wall:.1f} s"

    def _effective_stream(self) -> IO[str]:
        # sys.stderr is resolved at write time (late binding), so pytest's
        # capture and a user's redirection are honored mid-process.
        return self._stream if self._stream is not None else sys.stderr

    def _isatty(self) -> bool:
        try:
            return bool(self._effective_stream().isatty())
        except (AttributeError, ValueError):
            return False

    def _write(self, line: str) -> None:
        try:
            stream = self._effective_stream()
            stream.write(line + "\n")
            stream.flush()
        except (OSError, ValueError, AttributeError):
            # A closed/broken display channel must never kill the run.
            pass
