# Digital-twin release audit (2026-10-10)

Status vocabulary: **verified** = run and observed this session; **partial**; **blocked** (needs the user); **not done**.

## Verified
* Real-data pipeline: 3,009,696 OpenAQ + 614,810 Open-Meteo hourly rows; CO excluded as unit-suspect (`docs/real-data-pipeline.md`).
* Training on real data with chronological and rolling-origin validation; 12 cells (PM2.5, PM10, NO2, O3 at +1/+6/+24 h); 11 beat persistence on the held-out period, PM10 +24 h does not and is flagged (`docs/ML_TRAINING_AND_EVALUATION.md`).
* Artifacts with SHA-256 manifest; the API loads them, `/api/models/status` reports run, scores and provenance; `/api/twin/backtest` compares predictions with later observations; `/api/forecast` refuses on stale inputs and states the input age when it answers.
* Frontend: tsc and eslint clean, vitest 56 passed; Settings shows model table and diagnostics (MAE chart, coverage 85 to 88% against nominal 80%, station spread, feature importance) from the saved run only.
* Provenance audit found no fabricated production data (`docs/DATA_PROVENANCE_AUDIT.md`), with guards in tests.

## Partial
* Full backend suite: 633 passed (10m49s) after all fixes, on 2026-10-10.
* Axe and mobile-overflow checks were last run on the twin and settings pages; weather, air-quality, reports, assistant, knowledge, atmosphere need a re-run.
* UI migration to shared components covers shell, twin, settings, overview, atmosphere, weather, air quality; Reports, Assistant, Knowledge still use older controls.
* Risk windows and regimes exist in API and twin panels; most live requests are answered "unavailable" because the feed lags about two days.
* Exposure endpoint exists; no UI and no evidence documents.

## Known limitations (stated in the product)
* One year of data; test period is monsoon; seasonal shift limits confidence. Intervals are empirical, not guaranteed, and over-cover (85 to 88% against 80%).
* Station-level model; spatial maps are interpolation with a leave-one-out error, not a dispersion model. No traffic, plume or transport simulation exists.
* SO2 and +3/+12/+48/+72 h horizons not trained.

## Blocked on the user (`docs/NEEDS_YOUR_DECISION.md`)
Jev API key and any live shadow run; Qwen3 model pull; evidence documents for the knowledge base; licence terms for any redistribution of OpenAQ data.

## Not done
Performance before/after measurements; formal security review of the new endpoints (request-id sanitising and input validation were done and tested).
