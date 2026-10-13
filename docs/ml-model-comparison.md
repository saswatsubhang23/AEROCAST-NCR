# Model comparison report

Run `4702878405a8`, created 2026-10-09T23:42:11Z, total training and evaluation time 116.0 min. Generated from the run's `results.json`; every figure below was computed by the pipeline, none is typed in. Scores are in µg/m³. Dataset provenance: **real_source_ingest** (3,009,696 raw OpenAQ rows from 6 recorded ingest runs).

Libraries: joblib 1.6.0, lightgbm 4.7.0, numpy 2.5.3, psutil 7.2.2, scikit-learn 1.9.1, scipy 1.18.1, xgboost 3.4.1; Python 3.14.6; Windows-11-10.0.26300-SP0.

## Targets and horizons chosen from the data

Targets were not assumed. The historical data pipeline's support table (`docs/data/coverage-report.md`) judges every pollutant and horizon; this run trained only pm25, pm10, no2, o3 at horizons +1 h, +6 h, +24 h.

| pollutant | +1 h | +3 h | +6 h | +12 h | +24 h | +48 h | +72 h |
|---|---|---|---|---|---|---|---|
| pm25 | supported (69 st) | supported (69 st) | supported (69 st) | supported (69 st) | supported (69 st) | supported (69 st) | supported (69 st) |
| pm10 | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) |
| no2 | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) |
| so2 | supported (59 st) | supported (59 st) | supported (59 st) | supported (59 st) | supported (59 st) | supported (59 st) | supported (59 st) |
| co | insufficient (0 st) | insufficient (0 st) | insufficient (0 st) | insufficient (0 st) | insufficient (0 st) | insufficient (0 st) | insufficient (0 st) |
| o3 | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) | supported (68 st) |

## Protocol

* **Chronological split.** Origins are split by time: development = first 80% of the time span, held-out test = the last 20%, scored once at the end.
* **Rolling-origin validation.** 3 expanding-window folds inside development, each validating on a window of 10% of the span. A training row for horizon h is used only if its target time (origin + h) precedes the validation window (label purging).
* **Hyperparameters** come from a small grid scored on the last fold at +6 h and are reused for the other horizons. The test period is never used for any choice.
* **Model selection** per horizon is the lowest mean rolling-fold MAE. Training accuracy is not used anywhere.
* **Preprocessing** that learns anything (SVR median imputation and scaling) is inside the estimator and fitted on its training rows only. Trees receive NaN as is.
* **Samples.** Training rows are capped per model (lightgbm 100,000, random_forest 50,000, svr 6,000, xgboost 100,000), evaluation sets at 20,000 rows; the cap is a deterministic random subsample and every model and baseline is scored on the *same* rows. Tree models are also scored on every available test row (`full test`).
* **Inputs** are the validated model-ready features (pollutant lags and rolling statistics, weather at or before the origin, wind vectors, IST time features); location features are not included in the main comparison. Pollutant publication latency used when the features were built: 0 h.

## no2

513,251 origin rows from 69 stations, 79 input features, data digest `580f2268397b`. Data 2025-10-09T00 to 2026-10-07T14; development before 2026-07-26T22; **test from 2026-07-26T22**. Validation windows: 2026-04-08T19 to 2026-05-15T04; 2026-05-15T04 to 2026-06-20T13; 2026-06-20T13 to 2026-07-26T22.

### Held-out test results

**+1 h** — test sample 20,000 of 102,127 available rows. Model chosen on validation: **LightGBM** (adopted ensemble: lightgbm + random_forest).

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 7.92 | 17.05 | 0.801 | -0.03 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 14.94 | 28.93 | 0.428 | -0.44 | 20,000 | -88.5% | | | | | |
| Climatology (train mean by station and hour) | 37.90 | 49.92 | -0.703 | 29.21 | 20,000 | -378.3% | | | | | |
| LightGBM ★ | 7.55 | 16.23 | 0.820 | -0.02 | 20,000 | +4.7% | 9.23 | 18.6 | 1.9 | 794 | 100,000 |
| Random Forest | 7.59 | 16.09 | 0.823 | 0.45 | 20,000 | +4.2% | 9.24 | 18.6 | 0.7 | 670 | 50,000 |
| Support Vector Regression | 9.78 | 19.52 | 0.739 | -0.80 | 20,000 | -23.4% | 16.50 | 14.1 | 30.2 | 695 | 6,000 |
| XGBoost | 7.56 | 16.31 | 0.818 | -0.09 | 20,000 | +4.6% | 9.33 | 21.5 | 0.7 | 810 | 100,000 |
| Ensemble `mean_top2` (lightgbm + random_forest) — adopted | 7.49 | 16.02 | 0.825 | 0.21 | 20,000 | +5.5% | 9.05 | | | | |

Full test set (every available row, tree models): LightGBM MAE 7.51 vs persistence 7.87 (n=102,127); Random Forest MAE 7.53 vs persistence 7.87 (n=102,127); XGBoost MAE 7.55 vs persistence 7.87 (n=102,127).

**+24 h** — test sample 20,000 of 93,980 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 15.22 | 30.38 | 0.354 | -0.43 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 15.22 | 30.38 | 0.354 | -0.43 | 20,000 | +0.0% | | | | | |
| Climatology (train mean by station and hour) | 38.06 | 49.87 | -0.742 | 29.09 | 20,000 | -150.0% | | | | | |
| LightGBM | 14.17 | 25.29 | 0.552 | 1.75 | 20,000 | +6.9% | 18.82 | 19.6 | 1.6 | 910 | 100,000 |
| Random Forest ★ | 13.89 | 25.44 | 0.547 | 1.10 | 20,000 | +8.8% | 18.19 | 18.7 | 0.7 | 799 | 50,000 |
| Support Vector Regression | 16.42 | 27.18 | 0.483 | 1.43 | 20,000 | -7.8% | 24.72 | 12.8 | 35.2 | 818 | 6,000 |
| XGBoost | 14.25 | 25.34 | 0.550 | 1.78 | 20,000 | +6.4% | 19.05 | 21.9 | 0.7 | 929 | 100,000 |
| Ensemble `mean_top2` (random_forest + lightgbm) — not adopted | 13.89 | 25.21 | 0.555 | 1.43 | 20,000 | +8.7% | 18.05 | | | | |

Full test set (every available row, tree models): LightGBM MAE 14.16 vs persistence 14.99 (n=93,980); Random Forest MAE 13.80 vs persistence 14.99 (n=93,980); XGBoost MAE 14.20 vs persistence 14.99 (n=93,980).

