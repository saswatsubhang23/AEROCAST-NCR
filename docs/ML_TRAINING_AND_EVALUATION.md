# ML training and evaluation: results of run `4702878405a8`

Method, configuration and leakage rules: `docs/ml-training-pipeline.md`. Full generated tables (every model, every horizon,
calibration, per-station spread, location experiment): `docs/ml-model-comparison.md`. This page is the honest summary.

## Data
Real OpenAQ v3 + Open-Meteo archive data (3,009,696 + 614,810 hourly rows, 70 Delhi-NCR stations, 2025-10-09 to 2026-10-10),
see `docs/real-data-pipeline.md`. Training refuses any store not tied to a recorded real ingest run.

* Chronological split 80/20: development period ends 2026-07-28 17:00 UTC; the **test period is 2026-07-28 to 2026-10-10 (monsoon / post-monsoon)**.
* Model selection used three rolling-origin folds inside the development period; the test period was scored once.
* Targets trained: PM2.5, PM10, NO2, O3 at +1, +6, +24 h. SO2 and +3/+12/+48/+72 h are supported by the data but **not trained** yet. CO is unusable (unit labels).

## Held-out results (MAE, µg/m³; persistence = "same as the last observation")

| Pollutant | +1 h model / persistence | +6 h | +24 h |
|---|---|---|---|
| PM2.5 | 8.49 / 8.69 | 15.13 / 17.91 | 17.51 / 18.46 |
| PM10 | 16.71 / 16.97 | 34.29 / 39.82 | **42.44 / 41.38 (does not beat persistence)** |
| NO2 | 7.49 / 7.92 | 12.86 / 18.46 | 13.89 / 15.22 |
| O3 | 3.89 / 4.66 | 7.70 / 14.31 | 7.70 / 8.14 |

## What this does and does not show
* Gains at +1 h are small (1 to 5%): the last observation is already a strong predictor. Gains are largest at +6 h (8 to 46%).
* **PM10 at +24 h is worse than persistence.** The API marks that cell `beats_persistence_on_test = false` and the forecast provenance adds a WARNING when such a cell is served.
* Test period differs in season from training (training mostly winter/summer; test monsoon). Validation-fold and test errors differ; seasonal shift is a real limitation, not noise.
* Interval coverage on the test period is above the nominal 80% for several cells (intervals are wide; see per-horizon table in the comparison report).
* Station-level model only. Unseen-station experiment is in the comparison report; it is weaker than seen-station performance.
* Not validated against a full year-over-year cycle; one year of data cannot show inter-annual behaviour.
* Live use needs fresh inputs. The feed lags about two days for most CPCB stations, so most requests are refused; a request is answered only when a station within 15 km has an observation newer than 6 hours (verified: Delhi request on 2026-10-10 was served from New Delhi station 8118, input 5.7 h old, and says so).

## Back-test check through the API
`/api/twin/backtest?pollutant=pm25&station_id=6932&origin=2026-10-05T06:00:00Z`: +1 h predicted 23.0 [7.6, 35.2], observed 22.3;
+6 h predicted 48.8 [14.2, 73.7], observed 28.0 (an over-prediction inside the interval); +24 h had no observation. MAE of the two scored points 10.7. Two points illustrate the mechanism; they are not an accuracy estimate.

## Reproduce
`python -m app.ml train --config app/ml/configs/real_v1.json` then `python -m app.ml regimes`; artifacts in `api/data/models/<run_id>` with SHA-256 manifest, `latest.json` pointer.
