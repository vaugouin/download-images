# download-images

Bulk-download TMDb images from the `T_WC_TMDB_*_IMAGE` tables onto a NAS.

Two-stage pipeline because the Windows machine that talks to the NAS cannot
reach the MariaDB host:

1. `export_image_tables.py` — runs on a DB-reachable host. Dumps each
   `T_WC_TMDB_*_IMAGE` table to a CSV under `CSV_DIR`.
2. `download_images.py` — runs on the Windows machine. Reads the CSVs and
   downloads every image to `NAS_ROOT`, skipping anything already on disk
   or already recorded as done/404 in the SQLite state DB.

## Folder layout on the NAS

```
<NAS_ROOT>/
  movie/<id%1000>/<id_movie>/<size>/<basename.ext>
  serie/<id%1000>/<id_serie>/<size>/<basename.ext>
  serie/<id%1000>/<id_serie>/seasons/<id_season>/<size>/<basename.ext>
  serie/<id%1000>/<id_serie>/episodes/<id_episode>/<size>/<basename.ext>
  person/<id%1000>/<id_person>/<size>/<basename.ext>
  collection/<id%1000>/<id_collection>/<size>/<basename.ext>
  company/<id%1000>/<id_company>/<size>/<basename.ext>
  network/<id%1000>/<id_network>/<size>/<basename.ext>
```

`<id%1000>` is the entity ID modulo 1000, zero-padded to 3 digits. This caps
the per-shard directory at ~1k folders so Windows Explorer stays responsive
even at 1M+ movies.

`<size>` is one of TMDb's documented size keywords (`original`, `w780`,
`w342`, `w185`, …). Each size becomes a sibling folder, so you can add a
new size later without touching anything already downloaded.

`<basename.ext>` is the trailing component of `IMAGE_PATH` from the
database, e.g. `Adw6Lq9FiC9zjYEpOqfq03ituwp.jpg`.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
notepad .env   # fill in DB_* + NAS_ROOT
```

The exact same `.env` works for both scripts; each one only reads the keys
it needs.

## Stage 1 — export (on the DB host)

Filter applied to every table:
`WHERE (DELETED IS NULL OR DELETED = 0) AND IMAGE_PATH IS NOT NULL AND IMAGE_PATH <> ''`

Output: `csv/T_WC_TMDB_*_IMAGE.csv`. The downloader on the Windows machine
pulls these CSVs over SFTP automatically at startup (see Stage 2). If you
prefer to copy them manually instead, `--no-fetch` skips the SFTP step.

### Option A — Docker (intended for the VPS)

```bash
docker build -t tmdb-export .

# Full export, all 8 tables:
docker run --rm \
  --env-file .env \
  -v "$(pwd)/csv:/csv" \
  tmdb-export

# Restrict to specific tables (extra args are forwarded to the script):
docker run --rm --env-file .env -v "$(pwd)/csv:/csv" tmdb-export \
  --table T_WC_TMDB_MOVIE_IMAGE --table T_WC_TMDB_PERSON_IMAGE
```

**Reaching the DB from inside the container:**

- If MariaDB is reachable on an external host/IP, just set `DB_HOST` in
  `.env` to that hostname. Nothing else to do.
- If MariaDB runs on the same VPS bound to `127.0.0.1`, add
  `--add-host=host.docker.internal:host-gateway` to `docker run` and set
  `DB_HOST=host.docker.internal` in `.env`. (On Linux only;
  `host.docker.internal` resolves automatically on Docker Desktop.)
- If MariaDB runs in another container on the same VPS, attach to that
  network with `--network <name>` and set `DB_HOST=<service-name>`.

### Option B — bare Python

```bash
pip install -r requirements-export.txt
python export_image_tables.py
# or restrict to specific tables:
python export_image_tables.py --table T_WC_TMDB_MOVIE_IMAGE --table T_WC_TMDB_PERSON_IMAGE
```

## Stage 2 — download (on the Windows machine)

At startup the downloader pulls every `T_WC_TMDB_*.csv` from the VPS into
`CSV_DIR` over SFTP, skipping files whose local mtime+size already match
the remote. So once `.env` has the `SSH_*` and `REMOTE_CSV_DIR` keys
filled in, a fresh run is one command end-to-end:

```powershell
# default: SFTP CSV refresh, then all CSVs, "original" size only, 8 workers
python download_images.py

# multiple sizes:
python download_images.py --sizes original,w780,w342,w185

# resume after Ctrl-C: just run the same command again
python download_images.py

# one table only:
python download_images.py --table T_WC_TMDB_MOVIE_IMAGE

# dry run (no files written, but state DB is updated for already-present files):
python download_images.py --dry-run

# skip the SFTP refresh and run against whatever CSVs are already local:
python download_images.py --no-fetch
```

**Authentication for the SFTP fetch.** `SSH_KEY` (private key path) takes
precedence. If it's empty, paramiko falls back to the SSH agent and the
default keys in `~/.ssh/`. `SSH_PASSWORD` is the last resort. If `SSH_HOST`
is empty, the fetch is silently skipped and the run proceeds with whatever
CSVs are present locally.

The script is safe to interrupt. Re-running picks up where it left off:

- `done` / `file_exists` / `http_404` rows are skipped instantly.
- `error` rows (transient network/IO failures) are retried.

Errors are also logged in `state.sqlite`; inspect with:

```powershell
sqlite3 state.sqlite "SELECT table_name, COUNT(*) FROM image_state GROUP BY table_name, status"
sqlite3 state.sqlite "SELECT * FROM image_state WHERE status='error' LIMIT 20"
```

## Windows notes

- **Long paths**: target paths stay well under 260 chars in normal use. If
  you hit `OSError: [WinError 3]`, enable long-path support
  (`Computer\HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem\LongPathsEnabled = 1`)
  and restart.
- **SMB write speed dominates**: 8 workers is usually right. Bump
  `--workers` if your NAS handles concurrent writes well; lower if SMB
  starts dropping connections.
- **Mapped drives in elevated shells**: drives mapped in a normal user
  session are not visible in an Administrator PowerShell. Use the same
  privilege level for the mapping and the download.