**+6 h** — test sample 20,000 of 98,027 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 18.46 | 31.99 | 0.248 | 0.40 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 14.71 | 28.07 | 0.421 | -0.51 | 20,000 | +20.3% | | | | | |
| Climatology (train mean by station and hour) | 37.55 | 48.87 | -0.755 | 29.12 | 20,000 | -103.4% | | | | | |
| LightGBM | 12.96 | 22.28 | 0.635 | -0.55 | 20,000 | +29.8% | 17.99 | 20.5 | 1.9 | 853 | 100,000 |
| Random Forest ★ | 12.86 | 22.43 | 0.630 | 0.07 | 20,000 | +30.3% | 17.45 | 15.7 | 0.7 | 740 | 50,000 |
| Support Vector Regression | 14.63 | 23.72 | 0.587 | -1.39 | 20,000 | +20.7% | 22.75 | 14.3 | 39.6 | 765 | 6,000 |
| XGBoost | 13.55 | 22.49 | 0.628 | 1.16 | 20,000 | +26.6% | 17.88 | 22.0 | 0.6 | 872 | 100,000 |
| Ensemble `mean_top2` (random_forest + xgboost) — not adopted | 13.02 | 22.26 | 0.636 | 0.62 | 20,000 | +29.5% | 17.35 | | | | |

Full test set (every available row, tree models): LightGBM MAE 13.50 vs persistence 19.04 (n=98,027); Random Forest MAE 13.41 vs persistence 19.04 (n=98,027); XGBoost MAE 14.02 vs persistence 19.04 (n=98,027).

### Rolling-origin validation (MAE by fold)

| horizon | method | fold 0 | fold 1 | fold 2 | mean | sd |
|---|---|---:|---:|---:|---:|---:|
| +1 h | Climatology (train mean by station and hour) | 39.36 | 38.97 | 41.71 | 40.01 | 1.21 |
| +1 h | LightGBM | 9.83 | 9.94 | 7.91 | 9.23 | 0.93 |
| +1 h | Persistence | 11.08 | 10.51 | 8.19 | 9.93 | 1.25 |
| +1 h | Random Forest | 10.00 | 9.77 | 7.95 | 9.24 | 0.92 |
| +1 h | Seasonal naive (same hour, previous day) | 20.86 | 21.81 | 15.64 | 19.43 | 2.71 |
| +1 h | Support Vector Regression | 21.15 | 13.34 | 15.01 | 16.50 | 3.36 |
| +1 h | XGBoost | 9.94 | 10.11 | 7.95 | 9.33 | 0.98 |
| +24 h | Climatology (train mean by station and hour) | 39.92 | 39.23 | 42.00 | 40.38 | 1.17 |
| +24 h | LightGBM | 21.66 | 19.36 | 15.45 | 18.82 | 2.56 |
| +24 h | Persistence | 20.72 | 21.68 | 15.54 | 19.31 | 2.69 |
| +24 h | Random Forest | 19.51 | 19.79 | 15.29 | 18.19 | 2.06 |
| +24 h | Seasonal naive (same hour, previous day) | 20.72 | 21.68 | 15.54 | 19.31 | 2.69 |
| +24 h | Support Vector Regression | 28.31 | 22.57 | 23.29 | 24.72 | 2.55 |
| +24 h | XGBoost | 21.51 | 19.27 | 16.38 | 19.05 | 2.10 |
| +6 h | Climatology (train mean by station and hour) | 39.81 | 39.09 | 41.65 | 40.18 | 1.08 |
| +6 h | LightGBM | 18.90 | 21.49 | 13.59 | 17.99 | 3.29 |
| +6 h | Persistence | 32.32 | 28.87 | 19.04 | 26.74 | 5.62 |
| +6 h | Random Forest | 20.02 | 18.74 | 13.60 | 17.45 | 2.78 |
| +6 h | Seasonal naive (same hour, previous day) | 20.28 | 21.88 | 15.63 | 19.26 | 2.65 |
| +6 h | Support Vector Regression | 27.78 | 21.63 | 18.84 | 22.75 | 3.73 |
| +6 h | XGBoost | 19.05 | 20.94 | 13.66 | 17.88 | 3.08 |

### Hyperparameter search (last fold, validation only)

| model | tuned at | candidate | validation MAE | fit s | chosen |
|---|---|---|---:|---:|---|
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 31}` | 13.71 | 15.1 |  |
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 63}` | 13.56 | 20.9 | yes |
| Random Forest | +6 h | `{'max_depth': 12, 'min_samples_leaf': 10}` | 13.58 | 12.2 |  |
| Random Forest | +6 h | `{'max_depth': 20, 'min_samples_leaf': 5}` | 13.57 | 17.3 | yes |
| Support Vector Regression | +6 h | `{'C': 3.0, 'epsilon': 0.05}` | 19.00 | 15.4 | yes |
| Support Vector Regression | +6 h | `{'C': 10.0, 'epsilon': 0.05}` | 20.78 | 26.7 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 4}` | 13.71 | 15.3 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 6}` | 13.62 | 21.7 | yes |

### Ensembles (decided on validation)

An ensemble is adopted only if its mean rolling-fold MAE is at least 1% below the best single model.

| horizon | best single (validation MAE) | best ensemble (validation MAE) | adopted | test MAE of the ensemble | test MAE of the best single |
|---|---|---|---|---:|---:|
| +1 h | LightGBM (9.23) | mean_top2 (9.05) | yes | 7.49 | 7.55 |
| +24 h | Random Forest (18.19) | mean_top2 (18.05) | no | 13.89 | 13.89 |
| +6 h | Random Forest (17.45) | mean_top2 (17.35) | no | 13.02 | 12.86 |

### Performance by location (final model, test sample)

| horizon | stations | station MAE min / median / max | mean MAE by region |
|---|---:|---|---|
| +1 h | 68 | 0.48 / 7.03 / 24.12 | Delhi 8.63, Faridabad 2.00, Ghaziabad 7.68, Gurugram 6.59, Noida 9.31, Other NCR 5.97 |
| +24 h | 68 | 0.51 / 13.61 / 52.37 | Delhi 16.21, Faridabad 3.19, Ghaziabad 14.81, Gurugram 9.87, Noida 19.64, Other NCR 12.57 |
| +6 h | 68 | 0.52 / 12.75 / 48.03 | Delhi 14.83, Faridabad 2.79, Ghaziabad 13.52, Gurugram 11.16, Noida 17.08, Other NCR 10.60 |

