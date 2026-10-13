# Coupled model: evaluation on historical windows

Generated 2026-10-10T22:08:23Z. 25 windows of 12 h (every 60 h), 0 skipped.
Nothing is fitted: each window is run with the documented defaults and scored at stations that were withheld from the initial field.
Scoring: MAE at stations withheld from the initial field, leads 1..N h; skill = 1 - MAE_model / MAE_baseline (positive: closer to the observations).

A **median skill above 0** means the configuration was closer to later observations than the baseline in the typical window; `share>0` is the fraction of windows where it was. The model has no emissions, so beating persistence is not expected to be common.

## Skill against passive transport (the same engine with every coupling off)

| Configuration | pm25 | pm10 | no2 | o3 | so2 |
|---|---|---|---|---|---|
| defaults (deposition + washout + oxidation) | -0.09 (24% of 25) | -0.39 (8% of 25) | -0.06 (20% of 25) | +0.02 (52% of 25) | -0.02 (44% of 25) |
| ventilation only | -0.30 (24% of 25) | -0.27 (24% of 25) | -0.10 (40% of 25) | +0.00 (0% of 25) | -0.32 (20% of 25) |
| dilution only | -0.18 (12% of 25) | -0.26 (8% of 25) | -0.23 (4% of 25) | -0.01 (48% of 25) | -0.14 (28% of 25) |
| deposition only | -0.02 (36% of 25) | -0.13 (12% of 25) | -0.06 (20% of 25) | +0.02 (52% of 25) | -0.01 (44% of 25) |
| washout only | -0.01 (12% of 25) | -0.07 (4% of 25) | +0.00 (0% of 25) | +0.00 (0% of 25) | +0.00 (40% of 25) |
| oxidation only | +0.00 (52% of 25) | +0.00 (64% of 25) | +0.00 (0% of 25) | +0.00 (0% of 25) | +0.00 (68% of 25) |

## Skill against persistence (hold the station's starting value)

| Configuration | pm25 | pm10 | no2 | o3 | so2 |
|---|---|---|---|---|---|
| defaults (deposition + washout + oxidation) | -0.38 (16% of 25) | -0.84 (8% of 25) | -0.82 (4% of 25) | -0.19 (32% of 25) | -1.87 (0% of 25) |
| ventilation only | -0.64 (8% of 25) | -0.78 (8% of 25) | -1.17 (4% of 25) | -0.23 (28% of 25) | -2.98 (0% of 25) |
| dilution only | -0.48 (8% of 25) | -0.79 (0% of 25) | -1.42 (0% of 25) | -0.44 (28% of 25) | -1.74 (0% of 25) |
| deposition only | -0.29 (24% of 25) | -0.57 (12% of 25) | -0.82 (4% of 25) | -0.19 (32% of 25) | -1.79 (0% of 25) |
| washout only | -0.30 (20% of 25) | -0.61 (8% of 25) | -0.76 (4% of 25) | -0.23 (28% of 25) | -1.59 (0% of 25) |
| oxidation only | -0.23 (24% of 25) | -0.39 (12% of 25) | -0.76 (4% of 25) | -0.23 (28% of 25) | -1.58 (0% of 25) |
