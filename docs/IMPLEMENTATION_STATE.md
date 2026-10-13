# Implementation state (checkpoint)

Last updated: 2026-10-10 04:40 IST. Update at every checkpoint. Status words: **verified** = implemented and tested/observed;
**partial** = implemented, some part unverified or unwired; **blocked** = needs something only the user can give; **todo**.

## Workstreams

| Workstream | Status | Evidence / notes |
|---|---|---|
| A. Audit + checkpoints | verified | `docs/digital-twin-gap-analysis.md`, this file |
| B. Fake-data elimination | verified (nothing to remove) | `docs/DATA_PROVENANCE_AUDIT.md`; fixture guards in `ml/dataset.py:dataset_provenance`, tests |
| C. Real data pipeline | verified | `api/app/history/`, `docs/historical-data-pipeline.md` (= the real-data-pipeline doc); 3,009,696 raw OpenAQ hourly rows (404 sensors, 70 stations, 2025-10-09..2026-10-10) and 614,810 Open-Meteo archive rows ingested; second clean run in progress after the CO unit fix |
| D. ML training | **in progress** | code + 47 tests done; real training waits for the re-clean (CO excluded), `features`, coverage report |
| E. Inference integration | verified (code, tests) | `ml/inference.py`, `make_provider`, `/api/models/status`, assistant `get_pollution_forecast` tool; needs the trained run for a live check |
| F. UI design system | partial | Radix primitives (Tooltip from Skiper `skiper101`, Dialog/Sheet, Tabs, ScrollFade from `skiper87`), Button variants, Lucide icons, Motion nav highlight, ProvenanceBadge, `/twin` nav; tsc/eslint/vitest clean; browser-checked shell, /twin unavailable state, Settings. Not yet: full migration of every page's buttons/inputs, Reports/Knowledge/Assistant restyle, a11y re-run |
| G. Digital twin | partial | backend verified (28 tests); frontend `/twin` written, type-checked, unit-tested helpers; **not yet seen with data** (needs the cleaned store) |
| H. Uncertainty / regimes / risk windows | partial | intervals in the ML pipeline; risk windows + regimes API tested; regimes not yet run on real data; no UI for risk windows/regimes |
| I. AI orchestration (Ollama/RAG/Jev) | partial | Jev client + shadow + eval harness (32 tests, mock only, **no key**); forecast tool + refusal gating (5 tests); Ollama has `llama3.2` (set in `api/.env`), Qwen3 absent; RAG KB empty |
| J. Health intelligence | partial | exposure endpoint + 12 tests; no UI, no evidence documents (KB empty) |
| K. Release audit | todo | after D and a UI pass |

## Real numbers so far
* Tests last run per file: history 92, ml 47(+6 http), twin 28, jev 32, health 12, assistant 80 (all passed when run). **A full-suite run is pending.** Frontend: vitest 56 passed, tsc/eslint clean (last run).
* Defect found by real data: all CO sensors in the window are labelled "ppb" with median about 1 (physically impossible); `PLAUSIBLE_MEDIAN_FLOOR_STD["co"]=50` now marks them `UNIT_SUSPECT`, so CO is excluded from modelling.
* Ollama installed: `nomic-embed-text`, `llama3.2` (3.2B), `qwen2.5-coder:7b`; `qwen3:8b-q4_K_M` absent.

## Update 2026-10-10 (after training)
* **D. ML training: done and verified.** Run `4702878405a8` (pm25, pm10, no2, o3 at +1/+6/+24 h; real data, provenance-checked). Scores and limits: `docs/ML_TRAINING_AND_EVALUATION.md`, generated tables `docs/ml-model-comparison.md`. 11 of 12 cells beat persistence on the held-out monsoon period; **PM10 +24 h does not** and is flagged in the API and in forecast provenance.
* **E. Inference: verified live.** `ML_LOCAL_MODEL_DIR=./data/models` in `api/.env`; `/api/models/status` returns the run; `/api/twin/backtest` returns predictions with observed values; `/api/forecast` for Delhi was served from station 8118 (input 5.7 h old, within the 6 h limit) and states its input age; other requests are refused when inputs are stale.
* **G/H:** twin and regimes seen in the browser earlier with real data; risk windows depend on fresh inputs and are mostly "unavailable" now by design.
* Verified: full backend suite 633 passed; vitest 56 passed, tsc and eslint clean; `web/public/__axe.min.js` removed. Still pending: axe and mobile-overflow re-run on the non-twin pages.

