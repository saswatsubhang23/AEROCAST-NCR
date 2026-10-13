# Phase 1 artefacts (2026-10-11)

Written reports: `docs/articles/` (also served in the application at /report).

| File | What it is | How it was produced |
|---|---|---|
| `source-audit.json` | Schemas, coverage, units, rate-limit headers, freshness and licences of Open-Meteo, CAMS, OpenAQ and xKDR | `python -m app.envdata.audit` |
| `xkdr-alignment.json` | Lag-by-lag comparison of the xKDR and OpenAQ series for the one station both serve | `python -m app.envdata.crosscheck_xkdr` |
| `xkdr-utc-repair.json` | What the timestamp repair did to the store | `python -m app.history.repair_xkdr_utc --apply` |
| `cams-vs-stations.json` | CAMS against the stations and against persistence and climatology | `python -m app.envdata.source_eval` |
| `schema.postgis.sql` | The PostgreSQL/PostGIS schema (also Alembic revision 0002) | `python -m app.envdata.ddl` |

## Full report export
`GET /api/reports/export/html` and `/api/reports/export/pdf` (query: `location_id`, `hours`, `pollutant`, `articles`) build one document
of every figure, table and written report for a place, from live data. `sample-full-report.html` and `.pdf` here were produced by those
endpoints on 2026-10-11. In the app: Assistant → Generated reports → Full report. Code: `api/app/reports/{export,doc,charts,exporters}.py`.
