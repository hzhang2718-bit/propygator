"""Headless unit tests for ``core.progress._ProgressReporter`` (v0.5.0 Part B).

Pure-Python like the rest of ``tests/core`` — no JVM, and no wall-clock sleeps:
the reporter's ``stream`` seam takes a fake with a settable ``isatty()`` and the
``clock`` seam a hand-advanced counter, so the ~5 s heartbeat and the TTY gate
are both asserted deterministically (contract: general-upgrades-1 "Reporter
behavior").
"""

from __future__ import annotations

import logging

import pytest

from propygator.core.progress import _ProgressReporter


class _FakeStream:
    """Collects writes; ``isatty()`` is settable (the TTY-gate seam)."""

    def __init__(self, tty: bool) -> None:
        self._tty = tty
        self.text = ""

    def write(self, s: str) -> None:
        self.text += s

    def flush(self) -> None:
        pass

    def isatty(self) -> bool:
        return self._tty

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.text.splitlines() if ln]


class _FakeClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


def _reporter(progress, *, tty: bool, span_s: float | None = 3600.0):
    stream = _FakeStream(tty)
    clock = _FakeClock()
    rep = _ProgressReporter(
        "propagate_numerical", progress, span_s=span_s, stream=stream, clock=clock
    )
    return rep, stream, clock


# --- TTY fine cadence ---------------------------------------------------------


def test_tty_start_line_prints_immediately():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("1.0 h | DOP853 | 361 samples")
    assert stream.lines == ["propagate_numerical: start | 1.0 h | DOP853 | 361 samples"]


def test_tty_emits_on_each_new_ten_percent_only():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("go")
    for fraction in (0.03, 0.07, 0.10, 0.13, 0.19, 0.20, 0.24):
        rep.update(fraction)
    percent_lines = stream.lines[1:]
    assert [ln.split("|")[0].strip() for ln in percent_lines] == [
        "propagate_numerical:  10%",
        "propagate_numerical:  20%",
    ]


def test_tty_heartbeat_fires_without_percent_change():
    rep, stream, clock = _reporter(True, tty=True)
    rep.start("go")
    rep.update(0.11)  # 11% -> first tick
    assert len(stream.lines) == 2
    rep.update(0.12)  # same decade, no time passed -> silent
    assert len(stream.lines) == 2
    clock.t += 5.0  # the ~5 s heartbeat
    rep.update(0.13)
    assert len(stream.lines) == 3
    assert " 13% " in stream.lines[-1]


def test_tty_jump_across_thresholds_emits_once():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("go")
    rep.update(0.87)  # crossed 10..80 in one jump
    percent_lines = [ln for ln in stream.lines if "%" in ln]
    assert len(percent_lines) == 1
    assert " 87% " in percent_lines[0]


def test_tty_hundred_percent_tick_suppressed_done_reports_it():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("go")
    rep.update(1.0)
    rep.finish("done | 1.0 h | 2.1 s | 361 samples")
    assert stream.lines[-1] == "propagate_numerical: done | 1.0 h | 2.1 s | 361 samples"
    assert not any("100%" in ln for ln in stream.lines)


def test_progress_line_renders_span_and_wall():
    rep, stream, clock = _reporter(True, tty=True, span_s=7200.0)
    rep.start("go")
    clock.t += 3.1
    rep.update(0.5)
    assert stream.lines[-1] == "propagate_numerical:  50% | t+1.0/2.0 h | 3.1 s"


# --- non-TTY coarsening ---------------------------------------------------------


def test_non_tty_coarsens_to_quartile_milestones():
    rep, stream, clock = _reporter(True, tty=False)
    rep.start("go")
    for i in range(1, 101):
        clock.t += 1.0  # heartbeats must NOT fire off-TTY
        rep.update(i / 100.0)
    rep.finish("done | ok")
    prefixes = [ln.split("|")[0].strip() for ln in stream.lines]
    assert prefixes == [
        "propagate_numerical: start",
        "propagate_numerical:  25%",
        "propagate_numerical:  50%",
        "propagate_numerical:  75%",
        "propagate_numerical: done",
    ]


# --- callable / silent modes ----------------------------------------------------


def test_callable_gets_throttled_fractions_and_nothing_prints():
    seen: list[float] = []
    rep, stream, _ = _reporter(seen.append, tty=True)
    rep.start("go")
    for i in range(1, 101):
        rep.update(i / 100.0)
    rep.finish("done | ok")
    assert stream.text == ""  # the library prints nothing in callable mode
    assert seen == sorted(seen)  # monotonic
    assert seen[-1] == pytest.approx(1.0)  # the final tick arrives
    assert 0.0 < seen[0] <= 0.11  # fine cadence, not just quartiles