### Generalisation to unseen stations

14 randomly chosen stations (50, 5570, 5616, 5630, 5650, 6358, 6929, 6949, 6953, 8239, 8365, 8475, 10908, 301388) were removed from training; the same model type was scored on the test period for stations it had seen and ones it had not. Lower is better.

| horizon | model | inputs | seen MAE | unseen MAE | persistence seen / unseen | n seen / unseen |
|---|---|---|---:|---:|---|---|
| +6 h | Random Forest | no location | 12.97 | 13.40 | 18.21 / 19.40 | 15,859 / 4,141 |
| +6 h | Random Forest | with station coordinates | 12.92 | 13.41 | 18.21 / 19.40 | 15,859 / 4,141 |

### Prediction-interval calibration

Intervals use signed validation-residual quantiles of the final model (never test residuals). Empirical coverage is measured on the test sample.

| horizon | nominal | empirical coverage (test) | mean width |
|---|---:|---:|---:|
| +1 h | 80% | 85.2% | 26.3 |
| +24 h | 80% | 87.4% | 53.2 |
| +6 h | 80% | 88.0% | 51.2 |

### Most influential features (tree-model impurity/gain importance at the tuning horizon; indicative, not causal)

* **LightGBM**: `obs_o3` 3.2%, `target_std_72h` 3.2%, `target_mean_24h` 3.0%, `target_std_24h` 3.0%, `doy_sin` 2.7%, `target_lag24` 2.7%, `wx_pressure_tend_3h` 2.6%, `target_lag0` 2.6%
* **Random Forest**: `target_mean_24h` 28.0%, `target_mean_72h` 15.3%, `target_max_24h` 9.8%, `target_mean_12h` 4.9%, `target_max_72h` 2.6%, `target_max_12h` 2.5%, `wx_pressure_tend_3h` 2.5%, `target_min_24h` 2.3%
* **XGBoost**: `target_mean_24h` 32.3%, `target_mean_72h` 11.6%, `wx_pressure_tend_3h` 3.3%, `hour_ist` 3.2%, `hour_sin` 2.7%, `target_lag0` 2.1%, `wx_sw` 1.5%, `target_min_24h` 1.5%

## o3

511,243 origin rows from 68 stations, 79 input features, data digest `580f2268397b`. Data 2025-10-09T00 to 2026-10-07T14; development before 2026-07-26T22; **test from 2026-07-26T22**. Validation windows: 2026-04-08T19 to 2026-05-15T04; 2026-05-15T04 to 2026-06-20T13; 2026-06-20T13 to 2026-07-26T22.

### Held-out test results

**+1 h** — test sample 20,000 of 101,665 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 4.66 | 10.24 | 0.813 | -0.11 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 8.02 | 18.24 | 0.406 | 0.08 | 20,000 | -72.1% | | | | | |
| Climatology (train mean by station and hour) | 17.16 | 25.70 | -0.178 | 10.03 | 20,000 | -268.4% | | | | | |
| LightGBM | 3.96 | 8.93 | 0.858 | 0.27 | 20,000 | +15.0% | 5.68 | 18.6 | 1.6 | 915 | 100,000 |
| Random Forest ★ | 3.89 | 8.88 | 0.859 | 0.35 | 20,000 | +16.6% | 5.42 | 13.1 | 0.7 | 818 | 50,000 |
| Support Vector Regression | 5.08 | 9.94 | 0.824 | 0.22 | 20,000 | -8.9% | 9.08 | 11.8 | 28.4 | 797 | 6,000 |
| XGBoost | 3.99 | 9.03 | 0.855 | 0.35 | 20,000 | +14.4% | 5.81 | 20.8 | 0.8 | 951 | 100,000 |
| Ensemble `mean_top2` (random_forest + lightgbm) — not adopted | 3.87 | 8.83 | 0.861 | 0.31 | 20,000 | +16.9% | 5.42 | | | | |

Full test set (every available row, tree models): LightGBM MAE 4.02 vs persistence 4.64 (n=101,665); Random Forest MAE 3.95 vs persistence 4.64 (n=101,665); XGBoost MAE 4.06 vs persistence 4.64 (n=101,665).

**+24 h** — test sample 20,000 of 93,729 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 8.14 | 18.74 | 0.382 | 0.03 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 8.14 | 18.74 | 0.382 | 0.03 | 20,000 | +0.0% | | | | | |
| Climatology (train mean by station and hour) | 17.37 | 26.15 | -0.202 | 10.01 | 20,000 | -113.5% | | | | | |
| LightGBM | 7.83 | 15.26 | 0.591 | 0.79 | 20,000 | +3.8% | 12.86 | 18.6 | 1.7 | 934 | 100,000 |
| Random Forest ★ | 7.70 | 15.37 | 0.585 | 0.71 | 20,000 | +5.4% | 11.35 | 13.8 | 0.5 | 828 | 50,000 |
| Support Vector Regression | 8.98 | 16.02 | 0.549 | 0.33 | 20,000 | -10.3% | 14.49 | 13.2 | 33.9 | 853 | 6,000 |
| XGBoost | 7.89 | 15.26 | 0.590 | 0.90 | 20,000 | +3.1% | 13.19 | 19.7 | 0.8 | 961 | 100,000 |
| Ensemble `mean_top2` (random_forest + lightgbm) — not adopted | 7.69 | 15.23 | 0.592 | 0.75 | 20,000 | +5.5% | 11.82 | | | | |

Full test set (every available row, tree models): LightGBM MAE 7.71 vs persistence 8.03 (n=93,729); Random Forest MAE 7.57 vs persistence 8.03 (n=93,729); XGBoost MAE 7.75 vs persistence 8.03 (n=93,729).

**+6 h** — test sample 20,000 of 97,605 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 14.31 | 26.26 | -0.168 | -0.98 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 8.03 | 18.43 | 0.425 | -0.09 | 20,000 | +43.9% | | | | | |
| Climatology (train mean by station and hour) | 17.65 | 26.63 | -0.200 | 10.16 | 20,000 | -23.4% | | | | | |
| LightGBM | 7.73 | 14.81 | 0.629 | 0.67 | 20,000 | +46.0% | 11.79 | 19.8 | 1.9 | 919 | 100,000 |
| Random Forest ★ | 7.70 | 14.81 | 0.628 | 0.70 | 20,000 | +46.2% | 11.28 | 12.6 | 0.7 | 817 | 50,000 |
| Support Vector Regression | 8.61 | 15.74 | 0.580 | -1.67 | 20,000 | +39.8% | 12.75 | 14.2 | 39.1 | 836 | 6,000 |
| XGBoost | 7.74 | 14.75 | 0.632 | 0.88 | 20,000 | +45.9% | 12.00 | 21.4 | 0.6 | 951 | 100,000 |
| Ensemble `mean_all` (random_forest + lightgbm + xgboost + svr) — not adopted | 7.55 | 14.60 | 0.639 | 0.14 | 20,000 | +47.2% | 11.19 | | | | |

