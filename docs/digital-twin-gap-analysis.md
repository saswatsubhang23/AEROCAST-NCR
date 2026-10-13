# Digital-twin gap analysis

Audit date: 2026-10-10. Scope: the whole AEROCAST NCR repository against the planned additions: model training, spatial
forecasting, map-based pollutant transport, uncertainty analysis and environmental-health intelligence.

**This audit changed no application files.** The only file written is this document. Nothing was installed or migrated.

## 1. Method and evidence legend

Every finding carries one tag:

* **[L]** observed live during this audit (a real call to the running API, OpenAQ or Open-Meteo)
* **[C]** read directly from the code, with file and line
* **[T]** covered by an existing automated test (tests use mocks, so they prove logic, not provider behaviour)
* **[U]** not verified; stated so that nobody assumes it works

Live calls made: about 10 read-only requests to OpenAQ with the project's own key (locations, one station's sensors, three
hourly-history windows), 2 to Open-Meteo (archive and `past_days`), and GETs to the local API
(`/api/air/stations`, `/api/system/status`, `/api/kb/*`). The snapshot was taken on 2026-10-09 around 19:40 UTC; provider
state changes, so counts are a snapshot, not a constant. No metric below comes from anywhere else.

## 2. Status matrix

| Area | Status | Basis |
|---|---|---|
| Weather ingestion (Open-Meteo forecast API, point + 4x4 grid + recent) | Implemented, **verified live** | [L][C][T] `services/weather.py` |
| Air-quality ingestion (OpenAQ v3: inventory, latest, hourly history) | Implemented; **live data is largely stale; sensor selection defect** (D1, D2) | [L][C] |
| AQI (CPCB method) | Implemented; rarely computable on live data | [C][T]; [L] only 1 of 69 stations has a reading ≤3 h old |
| Persistent time-series store | **Not implemented**. Everything is an in-process TTL cache | [C] `services/air_quality.py:104,251`, `services/weather.py:190` |
| PostgreSQL / PostGIS | **Configured but unreachable and unused by any feature** | [L] status: `database unavailable`, `postgis unavailable`; [C] no ORM models, no tables; one migration only enables the extension |
| Map (MapLibre + deck.gl) | Implemented as point/icon/text layers only | [C] section 6 |
| ML forecast contract + provider client | Implemented as an interface; **single-location point forecast only**; never run against a real model | [C][T]; [L] `forecast_provider: not_configured` |
| ML forecasting, training, spatial or transport models | **Absent by design** | [C] no ML library in `requirements.txt` or the venv |
| Ollama chat + tools | Implemented; **configured model not installed** | [L] `llm_model degraded: qwen3:8b-q4_K_M is not installed`; only `llama3.2` was used in testing |
| RAG knowledge base | Implemented; embeddings work live; **0 documents indexed** | [L] `documents_total: 0`; [T] 73 KB tests with a fake embedder |
| Reports (JSON, PDF, Markdown, LLM summary) | Implemented, verified live on real data | [L][T] |
| Alerts | Implemented, verified live | [L][T] |
| Documentation | Present; matches the code at audit time | [C] `docs/*.md` |
| Tests | 410 pass (last run before this audit); backend mocks all providers | [T]; not re-run during this audit |
| Version control | **None.** `D:\python weather forecasting` is not a git repository | [L] `git rev-parse` fails |

## 3. Air-quality data: what actually exists

### 3.1 Inventory and spatial coverage [L]

