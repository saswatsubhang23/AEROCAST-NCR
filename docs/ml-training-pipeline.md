# ML training and evaluation pipeline

Offline, reproducible training of baselines and four model families on the validated historical dataset
(`docs/historical-data-pipeline.md`), plus an inference interface that speaks the existing forecast contract
(`docs/ml-forecast-interface.md`). **Actual scores are in the generated `docs/ml-model-comparison.md`; nothing is quoted here.**
Out of scope: the map simulation, a live data feed, any change to how the web app displays forecasts.

Code: `api/app/ml/` (`config`, `dataset`, `models`, `metrics`, `train`, `artifacts`, `inference`, `report`, `cli`).
Libraries: `api/requirements-ml.txt` (scikit-learn, XGBoost, LightGBM, SciPy, NumPy, joblib, psutil), pinned to the versions of the recorded runs.

## 1. Commands

```bash
cd api
python -m app.ml targets --coverage ../docs/data/coverage-report.json   # pollutants/horizons the data supports (verdicts from the data pipeline)
python -m app.history features --pollutants pm25,pm10                    # model-ready table for the targets you will train
python -m app.ml train [--pollutants pm25,pm10 --horizons 1,3,6,12,24 --config cfg.json]
python -m app.ml report                                                  # docs/ml-model-comparison.md from the latest run
python -m app.ml check                                                   # is the saved model loadable?
```

## 2. Choosing targets and horizons

Targets are not assumed. `python -m app.ml targets` reads the support table the data pipeline computed (stations with enough
origin/target pairs and span for each pollutant and horizon). Only cells it judges *supported* (or, if you choose, *limited*)
are trained. AQI is **not** a target: the CPCB AQI needs 24-hour averages of several pollutants, and with the sparse, lagged
feed it can rarely be computed from stored data; a PM2.5 or PM10 concentration is evaluated directly instead.

## 3. Protocol (all chronological)

1. **Split by time.** Development = first 80% of the origin time span, held-out **test = last 20%**, scored once at the end.
2. **Rolling-origin validation.** Inside development, `n_folds` expanding-window folds, each validating on the next window of
   10% of the span. A training row for horizon *h* is eligible only if its target time (origin + *h*) lies before the
   validation window (**label purging**), and a validation row's target must also lie inside its window, so the last fold cannot
   read a test-period value.
3. **Hyperparameters.** A small grid per model (2 settings) scored on the last fold at one horizon (`tune_horizon`), then reused
   for every horizon. Test data is never used.
4. **Model choice per horizon:** lowest mean rolling-fold MAE. Training accuracy is not computed for selection.
5. **Final models** are refit on all development rows and scored once on the test period, on the same rows as the baselines.
6. **Ensembles** (mean of the top two, mean of all models) are formed from validation results only; one is adopted only if its
   mean rolling MAE beats the best single model by at least `ensemble_min_gain` (default 1%). Its test score is reported either way.
7. **Samples.** Training rows per model and the evaluation sample are capped (see `MlConfig`); caps are deterministic random
   subsamples applied to *training rows only* and to a single shared evaluation sample, so every method is scored on identical rows.
   Tree models are additionally scored on every available test row.

## 4. Baselines and models

| Name | Definition |
|---|---|
| Persistence | the last observed value (`target_lag0`) |
| Seasonal naive | the value at the same hour of day, most recently before or at the origin: `o + h - 24 * ceil(h/24)` |
| Climatology | mean target by (station, IST hour of the target time), **from training rows only** |
| Random Forest, XGBoost, LightGBM | direct multi-horizon: one model per (pollutant, horizon); NaN passed natively |
| Support Vector Regression (RBF) | median imputer + standard scaler + scaled target, all inside the estimator and fitted on its training rows only; trained on a much smaller sample because of its cost |

Inputs are the validated model-ready features: pollutant lags and rolling statistics (with observed-count features), the six
pollutants' latest values, weather at or before the origin, wind vectors, IST time features, quality indicators. **Location**
(`station_lat`, `station_lon`) is *not* in the main comparison; it is judged by an experiment that removes a random 20% of
stations from training and scores seen vs unseen stations with and without coordinates.

