#!/bin/bash
# Switch tmdb-export.sh back on: removes the flag file CRON_OFF that off.sh wrote.
cd "$(dirname "$(readlink -f "$0")")" || exit 1
# A launcher renamed by the old off.sh (<name>-off.sh, before 2026-10-25) is put back,
# or dropped when git has already restored the tracked one.
[ -f tmdb-export-off.sh ] && { [ -f tmdb-export.sh ] && rm -f tmdb-export-off.sh || mv tmdb-export-off.sh tmdb-export.sh; }
rm -f CRON_OFF && echo "download-images: on (CRON_OFF removed)"