## Remaining work
Untrained targets (SO2, +3/+12/+48/+72 h); migrate Reports/Assistant/Knowledge pages to shared components; exposure/risk UI and assistant tools; before/after performance measurements; security review of new endpoints; items needing the user are in `docs/NEEDS_YOUR_DECISION.md` (Jev key, Qwen3 pull, evidence documents).

## Feature 01 (existing-feature integration), 2026-10-10
Done and verified: see `docs/feature-01-integration-audit.md`. Fixed: assistant status 500, status endpoint latency (cache), duplicated frontend request helpers
(`lib/http.ts`), keyboard-focusable scroll regions. Backend 644 passed; vitest 56 passed; tsc/eslint clean; axe 0 violations and no overflow at 375 px on all 9 pages.
The `real_v2` training run was stopped on request (not completed); XKDR history, cleaned data (12.9M rows) and the 8.9M-row feature table are ready for it.

## Feature 02 (operational weather map), 2026-10-10
Done and verified in the running app: see `docs/feature-02-operational-weather-map.md`. `/twin` has an Atmosphere view (same map instance):
precipitation, temperature, humidity, cloud and boundary-layer colour fields, MSL-pressure contours, animated wind particles and arrows,
layer manager with opacity and legends, forecast and historical time modes, inspector with ECharts, one shared selected time.
Backend `/api/weather/fields` (8 tests); frontend `lib/twin/fields.ts` (15 tests). Also fixed: slow station inventory (covering index + cache),
model re-loading on every status call (cache), tab ARIA panels.

## Feature 03 (dynamic digital twin), 2026-10-10
Done and verified in the running app: see `docs/feature-03-dynamic-digital-twin.md`. Transport engine (`api/app/twin/transport.py`), simulation runs
with provenance and hindcast validation (`simulation.py`), API (`/api/twin/simulations*`, `/api/twin/validation/estimates`), Simulation view on
the shared map with layers, scenario controls, live polling, inspector. Honest findings: the spatial estimate does not beat a plain mean in
leave-one-out (PM2.5 skill -0.05), and the passive transport run does not beat persistence at 1-24 h (skill about -0.2); both are stated in the product.
Tests: backend 677 (676 plus the endpoint list fix), vitest 73, tsc/eslint clean, axe 0, no overflow at 375 px. No ML retraining was done.

## Prompts 4 and 5 (CLAUDE_PROMPTS_4_TO_6.md), 2026-10-10
Done and verified: see `docs/geospatial-and-3d-twin.md`. Layer registry, shared twin store, AQI variable (CPCB method, derived), hexagon aggregation, estimate
contours, single wind convention, forecast-ready frame contract, and the 3D twin (Three.js + R3F + Drei) synchronised with the map, plus a Compare display.
Tests: vitest 116, backend 682 (run before the final warm-up edit; twin/system modules re-run: 42), tsc/eslint clean, production build passes.
**Prompt 6 (final forecasting and model training) is not started and is locked until you authorise it.**

## One-click training (requested after Prompt 5), 2026-10-10
Page `/training` and API `/api/training/*`; see `docs/one-click-training.md`. A button starts a local pipeline (optional data refresh, clean, features,
train, report) as a child process; no language model and no Claude tokens are involved. Finishing a job never changes the active model; "Use this
model" verifies and switches it atomically and a rollback is kept. Tests: `tests/test_training_jobs.py` (12). A real quick job was started from the
button in the browser. **A standard run (hours) has not been run: it is yours to start from the page.** Prompt 6's remaining items (forecast-driven
early-warning presentation, model attribution, production-readiness audit) are still open.

## Update 2026-10-10
Done: stratified evaluation (next training run), Early Warning page/endpoint. Not done: exposure (health-intel) UI, CSRF-style header on training
POSTs, response caching for early warning, SO2/more-horizon training (user starts from the Training page). Prompt 6 model retraining is the
user's button; no new model was trained or activated in this session.