* OpenAQ returns **108** monitor locations in the app's bounding box (76.7, 28.1, 77.8, 29.05). **69** have data in the last 7 days; the app drops the other 39 (`aq_active_days = 7`). Of the 69: 67 are CPCB-sourced (`CPCB` 67, `AirNow` 1, `N/A` 1), owned by DPCC (24), UPPCB (13), HSPCB (12), IMD (9), CPCB (6), RSPCB (2).
* Station coordinates: all 108 have coordinates; none are 0,0; no two of the 69 share identical coordinates. Spacing between nearest neighbours: median 3.2 km, max 25.4 km; the closest pair, `Pusa, Delhi - DPCC` and `Pusa, Delhi - IMD`, is about 0 m apart (two owners at one site).
* Stations within 20 km of each city centre: Delhi 42, Noida 27, Faridabad 16, Gurugram 13, Ghaziabad 13.
* Coverage skews to Delhi. 8 stations (Hapur, Meerut x2, Dharuhera, Sonipat, Bhiwadi, and others) lie **outside** the weather grid box (76.8-77.7, 28.2-28.95), so no grid cell represents them.
* Station metadata gives location, provider, owner, licence (often `null`), `isMonitor`. **No** site type (traffic, industrial, residential), elevation or inlet height is retained, which matters for spatial modelling. [C] `Record` in `services/air_quality.py`. [U] whether OpenAQ exposes any of that for these stations.

### 3.2 Freshness [L]

* Only **1 of 69** stations (`New Delhi`, AirNow) has any reading ≤3 h old. The 225 "latest" readings have median age **54.2 h**, minimum 1.2 h, maximum 100.2 h. Of all 108 locations, 67 last reported 2 days ago, 1 reported today, 37 more than 30 days ago.
* One snapshot cannot say whether the CPCB lag is permanent. [U] the typical publication delay.

### 3.3 Historical depth [L]

* Location records show `datetimeFirst` as early as **2016-01-30**; 94 of 108 started on or before 2020 and 11 in 2025 or later.
* One station (Alipur, location 6932) was probed in detail. It has an **active sensor set** (e.g. PM2.5 sensor 12235698, first 2025-02-18, last 2026-10-07) and a **legacy sensor set** (e.g. PM2.5 sensor 19935, 2018-12-15 to 2022-10-31).
* `/v3/sensors/12235698/hours` returned 168/168 rows for 2025-03-01 to 03-08, 166 rows for 2025-10-01 to 10-08, and 235 rows for 2026-09-25 to 10-08 (about 13 days; this window ends at the stale edge). Meta `found` equals the rows returned; page limit 1000.
* **Only this one sensor was probed.** Gap structure, validation state and depth for the other ~400 sensors are unmeasured. [U]
* Rate limit observed: `X-Ratelimit-Limit: 60` per minute [L]. The app's own notes also cite 2,000 requests/hour [C] `LIMITATIONS`, not verified here.

### 3.4 Units [L][C]

Units are per sensor and **mixed within the same pollutant across stations**. Across the 108 locations: PM2.5 and PM10 are µg/m³; NO₂ is ppb on 69 sensors and µg/m³ on 95; SO₂ ppb 60 / µg/m³ 81; CO ppb 68 / µg/m³ 90; O₃ µg/m³ 158 / ppm 1. Of the sensors the app currently selects: NO₂ ppb 40 / µg/m³ 28; SO₂ ppb 34 / µg/m³ 25; CO ppb 35 / µg/m³ 33. The app deliberately converts nothing (`ASSUMPTIONS` in `services/aqi.py`); the map hides stations whose unit differs from the majority (`commonUnit`, `components/air/StationMapPanel.tsx`). Any model or spatial surface needs an explicit, documented normalisation step first.

### 3.5 Co-located meteorology [L]

