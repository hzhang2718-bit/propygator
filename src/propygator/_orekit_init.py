"""Lazy JVM initialization and orekit-data resolution.

Importing ``propygator`` must NOT start the JVM. The JVM starts on the first
Orekit-touching call, or via an explicit :func:`init`. JPype allows exactly one
JVM per process and cannot reconfigure it once started (architecture §10).

Everything in this module is pure-Python at import time: ``jpype`` /
``orekit_jpype`` / ``orekit_jpype.pyhelpers`` are imported lazily inside the
functions that need them, so importing this module never starts the JVM.
``pyhelpers`` in particular does ``from java.io import File`` at module top and
therefore cannot even be imported until after ``initVM()``.
"""

from __future__ import annotations

import importlib.metadata
import logging
import os
import shutil
from functools import cache
from pathlib import Path

from .core.exceptions import JVMAlreadyStartedError, OrekitDataMissingError

logger = logging.getLogger(__name__)

_OREKIT_DATA_URL = "https://gitlab.orekit.org/orekit/orekit-data"

# Module-level record of how propygator started the JVM. ``_initialized`` is
# True once propygator owns the running JVM (started or adopted it);
# ``_init_vmargs`` is the (possibly None) vmargs string used, so a later init()
# can detect a conflicting request. ``_data_loaded`` tracks the orekit-data
# context separately, so that if data loading fails *after* the JVM starts, a
# later call can complete it instead of misreading our own JVM as external.
_initialized: bool = False
_init_vmargs: str | None = None
_data_loaded: bool = False


@cache
def _orekit_version() -> str:
    """Return the installed Orekit-stack version string, or ``"unknown"``.

    Resolved from the ``orekit_jpype`` distribution metadata (e.g.
    ``"13.1.4.0"``), which is the version that pins the bundled Orekit jar — the
    Orekit Java library itself exposes no version constant and its jar manifest
    carries no ``Implementation-Version``, so the wrapper distribution is the
    authoritative, reproducible source. Pure-Python (``importlib.metadata``) — no
    JVM, memoized. Recorded as the ``orekit_version`` reproducibility key on every
    propagation ``Trajectory`` (architecture §6, features.md §1.1); falls back to
    ``"unknown"`` from a source tree without the distribution metadata, matching
    the placeholder :func:`core.states._default_metadata` writes.
    """
    try:
        return importlib.metadata.version("orekit_jpype")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _data_missing_message(searched: list[tuple[str, Path]]) -> str:
    """Build the user-facing OrekitDataMissingError text (URL + remedies)."""
    lines = [
        "Could not locate orekit-data, which Orekit needs for its physical "
        "models (leap seconds, Earth orientation, ephemerides, gravity field).",
        "",
        "Searched:",
    ]
    lines += [f"  - {label}: {path}" for label, path in searched]
    lines += [
        "",
        "Resolution order: OREKIT_DATA_PATH (authoritative if set) -> "
        "~/.propygator/orekit-data/ -> ./orekit-data/.",
        "",
        f"Download it from {_OREKIT_DATA_URL} and then either:",
        "  - set OREKIT_DATA_PATH to the extracted folder,",
        "  - place the folder at ~/.propygator/orekit-data/, or",
        "  - run from a directory that contains ./orekit-data/.",
    ]
    return "\n".join(lines)


def _already_started_message(requested: str | None, running: str | None) -> str:
    """Build the user-facing JVMAlreadyStartedError text (constraint + fix)."""
    return (
        "The JVM is already running and JPype cannot reconfigure or restart it "
        "(one JVM per process).\n"
        f"  Requested vmargs: {requested!r}\n"
        f"  Running vmargs:   {running!r}\n"
        "To use different JVM arguments, apply them before anything triggers "
        "JVM start: call propygator.init(vmargs=...) once at startup, or set "
        "the PROPYGATOR_VM_ARGS environment variable."
    )


def _resolve_data_path() -> Path:
    """Resolve the orekit-data directory per the architecture §3 search order.

    Order: ``OREKIT_DATA_PATH`` env var (if set, it is authoritative — it wins
    even over a present ``./orekit-data/``, and a set-but-missing value raises
    rather than falling back) -> ``~/.propygator/orekit-data/`` ->
    ``./orekit-data/``. Raises :class:`OrekitDataMissingError` if none resolve.

    Called before the JVM starts so the missing-data condition surfaces as a
    clean propygator error rather than a Java stack trace.
    """
    env_value = os.environ.get("OREKIT_DATA_PATH")
    if env_value:
        env_path = Path(env_value)
        if env_path.is_dir():
            logger.debug("Resolved orekit-data via OREKIT_DATA_PATH: %s", env_path)
            return env_path
        # The env var is authoritative: if set but wrong, fail loudly rather
        # than silently falling back to another location.
        raise OrekitDataMissingError(
            _data_missing_message([("OREKIT_DATA_PATH", env_path)])
        )

    home_path = Path.home() / ".propygator" / "orekit-data"
    if home_path.is_dir():
        logger.debug("Resolved orekit-data at %s", home_path)
        return home_path

    cwd_path = Path.cwd() / "orekit-data"
    if cwd_path.is_dir():
        logger.debug("Resolved orekit-data at %s", cwd_path)
        return cwd_path

    raise OrekitDataMissingError(
        _data_missing_message(
            [
                ("~/.propygator/orekit-data/", home_path),
                ("./orekit-data/", cwd_path),
            ]
        )
    )


