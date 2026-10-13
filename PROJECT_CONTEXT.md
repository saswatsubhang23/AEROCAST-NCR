# AEROCAST NCR — Full project context (handoff for another laptop)

Written 2026-10-10. Read this first, then `CLAUDE.md` (standing rules), `docs/IMPLEMENTATION_STATE.md` and `docs/IMPLEMENTATION_LOG.md`.
This file contains no secrets; key *names* only. Real values live in `api/.env` (git-ignored) and must be moved or re-entered by you.

---------------------------------------------------------------------------------------------------------------------------------
## 1. What this project is
A weather-forecasting and air-pollution early-warning system for **Delhi NCR**: real observations, forecast-ready data pipelines, a
2-D geospatial map, a synchronized 3-D atmospheric digital twin, risk windows, uncertainty-aware model forecasts, a local AI assistant,
and a one-click local model-training button. Folder: `D:\python weather forecasting` (not a git repository).

Scientific-integrity rules (from `CLAUDE.md`, still binding):
* Never fabricate observations, wind fields, vertical profiles or forecasts. Distinguish measured / external-model / interpolated /
  trained-model / illustrative values everywhere (provenance badges exist in the UI).
* Never present an interpolated surface as station data. Show honest unavailable / stale states.
* Timestamps normalized to Asia/Kolkata for display; storage is UTC. Wind direction convention: direction FROM; u = −s·sin(dir),
  v = −s·cos(dir).
* Never claim a test passed unless it was run. Report implemented / verified / limitations.
* Prompt 6 (final model training / production readiness) is user-triggered: training happens only when the user clicks the button.

User decisions on record: no auth for now; PostgreSQL/PostGIS to be installed later; evidence documents and patient-level data will be
provided later; Open-Meteo stays non-commercial; Skiper UI free components only; use CPCB data directly; Ollama pulls approved;
laya used as the typed API client for the local "Jev" backend.

