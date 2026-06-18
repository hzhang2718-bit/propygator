"""Session-scoped test fixtures and the orekit-data gate (build-plan chunk 6).

Two responsibilities (architecture §11):

1. **Data gate** (``_orekit_data_gate``) — autouse, session scope, *no JVM*.
   Resolves orekit-data once at session start using the SAME search path as user
   code (``_orekit_init._resolve_data_path``). If it is unresolvable, the whole
   session aborts with the clean ``OrekitDataMissingError`` text and its
   remediation instructions — never a raw Java trace, never the same failure
   repeated once per test.

2. **JVM session** (``orekit``) — opt-in, session scope. Calls
   ``propygator.init()`` exactly once and is requested only by tests that
   actually touch Orekit (e.g. ``test_stack_compat``). JPype is
   one-JVM-per-process and ``init()`` is idempotent, so this naturally yields
   "JVM started once per session."

**Deliberate divergence from the literal Chunk-6 wording** ("session-scoped
autouse fixture calling ``propygator.init()`` once"): the autouse gate here does
NOT start the JVM. The pure-Python ``tests/core/*`` suite asserts the "safe
before init" invariant — constructing ``Epoch`` / ``State`` / ``Frame`` / … must
not start the JVM (architecture §10, whose guard tests *are* that suite's
``test_no_jvm_started`` checks). An autouse fixture that eagerly called
``init()`` would start the JVM before those tests run and break every one of
them. The lazy-init design already gives "init once per session" for free, so
the autouse fixture is scoped down to the data gate and the JVM start is made
opt-in. §10 (a source of truth) wins over the build-plan wording; the intent of
both — clean abort on missing data, JVM up exactly once — is preserved.
"""

from __future__ import annotations

import pytest

from propygator._orekit_init import _resolve_data_path
from propygator.core.exceptions import OrekitDataMissingError


@pytest.fixture(scope="session", autouse=True)
def _orekit_data_gate() -> None:
    """Abort the session early (clean message) if orekit-data is unresolvable.

    Pure-Python; does not start the JVM. Runs once before any test. Mirrors the
    user-code resolution path so the test session fails the same way a user
    would (architecture §11) — no test-only fallback.
    """
    try:
        _resolve_data_path()
    except OrekitDataMissingError as exc:  # pragma: no cover - only on misconfig
        pytest.exit(
            f"orekit-data is unavailable; aborting the test session.\n\n{exc}",
            returncode=1,
        )


@pytest.fixture(scope="session")
def orekit() -> None:
    """Start the JVM + load orekit-data once per session (opt-in).

    Requested only by tests that touch Orekit. Idempotent: JPype allows one JVM
    per process, so every Orekit-touching test in the session reuses it.

    Note: faulthandler is disabled suite-wide via ``addopts`` in
    ``pyproject.toml`` because a running JVM legitimately uses access violations
    / SIGSEGV internally; see the comment there for the full rationale.
    """
    import propygator as pgr

    pgr.init()


def pytest_collection_modifyitems(items: "list[pytest.Item]") -> None:
    """Schedule every JVM-starting test after all pure-Python tests (single-process).

    Holds for any single-process run, which is every run this project performs:
    pytest-xdist is not used (architecture §11), so collection is not split across
    workers and this stable reorder governs the whole session.

    JPype is one-JVM-per-process and ``jpype.isJVMStarted()`` is a *monotonic*
    global flag — once any test starts the JVM it stays up for the rest of the
    process and can never be torn down. The ``tests/core`` "safe before init"
    guards (each module's ``test_no_jvm_started``) assert that flag is still
    ``False``, so they hold only while *no* JVM-starting test has run yet in the
    process. They are tripwires for "did pure-Python construction leak a JVM
    start?", not self-contained checks of a single call.

    The default filesystem collection order already runs ``tests/core`` before the
    JVM files (``test_conversions`` / ``test_stack_compat`` sort after ``core``),
    so a bare ``pytest`` is fine. But an explicit ``pytest <jvm-file> tests/core``
    flips that and the guards spuriously fail — the JVM is up before they run. This
    hook removes that footgun by stably moving every test that requests the session
    ``orekit`` fixture (the one and only thing that starts the JVM) to the end, so
    the pure-Python guards always run first regardless of CLI path order.

    **Contributor invariant:** any new Orekit/JVM-touching test MUST acquire the
    JVM through the ``orekit`` fixture (a direct argument or
    ``pytest.mark.usefixtures("orekit")``). That is both how it gets a started JVM
    and how this hook knows to schedule it last; a test that starts the JVM by some
    other route would defeat the ordering guarantee (and the guards with it).
    """
    # list.sort is stable: False (0) sorts before True (1), so non-JVM tests keep
    # their order and land first. ``fixturenames`` includes fixtures applied via
    # ``usefixtures`` markers, so both JVM test modules are caught.
    items.sort(key=lambda item: "orekit" in getattr(item, "fixturenames", ()))
