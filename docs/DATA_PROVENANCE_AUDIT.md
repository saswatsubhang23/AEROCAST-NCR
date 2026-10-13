# Data provenance audit

Method: repository-wide search of `web/src` and `api/app` for random generators, mock/demo/fake/dummy/synthetic/placeholder
wording, hard-coded numeric arrays and silent fallbacks (`or 0`, default values after errors), plus a read of every component
that draws a measurement, and of every service that produces one. Results are exact; commands are in the implementation log.

**Result: no fabricated, hard-coded or synthetic environmental value was found in any production path.** Nothing had to be
removed. The earlier phases were built with the rule "unavailable, not invented"; this audit confirms it and adds guards.

## Inventory

| Field / visualisation | Source | Class | Files | Status | Evidence |
|---|---|---|---|---|---|
| Weather point / grid / timeline / map | Open-Meteo forecast API, 4x4 grid | real (model forecast, labelled forecast) | `services/weather.py`, `components/weather/*` | ok | live runs; `docs/release-readiness.md` |
| Recent weather, ventilation index, hours since rain | Open-Meteo `past_days` + arithmetic | derived from real, documented | `services/indicators.py` | ok | unit tests; null = unknown |
| Vertical temperature profile | Open-Meteo pressure-level temperatures | real, shown only when present | `services/profile.py`, `VerticalProfile.tsx` | ok | otherwise a labelled illustration (below) |
| Conceptual inversion diagram | static SVG, "Not measured data" label | **illustration, not data** | `ConceptualInversion.tsx` | retained, labelled | shown only when no profile exists |
| Station inventory, latest readings, history, CSV | OpenAQ v3 | real | `services/air_quality.py`, `components/air/*` | ok | live runs |
| AQI | CPCB method on real inputs | derived; only if inputs are sufficient | `services/aqi.py` | ok | otherwise "not computed" |
| Alerts | user thresholds vs observed values | user-defined rule on real data | `alerts/*` | ok | note shown with every alert |
| Reports, PDF, Markdown | the services above + KB | derived/composed | `reports/*` | ok | sources and limitations printed |
| LLM summary | local Ollama over the report's own facts | generated text, numbers checked | `reports/summary.py` | ok | rejected when numbers are unsupported |
| Assistant answers | validated tool results | real + guarded text | `assistant/*` | ok | grounding and citation checks |
| Service health | live probes | real | `services/system_status.py` | ok | unavailable shown as unavailable |
| Forecast provider status | live probe / local model load | real | `forecast/*`, `ml/inference.py` | ok | `not_configured` unless set |
| Pollution forecasts | none unless a provider/local model exists | **absent by default** | `api/forecast.py` | ok | 503 with a reason |
| Reference city centres, AQI bands, pollutant labels | fixed geography / published CPCB bands | static reference constants (not measurements) | `core/places.py`, `lib/locations.ts`, `lib/air/pollutants.ts` | retained | not displayed as observations |
| Map/legend colours, UI constants | design | not data | many | n/a | |
| Test fixtures | `api/tests/*fakes.py`, mocked transports | **synthetic, tests only** | tests | isolated | see guards |
| ML training/evaluation data | `history.sqlite` built by the ingestion CLI | real, provenance-checked | `history/*`, `ml/*` | done: 3,009,696 OpenAQ rows + 614,810 Open-Meteo rows; training refuses fixtures | see guards |
| Digital-twin observations, wind, spatial estimate | read-only from the same store; IDW with its leave-one-out error | observed / weather-model / interpolated, each badged | `twin/service.py`, `components/twin/*` | ok | `tests/test_twin.py`; seen in the browser with real data |
| Model forecasts, risk windows, interval, model scores | trained artifacts + `results.json` of the run | model output / recorded held-out scores | `ml/inference.py`, `api/twin.py`, `api/models.py` | ok after training | scores are read from the run, never typed |
| Weather regimes and PM2.5 by regime | K-means on stored weather, validated on the held-out period | derived, learned | `ml/regimes.py` | ok | `data/models/regimes.json` |
| Exposure summaries | stored observations, documented 24 h references | derived from observed | `health_intel/service.py` | ok | evidence section empty until documents are indexed |
| Modelled pollutant concentrations (past 24 h, next 48 h) | Open-Meteo Air Quality API, passed through unchanged | **atmospheric-model output, badged "Atmospheric model"**, never an observation | `services/model_air_quality.py`, `components/air/ModelAirPanel.tsx` | ok | `tests/test_model_air_quality.py`; seen in the browser |
| XKDR CPCB history (training only) | `airquality.xkdr.org` archive via `ingest_xkdr.py` | real, history only (ends 2025-09-01) | `history/ingest_xkdr.py` | ok | 10.16M rows, 0 failed windows |
| Simulated concentration fields (transport and scenario runs) | `twin/transport.py` from interpolated observations and weather-model wind | **simulated**, never an observation or a forecast; scenarios are **hypothetical** | `twin/simulation.py`, `components/twin/simulationLayers.ts` | ok | `tests/test_transport.py`, `tests/test_simulation.py`; unknown cells are null |
| AQI variable and AQI layers (map and 3D) | CPCB method over stored hourly concentrations (`compute_aqi`), per station and hour | **derived**, null when the 16-hour/three-pollutant rules are not met; never interpolated or forecast | `twin/service.py:aqi_window`, `lib/twin/layers/scales.ts` | ok | `tests/test_twin_aqi.py`, `layers.test.ts` |
| 3D scene (columns, boundary-layer surface, particles, slab) | the same registry data as the map | columns observed/derived, surface and particles weather-model, slab **illustrative** | `components/twin/scene3d/*`, `lib/twin/scene/*` | ok | `scene/data.test.ts`, `scene/geometry.test.ts`; notes panel states data vs illustration |
| Forecast frames | contract-validated frames only (`lib/twin/contract.ts`) | model forecast, never a field unless a grid frame passes validation | `lib/twin/contract.ts` | ok | `contract.test.ts` |
| Jev decisions | TypeSafe API, shadow only | external model output, never shown as data | `jev/*` | not live | no key; mock tests only |

No unknown-provenance item was found.

## Guards added

1. `app/ml/dataset.py:dataset_provenance` + `train.py`: training **refuses** a history store whose raw rows are not tied to a recorded
   `ingest-air` run (`ingest_runs`). Hand-built fixtures fail this check. Only the test config sets `allow_test_fixtures`, and any
   such result and report is stamped "TEST FIXTURE DATA". Tests: `test_training_refuses...`, `test_results_and_report_from_fixture...`,
   `test_a_store_with_recorded_real_ingest_runs...`.
2. `tests/test_ml.py::test_production_code_never_imports_test_fixtures` scans `api/app` for imports of test modules.
3. `tests/test_ml.py::test_the_web_api_does_not_import_training_code...` keeps training and ML libraries out of the API process.
4. Earlier guards still apply: forecast refusal in code, number-grounding checks on assistant text and report summaries.

## Findings from real data (new in this pass)

* All CO sensors in the ingestion window carry the unit label "ppb" with values near 1 (physically impossible): excluded as `UNIT_SUSPECT` instead of being shown or modelled. This is the one place real provider data were found to be misleading.
* OpenAQ hourly values blend neighbouring provider hours; the twin and the exposure endpoint say so.
* The default twin window originally ended where only one late station reported; it now ends where at least half the typical number of stations reported.

## Remaining exceptions
* The conceptual inversion illustration (labelled, no numbers).
* The synthetic stores in `tests/` (never reachable from `app/`).
* The development dry-run model in the session scratchpad is not in the repository and is not used by the application.