Full test set (every available row, tree models): LightGBM MAE 7.77 vs persistence 14.20 (n=97,605); Random Forest MAE 7.78 vs persistence 14.20 (n=97,605); XGBoost MAE 7.79 vs persistence 14.20 (n=97,605).

### Rolling-origin validation (MAE by fold)

| horizon | method | fold 0 | fold 1 | fold 2 | mean | sd |
|---|---|---:|---:|---:|---:|---:|
| +1 h | Climatology (train mean by station and hour) | 18.46 | 19.23 | 19.10 | 18.93 | 0.34 |
| +1 h | LightGBM | 5.59 | 6.73 | 4.73 | 5.68 | 0.82 |
| +1 h | Persistence | 7.11 | 7.17 | 5.10 | 6.46 | 0.96 |
| +1 h | Random Forest | 5.61 | 6.00 | 4.65 | 5.42 | 0.56 |
| +1 h | Seasonal naive (same hour, previous day) | 11.79 | 14.01 | 10.12 | 11.97 | 1.59 |
| +1 h | Support Vector Regression | 10.82 | 8.58 | 7.83 | 9.08 | 1.27 |
| +1 h | XGBoost | 5.62 | 6.84 | 4.97 | 5.81 | 0.77 |
| +24 h | Climatology (train mean by station and hour) | 18.58 | 19.45 | 19.39 | 19.14 | 0.40 |
| +24 h | LightGBM | 13.03 | 14.93 | 10.62 | 12.86 | 1.77 |
| +24 h | Persistence | 11.74 | 14.18 | 10.01 | 11.98 | 1.71 |
| +24 h | Random Forest | 11.36 | 12.66 | 10.03 | 11.35 | 1.07 |
| +24 h | Seasonal naive (same hour, previous day) | 11.74 | 14.18 | 10.01 | 11.98 | 1.71 |
| +24 h | Support Vector Regression | 15.93 | 15.06 | 12.48 | 14.49 | 1.46 |
| +24 h | XGBoost | 13.47 | 14.88 | 11.23 | 13.19 | 1.50 |
| +6 h | Climatology (train mean by station and hour) | 19.07 | 19.43 | 19.19 | 19.23 | 0.15 |
| +6 h | LightGBM | 11.83 | 14.30 | 9.22 | 11.79 | 2.07 |
| +6 h | Persistence | 26.43 | 25.35 | 14.89 | 22.22 | 5.21 |
| +6 h | Random Forest | 11.86 | 12.57 | 9.43 | 11.28 | 1.34 |
| +6 h | Seasonal naive (same hour, previous day) | 11.88 | 14.43 | 10.04 | 12.12 | 1.80 |
| +6 h | Support Vector Regression | 14.14 | 13.58 | 10.52 | 12.75 | 1.59 |
| +6 h | XGBoost | 12.05 | 14.53 | 9.42 | 12.00 | 2.09 |

### Hyperparameter search (last fold, validation only)

| model | tuned at | candidate | validation MAE | fit s | chosen |
|---|---|---|---:|---:|---|
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 31}` | 9.48 | 14.4 |  |
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 63}` | 9.22 | 20.3 | yes |
| Random Forest | +6 h | `{'max_depth': 12, 'min_samples_leaf': 10}` | 9.47 | 13.4 | yes |
| Random Forest | +6 h | `{'max_depth': 20, 'min_samples_leaf': 5}` | 9.64 | 17.1 |  |
| Support Vector Regression | +6 h | `{'C': 3.0, 'epsilon': 0.05}` | 10.53 | 11.4 | yes |
| Support Vector Regression | +6 h | `{'C': 10.0, 'epsilon': 0.05}` | 11.98 | 23.1 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 4}` | 9.48 | 15.5 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 6}` | 9.42 | 21.6 | yes |

### Ensembles (decided on validation)

An ensemble is adopted only if its mean rolling-fold MAE is at least 1% below the best single model.

| horizon | best single (validation MAE) | best ensemble (validation MAE) | adopted | test MAE of the ensemble | test MAE of the best single |
|---|---|---|---|---:|---:|
| +1 h | Random Forest (5.42) | mean_top2 (5.42) | no | 3.87 | 3.89 |
| +24 h | Random Forest (11.35) | mean_top2 (11.82) | no | 7.69 | 7.70 |
| +6 h | Random Forest (11.28) | mean_all (11.19) | no | 7.55 | 7.70 |

### Performance by location (final model, test sample)

| horizon | stations | station MAE min / median / max | mean MAE by region |
|---|---:|---|---|
| +1 h | 68 | 0.43 / 3.12 / 14.56 | Delhi 3.53, Faridabad 3.61, Ghaziabad 3.64, Gurugram 4.00, Noida 6.21, Other NCR 4.21 |
| +24 h | 68 | 0.88 / 6.04 / 26.82 | Delhi 7.42, Faridabad 3.76, Ghaziabad 7.35, Gurugram 6.95, Noida 15.44, Other NCR 7.79 |
| +6 h | 68 | 0.76 / 6.38 / 28.26 | Delhi 7.18, Faridabad 4.02, Ghaziabad 7.03, Gurugram 8.15, Noida 14.03, Other NCR 8.16 |

### Generalisation to unseen stations

14 randomly chosen stations (50, 5570, 5613, 5630, 5650, 6358, 6924, 6938, 6951, 8235, 8365, 8472, 10900, 301388) were removed from training; the same model type was scored on the test period for stations it had seen and ones it had not. Lower is better.

| horizon | model | inputs | seen MAE | unseen MAE | persistence seen / unseen | n seen / unseen |
|---|---|---|---:|---:|---|---|
| +6 h | Random Forest | no location | 7.99 | 7.12 | 14.70 / 12.80 | 15,870 / 4,130 |
| +6 h | Random Forest | with station coordinates | 7.98 | 7.13 | 14.70 / 12.80 | 15,870 / 4,130 |

### Prediction-interval calibration

Intervals use signed validation-residual quantiles of the final model (never test residuals). Empirical coverage is measured on the test sample.

