# Coupled model: evaluation on historical windows

Generated 2026-10-10T21:45:38Z. 22 windows of 12 h (every 60 h), 3 skipped.
Nothing is fitted: each window is run with the documented defaults and scored at stations that were withheld from the initial field.
Scoring: MAE at stations withheld from the initial field, leads 1..N h; skill = 1 - MAE_model / MAE_baseline (positive: closer to the observations).

A **median skill above 0** means the configuration was closer to later observations than the baseline in the typical window; `share>0` is the fraction of windows where it was. The model has no emissions, so beating persistence is not expected to be common.

## Skill against passive transport (the same engine with every coupling off)

| Configuration | pm25 | pm10 | no2 | o3 | so2 |
|---|---|---|---|---|---|
| defaults (all couplings on) | -0.23 (14% of 22) | -0.29 (9% of 22) | -0.14 (27% of 22) | -0.04 (46% of 22) | -0.18 (18% of 22) |
| ventilation only | -0.26 (23% of 22) | -0.32 (23% of 22) | -0.12 (36% of 22) | +0.00 (0% of 22) | -0.27 (23% of 22) |
| dilution only | -0.18 (14% of 22) | -0.29 (9% of 22) | -0.24 (4% of 22) | -0.08 (46% of 22) | -0.14 (32% of 22) |
| deposition only | -0.02 (36% of 22) | -0.13 (9% of 22) | -0.06 (18% of 22) | -0.04 (46% of 22) | +0.00 (50% of 22) |
| washout only | -0.01 (14% of 22) | -0.14 (4% of 22) | +0.00 (0% of 22) | +0.00 (0% of 22) | +0.00 (41% of 22) |
| oxidation only | +0.00 (50% of 22) | +0.00 (64% of 22) | +0.00 (0% of 22) | +0.00 (0% of 22) | +0.00 (73% of 22) |

## Skill against persistence (hold the station's starting value)

| Configuration | pm25 | pm10 | no2 | o3 | so2 |
|---|---|---|---|---|---|
| defaults (all couplings on) | -0.62 (4% of 22) | -0.75 (0% of 22) | -1.21 (4% of 22) | -0.19 (27% of 22) | -2.12 (0% of 22) |
| ventilation only | -0.68 (4% of 22) | -0.78 (9% of 22) | -1.21 (4% of 22) | -0.24 (27% of 22) | -2.63 (0% of 22) |
| dilution only | -0.62 (4% of 22) | -0.73 (0% of 22) | -1.37 (0% of 22) | -0.45 (23% of 22) | -1.70 (0% of 22) |
| deposition only | -0.31 (18% of 22) | -0.52 (14% of 22) | -0.81 (4% of 22) | -0.19 (27% of 22) | -1.64 (0% of 22) |
| washout only | -0.37 (14% of 22) | -0.56 (9% of 22) | -0.76 (4% of 22) | -0.24 (27% of 22) | -1.53 (0% of 22) |
| oxidation only | -0.30 (18% of 22) | -0.35 (14% of 22) | -0.76 (4% of 22) | -0.24 (27% of 22) | -1.38 (0% of 22) |

## Skipped windows

* 2026-08-31T12:00Z: wind data are unavailable (UpstreamError)
* 2026-09-13T00:00Z: wind data are unavailable (UpstreamError)
* 2026-09-25T12:00Z: wind data are unavailable (UpstreamError)
