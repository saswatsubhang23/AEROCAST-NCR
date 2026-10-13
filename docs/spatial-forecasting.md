# Spatial forecasting and estimation: what the data supports

## Finding from the data audit

The historical store covers about 70 active stations (median nearest-neighbour spacing about 3 km, uneven: Delhi 42 stations
within 20 km of its centre, Gurugram and Ghaziabad 13 each) with one hourly series per pollutant per station, and weather from the
Open-Meteo archive at station points (a coarse model grid, so neighbouring stations often share a cell). That supports:

* **station-level forecasts** (one model, features per station): implemented and trained (`docs/ml-model-comparison.md`);
* **a documented interpolation between stations for a past hour** with a leave-one-out error: implemented (`/api/twin/estimate`);
* **generalisation to unseen stations**: measured by a spatial hold-out in the training run (seen vs unseen MAE, with and without station coordinates).

It does **not** support: a high-resolution concentration surface, source attribution, hotspot detection, pollutant transport, or a
map-wide *future* concentration field. No emission inventory, no gridded wind field finer than the weather model's cell, no
vertical profile of pollutants and no validated dispersion model exist in the project, so none of those is shown.

## What the map therefore does

| Mode | Basis | Claim |
|---|---|---|
| Observations | station hourly values | measured at the station only |
| Spatial estimate | IDW (power 2, 12 km radius, at least 2 stations) between stations at one past hour, with leave-one-out MAE/RMSE/bias | an interpolation; empty where stations are too far apart |
| Model forecast | trained station-level model, one station at a time | forecast for that station, with interval and later observations |
| Wind | Open-Meteo archive wind at station points | air movement in the weather model; not pollutant transport |

## If a spatial forecast is added later

A graph or gridded model would need: a finer meteorological field for the forecast period (the archive's historical-forecast API
is reachable and not yet ingested), station coverage of the outer NCR (8 stations lie outside the weather grid used by the app),
a per-cell validation by spatial hold-out, and a stated uncertainty that grows with distance to the nearest station. The leave-one-out
error shown today is the baseline any such model must beat.


## Evaluation of the spatial estimate on withheld stations (2026-10-10)
Leave-one-out over 48 sampled hours (2026-07-01 to 2026-10-07): PM2.5 MAE 17.08 vs 16.30 for the mean of the other stations (skill -0.05), PM10 36.82
vs 36.52 (-0.01), NO2 26.84 vs 24.00 (-0.12). A radius/power/blend search tuned on half of the hours reached 17.05 vs 17.67 on the other half for PM2.5
(about 3.5% better) and no gain for NO2. Conclusion: interpolation between stations adds little beyond the regional mean for these pollutants in this
network; maps built from it are context, not detail. Endpoint: `GET /api/twin/validation/estimates`.
