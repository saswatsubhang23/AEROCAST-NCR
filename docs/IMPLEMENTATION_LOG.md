# Implementation log

Substantive changes, decisions and verification outcomes only.

## 2026-10-10 session
* **Audit** (`docs/digital-twin-gap-analysis.md`): found stale OpenAQ feed (median reading age 54 h), arbitrary sensor selection (D1), mixed units, no persistence layer, PostgreSQL unreachable.
* **Historical pipeline** (`api/app/history`): SQLite store with raw / clean / model-ready layers; OpenAQ hourly ingestion (resumable, windows of 40 days, concurrency-bounded, rate-limited); Open-Meteo archive ingestion; cleaning with hard/soft quality flags; unit standardisation to µg/m³ with a data-driven `UNIT_SUSPECT` check (CO labelled ppb read ~1); leakage-safe feature builder; coverage report with a supported-targets table. Decision: SQLite, because PostgreSQL was unreachable (`check-db`).
* **Verified against an independent source:** OpenAQ hourly value == mean of four 15-minute S3 samples in (from, to], so hourly values blend neighbouring CPCB hours (documented limitation).
* **Defects found by testing and fixed:** (1) forward-looking `FLATLINE` flag as a feature (leak) removed from features; (2) summary guard accepted invented numbers (previous phase); (3) serving/training skew in `hours_since_rain` fixed by capping at the longest look-back; (4) validation windows could read test-period labels, fixed (`eval_mask` requires the target inside the window).
* **ML pipeline** (`api/app/ml`): baselines (persistence, seasonal naive, train-only climatology) vs Random Forest, XGBoost, LightGBM, SVR; rolling-origin folds + chronological test; label purging; artifacts with SHA-256 manifest and version pinning; inference provider behind the forecast contract with strict "unavailable" behaviour; provenance guard that refuses to train on fixtures.
* **Operational lesson:** CPU-heavy work slows the OpenAQ backfill from ~45 to ~12 requests/min; do not run both.
* Tests: see `IMPLEMENTATION_STATE.md`.

## 2026-10-10 (continued): data completed, twin, Jev, assistant, health
* **Real data:** OpenAQ backfill finished (404 sensors, 3,009,696 hourly rows, 2025-10-09..2026-10-10; 0 failed windows in the final run; a refresh of 90 recent windows returned 0 revised rows) and Open-Meteo archive weather (614,810 rows). Cleaning: 86% usable coverage per pollutant.
* **Defect from real data:** every CO sensor in the window is labelled ppb with median ~1 (impossible for ppb). The reference-sensor rule could not fire (no native µg/m³ CO sensors left in the window). Added a documented plausibility floor; 68 CO sensors / 510,500 rows are now `UNIT_SUSPECT`; CO is "insufficient" in the support table and is not modelled.
* **Defects found by running on real data:** report rendering crashed on suspects without a reference value (fixed + test); full-table scan per station made cleaning take 15 min (added `ix_raw_air_station`, 5 min); feature building for 4 pollutants takes 17 min (2,054,381 rows).
* **Support table (real):** PM2.5, PM10, NO2, SO2, O3 "supported" at +1..+72 h by the pipeline's own thresholds (1,500 pairs/station, 120 days, 20 stations); CO insufficient.
* **Digital twin:** `api/app/twin` + `/api/twin/*`, `/api/models/status`; frontend `/twin` (map layers, timeline, station charts, risk-window and regime panels); 28 + 6 tests.
* **Jev:** built from TypeSafe's published OpenAPI; shadow-only; 32 mock-transport tests; not called live (no key).
* **Assistant:** `get_pollution_forecast` tool and refusal gating on whether a forecaster is configured; frontend types updated for the new source kind (a real gap: the label map had no entry).
* **Health intelligence:** `/api/health-intel/exposure` + 12 tests; evidence section is empty until documents are indexed.
* **UI:** Radix/Skiper-derived primitives, Lucide, Motion; provenance badges; model/Jev status on Settings and Overview.
* **Tests:** full backend suite 632 passed (9m42s) before the CO-floor report fix; history tests 48+45 passed after it.
* **Training:** started with `app/ml/configs/real_v1.json` (pm25, pm10, no2, o3 at +1/+6/+24 h) on `model_ready` digest 580f2268...; results go to `api/data/models/<run_id>/` and `docs/ml-model-comparison.md`.

## 2026-10-10 (training and live verification)
* Trained run `4702878405a8`; wrote `ML_TRAINING_AND_EVALUATION.md`. Added `beats_persistence_on_test` to `/api/models/status` and a persistence WARNING in served-forecast provenance.
* The API did not pick up the new `.env` until a Python file changed (settings are cached; uvicorn --reload watches `.py` only). Touching `app/main.py` reloaded it. After editing `.env`, restart the API.
* Live checks: status lists 12 cells; back-test (station 6932, origin 2026-10-05T06:00Z) +1 h 23.0 vs observed 22.3, +6 h 48.8 vs 28.0; Delhi forecast served from station 8118 with 5.7 h old input.

