"""Download TMDb images listed in the exported CSVs to the NAS.

Runs on the Windows machine. Reads CSVs produced by export_image_tables.py,
downloads each image from image.tmdb.org in the requested sizes, and writes
to NAS_ROOT using the per-entity sharded layout described in README.md.

Resumable: a SQLite progress DB (STATE_DB) records every (table, id_row,
size) outcome. Re-running the script picks up where it left off and only
retries rows that ended in transient errors.

Usage:
    python download_images.py [--sizes original,w780,w342]
                              [--workers 8]
                              [--csv-dir ./csv]
                              [--nas-root Z:\\tmdb]
                              [--table T_WC_TMDB_MOVIE_IMAGE ...]
                              [--state ./state.sqlite]
                              [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

import httpx
from dotenv import load_dotenv
from tqdm import tqdm


TMDB_BASE = "https://image.tmdb.org/t/p"

# Allow csv.reader to handle very large IMAGE_PATH-free strings without blowing
# up. TMDb paths are short, but be safe against pathological CSVs.
csv.field_size_limit(10_000_000)


# ---------------------------------------------------------------------------
# Path layout
# ---------------------------------------------------------------------------

def _shard(lngid: int) -> str:
    """3-digit zero-padded shard from an entity ID (id % 1000)."""
    return f"{lngid % 1000:03d}"


def _basename(strimagepath: str) -> str:
    """TMDb IMAGE_PATH starts with '/'; the filename is what follows."""
    return strimagepath.lstrip("/")


# Each builder receives (nas_root, row_dict, size) and returns a Path.
PathBuilder = Callable[[Path, dict, str], Path]


def _movie_path(nas: Path, row: dict, size: str) -> Path:
    lngid = int(row["ID_MOVIE"])
    return nas / "movie" / _shard(lngid) / str(lngid) / size / _basename(row["IMAGE_PATH"])


def _serie_path(nas: Path, row: dict, size: str) -> Path:
    lngid = int(row["ID_SERIE"])
    return nas / "serie" / _shard(lngid) / str(lngid) / size / _basename(row["IMAGE_PATH"])


def _season_path(nas: Path, row: dict, size: str) -> Path:
    lngserie = int(row["ID_SERIE"])
    lngseason = int(row["ID_SEASON"])
    return (
        nas / "serie" / _shard(lngserie) / str(lngserie)
        / "seasons" / str(lngseason) / size / _basename(row["IMAGE_PATH"])
    )


def _episode_path(nas: Path, row: dict, size: str) -> Path:
    lngserie = int(row["ID_SERIE"])
    lngepisode = int(row["ID_EPISODE"])
    return (
        nas / "serie" / _shard(lngserie) / str(lngserie)
        / "episodes" / str(lngepisode) / size / _basename(row["IMAGE_PATH"])
    )


def _person_path(nas: Path, row: dict, size: str) -> Path:
    lngid = int(row["ID_PERSON"])
    return nas / "person" / _shard(lngid) / str(lngid) / size / _basename(row["IMAGE_PATH"])


def _collection_path(nas: Path, row: dict, size: str) -> Path:
    lngid = int(row["ID_COLLECTION"])
    return nas / "collection" / _shard(lngid) / str(lngid) / size / _basename(row["IMAGE_PATH"])


def _company_path(nas: Path, row: dict, size: str) -> Path:
    lngid = int(row["ID_COMPANY"])
    return nas / "company" / _shard(lngid) / str(lngid) / size / _basename(row["IMAGE_PATH"])


def _network_path(nas: Path, row: dict, size: str) -> Path:
    lngid = int(row["ID_NETWORK"])
    return nas / "network" / _shard(lngid) / str(lngid) / size / _basename(row["IMAGE_PATH"])


BUILDERS: dict[str, PathBuilder] = {
    "T_WC_TMDB_MOVIE_IMAGE":      _movie_path,
    "T_WC_TMDB_SERIE_IMAGE":      _serie_path,
    "T_WC_TMDB_SEASON_IMAGE":     _season_path,
    "T_WC_TMDB_EPISODE_IMAGE":    _episode_path,
    "T_WC_TMDB_PERSON_IMAGE":     _person_path,
    "T_WC_TMDB_COLLECTION_IMAGE": _collection_path,
    "T_WC_TMDB_COMPANY_IMAGE":    _company_path,
    "T_WC_TMDB_NETWORK_IMAGE":    _network_path,
}


# ---------------------------------------------------------------------------
# Progress state
# ---------------------------------------------------------------------------

# Status values written to image_state.status:
#   done           -> file downloaded successfully this run
#   file_exists    -> target was already on disk on first encounter
#   http_404       -> server returned 404, will not retry
#   error          -> transient failure, will retry on next run
STATUS_DONE = "done"
STATUS_EXISTS = "file_exists"
STATUS_404 = "http_404"
STATUS_ERROR = "error"

# Statuses that mean "do nothing on subsequent runs".
TERMINAL_STATUSES = {STATUS_DONE, STATUS_EXISTS, STATUS_404}


class State:
    """Thread-safe SQLite wrapper for tracking per-(table, id_row, size) status."""

    def __init__(self, pathdb: Path) -> None:
        self._lock = threading.Lock()
        # check_same_thread=False so we can share the conn across workers under
        # the explicit lock.
        self._conn = sqlite3.connect(str(pathdb), check_same_thread=False, timeout=30.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS image_state (
                table_name  TEXT NOT NULL,
                id_row      INTEGER NOT NULL,
                size        TEXT NOT NULL,
                status      TEXT NOT NULL,
                error       TEXT,
                bytes       INTEGER,
                finished_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (table_name, id_row, size)
            )
            """
        )
        self._conn.commit()

    def get_status(self, strtable: str, lngrow: int, strsize: str) -> str | None:
        with self._lock:
            cur = self._conn.execute(
                "SELECT status FROM image_state WHERE table_name=? AND id_row=? AND size=?",
                (strtable, lngrow, strsize),
            )
            row = cur.fetchone()
        return row[0] if row else None

    def record(
        self,
        strtable: str,
        lngrow: int,
        strsize: str,
        strstatus: str,
        strerror: str | None = None,
        lngbytes: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO image_state (table_name, id_row, size, status, error, bytes, finished_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(table_name, id_row, size) DO UPDATE SET
                    status      = excluded.status,
                    error       = excluded.error,
                    bytes       = excluded.bytes,
                    finished_at = CURRENT_TIMESTAMP
                """,
                (strtable, lngrow, strsize, strstatus, strerror, lngbytes),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# ---------------------------------------------------------------------------
# Download work unit
# ---------------------------------------------------------------------------

@dataclass
class Job:
    """One image at one size, plus all the context needed to write it."""
    table: str
    id_row: int
    size: str
    url: str
    target: Path


@dataclass
class Result:
    job: Job
    status: str
    error: str | None = None
    bytes_written: int | None = None


def _build_jobs(strtable: str, row: dict, arrsizes: list[str], pathnas: Path) -> list[Job]:
    """Expand one CSV row into one Job per requested size."""
    builder = BUILDERS[strtable]
    lngrow = int(row["ID_ROW"])
    strpath = row["IMAGE_PATH"]
    arrjobs: list[Job] = []
    for strsize in arrsizes:
        pathtarget = builder(pathnas, row, strsize)
        strurl = f"{TMDB_BASE}/{strsize}{strpath}"  # strpath already starts with '/'
        arrjobs.append(Job(strtable, lngrow, strsize, strurl, pathtarget))
    return arrjobs


def _download_one(
    job: Job,
    client: httpx.Client,
    state: State,
    lngmaxretries: int,
    intdryrun: bool,
) -> Result:
    """Download a single image, with retry/backoff for transient failures.

    Idempotent against state: if the row is already in a terminal status,
    skip; if the file is already on disk, mark file_exists and skip.
    """
    strprior = state.get_status(job.table, job.id_row, job.size)
    if strprior in TERMINAL_STATUSES:
        return Result(job, strprior)

    if job.target.exists():
        state.record(job.table, job.id_row, job.size, STATUS_EXISTS)
        return Result(job, STATUS_EXISTS)

    if intdryrun:
        return Result(job, "dry_run")

    job.target.parent.mkdir(parents=True, exist_ok=True)
    pathpart = job.target.with_suffix(job.target.suffix + ".part")

    strlasterror = ""
    for lngattempt in range(1, lngmaxretries + 1):
        try:
            with client.stream("GET", job.url) as resp:
                if resp.status_code == 404:
                    state.record(job.table, job.id_row, job.size, STATUS_404, "404")
                    return Result(job, STATUS_404, "404")
                if resp.status_code != 200:
                    strlasterror = f"HTTP {resp.status_code}"
                    resp.read()  # drain
                    raise httpx.HTTPStatusError(strlasterror, request=resp.request, response=resp)
                lngbytes = 0
                with pathpart.open("wb") as fp:
                    for chunk in resp.iter_bytes(chunk_size=64 * 1024):
                        fp.write(chunk)
                        lngbytes += len(chunk)
            # Atomic rename onto the final filename. On Windows os.replace
            # overwrites if the target exists (race-safe under concurrent runs).
            os.replace(pathpart, job.target)
            state.record(job.table, job.id_row, job.size, STATUS_DONE, None, lngbytes)
            return Result(job, STATUS_DONE, bytes_written=lngbytes)
        except (httpx.HTTPError, OSError) as exc:
            strlasterror = f"{type(exc).__name__}: {exc}"
            # Clean up partial file before retry
            try:
                pathpart.unlink(missing_ok=True)
            except OSError:
                pass
            if lngattempt < lngmaxretries:
                time.sleep(2 ** (lngattempt - 1))  # 1s, 2s, 4s, ...

    state.record(job.table, job.id_row, job.size, STATUS_ERROR, strlasterror)
    return Result(job, STATUS_ERROR, strlasterror)


# ---------------------------------------------------------------------------
# CSV prefetch from the VPS over SFTP
# ---------------------------------------------------------------------------

def f_fetch_csvs(
    pathlocal: Path,
    strhost: str,
    lngport: int,
    struser: str,
    strkey: str | None,
    strpassword: str | None,
    strremote_dir: str,
) -> int:
    """Pull T_WC_TMDB_*.csv files from the VPS via SFTP into pathlocal.

    Only transfers files where the remote is newer than the local copy
    (or the local file is missing or wrong size). Preserves remote mtime
    locally so subsequent runs can short-circuit unchanged files.

    Downloads land in a .part file and are atomically renamed on success,
    so a Ctrl-C mid-transfer leaves the previous good CSV in place.

    Args:
        pathlocal: Local CSV directory (created if missing).
        strhost: SSH host.
        lngport: SSH port.
        struser: SSH user.
        strkey: Path to a private key, or None to fall back to agent /
            default keys / SSH_PASSWORD.
        strpassword: SSH password, or None.
        strremote_dir: Absolute path to the CSV directory on the VPS.

    Returns:
        Number of files actually transferred (skipped files don't count).
    """
    import paramiko  # local import: keeps export_image_tables.py free of this dep

    print(f"-> SFTP {struser}@{strhost}:{lngport}  {strremote_dir}")
    pathlocal.mkdir(parents=True, exist_ok=True)

    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    arrkwargs: dict = {
        "hostname": strhost,
        "port": lngport,
        "username": struser,
        "timeout": 30,
        "auth_timeout": 30,
    }
    if strkey:
        arrkwargs["key_filename"] = strkey
    if strpassword:
        arrkwargs["password"] = strpassword

    client.connect(**arrkwargs)
    try:
        sftp = client.open_sftp()
        try:
            lngdownloaded = 0
            arrentries = sorted(sftp.listdir_attr(strremote_dir), key=lambda a: a.filename)
            for attr in arrentries:
                strname = attr.filename
                if not (strname.startswith("T_WC_TMDB_") and strname.endswith(".csv")):
                    continue
                pathfile = pathlocal / strname
                lngremote_mtime = int(attr.st_mtime or 0)
                if pathfile.exists():
                    stat = pathfile.stat()
                    if int(stat.st_mtime) >= lngremote_mtime and stat.st_size == attr.st_size:
                        print(f"  {strname}: up-to-date, skipping")
                        continue

                strremote_path = f"{strremote_dir.rstrip('/')}/{strname}"
                pathpart = pathfile.with_suffix(pathfile.suffix + ".part")
                try:
                    with tqdm(
                        total=attr.st_size,
                        unit="B",
                        unit_scale=True,
                        unit_divisor=1024,
                        desc=strname,
                        leave=False,
                    ) as bar:
                        lnglast = [0]

                        def _cb(transferred: int, _total: int, _last=lnglast, _bar=bar) -> None:
                            _bar.update(transferred - _last[0])
                            _last[0] = transferred

                        sftp.get(strremote_path, str(pathpart), callback=_cb)
                    os.utime(pathpart, (attr.st_atime or lngremote_mtime, lngremote_mtime))
                    os.replace(pathpart, pathfile)
                except BaseException:
                    # Includes KeyboardInterrupt: leave the prior CSV (if any) intact.
                    try:
                        pathpart.unlink(missing_ok=True)
                    except OSError:
                        pass
                    raise
                print(f"  {strname}: {attr.st_size / 1024 / 1024:.1f} MB fetched")
                lngdownloaded += 1
            return lngdownloaded
        finally:
            sftp.close()
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def _iter_csv_jobs(
    pathcsv: Path,
    strtable: str,
    arrsizes: list[str],
    pathnas: Path,
) -> Iterator[Job]:
    """Yield Jobs from one CSV file."""
    with pathcsv.open("r", encoding="utf-8", newline="") as fp:
        reader = csv.DictReader(fp)
        for row in reader:
            if not row.get("IMAGE_PATH"):
                continue
            for job in _build_jobs(strtable, row, arrsizes, pathnas):
                yield job


def _count_csv_rows(pathcsv: Path) -> int:
    """Count data rows (excluding header) without loading the file."""
    with pathcsv.open("rb") as fp:
        lngrows = sum(1 for _ in fp)
    return max(lngrows - 1, 0)


def f_download(
    pathcsv_dir: Path,
    pathnas: Path,
    arrsizes: list[str],
    arrtables: list[str],
    lngworkers: int,
    pathstate: Path,
    lngtimeout: float,
    lngmaxretries: int,
    intdryrun: bool,
) -> dict[str, int]:
    """Process every CSV in pathcsv_dir with a thread pool.

    Args:
        pathcsv_dir: Directory containing T_WC_TMDB_*_IMAGE.csv files.
        pathnas: NAS root for image output.
        arrsizes: TMDb sizes to download (e.g. ["original", "w780"]).
        arrtables: Only process these tables. Empty = all CSVs found.
        lngworkers: Worker thread count.
        pathstate: SQLite progress DB path.
        lngtimeout: HTTP timeout in seconds.
        lngmaxretries: Max attempts per image within a single run.
        intdryrun: If True, do not write any files (still touches state DB).

    Returns:
        Status counter dict (status -> count) aggregated across all tables.
    """
    arrcsvs: list[tuple[str, Path]] = []
    if arrtables:
        for strtable in arrtables:
            pathcsv = pathcsv_dir / f"{strtable}.csv"
            if not pathcsv.exists():
                sys.exit(f"missing CSV: {pathcsv}")
            arrcsvs.append((strtable, pathcsv))
    else:
        for strtable in BUILDERS:
            pathcsv = pathcsv_dir / f"{strtable}.csv"
            if pathcsv.exists():
                arrcsvs.append((strtable, pathcsv))
    if not arrcsvs:
        sys.exit(f"no CSV files found in {pathcsv_dir}")

    state = State(pathstate)
    timeout = httpx.Timeout(connect=15.0, read=lngtimeout, write=lngtimeout, pool=lngtimeout)
    limits = httpx.Limits(max_connections=lngworkers * 2, max_keepalive_connections=lngworkers)
    client = httpx.Client(
        timeout=timeout,
        limits=limits,
        headers={"User-Agent": "tmdb-image-downloader/1.0"},
        follow_redirects=True,
    )

    counters: dict[str, int] = {}
    try:
        for strtable, pathcsv in arrcsvs:
            lngrows = _count_csv_rows(pathcsv)
            lngtotal = lngrows * len(arrsizes)
            print(f"-> {strtable}: {lngrows:,} rows × {len(arrsizes)} sizes = {lngtotal:,} images")

            with ThreadPoolExecutor(max_workers=lngworkers) as pool, \
                    tqdm(total=lngtotal, unit="img", desc=strtable) as bar:
                # Submit in batches to bound memory while still keeping the
                # worker pool saturated.
                lngbatch = max(lngworkers * 8, 64)
                arrfutures: list = []
                for job in _iter_csv_jobs(pathcsv, strtable, arrsizes, pathnas):
                    arrfutures.append(pool.submit(
                        _download_one, job, client, state, lngmaxretries, intdryrun
                    ))
                    if len(arrfutures) >= lngbatch:
                        for fut in as_completed(arrfutures):
                            result = fut.result()
                            counters[result.status] = counters.get(result.status, 0) + 1
                            bar.update(1)
                        arrfutures.clear()
                for fut in as_completed(arrfutures):
                    result = fut.result()
                    counters[result.status] = counters.get(result.status, 0) + 1
                    bar.update(1)
    finally:
        client.close()
        state.close()

    return counters


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--csv-dir",
        default=os.environ.get("CSV_DIR", "./csv"),
        help="directory containing T_WC_TMDB_*_IMAGE.csv (default: $CSV_DIR or ./csv)",
    )
    parser.add_argument(
        "--nas-root",
        default=os.environ.get("NAS_ROOT", r"Z:\tmdb"),
        help="destination root on the NAS (default: $NAS_ROOT or Z:\\tmdb)",
    )
    parser.add_argument(
        "--sizes",
        default="original",
        help="comma-separated TMDb sizes (default: original). Examples: w185,w342,w780,original",
    )
    parser.add_argument("--workers", type=int, default=8, help="concurrent workers (default: 8)")
    parser.add_argument(
        "--table",
        action="append",
        default=[],
        help="restrict to one table; repeat for multiple. Default: every CSV present.",
    )
    parser.add_argument(
        "--state",
        default=os.environ.get("STATE_DB", "./state.sqlite"),
        help="SQLite progress DB (default: $STATE_DB or ./state.sqlite)",
    )
    parser.add_argument("--timeout", type=float, default=30.0, help="HTTP timeout seconds (default: 30)")
    parser.add_argument("--max-retries", type=int, default=3, help="retries per image (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="do not write image files")
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip the SFTP pre-fetch of CSVs from the VPS",
    )
    args = parser.parse_args()

    arrsizes = [s.strip() for s in args.sizes.split(",") if s.strip()]
    if not arrsizes:
        sys.exit("--sizes is empty")

    arrunknown = [t for t in args.table if t not in BUILDERS]
    if arrunknown:
        sys.exit(f"unknown table(s): {', '.join(arrunknown)}")

    # Pull fresh CSVs from the VPS unless explicitly skipped or unconfigured.
    # SFTP_* takes precedence over SSH_* so users can override SSH_* defaults
    # with deployment-specific SFTP credentials without editing two places.
    strhost = (
        os.environ.get("SFTP_HOST", "").strip()
        or os.environ.get("SSH_HOST", "").strip()
    )
    if not args.no_fetch and strhost:
        try:
            lngfetched = f_fetch_csvs(
                pathlocal=Path(args.csv_dir),
                strhost=strhost,
                lngport=int(os.environ.get("SFTP_PORT") or os.environ.get("SSH_PORT") or "22"),
                struser=(
                    os.environ.get("SFTP_LOGIN", "").strip()
                    or os.environ.get("SSH_USER", "").strip()
                ),
                strkey=os.environ.get("SFTP_KEY") or os.environ.get("SSH_KEY") or None,
                strpassword=(
                    os.environ.get("SFTP_PASSWORD")
                    or os.environ.get("SSH_PASSWORD")
                    or None
                ),
                strremote_dir=os.environ.get("REMOTE_CSV_DIR", ""),
            )
            print(f"   {lngfetched} file(s) transferred")
        except Exception as exc:
            # Don't kill the run if the VPS is offline and we already have CSVs.
            if any(Path(args.csv_dir).glob("T_WC_TMDB_*.csv")):
                print(f"warning: SFTP fetch failed ({exc}); continuing with local CSVs")
            else:
                sys.exit(f"SFTP fetch failed and no local CSVs found: {exc}")
    elif not args.no_fetch:
        print(
            "note: neither SFTP_HOST nor SSH_HOST set in .env, "
            "skipping CSV fetch (use --no-fetch to silence)"
        )

    counters = f_download(
        pathcsv_dir=Path(args.csv_dir),
        pathnas=Path(args.nas_root),
        arrsizes=arrsizes,
        arrtables=args.table,
        lngworkers=args.workers,
        pathstate=Path(args.state),
        lngtimeout=args.timeout,
        lngmaxretries=args.max_retries,
        intdryrun=args.dry_run,
    )

    print("\nsummary:")
    for strstatus in (STATUS_DONE, STATUS_EXISTS, STATUS_404, STATUS_ERROR, "dry_run"):
        if strstatus in counters:
            print(f"  {strstatus:<14} {counters[strstatus]:>10,}")
    lngerrors = counters.get(STATUS_ERROR, 0)
    return 1 if lngerrors else 0


if __name__ == "__main__":
    raise SystemExit(main())