---------------------------------------------------------------------------------------------------------------------------------
## 2. Stack
| Layer | Technology |
|---|---|
| Frontend | Next.js 16.4 (Turbopack), React 19.3, TypeScript, Tailwind v4, ECharts, MapLibre GL 6 + deck.gl 9 (MapboxOverlay), three 0.186 + React Three Fiber 9.8 + drei 10.7 |
| Backend | FastAPI 0.143, pydantic v2, httpx, SQLite (history store), uvicorn |
| ML | scikit-learn 1.9.1, XGBoost 3.4.1, LightGBM 4.7.0, numpy 2.5.3, scipy, joblib (versions pinned in `api/requirements-ml.txt`; a saved model refuses to load under different versions) |
| LLM | Ollama (code default `qwen3:8b-q4_K_M`; this machine's `api/.env` sets `hermes3:8b`; embeddings `nomic-embed-text`) |
| Other | chromadb (knowledge base), fpdf2 (reports), laya (Jev client), alembic/psycopg (PostgreSQL later) |

---------------------------------------------------------------------------------------------------------------------------------
## 3. Repository layout
```
CLAUDE.md, TECH_STACK.md, DATASET_AUDIT.md, CLAUDE_PROMPTS_4_TO_6.md, README.md, start.bat, PROJECT_CONTEXT.md
api/
  app/
    api/        routers: air, weather, twin, alerts, assistant, knowledge, reports, models, training, jev, health_intel, routes, forecast
    history/    store.py, ingest_air.py (OpenAQ), ingest_xkdr.py (CPCB archive), ingest_weather.py, clean, features.py, cli.py
    ml/         dataset.py, train.py, metrics.py (incl. stratified), report.py, artifacts.py, inference.py, regimes.py, configs/*.json
    twin/       service.py (store reads, IDW, window), transport.py, simulation.py, risk.py, early_warning.py
    training/   jobs.py (one-click training manager)
    services/   aqi.py (CPCB AQI), air_quality, model_air_quality, weather_fields, system_status
    forecast/   contract.py (typed forecast contract; provider interface)
    jev/        laya_client.py, shadow.py
    core/       config.py (settings), time, places
  data/         history.sqlite (~16 GB), models/, models_candidates/, training_jobs/, twin_runs/, kb/, alerts.sqlite, jev_shadow.sqlite
  tests/        ~607 backend tests
  .env          local secrets/config (not in git)   .env.example = template
web/
  src/app/      pages: / , weather, air-quality, atmosphere, twin, early-warning, assistant, knowledge, reports, training, settings
  src/lib/      http.ts, twin/{store,contract,fields,simulation,earlyWarning,api,layers/*,scene/*}, training/api.ts, nav.ts
  src/components/{twin,ui,...}
docs/           ~35 documents; the most important are listed in section 9
```

---------------------------------------------------------------------------------------------------------------------------------
## 4. Moving to another laptop — checklist
1. **Copy the folder.** `api/data/history.sqlite` is about **16 GB** (plus `-wal`/`-shm`; stop the API first, or copy after a clean shutdown).
   If you do not want to move it, you can rebuild it (section 5), but that needs the CPCB archive key and many hours of downloads.
   Do **not** copy `api/.venv` or `web/node_modules`; recreate them (virtualenvs are not portable between machines).
2. **Install prerequisites:** Python 3.12+ (match the version the venv used), Node.js 20+/22, Ollama (optional, for the assistant).
3. **Backend environment**
   ```
   cd api
   python -m venv .venv
   .venv\Scripts\python.exe -m pip install -r requirements-ml.txt     # includes requirements.txt
   ```
   Keep the pinned ML versions; otherwise the saved models will refuse to load and you must retrain.
4. **Frontend:** `cd web` then `npm install`.
5. **`api/.env`:** copy it from the old laptop (or from `.env.example`). Keys used: `AQ_API_KEY` (OpenAQ v3), `INDIA_AQI_API_KEY`
   (xKDR/CPCB), `OLLAMA_MODEL`, `ML_LOCAL_MODEL_DIR`, `CORS_ORIGINS`, `ENVIRONMENT`, `LOG_LEVEL`. **Rotate the keys if the file
   travelled over an insecure channel.** `ML_LOCAL_MODEL_DIR` is a path: fix it for the new machine (see section 6).
6. **Ollama (optional):** `ollama pull qwen3:8b-q4_K_M` and `ollama pull nomic-embed-text`. The app works without it; the assistant then
   reports unavailable.
7. **Run:** double-click `start.bat` (API on **:8000**, web on **:3000**), or run
   `api\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir api --port 8000` and `npm --prefix web run dev`.
8. **Verify:** open http://localhost:3000/training (shows data and model status), `GET http://localhost:8000/api/health`, then run the tests
   (section 8).

---------------------------------------------------------------------------------------------------------------------------------
## 5. Data
* **Store:** `api/data/history.sqlite`. Tables include raw per-provider tables, `clean_air`, `clean_weather`, `stations`, feature sets,
  ingest-run bookkeeping. Cleaned: ~12.9 M air rows; feature table ~8.9 M rows ("model_ready", 90 columns, horizons 1, 3, 6, 12, 24, 48, 72 h).
* **Sources**
  * OpenAQ v3 (2025-10 → present; lags days for many stations) — key `AQ_API_KEY`.
  * xKDR CPCB archive (2022-01 → 2025-09-01; the archive is not refreshed) — key `INDIA_AQI_API_KEY`, endpoint `https://airquality.xkdr.org/v1/`.
  * Open-Meteo: archive (lags ~2 days), forecast, and air-quality model (non-commercial use only).
* **Newest stored hour:** about 2026-10-07/09 (live feed is stale), so "now" forecasts are usually refused as unavailable. This is by design.
* **Rebuild commands** (from `api`, with the venv): `python -m app.history discover`, `ingest-air`, `ingest-xkdr`, `ingest-weather`,
  `clean`, `features --pollutants pm25 pm10 no2 so2 o3`. See `docs/historical-data-pipeline.md` and `docs/real-data-pipeline.md`.
* **Known gap:** the files named in `DATASET_AUDIT.md` (the Open-Meteo CSV, the wide AQI file, the PPT) are **not present** in the repo.
  The app relies on the API-built store instead; provenance is documented in `docs/DATA_PROVENANCE_AUDIT.md`.

---------------------------------------------------------------------------------------------------------------------------------
## 6. Machine-learning state
* **Active model:** run `4702878405a8` under `api/data/models/` (registry pointer `latest.json`; `regimes.json` alongside). Configuration:
  `ML_LOCAL_MODEL_DIR` in `api/.env` should point at `api/data/models` on the new laptop (absolute path).
* **Presets:** `api/app/ml/configs/real_v2.json` (standard: PM2.5/PM10/NO₂/O₃ at +1/+6/+24 h; RF, XGBoost, LightGBM, SVR; hours),
  `quick.json` (PM2.5; RF + LightGBM; minutes), `real_v1.json` (earlier).
* **Honest findings (keep them visible):**
  * PM10 +24 h model does not beat persistence on the held-out period.
  * The inverse-distance spatial estimate and the 2-D transport hindcast do **not** beat simple baselines.
  * Intervals are empirical validation-residual quantiles, not guarantees.
* **One-click training** (`/training`; code `api/app/training/jobs.py`, `api/app/api/training.py`): runs the CLI steps as child
  processes, never uses Claude/LLM tokens. Options validated against allow-lists; one job at a time; cancel kills the process tree; a
  finished job only writes to `api/data/models_candidates/<job>`; **activation is a separate click** (checksum + library-version verified,
  pointer switched atomically, previous pointer kept for rollback). Job state/logs: `api/data/training_jobs/<job>`.
* **Last job:** quick job `20261010T152723Z-00b08a` was interrupted (the API stopped); nothing activated. The Standard run has not been
  done in this session — start it from the button (expect hours).
* **Stratified evaluation** (season × CPCB concentration band, persistence baseline per stratum) is implemented and will appear in results
  of the next training run only.

---------------------------------------------------------------------------------------------------------------------------------
## 7. Features implemented (and how they were verified)
* **Observed & model data pages:** weather, air quality (CPCB-method AQI via `app/services/aqi.py`), atmospheric conditions, with
  provenance badges and stale/unavailable states.
* **Digital twin** (`/twin`): shared store (`useSyncExternalStore`) for time, pollutant, location, playback, layer visibility;
  MapLibre + deck.gl layers (wind particles from U/V, IDW surface, hex-bin area layer, stations); R3F 3-D scene as a labelled visual
  representation; a contract-validated forecast-frame interface; passive 2-D advection–diffusion simulation with a validity mask and
  scenario controls; back-tests, risk windows, regimes.
* **Early warning** (`/early-warning`, `GET /api/twin/early-warning`): ranks every station that reported at an origin against a NAAQS/
  WHO/custom threshold using the saved model; "likely" only when the interval's lower bound also reaches it; replay flag for origins
  older than 6 h; weak-horizon warning; non-causal importance. ~57 s for 40 stations (no caching yet).
* **AI assistant** (local Ollama, grounded), **knowledge base**, **reports/alerts**, **Jev shadow comparison** (shadow only).
* **System status** with a 15 s cache; start-up warm-up of the twin station inventory (cold inventory otherwise >20 s).
* **Verification on record:** backend suite 607 passed (before the last small test-inventory edit, then `test_system.py` 14 passed);
  frontend vitest 116 passed; `tsc --noEmit` and eslint clean; production build checked earlier; browser checks at desktop and narrow
  widths; real Early Warning run in the browser (40 stations, no console errors, no horizontal overflow).

---------------------------------------------------------------------------------------------------------------------------------
## 8. Commands
```
# backend tests (from api)
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider
# frontend (from web)
npx tsc --noEmit ; npx eslint src ; npx vitest run ; npm run build
# training from the command line (the UI button does the same)
.venv\Scripts\python.exe -m app.ml train --config app/ml/configs/quick.json --out data/models_candidates/manual
.venv\Scripts\python.exe -m app.ml report ...
```
Windows notes: `os.replace` on `job.json` can hit PermissionError (a retry loop exists); long cold-cache store reads can exceed
30 s (client timeouts are 90 s for twin status/window and 180 s for early warning).

---------------------------------------------------------------------------------------------------------------------------------
## 9. Documents to read (in `docs/`)
`IMPLEMENTATION_STATE.md` (current state) · `IMPLEMENTATION_LOG.md` (history) · `NEEDS_YOUR_DECISION.md` (open decisions) ·
`NEXT_SESSION_PROMPT.md` · `DATA_PROVENANCE_AUDIT.md` · `historical-data-pipeline.md` · `real-data-pipeline.md` ·
`ML_TRAINING_AND_EVALUATION.md` · `ml-training-pipeline.md` · `one-click-training.md` · `early-warning.md` ·
`spatial-forecasting.md` · `digital-twin-architecture.md` · `geospatial-and-3d-twin.md` · `feature-01/02/03-*.md` ·
`forecast-uncertainty-and-risk.md` · `jev-integration.md` · `ml-forecast-interface.md` · `release-readiness.md`.

---------------------------------------------------------------------------------------------------------------------------------
## 9b. Status against `CLAUDE_PROMPTS_4_TO_6.md` (Prompts 1–3 were done before; this is the map for continuing)
Legend: DONE = built and checked; PARTIAL = built with a stated gap; NOT DONE.

### Prompt 4 — MapLibre + deck.gl geospatial layer: DONE
| Requirement | Status | Where / notes |
|---|---|---|
| MapLibre integrated, routing/API preserved | DONE | `web/src/components/twin/TwinMap.tsx`, page `/twin` |
| deck.gl via supported API | DONE | `MapboxOverlay` (deck.gl 9 with MapLibre 6) |
| Reusable layers + registry | DONE | `lib/twin/layers/{types,definitions,scales,hex,raster,staleness,particles}.ts`, `LayerPanel.tsx` |
| Variables from real contracts (AQI, weather fields) | DONE | `lib/twin/variables.ts`, `/api/weather/fields`, `/api/twin/window`, `aqi` via `compute_aqi` |
| Stations, hex aggregation, surfaces with documented interpolation | DONE | IDW (`idw_point`/`idw_grid`) marked "estimate"; hex layer only when density justifies it |
| Wind from real vectors, U/V convention tested | DONE | `lib/twin/windVector.ts` (direction FROM; u=−s·sin, v=−s·cos), `test_weather_fields.py`, vitest |
| Time selector/playback, variable selector, toggles, opacity, legend with units, timestamp, no-data/stale states | DONE | `TimelineControls.tsx`, `LayerPanel.tsx`, `staleness.ts` |
| Observation vs forecast vs interpolated vs scenario styling | DONE | `ProvenanceBadge.tsx`, per-layer provenance |
| No invented stations / single-point honesty | DONE | only stations present in the store |
| Update optimization and cleanup | DONE | layer diffing, resource cleanup on unmount |
| Gates: timestamp/layer tests, missing/invalid coordinates, legend match, lint/type/test/build, browser desktop+narrow | DONE | `store.test.ts`, `layers.test.ts`, `fields.test.ts`, `contract.test.ts`; mobile overflow fixed |
Docs: `docs/feature-02-operational-weather-map.md`, `docs/geospatial-and-3d-twin.md`.

### Prompt 5 — Three.js/R3F 3D twin + synchronization: DONE (with documented illustrative parts)
| Requirement | Status | Where / notes |
|---|---|---|
| Separate 3D view: frame, camera, altitude axis, base, legend | DONE | `components/twin/scene3d/{Scene3D,Scene3DLazy,SceneNotes}.tsx`, `cameraPresets.ts`, `lib/twin/scene/{geometry,data}.ts` |
| Shared state with the 2D map (time, variable, location, playback, layer visibility) | DONE | `lib/twin/store.ts` (`useSyncExternalStore`), `store.test.ts` |
| Wind animation from real speed/direction; no implied resolved field from one point | DONE | `particles.ts`, bounded particle budget |
| Spatial concentration only where coverage supports it; method exposed | DONE | IDW estimate labelled "estimated/interpolated" with validity mask |
| Altitude/volumetric layers only if defensible | DONE (labelled) | no vertical measurements exist, so altitude is labelled a visual representation, not a measured 3-D field |
| Playback, speed, variable select, camera presets, hover/click inspection, compare views | DONE | `TimelineControls.tsx`, `FieldInspector.tsx`, `SimulationInspector.tsx`, lens/display tabs on `/twin` |
| Lighting, depth, accessible controls, responsive | DONE | verified in browser |
| Particle budget, memoized geometry, GPU disposal | DONE | production build: 0 console errors (dev StrictMode shows R3F "unmount root" messages only) |
| Forecast-ready interface, no training | DONE | `lib/twin/contract.ts` + `contract.test.ts` (validated forecast frames) |
| Honest unavailable/stale/loading states | DONE | |
Docs: `docs/feature-03-dynamic-digital-twin.md`, `docs/digital-twin-architecture.md`, `docs/geospatial-and-3d-twin.md`.

### Prompt 6 — Validate, train/evaluate, connect forecasts: MOSTLY DONE (model training itself is the user's button)
| Step | Status | Evidence / gap |
|---|---|---|
| 1. Audit actual data | PARTIAL | The CSV/AQI/PPT files in `DATASET_AUDIT.md` are **not in the repo**, so those specific files were never parsed. Instead a station-level pollutant store was built from OpenAQ, xKDR/CPCB and Open-Meteo APIs, with provenance, units, IST alignment, duplicates/gap/sentinel cleaning (`docs/DATA_PROVENANCE_AUDIT.md`, `historical-data-pipeline.md`). Pollutant-specific models are justified because pollutants (not AQI alone) are observed. If those original files turn up, audit them as DATASET_AUDIT.md describes and do **not** call the wide AQI file CPCB ground truth without verification. |
| 2. Baselines, time-ordered splits, leakage control | DONE | `api/app/ml/{dataset,train}.py`: chronological dev/test split with rolling-origin folds; persistence, seasonal-naive, climatology baselines vs RF/XGBoost/LightGBM/SVR; features built by the same function at train and serve time (`history/features.py`, with a latency parameter); regimes learned on development period only and tested on the rest (`ml/regimes.py`, Kruskal–Wallis; `test_twin.py`). |
| 3. Proper evaluation | DONE / PARTIAL | MAE, RMSE, R², bias per horizon with baseline comparison, per-station summary, calibration and empirical intervals are recorded (`ml/metrics.py`, `docs/ML_TRAINING_AND_EVALUATION.md`, `ml-model-comparison.md`). **By season and by AQI/concentration range is implemented but only appears after the next training run** (the active run predates it). |
| 4. Versioned forecast contract and twin connection | PARTIAL | `api/app/forecast/contract.py` (strict pydantic contract: times, values, units, intervals, model_version, provenance incl. generated_at and input_data; JSON schema at `docs/ml-forecast-contract.schema.json`); served through `ml/inference.py` and shown in the twin as back-tests/risk windows. Gaps: spatial-resolution and per-field data-freshness/quality flags are not separate contract fields (freshness is enforced by refusing stale input); forecasts are station-level only, and no city-wide predicted field is drawn (correct: no validated spatial model — the IDW estimate and transport hindcast failed to beat baselines). |
| 5. Early warning | DONE | thresholds (NAAQS, WHO, custom), future windows, stale/replay flag, uncertainty explanation, weak-horizon flag, model feature importance labelled non-causal (`twin/risk.py`, `twin/early_warning.py`, `/early-warning`). Importance is global to the model at its tuning horizon, not a per-forecast attribution. |
| 6. Production readiness | DONE / PARTIAL | repeatable CLI (`python -m app.ml train/report`), versioned artifacts with manifest + checksums + library-version check, fail-safe loading (`ModelUnavailable` → `ForecastUnavailable`, app keeps running), schema/missing-input/timestamp tests, backend and frontend suites, build. Limits: summary of limitations lives in `docs/ML_TRAINING_AND_EVALUATION.md`; a fresh Standard run and its activation have not been done this session. |

### Final restrictions from the prompt — current standing
* No fabricated metrics: all numbers come from recorded `results.json` of a run. Quote only those.
* No superiority claim without baseline: PM10 +24 h does not beat persistence; spatial/transport estimates do not either — keep saying so.
* No physical-transport claim: the simulation is passive, 2-D, labelled a simulation.
* No synthetic substitution: when data is unavailable the app says unavailable.

### If you continue "from Prompt 6"
1. Start a Standard training run from `/training`; read the report's season/band table and the persistence comparison; activate only if
   acceptable.
2. Add spatial-resolution and freshness/quality fields to the forecast contract (bump the contract version, update the JSON schema,
   `contract.test.ts`, and the provider tests).
3. If the original CSV/AQI/PPT files become available, run the Step 1 audit on them as a separate, documented pass.

---------------------------------------------------------------------------------------------------------------------------------
## 10. Not done / next steps
1. Start a **Standard** training run from `/training`, review results (incl. the new season/band table), then activate if acceptable.
2. Exposure (health-intel) UI — waiting on the patient-level data you will provide; evidence documents likewise.
3. CSRF-style header requirement on the state-changing training endpoints; response caching for early warning.
4. PostgreSQL/PostGIS migration (alembic scaffolding exists; not installed or used).
5. Refresh the live feed (OpenAQ/Open-Meteo) via the training button's "download newest hours" option; the CPCB archive itself ends
   2025-09 and cannot be extended from this source.
6. Known/accepted: dev-mode React StrictMode console messages from R3F (production build has none); `npm audit` dev-only `braces`.

---------------------------------------------------------------------------------------------------------------------------------
## 11. Working with Claude Code on the new laptop
Open the folder `D:\python weather forecasting` (or its new path) so `CLAUDE.md` is loaded automatically. A good first message:
"Read PROJECT_CONTEXT.md, docs/IMPLEMENTATION_STATE.md and CLAUDE.md, verify the environment (health endpoint, tests), and continue
with the next steps in section 10." Claude's per-session memory and transcripts are stored under your user profile
(`~\.claude\projects\...`), not in this folder; they do **not** transfer unless you copy them, which is why this file exists.