def test_callable_cadence_ignores_tty_state():
    seen: list[float] = []
    rep, _, _ = _reporter(seen.append, tty=False)
    rep.start("go")
    for i in range(1, 101):
        rep.update(i / 100.0)
    assert len(seen) == 10  # every 10%, not the 25/50/75 print coarsening


def test_false_is_silent_but_still_logs_milestones(caplog):
    rep, stream, _ = _reporter(False, tty=True)
    with caplog.at_level(logging.INFO, logger="propygator.core.progress"):
        rep.start("go")
        rep.update(0.30)
        rep.update(0.60)
        rep.update(0.80)
        rep.finish("done | ok")
    assert stream.text == ""
    messages = [rec.getMessage() for rec in caplog.records]
    assert "propagate_numerical: start | go" in messages
    assert "propagate_numerical: 30%" in messages  # crossed 25
    assert "propagate_numerical: 60%" in messages  # crossed 50
    assert "propagate_numerical: 80%" in messages  # crossed 75
    assert "propagate_numerical: done | ok" in messages


def test_junk_progress_argument_raises_typeerror():
    with pytest.raises(TypeError, match="progress must be"):
        _ProgressReporter("propagate_numerical", "yes")  # type: ignore[arg-type]


# --- lifecycle: finish / close --------------------------------------------------


def test_close_without_finish_emits_failed_line_once():
    rep, stream, clock = _reporter(True, tty=True)
    rep.start("go")
    rep.update(0.42)
    clock.t += 18.3
    rep.close()
    rep.close()  # idempotent
    assert stream.lines[-1] == "propagate_numerical: failed at 42% | 18.3 s"
    assert sum("failed" in ln for ln in stream.lines) == 1


def test_close_after_finish_is_a_noop():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("go")
    rep.finish("stopped at 61% | reentry at t+1.4 h | 2.0 s | 148 samples (partial)")
    rep.close()
    assert stream.lines[-1].endswith("(partial)")
    assert not any("failed" in ln for ln in stream.lines)


def test_close_before_start_is_silent():
    rep, stream, _ = _reporter(True, tty=True)
    rep.close()
    assert stream.text == ""


def test_zero_tick_run_prints_start_and_done_only():
    # The degenerate single-sample propagation: span == 0, no handler registered,
    # so no update() ever fires (contract: Mechanism, parenthetical).
    rep, stream, _ = _reporter(True, tty=True, span_s=None)
    rep.start("0.0 h | DOP853 | 1 sample")
    rep.finish("done | 0.0 h | 0.1 s | 1 sample")
    assert len(stream.lines) == 2


def test_updates_after_finish_are_ignored():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("go")
    rep.finish("done | ok")
    rep.update(0.5)
    rep.step("iter 9 | rms 1.0")
    assert len(stream.lines) == 2


# --- indeterminate mode ----------------------------------------------------------


def test_indeterminate_step_lines_render_without_percentage():
    rep, stream, _ = _reporter(True, tty=True)
    rep.start("differential correction")
    rep.step("iter 1 | rms 12.500")
    rep.step("iter 2 | rms 0.031")
    rep.finish("done | converged in 2 iters")
    assert stream.lines[1] == "propagate_numerical: iter 1 | rms 12.500"
    assert stream.lines[2] == "propagate_numerical: iter 2 | rms 0.031"
    assert not any("%" in ln for ln in stream.lines)


# --- rendering hygiene -----------------------------------------------------------


def test_all_output_is_ascii():
    # Windows cp1252 stderr: any non-ASCII glyph is a UnicodeEncodeError risk.
    rep, stream, clock = _reporter(True, tty=True)
    rep.start("168.0 h | DOP853 | 60481 samples")
    for i in range(1, 100):
        clock.t += 1.0
        rep.update(i / 100.0)
    rep.close()
    stream.text.encode("ascii")  # raises on any non-ASCII byte


def test_broken_stream_never_raises():
    class _BrokenStream:
        def write(self, s):
            raise OSError("stderr is gone")

        def flush(self):
            raise OSError("stderr is gone")

        def isatty(self):
            return True

    rep = _ProgressReporter("propagate_numerical", True, stream=_BrokenStream())
    rep.start("go")  # must not raise
    rep.update(0.5)
    rep.close()