## 2026-10-10 (XKDR history, Laya, Open-Meteo air quality)
* **XKDR archive:** `ingest-xkdr` loaded 10,161,751 rows (72 NCR stations, 68 matched to OpenAQ ids, 4 new; 1,694 requests, 0 failed). Open-Meteo archive weather extended back to 2022-01-01 (it hit the free hourly limit twice; the resumable loop finished). Cleaning: 12,899,133 hourly rows; feature table 8,906,334 rows.
* **Defect found:** synthetic station ids (9e9+) overflowed int32 in `ml/dataset.py`; now int64.
* **Laya:** local backend for the optional decision support (`JEV_BACKEND=laya`); 76% on the 42 labelled examples vs 98% for the deterministic router; shadow-only.
* **Open-Meteo Air Quality:** `/api/air/model-forecast` and the "Modelled pollution" panel, badged as an atmospheric model; independent of station data.
* **Qwen3:** pulled and set as `OLLAMA_MODEL`; assistant tool selection works.
* **Training v2:** `app/ml/configs/real_v2.json` into `api/data/models_v2` (so the serving model is not replaced until it is compared).

## 2026-10-10 Feature 01 integration pass
* Stopped the `real_v2` training run (instruction: no retraining in this feature) and deleted `data/models_v2`.
* Fixed assistant status schema, added status-result cache and `refresh`, consolidated frontend request helpers, focusable scroll regions, endpoint test list.
* Observed: reports/alerts/assistant workflows, 9 pages axe-clean, no overflow at 375 px. Backend 644 passed, vitest 56 passed.

## 2026-10-10 Feature 02 weather map
* Inspected real Open-Meteo responses (variables, units, 0.07 deg model cells, pressure gradient) before implementing each layer.
* Added `/api/weather/fields`, Atmosphere view on `/twin`, layer manager, inspector, timeline sync, particle loop with cleanup.
* Defects: station inventory 22 s cold (index + cache), model re-load per status call leaking to 3 GB (cache), tab aria-controls.
* Tests: backend 53 passed in the touched modules (full suite not re-run after the load_run cache; ML module 53 passed); vitest 67 passed; axe 0; no overflow at 375 px.

## 2026-10-10 Feature 03 dynamic digital twin
* Engine, run service, API, map integration, scenario and live modes, validation; 12 engine tests and 13 simulation tests, 6 frontend tests.
* Real-data validation: interpolation vs mean of other stations (skill -0.05 PM2.5), transport vs persistence (skill -0.22 / -0.19 withheld).
* Live run on the stored history is stale (initial observations 70 h old) and is labelled so.
* Vectorised the interpolation for the initial field (same method, asserted equal to the scalar one).

## 2026-10-10 Prompts 4 and 5
* Read the four instruction files; preserved the existing MapLibre/deck.gl map; added registry, shared store, AQI, hexagon layer, estimate contours, wind convention tests.
* Installed three 0.186.1, @react-three/fiber 9.8.1, @react-three/drei 10.7.9 (+ @types/three); built the 3D scene, scene data layer, notes panel, camera presets, Compare display.
* Defects fixed: default station without data in the window, 58 px overflow at 375 px (grid track and fieldsets), cold twin status exceeding the client timeout (start-up warm-up, longer timeout), hexagons hidden under dots.
* Verified a production build in the browser (0 console errors); dev-only StrictMode messages documented. CORS was widened temporarily for that check and restored.

## 2026-10-10 one-click training
* Added `app/training/jobs.py` (job manager), `app/api/training.py`, `/training` page, nav entry, `quick.json` preset, `summarize_run` shared with `/api/models/status`.
* `LocalModelProvider` now re-resolves the registry pointer each request so an activated model is used without a restart.
* Defect fixed during testing: a Windows PermissionError when replacing `job.json` while it was being read (retry on replace).
* Verified a real quick job from the button; the stopped earlier background shell (`bs3vdvxc3`) had produced no output and nothing was lost.

## 2026-10-10 — stratified evaluation and early warning
* `ml/metrics.py`: `stratified()` (season by IST month, CPCB concentration bands, persistence MAE per stratum, min 30 rows); recorded per cell by
  `ml/train.py`, rendered by `ml/report.py`, exposed by `summarize_run`, shown on the Training page. Applies to the next training run; existing
  run artifacts do not carry it.
* `twin/early_warning.py` + `GET /api/twin/early-warning` + `/early-warning` page: station ranking against a threshold, replay flag, weak
  horizons, uncertainty text, non-causal importance. 57 s for 40 stations (uncached).
* Tests: backend suite 607 passed after updating the endpoint inventory test; vitest and tsc/eslint clean.
* Quick training job `20261010T152723Z-00b08a` was found interrupted (the API process stopped while it ran); nothing was activated. Start a new one
  from the Training page.
