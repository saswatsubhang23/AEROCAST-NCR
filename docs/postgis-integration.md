# PostgreSQL / PostGIS integration

PostGIS is the **serving and spatial copy** of the cleaned station history. SQLite (`api/data/history.sqlite`) remains the pipeline's
working store (ingest, clean, features, training). Nothing in training or inference reads PostGIS, so model results are unaffected.

## Local setup (Windows)

1. PostgreSQL 18 with the PostGIS bundle (Stack Builder) installed as a service on port 5432.
2. One-time role + database + extension: `api/scripts/setup_local_postgres.sql` (run as `postgres`; it takes the app password as a psql variable).
3. `api/.env`: `DATABASE_URL=postgresql+psycopg://aerocast:<password>@localhost:5432/aerocast`
4. From `api/`: `python -m alembic upgrade head` (0001 PostGIS, 0002 environmental schema, 0003 sync bookkeeping).

## Load data

```
python -m app.history sync-postgis --full   # first load: every cleaned observation (about 12.9 M rows, tens of minutes)
python -m app.history sync-postgis          # afterwards: newest stored hour minus 7 days, upserted by record_id
```

Run it after `python -m app.history clean`. Re-running is idempotent. Each run is recorded in `env_sync_run`.

### Mapping (one `clean_air` row -> one `env_record` row)

| env_record | from |
|---|---|
| `kind` | `observation` (clean_air holds measurements only) |
| `source` | `xkdr` if the chosen sensor id is a synthetic xKDR id (>= 9e9), else `openaq` |
| `value`, `unit` | `value_std`, µg/m³ (conversion and plausibility flags were applied by the clean step) |
| `valid_from` / `valid_to` | `period_from_utc` / `period_to_utc` |
| `retrieved_at` | `raw_air.fetched_at`; if no raw row matches the row is flagged `RETRIEVED_AT_UNKNOWN` and gets the sync time |
| `usable`, `quality_flags` | carried over; unusable rows are kept, never dropped |
| `record_id` | same SHA-1 identity as `EnvRecord.record_id` |
| `geom` | the station's point (EPSG:4326) |

Weather (`clean_weather`) and model outputs are **not** synced yet: they need model-cell geometry and a variable mapping decision
(`surface_pressure` has no canonical variable). The `exposure_cell` and `sensitive_site` tables stay empty until a population raster
and a facility list are loaded; nothing is invented to fill them.

## API (all return 503 `geo_unavailable` if PostgreSQL is down; the rest of the app is unaffected)

| endpoint | purpose |
|---|---|
| `GET /api/geo/status` | counts, series coverage, last sync |
| `GET /api/geo/stations/nearby?lat&lon&radius_km&variable&limit` | stations within a radius (geography distance, GiST/KNN), nearest first, with latest usable observation |
| `GET /api/geo/stations.geojson?variable` | all stations as GeoJSON with latest observation |
| `GET /api/geo/stations/{id}/series?variable&hours` | hourly usable observations |

Values are station measurements with source, period and flags. `latest` can be old: always check `period_to`.
The system-status page already probes PostgreSQL and the PostGIS version.