| horizon | nominal | empirical coverage (test) | mean width |
|---|---:|---:|---:|
| +1 h | 80% | 87.0% | 15.1 |
| +24 h | 80% | 88.4% | 30.5 |
| +6 h | 80% | 89.1% | 31.5 |

### Most influential features (tree-model impurity/gain importance at the tuning horizon; indicative, not causal)

* **LightGBM**: `target_mean_24h` 3.3%, `target_mean_72h` 3.3%, `doy_cos` 3.2%, `doy_sin` 3.2%, `target_std_72h` 3.0%, `target_max_72h` 2.9%, `target_max_24h` 2.6%, `wx_hours_since_rain` 2.4%
* **Random Forest**: `hour_ist` 16.1%, `hour_sin` 15.5%, `target_mean_24h` 10.1%, `target_mean_72h` 8.4%, `hour_cos` 7.2%, `target_max_24h` 7.1%, `target_std_72h` 5.1%, `target_std_24h` 3.6%
* **XGBoost**: `hour_ist` 15.6%, `hour_sin` 14.1%, `target_max_24h` 7.6%, `target_mean_24h` 6.8%, `target_std_72h` 4.3%, `hour_cos` 4.2%, `obs_o3` 3.8%, `target_mean_72h` 3.6%

## pm10

511,337 origin rows from 69 stations, 79 input features, data digest `580f2268397b`. Data 2025-10-09T00 to 2026-10-07T14; development before 2026-07-26T22; **test from 2026-07-26T22**. Validation windows: 2026-04-08T19 to 2026-05-15T04; 2026-05-15T04 to 2026-06-20T13; 2026-06-20T13 to 2026-07-26T22.

### Held-out test results

**+1 h** — test sample 20,000 of 100,439 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 16.97 | 32.08 | 0.791 | -0.51 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 42.03 | 66.28 | 0.107 | -0.39 | 20,000 | -147.7% | | | | | |
| Climatology (train mean by station and hour) | 119.67 | 136.75 | -2.800 | 112.51 | 20,000 | -605.3% | | | | | |
| LightGBM | 16.54 | 29.64 | 0.821 | 1.46 | 20,000 | +2.5% | 29.80 | 18.7 | 1.7 | 716 | 100,000 |
| Random Forest ★ | 16.71 | 30.39 | 0.812 | 2.96 | 20,000 | +1.5% | 27.59 | 13.0 | 0.7 | 567 | 50,000 |
| Support Vector Regression | 21.68 | 34.65 | 0.756 | 4.72 | 20,000 | -27.8% | 42.37 | 15.3 | 42.2 | 611 | 6,000 |
| XGBoost | 16.69 | 30.06 | 0.816 | 1.40 | 20,000 | +1.7% | 31.20 | 15.0 | 0.5 | 699 | 100,000 |
| Ensemble `mean_top2` (random_forest + lightgbm) — not adopted | 16.43 | 29.80 | 0.820 | 2.21 | 20,000 | +3.1% | 27.96 | | | | |

Full test set (every available row, tree models): LightGBM MAE 16.40 vs persistence 16.91 (n=100,439); Random Forest MAE 16.59 vs persistence 16.91 (n=100,439); XGBoost MAE 16.56 vs persistence 16.91 (n=100,439).

**+24 h** — test sample 20,000 of 92,050 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 41.38 | 64.91 | 0.136 | -0.34 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 41.38 | 64.91 | 0.136 | -0.34 | 20,000 | +0.0% | | | | | |
| Climatology (train mean by station and hour) | 121.28 | 138.60 | -2.938 | 114.56 | 20,000 | -193.1% | | | | | |
| LightGBM | 41.70 | 58.79 | 0.291 | 14.89 | 20,000 | -0.8% | 71.79 | 20.5 | 1.4 | 734 | 100,000 |
| Random Forest ★ | 42.44 | 58.99 | 0.287 | 19.09 | 20,000 | -2.5% | 67.11 | 13.0 | 0.6 | 610 | 50,000 |
| Support Vector Regression | 46.40 | 63.51 | 0.173 | 5.89 | 20,000 | -12.1% | 77.95 | 13.1 | 38.2 | 666 | 6,000 |
| XGBoost | 42.87 | 58.84 | 0.290 | 18.57 | 20,000 | -3.6% | 69.39 | 15.4 | 0.5 | 735 | 100,000 |
| Ensemble `mean_top2` (random_forest + xgboost) — not adopted | 42.06 | 58.07 | 0.309 | 18.83 | 20,000 | -1.6% | 67.19 | | | | |

Full test set (every available row, tree models): LightGBM MAE 41.99 vs persistence 41.58 (n=92,050); Random Forest MAE 42.80 vs persistence 41.58 (n=92,050); XGBoost MAE 43.16 vs persistence 41.58 (n=92,050).

**+6 h** — test sample 20,000 of 96,061 available rows. Model chosen on validation: **Random Forest** (adopted ensemble: random_forest + lightgbm + xgboost + svr).

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 39.82 | 63.33 | 0.182 | -0.03 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 41.46 | 65.79 | 0.117 | -1.13 | 20,000 | -4.1% | | | | | |
| Climatology (train mean by station and hour) | 120.08 | 137.33 | -2.847 | 112.91 | 20,000 | -201.5% | | | | | |
| LightGBM | 35.53 | 53.32 | 0.420 | 10.18 | 20,000 | +10.8% | 60.52 | 22.0 | 1.5 | 726 | 100,000 |
| Random Forest ★ | 34.06 | 51.50 | 0.459 | 8.13 | 20,000 | +14.5% | 59.96 | 13.0 | 0.6 | 595 | 50,000 |
| Support Vector Regression | 38.76 | 56.02 | 0.360 | 8.01 | 20,000 | +2.7% | 66.49 | 14.4 | 41.3 | 646 | 6,000 |
| XGBoost | 35.37 | 52.77 | 0.432 | 10.78 | 20,000 | +11.2% | 61.86 | 15.5 | 0.5 | 716 | 100,000 |
| Ensemble `mean_all` (random_forest + lightgbm + xgboost + svr) — adopted | 34.29 | 51.45 | 0.460 | 9.27 | 20,000 | +13.9% | 58.51 | | | | |

Full test set (every available row, tree models): LightGBM MAE 35.97 vs persistence 40.60 (n=96,061); Random Forest MAE 34.58 vs persistence 40.60 (n=96,061); XGBoost MAE 35.89 vs persistence 40.60 (n=96,061).

### Rolling-origin validation (MAE by fold)