59 of 108 OpenAQ locations expose their own **wind speed, wind direction, temperature and relative humidity** sensors (Alipur's go back to 2025-10-10, wind speed ends 2026-08-06). The app counts these as `other_parameters` and discards them (`services/air_quality.py:_parse_locations`). They are the only ground-truth wind source found in the project's data.

### 3.6 Defects found

* **D1 (high): sensor selection is arbitrary.** `sensors.setdefault(name, ...)` takes whichever sensor OpenAQ lists first per pollutant ([C] `services/air_quality.py:153-158`). The location listing carries only `id`, `name` and `parameter` per sensor, with no first/last dates [L], so active and legacy sensors cannot be told apart. 58 of 108 locations list more than one sensor for a supported pollutant [L]. Evidence of harm: for the 69 stations, stations listing a pollutant versus having a current reading are CO 68/39, NO₂ 68/40, O₃ 68/35, PM10 68/38, PM2.5 69/43, SO₂ 59/30. Alipur lists all six pollutants as µg/m³, but its active gas sensors are ppb, so for CO, NO₂ and SO₂ the app is evidently bound to the 2018-2022 sensors. This was proven for Alipur only; the same mechanism is the likely cause elsewhere but is **not verified per station**.
* **D2 (medium): short history windows only.** History is limited to 168 h per request and a single un-paginated page of 1000 rows ([C] `integrations/openaq.py:hours`, `api/air.py:48`). Nothing is stored, so no depth beyond a week ever accumulates inside the app.
* **D3 (low): two co-owned sites at one point** (Pusa DPCC/IMD) are shown as separate stations. Not a bug, but a duplicate-handling decision for any spatial model.

## 4. Weather data

* Source: Open-Meteo **forecast** endpoint with `past_days` (up to 92 verified: 2,232 hourly rows returned [L]) and `forecast_days=4`; no key ([C] `integrations/openmeteo.py`, `services/weather.py`). Values are model analysis for a grid cell, not station observations.
* The **archive** endpoint (`archive-api.open-meteo.com`) answered keylessly with temperature, wind speed, wind direction, surface pressure and **boundary layer height**, 48 rows and no nulls for the one day tested [L]. The app does not use it. Archive depth beyond that test was not probed. [U]
* Variables in use: temperature, humidity, dew point, wind speed (km/h) and direction, precipitation, surface pressure, cloud cover, boundary layer height; pressure-level temperature and geopotential at 1000/925/850/700 hPa for the profile ([C] `VARIABLES`, `PROFILE_*`). No wind components, no pressure-level winds, no radiation or visibility.
* Spatial resolution: a **4 x 4 point grid** over (76.8, 28.2, 77.7, 28.95), about 29 km east-west by 28 km north-south between points, **16 cells** ([C] `NCR_BBOX`, `grid_points`; [L] spacing computed). This cannot resolve urban-scale transport.
* Everything is cached in process for 15 min (`weather_cache_ttl_s`); nothing is stored.
* Licence: Open-Meteo's free tier is non-commercial ([C] `core/config.py`).

## 5. Persistence and database

* `database_url` is not set in `api/.env`; the app uses the placeholder default `postgresql+psycopg://aerocast:change-me@localhost:5432/aerocast` ([C] `core/config.py:19`; `.env` keys: `ENVIRONMENT`, `LOG_LEVEL`, `AQ_API_KEY`, `CORS_ORIGINS`). Status confirms the database and PostGIS are **unavailable** [L]. The user planned PostgreSQL on another machine; it is not connected. **PostgreSQL/PostGIS must be treated as unverified.**
* There are **no ORM models, tables or time-series schema.** `migrations/versions/0001_enable_postgis.py` only runs `CREATE EXTENSION postgis` ([C]). `GeoAlchemy2` is installed in the venv but is neither imported nor listed in `requirements.txt`. [C]
* Local state today: `api/data/alerts.sqlite` (alert rules), `api/data/kb/registry.sqlite` and the Chroma folder (knowledge base, currently empty of documents [L]). SQLite is the established fallback pattern ([C] `alerts/store.py`, `kb/registry.py`).
* No ML or geospatial libraries are installed: no pandas, scipy, scikit-learn, PyTorch, shapely, pyproj, xarray. `numpy 2.5.3` and `onnxruntime` are present only as Chroma dependencies. [L] pip list

## 6. Map capabilities [C]

* `components/map/useBaseMap.ts`: MapLibre map with a deck.gl `MapboxOverlay` (non-interleaved), bounds over Delhi-NCR, CARTO dark-matter basemap fetched from the public CDN with a blank-style fallback if it fails.
* `components/weather/WeatherMapPanel.tsx` (255 lines): `ScatterplotLayer` (grid-cell values), `IconLayer` (wind arrows rotated from `wind_direction_10m`), `TextLayer` and city markers; one variable at a time, colour bins fixed over the whole loaded window; driven by the shared 72 h timeline index.
* `components/air/StationMapPanel.tsx` (154 lines): `ScatterplotLayer` for stations (valued, other-unit, selected) and `TextLayer`; shows the **latest** value only; no time dimension.
* **Absent:** interpolated or heat-map surfaces, polygons/GeoJSON, tile or raster layers, animation of pollutants over time, trajectories or particle layers, uncertainty rendering, layer-selection state shared across pages, any map tests (there are none; only `lib/*` is unit-tested).
* Verification limit: map and chart canvases returned black screenshots in the browser pane, so the visual rendering was never inspected, only DOM/network. [U]

## 7. ML forecast contract [C][T]

Files: `api/app/forecast/contract.py`, `provider.py`, `api/app/api/forecast.py`, `docs/ml-forecast-contract.schema.json`, `docs/ml-forecast-interface.md`.

What it supports: one location (lat/lon), `issued_at`, `horizon_hours` 1-72, up to six pollutants, a per-pollutant hourly series with optional prediction intervals (`level`, `lower`, `upper`), and provenance (`provider`, `model_name`, `generated_at`, `input_data`, `training_data`).

What it cannot express, which the planned work needs:

* **spatial output** (a grid, raster or station set), **transport** (wind field, trajectories), **scenarios**, **ensemble members or quantiles beyond intervals**, **calibration or skill metrics**, **health outputs**;
* a **training/evaluation** surface at all (datasets, model registry, backtests);
* the request carries **no inputs**, so providers must source their own data. Today the only source of historical observations they could reach is OpenAQ directly, because AEROCAST stores none.
* The contract was only ever exercised against a mock transport and one throwaway local fixture. **It has never met a real model.** [U]

Behavioural coupling to remember: `assistant/guards.py:asks_for_pollution_forecast` and the `orchestrator.py:89` refusal are **unconditional**; they refuse pollution forecasts even when a provider is configured. `components/air/ForecastPanel.tsx` is fixed at PM2.5/24 h/the selected city. `reports/builder.py:_build_forecast` requests 24 h for one pollutant.

## 8. Ollama, RAG, reports, alerts

* **Ollama** [L][C]: reachable at `localhost:11434`; `nomic-embed-text` installed; **`qwen3:8b-q4_K_M` not installed**. Machine is CPU-only; the `llama3.2` stand-in took 24-44 s for a report summary and 141 s for a chat report (cold OpenAQ cache). Tool selection with the intended model is unmeasured. [U]
* **RAG** [L][T]: embedding service up; 0 documents indexed; `kb_min_score` 0.62 was calibrated on a small hand test. No corpus of health or science documents exists in the app. Retrieval quality on a real corpus is unmeasured. [U]
* **Reports** [L][T]: built from real services, with limitations and sources. 143 s cold build, 0.3 s warm. They contain no spatial or model content; the forecast section is the only hook.
* **Alerts** [L][T]: rules on latest observed values; given D1 and section 3.2, many stations return `stale` or `no data`.

## 9. What to reuse (and where it plugs in)

| Planned capability | Reuse | New work needed |
|---|---|---|
| Historical store / ingestion | `integrations/openaq.py` (rate-limited client, retries), `integrations/http.py`, `services/air_quality.py` (`_parse_locations`, `_hourly`, hour-ending alignment `_floor_hour`), `integrations/openmeteo.py`, `services/weather.py` (`_params`, normalisation and plausibility ranges `VARIABLES`), `core/places.py`, `core/time.py`, the SQLite store pattern in `alerts/store.py` | storage schema, backfill job, pagination, sensor-selection fix, unit normalisation, archive-API client, provenance per row |
| Model training | `reports/analysis.py` (stats), `services/indicators.py`, `forecast/contract.py` (output shape), `forecast/provider.py` (`ForecastProvider` protocol) | ML libraries (none installed), dataset builder, backtest harness, model registry, evaluation metrics |
| Spatial forecasting | `core/places.py:distance_km`, `STATION_RADIUS_KM`, `services/weather.py:grid()` | gridded weather inputs at finer resolution, interpolation/graph model, spatial contract, station-network handling (D1, 8 stations outside the weather box) |
| Pollutant transport on the map | `components/map/useBaseMap.ts`, `WeatherMapPanel.tsx` wind `IconLayer`, `lib/weather/{scales,wind,context}`, shared timeline (`components/weather/Timeline.tsx`) | gridded wind field (only 10 m wind on 16 points exists), co-located station wind (3.5), transport model, deck.gl layers for surfaces/trajectories, time animation |
| Uncertainty analysis | `forecast/contract.py:PredictionInterval`, `ReportView` tables | ensembles or quantile outputs, calibration metrics, map/chart uncertainty rendering, contract extension |
| Environmental-health intelligence | `kb/*` (ingestion, retrieval, citations), `assistant/tools.py:search_knowledge_base`, `reports/builder.py:_build_references`, `assistant/guards.py` (grounding) | curated health/guidance corpus, an exposure-metric definition, a non-medical-advice policy, report sections; no health data exists in the app |
| Serving results | `api/forecast.py`, `reports/*`, `alerts/*` (which must stay observation-only unless scope changes) | spatial endpoints, caching, gating of the assistant's refusal |

## 10. Priorities, dependencies and acceptance criteria

Order reflects dependencies: nothing after P0 can be trained or validated without stored, correct data.

### P0: data foundation (blocks everything)

**G1. Correct, deterministic sensor selection** (fixes D1). Depends on: per-sensor first/last dates (e.g. `/v3/locations/{id}/sensors`, one call per station, ~69 calls). Files: `integrations/openaq.py`, `services/air_quality.py`.
Acceptance: for the 69 active stations, the chosen sensor per pollutant is the one with the most recent `datetimeLast` (ties broken by a documented rule); a report states which sensor id and unit were chosen; the list "stations with a latest reading / stations listing the pollutant" is recorded before and after on the same day; Alipur's CO/NO₂/SO₂ resolve to sensors measuring ppb; tests cover a location with a legacy and an active sensor.

**G2. A persistent, versioned time-series store.** Depends on: a decision on engine (section 11). Files: `db/session.py`, `migrations/`, new store module following `alerts/store.py`.
Acceptance: observations and weather rows are stored with provider, sensor id, unit, source timestamp, retrieval time and raw validity flags; re-ingesting the same window is idempotent; a documented query returns any hour for any station; survives a restart; no existing endpoint changes behaviour.

**G3. Historical backfill with a measured budget.** Depends on G1, G2. Files: `integrations/openaq.py` (add pagination), a new job, and the Open-Meteo archive client. Back-of-envelope only: ~414 sensors x about 14 pages for 1.6 years is roughly 5,800 requests at 60/min, so several hours, not yet measured. An OpenAQ bulk archive may avoid that; [U], to be checked.
Acceptance: a coverage report per station and pollutant (first/last hour, observed hours, gap lengths) computed from the store; the backfill resumes after interruption; the actual request count and wall time are recorded.

**G4. Unit normalisation policy.** Files: `services/aqi.py` (existing assumptions), new conversion module. Acceptance: a documented, test-covered conversion for ppb/ppm ↔ µg/m³ with its temperature/pressure assumption stated; the original value and unit are always kept; the UI never mixes units silently.

### P1: inputs and evaluation

**G5. Historical weather store from the archive API** (verified reachable [L]) at finer than 16 cells, plus station-level interpolation. Acceptance: hourly values for the full air-quality history window with a null-rate report per variable; units and time basis (UTC) tested.

**G6. Use station-side meteorology** (3.5) as an optional input, flagged as measurement vs model. Acceptance: wind/temperature/humidity series stored and exposed with gaps preserved.

**G7. Data-quality layer:** outlier, flat-line and duplicate-site rules (Pusa), recorded, never overwritten. Acceptance: every excluded value is listed with a reason.

**G8. Backtesting harness** before any model: persistence and climatology baselines on stored data, with rolling-origin evaluation. Acceptance: reproducible metrics from a script, with the data window and the number of stations stated; a model is accepted only if it beats the baselines on the same split.

### P2: models and contract

**G9. Contract v2** (additive): spatial/gridded output, scenario or ensemble fields, skill metrics, and the inputs actually used. Files: `forecast/contract.py`, `docs/ml-forecast-*`. Acceptance: v1 clients keep working; the schema file and code are checked equal by the existing test; unknown fields are rejected.

**G10. Model training/serving**, either behind the provider interface (separate service) or inside the API. Depends on G2-G8 and an ML-library decision. Acceptance: provenance fields name training window and data; every prediction passes contract validation; **no forecast is shown without a stated skill measurement**.

**G11. Gate the assistant's refusal** (`assistant/guards.py`, `orchestrator.py:89`) so it only refuses when no provider exists, and only quotes provider output. Acceptance: tests for both states.

### P3: spatial, transport, uncertainty, health

**G12. Spatial surface and transport layers** on the existing deck.gl overlay. Depends on G5, G9, G10. Acceptance: layers show only stored/validated inputs and clearly separate observation, interpolation and model output; every pixel can be traced to its source; map tests exist; a visual check with real screenshots is done (the black-screenshot limitation in section 6 must be solved first).

**G13. Uncertainty display and calibration**: intervals rendered on charts and maps; coverage computed on held-out data. Acceptance: reported nominal vs empirical coverage on the backtest set.

**G14. Environmental-health intelligence** on the existing KB. Depends on a vetted corpus (user-supplied) and a scope decision. Acceptance: statements are retrieved and cited, no individual medical advice, and the existing grounding checks apply to health numbers.

### Cross-cutting

* **G15. Put the project under version control** before any further change (it is not a git repo). Acceptance: initial baseline commit; `.env`, `api/data/` excluded.
* **G16. Install the intended Ollama model** (`qwen3:8b-q4_K_M`) on the target host and re-measure tool use and latency. Acceptance: recorded timings and the same live checks re-run.
* **G17. Map rendering verification** by a method that captures WebGL. Acceptance: screenshots or pixel checks of each layer.

## 11. Decisions needed from you before any build

1. **Storage engine:** the PostgreSQL/PostGIS machine you planned (needs to be reachable and credentialled), or SQLite for now. Each changes G2 and spatial queries.
2. **Scope of "digital twin":** is a forecast shown to users allowed once it has measured skill, or must the app stay observation-only with the external provider as the only source?
3. **Where models run:** in this API process, a separate service behind the existing contract, or both.
4. **Allowed new dependencies** (pandas, scikit-learn, PyTorch, shapely/pyproj, xarray): none are installed; this is a stack change you should approve explicitly.
5. **Backfill depth and station set:** all 108 locations since 2016, or the 69 active ones since 2025-02?
6. **Health corpus:** which documents you will supply.
7. **Hardware:** the dev machine is CPU-only; training location is undecided.

## 12. What was not verified in this audit

* Any PostgreSQL/PostGIS behaviour; the backend suite was not re-run; the frontend build was not re-run.
* Open-Meteo archive depth and completeness beyond one day; OpenAQ history for any sensor other than one at Alipur; per-station data gaps.
* Whether the CPCB publication lag is persistent.
* Any model, any real forecast provider, Qwen3-8B behaviour, RAG quality on a real corpus.
* Visual rendering of maps, charts and PDFs.
* The 2,000 requests/hour OpenAQ quota and the existence or usability of a bulk archive.
