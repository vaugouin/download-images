# AGENTS.md - Agent Guide for Download Images

Agent rules only. Overview, NAS layout, setup, both stages, Docker usage and
Windows notes: @README.md (canonical). Keep it aligned with any behaviour change.
Reference DDL in [doc/sql/](doc/sql/) (`TMDb-tables.sql`, `Wikipedia-tables.sql`)
is read-only unless the user asks for schema-doc edits; do not copy table
definitions here.

---

## Role in Agent BBB

Acquisition / asset stage of the `vaugouin` multi-repo pipeline (shared MariaDB
`T_WC_*`, ChromaDB). Mirrors every image of the `T_WC_TMDB_*_IMAGE` tables from
the TMDb CDN to the NAS; `tmdb-front` serves them and `image-captioning` reads
them (it copies this repo's NAS layout and SQLite state pattern). Sibling roster:
`%USERPROFILE%/Nestor/projets/t2s-backlog/topics/related-repositories.txt`.

Split by design: `export_image_tables.py` runs in Docker on the VPS (the only
file the image ships); `download_images.py` runs on the Windows PC, which sees
the NAS but not MariaDB. Do not merge them.

`off.sh` / `on.sh` toggle the cron launcher `tmdb-export.sh` through a `CRON_OFF`
flag file (see their header comments); `~/docker/off-all.sh` and `on-all.sh` call
them around evaluation campaigns and load tests.

---

## Code conventions

- **Hungarian notation** (legacy style): `str` strings, `lng` integers, `dbl`
  floats, `arr` lists, `int` boolean-like flags.
- Public entry points `f_*`, private helpers `_*`; Google-style docstrings on
  public functions. Broad try/except with console logging.

## SQL Object Naming Conventions

- Uppercase snake case (legacy TMDb genre columns `id`, `name` excepted).
  Prefixes: `T_WC_*` persistent, `T_WC_T2S_*` Text2SQL read model,
  `T_WC_TMDB_*`, `T_WC_WIKIDATA_*` (staging `STG_T_WC_WIKIDATA_*`),
  `T_WC_WIKIPEDIA_*`; join tables `T_WC_T2S_{PARENT}_{CHILD}`.
- PK `ID_{ENTITY}`, `ID_ROW` or a table-specific surrogate; FKs reuse the
  referenced PK name. Columns: `DAT_*` dates, `TIM_*` timestamps, `IS_*` or legacy
  `DELETED` flags, `DISPLAY_ORDER`, `*_COUNT`, `*_PATH`, `_FR` suffix / `LANG`,
  `*_NORM` / `*_KEY` for RapidFuzz, `POPULARITY` tie-breaker.
- Indexes: preserve the mixed legacy style (`KEY COLUMN_NAME`, `IDX_*`, `UK_*`,
  `FK_*`, `ft_*`).

## Encoding

Keep Markdown, JSON and logs UTF-8 (non-ASCII names); avoid tools that rewrite
files with mojibake.

---

**Last Updated**: 2026-10-31
**Current Version**: 1.0.8

## Backlog (Nestor second-brain)

Tasks `DOWNLOAD-IMAGES-NNN` (status, priority, quick wins) live in
`C:\Users\vaugo\Nestor\projets\t2s-backlog\repos\download-images.md`; dashboard
`...\t2s-backlog\index.md`. Consult before implementing. Local PC paths, not on
the VPS or cloud agents.
