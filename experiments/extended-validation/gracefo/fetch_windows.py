"""Download, extract and tier-1 screen the ten GRACE-FO windows (maintainer's step).

    conda run -n propygator python fetch_windows.py --all --dry-run
    conda run -n propygator python fetch_windows.py --window low_2019_12
    conda run -n propygator python fetch_windows.py --all

WHAT IT DOES, one day at a time: fetch the daily tarball, extract the six members
this study keeps (GNV1B / MAS1B / THR1B for satellites C and D), gzip them into
the window's directory, delete the tarball, move on. When a window's fourteenth
day lands, run the tier-1 THR1B screen over it and print the verdict.

WHY STREAMING RATHER THAN FETCH-ALL-THEN-EXTRACT. 140 days at 148 MB is about
20.2 GB in, against about 2.6 GB retained (19.23 MB/day gzipped, measured). Only
one tarball is ever on disk at a time, so peak usage is the retained tree plus
one file. Nothing the screen reads lives in the tarball once extraction is done,
so discarding it immediately costs nothing (contract, "New truth data lands in
the new study's own folder").

SOURCE. GFZ ISDC serves the identical JPL RL04 bundles from an open directory
with NO LOGIN, which is why this is scriptable at all -- PO.DAAC would need
Earthdata auth for the same bytes. The ACX and LRI variants hold only
accelerometer and laser-ranging products; GNV1B, MAS1B and THR1B are all in
noLRI, so there is no lighter route to THR1B and no way to screen before
downloading. Verified 2026-08-17: the archive serves every day of all ten
windows, currently through 2026-07-30.

IDEMPOTENT. A day whose six outputs already exist is skipped, so an interrupted
run resumes by being re-run. A partial download resumes mid-file via an HTTP
Range request against its .part file.

INTEGRITY. ISDC publishes no checksums, so the check is functional rather than
cryptographic: the transfer must match Content-Length, the tarball must open,
and all six expected members must be present and non-empty. Any failure deletes
the tarball and retries -- a truncated tarball is the one failure mode that
could otherwise produce a silently short window.

Not shipped, not in CI, outside ``testpaths``. ASCII-only output; byte-level
progress goes to stderr so a redirected stdout stays readable.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thr1b import format_screen, screen_thr1b  # noqa: E402
from windows import (  # noqa: E402
    DATA_ROOT,
    PRODUCTS,
    SAT_IDS,
    TARBALL_ROOT,
    WINDOWS,
    Window,
    find_product_files,
    resolve,
)

BASE_URL = "https://isdc-data.gfz.de/grace-fo/Level-1B/JPL/INSTRUMENT/RL04"
PRODUCT_VERSION = "04"
CHUNK_BYTES = 1 << 20  # 1 MiB
DEFAULT_RETRIES = 4
USER_AGENT = "propygator-extended-validation/0.8.1 (research; contact via repo)"

# Measured on a delivered tarball (2019-11-14): 148.2 MB in, 19.23 MB retained.
NOMINAL_TARBALL_MB = 148.0
NOMINAL_RETAINED_MB = 19.23


def tarball_name(day: date) -> str:
    return f"gracefo_1B_{day.isoformat()}_RL04.ascii.noLRI.tgz"


def tarball_url(day: date) -> str:
    """The archive URL. NOTE the year comes from the DAY, not the window's t0 --
    window 1 (low_2019_12) runs 2019-12-23 to 2020-01-05 and straddles two
    yearly directories."""
    return f"{BASE_URL}/{day.year}/{tarball_name(day)}"


def member_name(product: str, day: date, sat_id: str) -> str:
    return f"{product}_{day.isoformat()}_{sat_id}_{PRODUCT_VERSION}.txt"


def outputs_for(window_dir: Path, day: date) -> list[Path]:
    """The six gzipped products this study keeps from one daily tarball."""
    return [
        window_dir / f"{member_name(product, day, sat)}.gz"
        for product in PRODUCTS
        for sat in SAT_IDS
    ]


def _human(n_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n_bytes) < 1024.0 or unit == "GB":
            return f"{n_bytes:.1f} {unit}"
        n_bytes /= 1024.0
    return f"{n_bytes:.1f} GB"


def download(url: str, dest: Path, *, retries: int = DEFAULT_RETRIES) -> int:
    """Fetch ``url`` to ``dest``, resuming a partial ``.part`` if one is present.

    Returns the number of bytes actually transferred this call (0 if the file
    was already complete). Raises SystemExit after ``retries`` failures -- a
    download that will not complete is not something to paper over.
    """
    part = dest.with_suffix(dest.suffix + ".part")
    last_error: Exception | None = None

    for attempt in range(1, retries + 1):
        have = part.stat().st_size if part.exists() else 0
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        if have:
            request.add_header("Range", f"bytes={have}-")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                # A server that ignores Range answers 200 and resends from zero.
                resuming = response.status == 206
                if have and not resuming:
                    have = 0
                declared = response.headers.get("Content-Length")
                total = (int(declared) + have) if declared is not None else None
                mode = "ab" if resuming and have else "wb"
                got = have
                t0 = time.perf_counter()
                with open(part, mode) as fh:
                    while True:
                        chunk = response.read(CHUNK_BYTES)
                        if not chunk:
                            break
                        fh.write(chunk)
                        got += len(chunk)
                        if total:
                            pct = 100.0 * got / total
                            print(
                                f"\r      {_human(got)} / {_human(total)} "
                                f"({pct:5.1f}%)",
                                end="",
                                file=sys.stderr,
                                flush=True,
                            )
                dt = max(time.perf_counter() - t0, 1e-6)
            print(
                f"\r      {_human(got)} in {dt:.0f} s "
                f"({_human((got - have) / dt)}/s)          ",
                file=sys.stderr,
            )
            if total is not None and got != total:
                raise OSError(
                    f"short transfer: {got} bytes written, {total} declared"
                )
            part.replace(dest)
            return got - have
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last_error = exc
            # 416 Range Not Satisfiable means the .part is already at or past the
            # full length -- retrying with the same offset would 416 forever, so
            # drop it and start clean. Any other error keeps the .part so the
            # next attempt resumes rather than restarting 148 MB.
            if isinstance(exc, urllib.error.HTTPError) and exc.code == 416:
                print(
                    f"      416 Range Not Satisfiable at offset {have}; "
                    f"discarding the partial file and restarting this day",
                    file=sys.stderr,
                )
                part.unlink(missing_ok=True)
            backoff = min(2**attempt, 30)
            print(
                f"      attempt {attempt}/{retries} failed ({exc}); "
                f"retrying in {backoff} s",
                file=sys.stderr,
            )
            if attempt < retries:
                time.sleep(backoff)

    raise SystemExit(
        f"  FAILED after {retries} attempts: {url}\n  last error: {last_error}"
    )


def extract_day(tarball: Path, window_dir: Path, day: date) -> int:
    """Extract and gzip the six kept members. Returns bytes written.

    All six are written to ``.part`` names and renamed only once every one of
    them has succeeded, so an interrupted extraction never leaves a directory
    that looks complete to :func:`outputs_for`.
    """
    window_dir.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, Path]] = []
    written = 0
    try:
        with tarfile.open(tarball, "r:*") as tar:
            index = {Path(m.name).name: m for m in tar.getmembers()}
            for product in PRODUCTS:
                for sat in SAT_IDS:
                    name = member_name(product, day, sat)
                    member = index.get(name)
                    if member is None:
                        raise ValueError(
                            f"{tarball.name}: no member {name}. The tarball is "
                            f"truncated or the product naming changed."
                        )
                    if member.size == 0:
                        raise ValueError(f"{tarball.name}: member {name} is empty")
                    source = tar.extractfile(member)
                    if source is None:
                        raise ValueError(f"{tarball.name}: could not extract {name}")
                    final = window_dir / f"{name}.gz"
                    temp = final.with_suffix(final.suffix + ".part")
                    with gzip.open(temp, "wb", compresslevel=6) as out:
                        shutil.copyfileobj(source, out, CHUNK_BYTES)
                    staged.append((temp, final))
                    written += temp.stat().st_size
    except Exception:
        for temp, _ in staged:
            temp.unlink(missing_ok=True)
        raise
    for temp, final in staged:
        temp.replace(final)
    return written


def screen_window(window: Window, window_dir: Path) -> bool:
    """Tier-1 THR1B screen over the landed window, both satellites."""
    print(f"  [tier-1 screen] {window.name}")
    all_clean = True
    for sat in SAT_IDS:
        files = find_product_files(window_dir, "THR1B", sat)
        if len(files) != len(window.days):
            print(
                f"    sat {sat}: SKIPPED -- {len(files)} of {len(window.days)} "
                f"THR1B days present, the screen needs all of them"
            )
            all_clean = False
            continue
        screen = screen_thr1b(files, sat_id=sat)
        for line in format_screen(screen, indent="    "):
            print(line)
        all_clean = all_clean and screen.clean
    return all_clean


def process_window(
    window: Window,
    *,
    data_root: Path,
    tarball_root: Path,
    keep_tarballs: bool,
    no_download: bool,
    force: bool,
) -> tuple[int, int, bool]:
    """Land one window. Returns (bytes downloaded, bytes retained, tier-1 clean)."""
    window_dir = data_root / window.name
    downloaded = 0
    retained = 0
    print(f"=== {window.index:2d}. {window.name} "
          f"({window.t0} .. {window.days[-1]}, band {window.band}) ===")

    for n, day in enumerate(window.days, start=1):
        outputs = outputs_for(window_dir, day)
        if not force and all(p.exists() for p in outputs):
            print(f"  {n:2d}/14 {day}  already extracted, skipping")
            retained += sum(p.stat().st_size for p in outputs)
            continue

        tarball = tarball_root / tarball_name(day)
        if not tarball.exists():
            if no_download:
                raise SystemExit(
                    f"  {day}: --no-download given but {tarball} is not present"
                )
            tarball_root.mkdir(parents=True, exist_ok=True)
            print(f"  {n:2d}/14 {day}  fetching {tarball_url(day)}")
            downloaded += download(tarball_url(day), tarball)
        else:
            print(f"  {n:2d}/14 {day}  tarball already on disk")

        try:
            written = extract_day(tarball, window_dir, day)
        except Exception as exc:
            # A tarball that will not extract is the failure mode that would
            # otherwise leave a silently short window: drop it so a re-run
            # re-fetches rather than re-reading the same bad bytes.
            tarball.unlink(missing_ok=True)
            raise SystemExit(f"  {day}: extraction failed, tarball discarded: {exc}")
        retained += written
        print(f"        extracted 6 members, {_human(written)} retained")

        if not keep_tarballs:
            tarball.unlink(missing_ok=True)

    clean = screen_window(window, window_dir)
    print(f"  {window.name}: tier-1 {'CLEAN' if clean else 'NOT CLEAN -- see above'}")
    if window.note:
        print(f"  note: {window.note}")
    print()
    return downloaded, retained, clean


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--window",
        action="append",
        default=None,
        metavar="NAME",
        help="window to land; repeatable. Default: none (pass --all for every window)",
    )
    parser.add_argument("--all", action="store_true", help="land all ten windows")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the URLs and the byte budget, download nothing",
    )
    parser.add_argument(
        "--keep-tarballs",
        action="store_true",
        help="keep each daily tarball after extraction (about 20.2 GB for all ten)",
    )
    parser.add_argument(
        "--no-download",
        action="store_true",
        help="extract from tarballs already staged; never touch the network",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-extract days whose outputs already exist",
    )
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--tarball-root", type=Path, default=TARBALL_ROOT)
    args = parser.parse_args()

    if args.all:
        selected = list(WINDOWS)
    elif args.window:
        selected = [resolve(name) for name in args.window]
    else:
        raise SystemExit("pass --window NAME (repeatable) or --all")

    if args.dry_run:
        n_days = 0
        for window in selected:
            print(f"=== {window.index:2d}. {window.name} ({window.band}) ===")
            window_dir = args.data_root / window.name
            for day in window.days:
                have = all(p.exists() for p in outputs_for(window_dir, day))
                print(f"  {'have' if have else 'need'}  {tarball_url(day)}")
                n_days += 0 if have else 1
        print()
        print(
            f"{n_days} day(s) to fetch: about "
            f"{n_days * NOMINAL_TARBALL_MB / 1024:.1f} GB downloaded, "
            f"{n_days * NOMINAL_RETAINED_MB / 1024:.1f} GB retained"
        )
        return

    t0 = time.perf_counter()
    total_down = 0
    total_kept = 0
    not_clean: list[str] = []
    for window in selected:
        down, kept, clean = process_window(
            window,
            data_root=args.data_root,
            tarball_root=args.tarball_root,
            keep_tarballs=args.keep_tarballs,
            no_download=args.no_download,
            force=args.force,
        )
        total_down += down
        total_kept += kept
        if not clean:
            not_clean.append(window.name)

    dt = time.perf_counter() - t0
    print(
        f"[fetch_windows] {len(selected)} window(s) in {dt / 60:.0f} min: "
        f"{_human(total_down)} downloaded, {_human(total_kept)} retained"
    )
    # The verdict repeated at the end, because on a --all run the per-window
    # block that carries it is buried under ~140 day lines of scrollback. The
    # EXIT STATUS STAYS 0 deliberately: the download succeeded, and a burn is a
    # science verdict rather than a transfer failure. run_screen.py re-runs both
    # gates over every window and is the gate Part 2 actually waits on.
    if not_clean:
        print(f"  TIER-1 NOT CLEAN: {', '.join(not_clean)} -- see the blocks above")
    else:
        print(f"  tier-1 CLEAN: all {len(selected)} window(s), both satellites")


if __name__ == "__main__":
    main()