Metrics: MAE, RMSE, R² (undefined, not 1, if the truth is constant), bias, sample count, skill versus persistence
(1 − MAE/MAE_persistence), per horizon, per station and region, and the unseen-station gap. Runtime is wall time of `fit` and
`predict`; memory is the **peak resident memory of the whole process** sampled every 50 ms during the call (it includes the
loaded dataset, so it is an upper bound for the model, not the model's own size).

## 5. Leakage prevention (each item is tested in `tests/test_ml.py`, `tests/test_history_*.py`)

| Risk | Prevention |
|---|---|
| Future values in features | features are built by `history/features.py` from data at or before the origin (pollutants) / origin (weather); tests perturb the future and require identical past features |
| Labels from the evaluated period in training | label purging (`train_mask`): target time before the evaluated window |
| Validation reading test labels | `eval_mask` requires the target inside the window; a test shifts the whole test period by +80 µg/m³ and requires identical tuning, validation scores and model choice |
| Imputation / scaling fitted on all data | inside the SVR estimator, fitted on its training rows; tree models need none (test checks the statistics equal the training medians and means) |
| Climatology from the full series | fitted on training rows only (test corrupts held-out targets and requires the same table) |
| Seasonal naive peeking | looks only at hours at or before the origin (test over horizons 1-72) |
| Tuning or selection on test | not possible by construction; selection uses rolling-fold MAE only |
| Training-set subsampling | applied to training rows only, deterministic |
| Serving differs from training | inference builds the row with the same `compute_rows`; a test compares the served row with the stored training row; the "hours since rain" feature is capped at the longest look-back so a 200-hour serving window equals full history |

Not leak-free by construction: whole-history decisions in the cleaning layer (`UNIT_SUSPECT` sensor exclusion, physical limits).
They fix which hours are usable once, before any split; see `docs/historical-data-pipeline.md` §8.

## 6. Artifacts (`api/data/models/<run_id>/`, git-ignored)

`config.json` (hashed into the run id), `feature_schema.json` (ordered input names, unit, horizons, latency), `environment.json`
(Python, OS, library versions), `intervals.json` (validation-residual quantiles per horizon), `results.json` (every score),
`models/*.joblib`, and `manifest.json` with the SHA-256 of each file and the data digest of the feature table. `latest.json`
at the model root points at the newest run. Run id = hash(config + data digest): the same config on the same data gives the
same id, and a test shows the scores repeat (up to floating-point summation order of threaded libraries).

Loading refuses (as "unavailable") a run with a missing or edited file (checksum), a manifest pointing outside the folder, or a
scikit-learn/XGBoost/LightGBM version that differs from training in major.minor. **Only point `ML_LOCAL_MODEL_DIR` at a folder you
produced yourself:** `joblib` files are pickles.

## 7. Request-time inference

`app/ml/inference.py` implements the `ForecastProvider` protocol, so `/api/forecast`, reports and the Air Quality panel work
unchanged. Training code and ML libraries are not imported by the web API at start-up (a test checks `sys.modules` in a clean process).
It is off unless `ML_LOCAL_MODEL_DIR` is set and `ML_FORECAST_URL` is empty (an external service wins).

For a `ForecastRequest` it: picks the nearest station within `ML_MAX_STATION_KM` (15) whose newest usable observation is at most
`ML_MAX_INPUT_AGE_HOURS` (6) old; reads 200 h of history from `ML_HISTORY_DB`; builds the model row with `compute_rows`; predicts
every trained horizon that falls after `issued_at` and within the requested range; clips at 0; adds the empirical interval; and
returns a contract-valid `ForecastResponse` with provenance (training window, inputs, caveats). Several requested pollutants
are answered if each has a model; unsupported ones are left out.

**It answers "unavailable" (HTTP 503 `forecast_unavailable`) rather than guess** when: no model directory is set or the run is
missing/edited/incompatible; no station is within range; the newest observation is too old; there are no weather inputs at the
origin; the history database is missing; or no requested pollutant has a model. Because the real OpenAQ/CPCB feed was about
two days behind when measured, **a request made "now" will normally be unavailable**; requests inside the stored history
(back-testing) are answered. A live ingestion path is not part of this phase.

## 8. Limitations

See the "Limitations" section of the generated comparison for the figures of the recorded run. Structural ones: about one year of
history (one winter, one monsoon, no repeated seasons), a test period from a different season than most training data,
published data lag, OpenAQ hourly values that blend neighbouring CPCB hours, archive weather standing in for the forecast
weather a real system would have, small hyperparameter grids, subsampled training sets, and no calibration guarantee for the
intervals beyond what the report measures.
