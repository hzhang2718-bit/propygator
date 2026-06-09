"""Download and extract orekit-data into a local directory.

Orekit needs an ``orekit-data`` directory — leap seconds, Earth-orientation
parameters, planetary ephemerides, and gravity-field coefficients — which
propygator treats as an external dependency rather than shipping (architecture
§3). This script fetches the canonical dataset from the Orekit GitLab and lays
it out where propygator's resolution order can find it; by default that is
``~/.propygator/orekit-data/`` (the second entry in the search order).

Examples
--------
Download to the default location::

    python scripts/download_orekit_data.py

Download somewhere else and overwrite an existing copy::

    python scripts/download_orekit_data.py --target /data/orekit-data --force

The same entry point is used by CI to provision the dataset on a cache miss.
All output goes through the :mod:`logging` module, never ``print``.

This script is deliberately self-contained (``requests`` + ``zipfile``): it must
run *before* any orekit-data exists, so it cannot rely on Orekit's own helpers
(``orekit_jpype.pyhelpers`` cannot even be imported without a running JVM).
"""

from __future__ import annotations

import argparse
import logging
import shutil
import tempfile
import zipfile
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

#: Canonical orekit-data archive (master branch) on the Orekit GitLab.
ARCHIVE_URL = (
    "https://gitlab.orekit.org/orekit/orekit-data/-/archive/master/"
    "orekit-data-master.zip"
)
#: Default install location — the second entry in propygator's search order (§3).
DEFAULT_TARGET = Path.home() / ".propygator" / "orekit-data"

_DOWNLOAD_TIMEOUT_S = 120.0
_CHUNK_SIZE = 1 << 16  # 64 KiB streaming chunks


def _stream_download(url: str, dest: Path, timeout: float) -> None:
    """Stream ``url`` to ``dest`` without holding the whole archive in memory."""
    with requests.get(url, stream=True, timeout=timeout) as response:
        response.raise_for_status()
        with dest.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=_CHUNK_SIZE):
                handle.write(chunk)


def _single_subdir(directory: Path) -> Path:
    """Return the one directory a GitLab archive wraps its contents in.

    GitLab archives place everything under a single top-level folder (e.g.
    ``orekit-data-master/``). Raise if the layout is not exactly that one entry,
    so an unexpected archive shape fails loudly rather than silently mislaying
    the data.
    """
    entries = list(directory.iterdir())
    subdirs = [entry for entry in entries if entry.is_dir()]
    if len(entries) != 1 or len(subdirs) != 1:
        names = sorted(entry.name for entry in entries)
        raise RuntimeError(f"Unexpected archive layout under {directory}: {names}")
    return subdirs[0]


def download_orekit_data(
    target: Path = DEFAULT_TARGET,
    *,
    url: str = ARCHIVE_URL,
    force: bool = False,
    timeout: float = _DOWNLOAD_TIMEOUT_S,
) -> Path:
    """Download and extract orekit-data into ``target``.

    Parameters
    ----------
    target:
        Directory to populate with the orekit-data files. Created if absent.
    url:
        Archive URL to fetch. Defaults to the master-branch zip on the Orekit
        GitLab.
    force:
        Overwrite ``target`` if it already contains files. Without this, a
        non-empty ``target`` is left untouched (a no-op that keeps CI cache
        restores cheap).
    timeout:
        Per-request timeout in seconds, passed to :func:`requests.get`.

    Returns
    -------
    Path
        The populated ``target`` directory.
    """
    target = Path(target)
    if target.is_dir() and any(target.iterdir()) and not force:
        logger.info(
            "orekit-data already present at %s; skipping (pass --force to refresh).",
            target,
        )
        return target

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        archive = tmp_dir / "orekit-data.zip"
        logger.info("Downloading orekit-data from %s", url)
        _stream_download(url, archive, timeout)

        extract_dir = tmp_dir / "extracted"
        logger.info("Extracting archive")
        with zipfile.ZipFile(archive) as zip_file:
            zip_file.extractall(extract_dir)
        data_root = _single_subdir(extract_dir)

        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            shutil.rmtree(target)
        # Move the unwrapped data folder so it *becomes* target (dir -> dir).
        shutil.move(str(data_root), str(target))

    logger.info("orekit-data ready at %s", target)
    return target


def main(argv: list[str] | None = None) -> None:
    """CLI entry point: parse args, configure logging, run the download."""
    parser = argparse.ArgumentParser(
        description="Download and extract orekit-data for propygator.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=DEFAULT_TARGET,
        help="Directory to populate with orekit-data.",
    )
    parser.add_argument(
        "--url",
        default=ARCHIVE_URL,
        help="Archive URL to download.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing non-empty target directory.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=_DOWNLOAD_TIMEOUT_S,
        help="Per-request timeout in seconds.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable debug-level logging.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    download_orekit_data(
        args.target, url=args.url, force=args.force, timeout=args.timeout
    )


if __name__ == "__main__":
    main()