| horizon | method | fold 0 | fold 1 | fold 2 | mean | sd |
|---|---|---:|---:|---:|---:|---:|
| +1 h | Climatology (train mean by station and hour) | 103.53 | 98.53 | 118.29 | 106.79 | 8.39 |
| +1 h | LightGBM | 28.82 | 33.40 | 27.18 | 29.80 | 2.64 |
| +1 h | Persistence | 32.01 | 30.38 | 24.84 | 29.08 | 3.07 |
| +1 h | Random Forest | 28.41 | 28.77 | 25.59 | 27.59 | 1.42 |
| +1 h | Seasonal naive (same hour, previous day) | 74.98 | 78.54 | 72.14 | 75.22 | 2.62 |
| +1 h | Support Vector Regression | 47.09 | 38.74 | 41.28 | 42.37 | 3.49 |
| +1 h | XGBoost | 35.07 | 31.85 | 26.69 | 31.20 | 3.45 |
| +24 h | Climatology (train mean by station and hour) | 104.10 | 101.33 | 120.16 | 108.53 | 8.30 |
| +24 h | LightGBM | 77.87 | 69.04 | 68.47 | 71.79 | 4.30 |
| +24 h | Persistence | 76.09 | 78.26 | 72.41 | 75.59 | 2.42 |
| +24 h | Random Forest | 67.12 | 64.92 | 69.28 | 67.11 | 1.78 |
| +24 h | Seasonal naive (same hour, previous day) | 76.09 | 78.26 | 72.41 | 75.59 | 2.42 |
| +24 h | Support Vector Regression | 84.42 | 67.84 | 81.60 | 77.95 | 7.24 |
| +24 h | XGBoost | 77.64 | 65.28 | 65.26 | 69.39 | 5.83 |
| +6 h | Climatology (train mean by station and hour) | 102.87 | 99.42 | 118.10 | 106.80 | 8.12 |
| +6 h | LightGBM | 66.11 | 61.84 | 53.60 | 60.52 | 5.19 |
| +6 h | Persistence | 86.67 | 74.34 | 65.07 | 75.36 | 8.84 |
| +6 h | Random Forest | 65.44 | 59.57 | 54.88 | 59.96 | 4.32 |
| +6 h | Seasonal naive (same hour, previous day) | 74.24 | 78.39 | 70.87 | 74.50 | 3.08 |
| +6 h | Support Vector Regression | 68.91 | 68.00 | 62.56 | 66.49 | 2.81 |
| +6 h | XGBoost | 70.88 | 60.01 | 54.70 | 61.86 | 6.73 |

### Hyperparameter search (last fold, validation only)

| model | tuned at | candidate | validation MAE | fit s | chosen |
|---|---|---|---:|---:|---|
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 31}` | 54.19 | 15.1 |  |
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 63}` | 53.53 | 21.0 | yes |
| Random Forest | +6 h | `{'max_depth': 12, 'min_samples_leaf': 10}` | 54.81 | 11.8 | yes |
| Random Forest | +6 h | `{'max_depth': 20, 'min_samples_leaf': 5}` | 55.42 | 15.2 |  |
| Support Vector Regression | +6 h | `{'C': 3.0, 'epsilon': 0.05}` | 62.70 | 15.1 | yes |
| Support Vector Regression | +6 h | `{'C': 10.0, 'epsilon': 0.05}` | 67.11 | 23.4 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 4}` | 54.53 | 15.5 | yes |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 6}` | 56.26 | 21.7 |  |

### Ensembles (decided on validation)

An ensemble is adopted only if its mean rolling-fold MAE is at least 1% below the best single model.

| horizon | best single (validation MAE) | best ensemble (validation MAE) | adopted | test MAE of the ensemble | test MAE of the best single |
|---|---|---|---|---:|---:|
| +1 h | Random Forest (27.59) | mean_top2 (27.96) | no | 16.43 | 16.71 |
| +24 h | Random Forest (67.11) | mean_top2 (67.19) | no | 42.06 | 42.44 |
| +6 h | Random Forest (59.96) | mean_all (58.51) | yes | 34.29 | 34.06 |

### Performance by location (final model, test sample)

| horizon | stations | station MAE min / median / max | mean MAE by region |
|---|---:|---|---|
| +1 h | 68 | 7.32 / 15.95 / 39.31 | Delhi 17.23, Faridabad 13.02, Ghaziabad 14.17, Gurugram 19.07, Noida 19.66, Other NCR 13.39 |
| +24 h | 68 | 22.10 / 39.79 / 71.60 | Delhi 41.07, Faridabad 33.36, Ghaziabad 45.33, Gurugram 47.81, Noida 53.36, Other NCR 39.37 |
| +6 h | 68 | 16.91 / 32.11 / 72.60 | Delhi 33.89, Faridabad 28.35, Ghaziabad 33.04, Gurugram 36.17, Noida 46.16, Other NCR 29.82 |

### Generalisation to unseen stations

14 randomly chosen stations (50, 5570, 5616, 5630, 5650, 6358, 6929, 6949, 6953, 8239, 8365, 8475, 10908, 301388) were removed from training; the same model type was scored on the test period for stations it had seen and ones it had not. Lower is better.

| horizon | model | inputs | seen MAE | unseen MAE | persistence seen / unseen | n seen / unseen |
|---|---|---|---:|---:|---|---|
| +6 h | Random Forest | no location | 35.18 | 32.51 | 40.39 / 37.71 | 15,772 / 4,228 |
| +6 h | Random Forest | with station coordinates | 35.24 | 32.55 | 40.39 / 37.71 | 15,772 / 4,228 |

### Prediction-interval calibration

Intervals use signed validation-residual quantiles of the final model (never test residuals). Empirical coverage is measured on the test sample.

| horizon | nominal | empirical coverage (test) | mean width |
|---|---:|---:|---:|
| +1 h | 80% | 90.6% | 73.7 |
| +24 h | 80% | 92.6% | 200.3 |
| +6 h | 80% | 93.8% | 164.6 |

### Most influential features (tree-model impurity/gain importance at the tuning horizon; indicative, not causal)

