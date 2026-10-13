# Forecast uncertainty, atmospheric regimes and risk windows

## Uncertainty (implemented, measured on held-out data)

Method: **empirical residual quantiles**. For each (pollutant, horizon) the signed errors of the selected model on the
rolling-origin *validation* folds are pooled; the (1-L)/2 and 1-(1-L)/2 quantiles (L = 0.8) are saved in `intervals.json`.
A forecast is returned as `value + q_low` .. `value + q_high`, lower bound clipped at 0 and the value forced inside the band
(the contract requires 0 <= lower <= value <= upper). No test residual is used to build the band.
Calibration is then *measured*: empirical coverage and mean width on the held-out test sample are printed per horizon in
`docs/ml-model-comparison.md` ("Prediction-interval calibration"). Nothing is labelled a confidence percentage; the interval's
nominal level is stated together with the measured coverage.

What it is not: it is not conformal prediction with finite-sample guarantees, it does not separate measurement, input and model
uncertainty (provider measurement uncertainty is unknown), and it assumes errors in the future resemble validation errors.
Distribution shift between seasons (see the comparison report) can make the measured coverage differ from nominal; that is the
reason coverage is reported on the later test period.

## Atmospheric regimes (implemented offline; run after training)

`python -m app.ml regimes` (`app/ml/regimes.py`) clusters standardised weather (wind speed, boundary layer height, humidity,
a wet flag, temperature) with K-means fitted on the development period only; k = 2..5 by silhouette; regimes are named only from
their own centroids ("low wind", "shallow boundary layer", ...). PM2.5 is then compared across regimes on the held-out period
(medians, counts, Kruskal-Wallis). Result and caveat are served by `/api/twin/regimes`; a regime with few test samples is flagged.
The result is an association between weather state and concentration, not a causal claim. Real results: see
`docs/ml-model-comparison.md` / `docs/IMPLEMENTATION_STATE.md` once the command has been run on the real data.

## Risk windows (implemented)

`GET /api/twin/risk-windows` evaluates the model's forecast at its discrete lead times against a threshold and groups consecutive
exceedances. Each result carries pollutant, unit, station, origin, model version, threshold (key, value, kind, averaging period,
source), duration rule, per-point status (`likely` if the interval's lower bound also reaches the threshold, else `possible`),
the inputs used and the limitations.

Thresholds (`/api/twin/thresholds`): India NAAQS PM2.5 24-hour 60 µg/m³ and PM10 24-hour 100 µg/m³ (CPCB, 2009); WHO global air
quality guidelines 2021 PM2.5 24-hour 15 µg/m³ and PM10 24-hour 45 µg/m³; or a user-defined value, which is labelled
`user_defined` and "not an official standard".

Limits stated in every response: windows are evaluated at lead times only (no interpolation between +6 h and +12 h); the
reference values are 24-hour averages and a single forecast value is not one, so a window is an *indicator*; intervals are
empirical, not guarantees; and the model needs fresh inputs, so most requests made now are answered "unavailable".

Tests: `tests/test_twin.py` (grouping, duration rule, equality at the threshold, likely vs possible, custom thresholds, request
validation) and `tests/test_ml.py` (against a trained model).
