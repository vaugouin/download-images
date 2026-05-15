"""Export every T_WC_TMDB_*_IMAGE table to a CSV file.

Runs on a host that can reach the MariaDB instance. Produces one CSV per
image table in CSV_DIR. The CSVs are then carried over to the Windows
machine for download_images.py to consume.

Filter applied: (DELETED IS NULL OR DELETED = 0) AND IMAGE_PATH IS NOT NULL
AND IMAGE_PATH <> ''.

Usage:
    python export_image_tables.py [--out PATH] [--table NAME ...]
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

import pymysql
import pymysql.cursors
from dotenv import load_dotenv
from tqdm import tqdm


# Per-table column projection. ID_ROW + FK columns + the image columns we
# need to construct URLs and target paths. Order here = column order in CSV.
TABLES: dict[str, list[str]] = {
    "T_WC_TMDB_MOVIE_IMAGE":      ["ID_ROW", "ID_MOVIE",                                  "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_SERIE_IMAGE":      ["ID_ROW", "ID_SERIE",                                  "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_SEASON_IMAGE":     ["ID_ROW", "ID_SERIE", "ID_SEASON",                     "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_EPISODE_IMAGE":    ["ID_ROW", "ID_SERIE", "ID_SEASON", "ID_EPISODE",       "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_PERSON_IMAGE":     ["ID_ROW", "ID_PERSON",                                 "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_COLLECTION_IMAGE": ["ID_ROW", "ID_COLLECTION",                             "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_COMPANY_IMAGE":    ["ID_ROW", "ID_COMPANY",                                "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
    "T_WC_TMDB_NETWORK_IMAGE":    ["ID_ROW", "ID_NETWORK",                                "IMAGE_PATH", "TYPE_IMAGE", "LANG"],
}


def _connect() -> pymysql.connections.Connection:
    """Open a MariaDB connection from environment variables."""
    return pymysql.connect(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "3306")),
        user=os.environ["DB_USER"],
        password=os.environ["DB_PASSWORD"],
        database=os.environ["DB_NAME"],
        charset="utf8mb4",
    )


def _count_rows(conn: pymysql.connections.Connection, strtable: str) -> int:
    """Return the number of rows that will be exported for `strtable`."""
    strsql = (
        f"SELECT COUNT(*) FROM `{strtable}` "
        "WHERE (DELETED IS NULL OR DELETED = 0) "
        "AND IMAGE_PATH IS NOT NULL AND IMAGE_PATH <> ''"
    )
    with conn.cursor() as cur:
        cur.execute(strsql)
        (lngcount,) = cur.fetchone()
    return int(lngcount)


def _export_table(conn: pymysql.connections.Connection, strtable: str, pathout: Path) -> int:
    """Stream one table into a CSV file using a server-side cursor.

    Args:
        conn: Open MariaDB connection.
        strtable: Source table name.
        pathout: Output CSV path.

    Returns:
        Number of rows written.
    """
    arrcols = TABLES[strtable]
    strcols = ", ".join(f"`{c}`" for c in arrcols)
    strsql = (
        f"SELECT {strcols} FROM `{strtable}` "
        "WHERE (DELETED IS NULL OR DELETED = 0) "
        "AND IMAGE_PATH IS NOT NULL AND IMAGE_PATH <> ''"
    )

    lngtotal = _count_rows(conn, strtable)
    if lngtotal == 0:
        print(f"  {strtable}: 0 rows, skipping")
        return 0

    lngwritten = 0
    # SSCursor streams rows without buffering the whole result set in memory.
    with conn.cursor(pymysql.cursors.SSCursor) as cur:
        cur.execute(strsql)
        with pathout.open("w", encoding="utf-8", newline="") as fp:
            writer = csv.writer(fp, quoting=csv.QUOTE_MINIMAL)
            writer.writerow(arrcols)
            with tqdm(total=lngtotal, unit="row", desc=strtable, leave=False) as bar:
                for row in cur:
                    writer.writerow(row)
                    lngwritten += 1
                    if lngwritten % 1000 == 0:
                        bar.update(1000)
                bar.update(lngwritten - (lngwritten // 1000) * 1000)
    return lngwritten


def f_export(pathout: Path, arrtables: list[str]) -> int:
    """Export the requested image tables to CSV.

    Args:
        pathout: Output directory. Created if it doesn't exist.
        arrtables: List of table names to export. Empty = all of TABLES.

    Returns:
        Total rows written across all tables.
    """
    pathout.mkdir(parents=True, exist_ok=True)
    if not arrtables:
        arrtables = list(TABLES.keys())

    arrunknown = [t for t in arrtables if t not in TABLES]
    if arrunknown:
        sys.exit(f"unknown table(s): {', '.join(arrunknown)}")

    lngtotal = 0
    conn = _connect()
    try:
        for strtable in arrtables:
            pathcsv = pathout / f"{strtable}.csv"
            print(f"-> {strtable} -> {pathcsv}")
            lngrows = _export_table(conn, strtable, pathcsv)
            print(f"   {lngrows:,} rows")
            lngtotal += lngrows
    finally:
        conn.close()
    return lngtotal


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=os.environ.get("CSV_DIR", "./csv"),
        help="output directory for CSV files (default: $CSV_DIR or ./csv)",
    )
    parser.add_argument(
        "--table",
        action="append",
        default=[],
        help="restrict to one table; repeat for multiple. Default: all 8 tables.",
    )
    args = parser.parse_args()

    lngtotal = f_export(Path(args.out), args.table)
    print(f"done: {lngtotal:,} rows exported")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