* **LightGBM**: `doy_sin` 5.5%, `doy_cos` 4.2%, `target_mean_24h` 2.6%, `wx_pressure_tend_3h` 2.3%, `wx_hours_since_rain` 2.3%, `target_mean_72h` 2.3%, `target_lag0` 2.2%, `target_lag48` 2.0%
* **Random Forest**: `target_mean_24h` 26.1%, `target_mean_72h` 11.1%, `target_mean_12h` 9.2%, `target_min_24h` 4.6%, `target_lag0` 4.3%, `wx_pressure_tend_3h` 3.7%, `obs_pm10` 2.6%, `target_mean_6h` 1.8%
* **XGBoost**: `target_mean_24h` 23.2%, `target_mean_72h` 8.8%, `obs_pm10` 6.1%, `target_lag0` 4.8%, `wx_pressure_tend_3h` 3.4%, `month_ist` 3.3%, `wx_precip_sum_24h` 2.6%, `hour_sin` 2.2%

## pm25

518,550 origin rows from 70 stations, 79 input features, data digest `580f2268397b`. Data 2025-10-09T00 to 2026-10-09T20; development before 2026-07-28T17; **test from 2026-07-28T17**. Validation windows: 2026-04-09T23 to 2026-05-16T13; 2026-05-16T13 to 2026-06-22T03; 2026-06-22T03 to 2026-07-28T17.

### Held-out test results

**+1 h** — test sample 20,000 of 97,664 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 8.69 | 19.71 | 0.601 | -0.11 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 18.42 | 31.55 | -0.022 | -1.06 | 20,000 | -112.0% | | | | | |
| Climatology (train mean by station and hour) | 65.40 | 73.74 | -4.581 | 63.04 | 20,000 | -652.6% | | | | | |
| LightGBM | 8.42 | 17.81 | 0.674 | 0.31 | 20,000 | +3.1% | 10.97 | 18.9 | 2.3 | 663 | 100,000 |
| Random Forest ★ | 8.49 | 17.81 | 0.675 | 1.05 | 20,000 | +2.2% | 10.68 | 12.4 | 0.6 | 518 | 50,000 |
| Support Vector Regression | 10.76 | 19.09 | 0.626 | 3.24 | 20,000 | -23.8% | 19.97 | 12.5 | 35.6 | 559 | 6,000 |
| XGBoost | 8.50 | 17.77 | 0.676 | 0.58 | 20,000 | +2.2% | 11.10 | 20.3 | 0.8 | 659 | 100,000 |
| Ensemble `mean_top2` (random_forest + lightgbm) — not adopted | 8.38 | 17.68 | 0.679 | 0.68 | 20,000 | +3.5% | 10.64 | | | | |

Full test set (every available row, tree models): LightGBM MAE 8.33 vs persistence 8.55 (n=97,664); Random Forest MAE 8.41 vs persistence 8.55 (n=97,664); XGBoost MAE 8.41 vs persistence 8.55 (n=97,664).

**+24 h** — test sample 20,000 of 89,004 available rows. Model chosen on validation: **Random Forest**.

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 18.46 | 32.28 | -0.072 | -0.63 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 18.46 | 32.28 | -0.072 | -0.63 | 20,000 | +0.0% | | | | | |
| Climatology (train mean by station and hour) | 66.08 | 74.50 | -4.707 | 63.89 | 20,000 | -258.0% | | | | | |
| LightGBM | 18.29 | 28.42 | 0.169 | 4.77 | 20,000 | +0.9% | 28.07 | 19.4 | 1.8 | 698 | 100,000 |
| Random Forest ★ | 17.51 | 27.78 | 0.206 | 4.61 | 20,000 | +5.1% | 25.02 | 13.5 | 0.6 | 577 | 50,000 |
| Support Vector Regression | 22.12 | 32.37 | -0.077 | 6.55 | 20,000 | -19.8% | 30.38 | 12.4 | 37.8 | 621 | 6,000 |
| XGBoost | 19.85 | 30.25 | 0.059 | 6.31 | 20,000 | -7.5% | 28.62 | 20.6 | 0.7 | 703 | 100,000 |
| Ensemble `mean_top2` (random_forest + lightgbm) — not adopted | 17.61 | 27.75 | 0.208 | 4.69 | 20,000 | +4.6% | 26.11 | | | | |

Full test set (every available row, tree models): LightGBM MAE 18.20 vs persistence 18.35 (n=89,004); Random Forest MAE 17.38 vs persistence 18.35 (n=89,004); XGBoost MAE 19.75 vs persistence 18.35 (n=89,004).

**+6 h** — test sample 20,000 of 93,032 available rows. Model chosen on validation: **LightGBM** (adopted ensemble: lightgbm + random_forest).

| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Persistence | 17.91 | 31.72 | -0.083 | 0.29 | 20,000 | n/a | | | | | |
| Seasonal naive (same hour, previous day) | 18.22 | 31.23 | -0.050 | -1.23 | 20,000 | -1.7% | | | | | |
| Climatology (train mean by station and hour) | 65.38 | 73.70 | -4.847 | 63.25 | 20,000 | -265.0% | | | | | |
| LightGBM ★ | 15.42 | 25.15 | 0.319 | 3.44 | 20,000 | +13.9% | 22.15 | 19.4 | 1.3 | 674 | 100,000 |
| Random Forest | 15.22 | 24.53 | 0.352 | 3.63 | 20,000 | +15.1% | 22.27 | 12.9 | 0.6 | 551 | 50,000 |
| Support Vector Regression | 17.51 | 26.72 | 0.232 | 4.19 | 20,000 | +2.3% | 25.92 | 13.0 | 38.2 | 599 | 6,000 |
| XGBoost | 17.66 | 27.74 | 0.171 | 6.31 | 20,000 | +1.4% | 23.07 | 20.7 | 0.6 | 684 | 100,000 |
| Ensemble `mean_top2` (lightgbm + random_forest) — adopted | 15.13 | 24.62 | 0.348 | 3.54 | 20,000 | +15.5% | 21.88 | | | | |

Full test set (every available row, tree models): LightGBM MAE 15.62 vs persistence 18.05 (n=93,032); Random Forest MAE 15.35 vs persistence 18.05 (n=93,032); XGBoost MAE 17.85 vs persistence 18.05 (n=93,032).

### Rolling-origin validation (MAE by fold)