def _setup_orekit_data(data_path: Path) -> None:
    """Point Orekit's global data context at ``data_path``.

    Imported lazily: ``orekit_jpype.pyhelpers`` does ``from java.io import File``
    at module top, so it can only be imported after the JVM is running.
    """
    from orekit_jpype.pyhelpers import setup_orekit_curdir

    setup_orekit_curdir(str(data_path))
    logger.info("Loaded orekit-data from %s", data_path)


def init(vmargs: str | None = None) -> None:
    """Start the JVM exactly once and load orekit-data.

    Parameters
    ----------
    vmargs:
        JVM argument string (e.g. ``"-Xmx8g"``). When ``None``, the
        ``PROPYGATOR_VM_ARGS`` environment variable is used if set.

    Behavior
    --------
    - First call: resolve orekit-data (raising :class:`OrekitDataMissingError`
      cleanly if absent), start the JVM via ``orekit_jpype.initVM``, then load
      the data context via ``setup_orekit_curdir``.
    - Subsequent calls with matching args: no-op.
    - Subsequent calls with differing args: :class:`JVMAlreadyStartedError`
      (JPype cannot reconfigure a running JVM).
    """
    global _initialized, _init_vmargs, _data_loaded

    import jpype

    if vmargs is None:
        vmargs = os.environ.get("PROPYGATOR_VM_ARGS")

    if jpype.isJVMStarted():  # type: ignore[attr-defined]  # jpype stubs omit it
        if _initialized:
            if vmargs != _init_vmargs:
                raise JVMAlreadyStartedError(
                    _already_started_message(vmargs, _init_vmargs)
                )
            # Same args, JVM already ours. Finish loading the data context if a
            # prior call started the JVM but failed before the data loaded.
            if not _data_loaded:
                _setup_orekit_data(_resolve_data_path())
                _data_loaded = True
            return
        # JVM was started outside propygator (e.g. a direct orekit_jpype.initVM
        # by other code). We cannot apply different vmargs to a running JVM.
        if vmargs is not None:
            raise JVMAlreadyStartedError(_already_started_message(vmargs, None))
        # Adopt the running JVM: load our data context once and record state.
        _setup_orekit_data(_resolve_data_path())
        _initialized = True
        _init_vmargs = None
        _data_loaded = True
        return

    # Fresh start. Resolve data BEFORE touching the JVM so a missing-data
    # condition raises a clean propygator error, never a Java trace.
    data_path = _resolve_data_path()

    import orekit_jpype

    logger.info("Starting JVM (vmargs=%r)", vmargs)
    orekit_jpype.initVM(vmargs=vmargs)
    # The JVM is running and owned by propygator. Record that immediately, before
    # loading data, so that if _setup_orekit_data raises, module state stays
    # consistent (JVM up, data not yet loaded) and a later call can complete the
    # load — rather than misclassifying our own JVM as externally started.
    _initialized = True
    _init_vmargs = vmargs
    _setup_orekit_data(data_path)
    _data_loaded = True


def _ensure_started() -> None:
    """Idempotent JVM bootstrap for Orekit-touching code paths.

    Feature code calls this before any Orekit access; cheap after the first
    successful init(). If a prior init() started the JVM but failed to load the
    data context, complete the data load here rather than re-entering init()
    (which compares vmargs and could spuriously reject the implicit retry).
    """
    global _data_loaded
    if _initialized and _data_loaded:
        return
    if _initialized and not _data_loaded:
        _setup_orekit_data(_resolve_data_path())
        _data_loaded = True
        return
    init()


def _cache_dir() -> Path:
    """The propygator on-disk cache root, ``~/.propygator/cache/`` (architecture §10).

    The single source of truth for the cache location, shared by :func:`clear_cache`
    and the TLE fetch path (``tle.sources``) so a fetched TLE written here is cleared
    by ``clear_cache()`` by construction. Pure-Python; the directory is created lazily
    by writers, not here. (Tests monkeypatch this one function to redirect the cache to
    a ``tmp_path`` and never touch the real ``~/.propygator/``.)
    """
    return Path.home() / ".propygator" / "cache"


def clear_cache() -> None:
    """Recursively empty ``~/.propygator/cache/``, preserving the directory.

    No-op if the cache directory does not exist. Selective clearing (by source,
    satellite, or age) is out of scope for v1 (architecture §10).
    """
    cache_dir = _cache_dir()
    if not cache_dir.is_dir():
        logger.debug("No cache to clear at %s", cache_dir)
        return

    for child in cache_dir.iterdir():
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    logger.info("Cleared propygator cache at %s", cache_dir)