## Update 2026-10-11 (environment rebuilt on a new laptop; georegistered terrain; contract v2)
Environment: venv rebuilt on Python 3.13.7 (the 3.14 venv from the old laptop was unusable); `requirements.txt` + `requirements-ml.txt` installed; the
saved model `4702878405a8` loads under the pinned library versions. `OLLAMA_MODEL=hermes3:8b` (user's choice instead of Qwen3); `hermes3:8b` and
`nomic-embed-text` pulled. OpenAQ key set in `api/.env`.
Done and verified:
* **Terrain and imagery** (`docs/terrain-and-imagery.md`): `/api/terrain/{meta,heightmap,imagery}`, real DEM and Sentinel-2 composite registered to
  latitude/longitude, 3D scene on real relief with data fields draped on it, smooth radar-style rendering, Voyager/Dark/Satellite/Relief basemap
  switch on every map (CARTO key in `web/.env.local`). Weather lattice raised from 8x9 to the model's native 14x11.
* **Forecast contract v2**: optional per-pollutant `spatial`, `freshness`, `quality_flags` (+ `contract_version`); the local provider fills them from what
  it used; schema file regenerated; the Air Quality forecast panel shows them.
* **Training endpoints**: state-changing POSTs require `X-AEROCAST-Action: training` (403 otherwise); the frontend sends it.
* **Early warning**: the per-station forecasts are cached for 5 minutes per (pollutant, origin, station set, active model); ranking is rebuilt for
  each threshold; a total failure is never cached; response says `forecasts_reused`.
Tests: backend 727 passed (full suite); vitest 137 passed; `tsc`, `eslint`, `next build` clean.
Not done: a Standard training run (the user's button); exposure UI; PostgreSQL. 2D map is flat (terrain only in 3D).

## Update 2026-10-11 (air flow, coupled model, live sources, data coverage, UI)
See `docs/air-flow-and-coupling.md` for the design and the evidence.
Done and verified:
* **Air flow** `/flow`: 2D canvas flow over MapLibre and a 3D scene (real terrain + imagery) with particles at seven real model heights;
  sources: stored replay, live CAMS model (hourly, 0.4 degree cells, labelled model output), coupled model.
* **Coupled model** `POST /api/twin/coupled`: PM2.5, coarse PM, NO2, O3, SO2 with deposition, rain scavenging, SO2 to sulfate; ventilation and
  dilution opt-in. Starts: CAMS now, live OpenAQ, trained-model forecasts at +1/+6/+24 h, stored hour. Hindcast over 25 windows: no reliable
  gain over passive transport and none over persistence (`docs/coupled-evaluation.md`); the UI says so.
* **Data coverage** `/data` and `GET /api/system/data-availability`: 27 sources with live status and the consequence of each gap.
* **Weather fields**: radiation, visibility, and (with `levels=true`) winds at 80/120/180 m and 925/850/700 hPa.
* **UI**: grouped navigation, wide layout for map pages, redesigned Overview, glass panels / segmented controls / chips.
Found by testing (not assumed): the OpenAQ feed for Delhi lags about 3.3 days; CAMS cells are 0.4 degrees; ventilation lowered skill.
Tests: backend 769 passed (one failure appeared once in a loaded full run and did not reproduce); vitest 159 passed.

## Update 2026-10-11 (Phase 1: audit, repair, model selection, consolidation)
Done and verified (see `docs/articles/engineering-report.md`):
* **Audit**: live probes of Open-Meteo, CAMS, OpenAQ and xKDR (`docs/phase1/`). Findings: OpenAQ lags a median of 80 h; CAMS cells are 0.4 degrees;
  OpenAQ offers NO/NOx and station weather (not ingested); xKDR's US-Embassy rows are UTC, not IST.
* **Repair**: xKDR US-Embassy timestamps (ingest fixed, station 8118 re-ingested/re-cleaned/re-featurised, backup kept). The trained model predates it: retrain.
* **Typed pipeline**: `app/envdata/schema.py` (EnvRecord, normalisers, EnvStore), PostGIS DDL + Alembic 0002, 22 tests.
* **Next.js fixes**: 3D labels no longer use drei `Html` (121 removeChild + 88 createRoot errors per session gone); ECharts waits for a real size.
* **Consolidation**: 14 sidebar entries -> 7 (section tabs); Report page with four articles; prose moved out of the pages.
Tests: backend 794 passed, vitest 163 passed, tsc/eslint clean, production build OK, `npm audit --omit=dev` 0.
Not done: PostgreSQL migration against a live server; NO/NOx and station-weather ingest; population and sensitive-site layers; retraining.

## Update 2026-10-11 (full report export)
`/api/reports/export/{html,pdf}` + "Full report" card on /reports. One block model (`app/reports/doc.py`) renders to a self-contained HTML
and to a PDF, so both match. Sections: summary, station series, weather charts, atmosphere, regional CAMS/wind/station map, station ranking,
forecast, model performance (trained model and coupled hindcast), data coverage, freshness/limitations/sources, and the written reports.
A failed section is reported in place; the rest is still produced. The first build after a restart takes about two minutes (Open-Meteo calls).
Not verified: the PDF was checked by text extraction and page count, not by looking at a rendered page.