| horizon | method | fold 0 | fold 1 | fold 2 | mean | sd |
|---|---|---:|---:|---:|---:|---:|
| +1 h | Climatology (train mean by station and hour) | 75.79 | 76.13 | 70.33 | 74.08 | 2.66 |
| +1 h | LightGBM | 11.38 | 10.18 | 11.35 | 10.97 | 0.56 |
| +1 h | Persistence | 12.82 | 10.51 | 10.10 | 11.14 | 1.20 |
| +1 h | Random Forest | 11.74 | 10.25 | 10.06 | 10.68 | 0.75 |
| +1 h | Seasonal naive (same hour, previous day) | 29.96 | 25.94 | 22.26 | 26.05 | 3.14 |
| +1 h | Support Vector Regression | 26.31 | 15.50 | 18.10 | 19.97 | 4.61 |
| +1 h | XGBoost | 11.75 | 10.19 | 11.38 | 11.10 | 0.67 |
| +24 h | Climatology (train mean by station and hour) | 76.06 | 76.98 | 71.36 | 74.80 | 2.46 |
| +24 h | LightGBM | 27.53 | 33.10 | 23.59 | 28.07 | 3.90 |
| +24 h | Persistence | 31.09 | 25.67 | 22.24 | 26.33 | 3.64 |
| +24 h | Random Forest | 27.44 | 26.04 | 21.58 | 25.02 | 2.50 |
| +24 h | Seasonal naive (same hour, previous day) | 31.09 | 25.67 | 22.24 | 26.33 | 3.64 |
| +24 h | Support Vector Regression | 34.49 | 25.48 | 31.18 | 30.38 | 3.72 |
| +24 h | XGBoost | 27.95 | 33.65 | 24.27 | 28.62 | 3.86 |
| +6 h | Climatology (train mean by station and hour) | 75.94 | 76.46 | 70.79 | 74.39 | 2.56 |
| +6 h | LightGBM | 25.74 | 23.09 | 17.61 | 22.15 | 3.39 |
| +6 h | Persistence | 36.15 | 25.48 | 21.17 | 27.60 | 6.30 |
| +6 h | Random Forest | 26.42 | 22.14 | 18.25 | 22.27 | 3.33 |
| +6 h | Seasonal naive (same hour, previous day) | 29.39 | 25.92 | 22.18 | 25.83 | 2.95 |
| +6 h | Support Vector Regression | 29.34 | 24.46 | 23.95 | 25.92 | 2.43 |
| +6 h | XGBoost | 27.82 | 23.05 | 18.34 | 23.07 | 3.87 |

### Hyperparameter search (last fold, validation only)

| model | tuned at | candidate | validation MAE | fit s | chosen |
|---|---|---|---:|---:|---|
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 31}` | 18.04 | 15.1 |  |
| LightGBM | +6 h | `{'learning_rate': 0.05, 'num_leaves': 63}` | 17.82 | 20.3 | yes |
| Random Forest | +6 h | `{'max_depth': 12, 'min_samples_leaf': 10}` | 18.38 | 12.9 | yes |
| Random Forest | +6 h | `{'max_depth': 20, 'min_samples_leaf': 5}` | 18.53 | 16.9 |  |
| Support Vector Regression | +6 h | `{'C': 3.0, 'epsilon': 0.05}` | 24.18 | 15.5 | yes |
| Support Vector Regression | +6 h | `{'C': 10.0, 'epsilon': 0.05}` | 27.50 | 24.9 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 4}` | 18.81 | 15.5 |  |
| XGBoost | +6 h | `{'learning_rate': 0.05, 'max_depth': 6}` | 18.54 | 21.6 | yes |

### Ensembles (decided on validation)

An ensemble is adopted only if its mean rolling-fold MAE is at least 1% below the best single model.

| horizon | best single (validation MAE) | best ensemble (validation MAE) | adopted | test MAE of the ensemble | test MAE of the best single |
|---|---|---|---|---:|---:|
| +1 h | Random Forest (10.68) | mean_top2 (10.64) | no | 8.38 | 8.49 |
| +24 h | Random Forest (25.02) | mean_top2 (26.11) | no | 17.61 | 17.51 |
| +6 h | LightGBM (22.15) | mean_top2 (21.88) | yes | 15.13 | 15.42 |

### Performance by location (final model, test sample)

| horizon | stations | station MAE min / median / max | mean MAE by region |
|---|---:|---|---|
| +1 h | 69 | 3.67 / 7.64 / 22.81 | Delhi 8.77, Faridabad 9.16, Ghaziabad 7.05, Gurugram 10.21, Noida 7.70, Other NCR 5.89 |
| +24 h | 69 | 7.34 / 16.93 / 37.09 | Delhi 16.86, Faridabad 17.05, Ghaziabad 17.95, Gurugram 20.38, Noida 18.96, Other NCR 15.44 |
| +6 h | 69 | 6.33 / 14.28 / 35.50 | Delhi 14.96, Faridabad 14.33, Ghaziabad 14.40, Gurugram 18.86, Noida 15.51, Other NCR 12.47 |

### Generalisation to unseen stations

14 randomly chosen stations (50, 5570, 5586, 5616, 5634, 5650, 6358, 6929, 6949, 6953, 8239, 8365, 8475, 10908) were removed from training; the same model type was scored on the test period for stations it had seen and ones it had not. Lower is better.

| horizon | model | inputs | seen MAE | unseen MAE | persistence seen / unseen | n seen / unseen |
|---|---|---|---:|---:|---|---|
| +6 h | LightGBM | no location | 15.71 | 16.41 | 17.58 / 19.15 | 15,773 / 4,227 |
| +6 h | LightGBM | with station coordinates | 15.57 | 16.18 | 17.58 / 19.15 | 15,773 / 4,227 |

### Prediction-interval calibration

Intervals use signed validation-residual quantiles of the final model (never test residuals). Empirical coverage is measured on the test sample.

| horizon | nominal | empirical coverage (test) | mean width |
|---|---:|---:|---:|
| +1 h | 80% | 84.4% | 27.4 |
| +24 h | 80% | 89.9% | 65.6 |
| +6 h | 80% | 89.4% | 56.9 |

### Most influential features (tree-model impurity/gain importance at the tuning horizon; indicative, not causal)

* **LightGBM**: `doy_sin` 4.0%, `doy_cos` 3.5%, `target_max_72h` 2.5%, `target_mean_24h` 2.5%, `target_std_72h` 2.4%, `target_lag0` 2.3%, `target_mean_72h` 2.2%, `target_lag24` 2.2%
* **Random Forest**: `target_mean_24h` 28.0%, `target_mean_72h` 13.8%, `target_max_24h` 9.6%, `target_min_24h` 6.2%, `target_lag0` 4.1%, `target_mean_12h` 3.3%, `obs_pm25` 2.1%, `hour_ist` 1.9%
* **XGBoost**: `target_mean_24h` 32.2%, `target_mean_72h` 9.5%, `target_lag0` 3.7%, `month_ist` 3.3%, `obs_pm25` 2.7%, `hour_sin` 2.4%, `hour_ist` 2.1%, `wx_rh_lag6` 2.0%

