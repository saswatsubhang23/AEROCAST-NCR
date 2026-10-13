# Engineering report: defects found, fixes, setup and what remains

> What was wrong in the data pipeline and the web application, in priority order, with the root cause and the evidence for each fix; then how to set the system up, migrate the database and re-run every check. Nothing is marked as passing that was not run.

## Inventory

The backend is FastAPI on Python 3.13 (the project's pins also work on 3.14), with SQLite for the historical store (15.5 GB, 68 stations), Chroma for the knowledge base and Alembic scaffolding for PostgreSQL/PostGIS. The frontend is Next.js 16.4.0 with Turbopack, React 19.3, MapLibre 6.13, deck.gl 9.4, three 0.185 with React Three Fiber 9.8, and ECharts 6. The build uses Next's Cache Components and partial prefetching; every page is a client component, and the production build prerenders all routes statically. PostgreSQL and PostGIS are not configured on this machine (the status page reports both unreachable, as it should), so the new schema is delivered as a migration and a SQL file rather than applied.

## Defects, in priority order

| # | Severity | Where | Root cause | Fix | Evidence |
|---|---|---|---|---|---|
| 1 | High (data correctness) | `api/app/history/ingest_xkdr.py` | xKDR's US-Embassy rows were read as Indian time but are UTC; the series sat 5.5 to 6 hours off the same station's OpenAQ data, and was merged into station 8118, the one the live forecast was served from | Sources listed in `UTC_NAIVE_SOURCES` are read as UTC; the station was re-ingested, re-cleaned and its features rebuilt by `app/history/repair_xkdr_utc.py`, with a backup | Series identical at +6 h (r 1.000, MAE 0.0, 1,306 h); daily minimum 11:00 → 17:00; test `test_us_embassy_timestamps_are_read_as_utc_not_ist` |
| 2 | High (data correctness) | `api/app/services/data_availability.py` | The coverage catalogue asserted that NO, NOx and station weather were unavailable; the audit found OpenAQ serves them | Catalogue corrected and a distinct "obtainable" status added | `docs/phase1/source-audit.json`; `tests/test_data_availability.py` |
| 3 | Medium (documentation of a limit) | `api/app/services/cams_fields.py` and its callers | CAMS resolution was stated as about 11 km; measured it is 0.4° (44 km), so the live field is a few blocks | Text corrected everywhere it appeared | Step probe in the audit: 3 distinct values over 1.1° of longitude |
| 4 | Medium (frontend) | `web/src/components/twin/scene3d/Scene3D.tsx` | drei's `<Html>` mounts a separate React root per label and unmounts it synchronously during React 19's commit; under StrictMode this raised `removeChild` (121 times) and `createRoot` (88 times) errors on every mount of the 3D view | Labels are now canvas-texture sprites (`TextSprite` in `ground.tsx`); no DOM roots exist inside the WebGL tree | Dev log counts before; 0 errors captured when opening 3D after |
| 5 | Medium (frontend) | `web/src/components/charts/EChart.tsx` | The chart was initialised inside hidden tabs and collapsed panels while their width was 0 ("Can't get DOM width or height", four times) | The chart is created when its container first has a size | Warnings absent after change |
| 6 | Medium (accuracy) | `api/app/services/weather_fields.py` | The weather lattice (8 × 9) under-sampled the model's native cells (0.07° × 0.10°) | Lattice raised to 14 × 11, matching the native grid | Probe at 0.02° spacing |
| 7 | Medium (modelling) | `api/app/twin/coupled.py` | The one-sided dilution rule and, later, the ventilation rule lowered skill in a 25-window hindcast | Both are opt-in; the evidence is shown in the interface | `docs/coupled-evaluation.md` |
| 8 | Low (security) | `api/app/api/training.py` | State-changing training endpoints could be reached by a cross-site form | Require header `X-AEROCAST-Action: training` | `test_state_changing_training_calls_need_the_action_header` |
| 9 | Low (performance) | `api/app/api/twin.py` | Early warning recomputed 40 station forecasts (about a minute) on every request | Per-station forecasts cached by pollutant, origin, stations and active model | `test_early_warning_reuses_station_forecasts...` |
| 10 | Low (interface) | `web/src/components/map/useBaseMap.ts` | One dark basemap, no imagery or terrain; a flat 3D ground | Voyager, Dark, Satellite and Relief; real terrain and imagery in 3D | `docs/terrain-and-imagery.md` |

### Not defects, but worth knowing

The browser console in development mode still shows `THREE.Clock: This module has been deprecated`, which comes from inside @react-three/fiber 9.8 and is harmless; it should disappear with an update of that library. Next.js prints "Route … is rendering with server caches disabled" in development, an informational message of the Cache Components feature. The OpenAQ feed's lag and the CPCB archive's end in September 2025 are properties of the sources, not of the code.

## Setup

**Backend** (from `api`):

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-ml.txt
copy .env.example .env
.venv\Scripts\python.exe -m uvicorn app.main:app --port 8000
```

`api/.env` keys: `AQ_API_KEY` (OpenAQ), `INDIA_AQI_API_KEY` (xKDR), `OLLAMA_MODEL`, `ML_LOCAL_MODEL_DIR=./data/models`, `CORS_ORIGINS`, and `DATABASE_URL` only when PostgreSQL is used. **Frontend** (from `web`): `npm install`, then `npm run dev`; `web/.env.local` takes `NEXT_PUBLIC_CARTO_API_KEY` (public by design; restrict it to your domains).

## Database: schema and migration

The normalised schema is in `docs/phase1/schema.postgis.sql` and in Alembic revision `0002_environmental_schema` (after `0001`, which enables PostGIS). It has: `env_source` (provider, licence, attribution, native resolution, cadence); `env_station` and `env_cell` (point and polygon geometries with GiST indexes); `env_record` (one row per value, with `kind` constrained to observation, forecast, analysis, interpolation or simulation, a CHECK that forecasts carry an issue time and observations do not, and a CHECK that a record without a value is not usable); and the two exposure layers `exposure_cell` and `sensitive_site`, which are empty until a population raster and a facility list are loaded.

To apply it on a PostgreSQL server with PostGIS available: set `DATABASE_URL` in `api/.env`, then run `.venv\Scripts\python.exe -m alembic upgrade head` from `api`. The role needs permission to create the extension or PostGIS must already be installed. Rollback is `alembic downgrade 0001`. The development store keeps the same typed record in SQLite (`app/envdata/schema.py`, `EnvStore`), so code written against it runs unchanged against the PostgreSQL table.

## Re-running every check

```
# backend: unit and integration tests (external services are mocked)
cd api && .venv\Scripts\python.exe -m pytest -q
# source audit and cross-checks against the live providers (a few dozen requests)
.venv\Scripts\python.exe -m app.envdata.audit
.venv\Scripts\python.exe -m app.envdata.crosscheck_xkdr
.venv\Scripts\python.exe -m app.envdata.source_eval
# the hindcast of the coupled model (about 25 minutes, rate-limited by the weather API)
.venv\Scripts\python.exe -m app.twin.coupled_eval --from 2026-08-04T00:00 --to 2026-10-04T00:00 --step-hours 60 --hours 12
# frontend
cd web && npx tsc --noEmit && npx eslint src && npx vitest run && npm run build
```

Results of the run described in this report: backend **794 passed**; frontend **163 passed** in 19 files; `tsc` and `eslint` clean; the production build compiled and prerendered all 15 routes; `npm audit --omit=dev` found 0 vulnerabilities in production dependencies (development tooling was not audited). One backend test failed once in a heavily loaded full run and passed in every later run, alone and in the full suite; it is recorded as intermittent rather than explained.

## Remaining limitations

The observation feed is days old, so the trained model refuses to forecast for the present and every "now" map is a replay or a model. The trained model was fitted before the timestamp repair and should be retrained (a user action). Raw CAMS is coarse (44 km) and, over Delhi stations, a worse predictor than yesterday's value. The coupled model has no emissions; its couplings did not reliably improve on plain transport and nothing beat persistence. The 3D concentration colouring inside the mixed layer assumes a uniform concentration with height, because there are no vertical measurements. Station licences in OpenAQ are mostly unstated, so redistribution terms are unknown. NO, NOx and station weather are available but not yet ingested. Population and sensitive-site layers are not loaded, so exposure is not computed. PostgreSQL and PostGIS are not configured here, so the migration is untested against a live server; its DDL is covered only by string-level tests. The model candidates marked as not evaluated in the model report were not run.
