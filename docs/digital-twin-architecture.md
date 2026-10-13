# Digital twin: architecture and what it does and does not claim

Route `/twin` (frontend), `/api/twin/*` and `/api/models/status` (backend). **It is a historical replay and analysis workspace,
not a live simulator.** Every layer says what kind of information it shows, using one badge vocabulary
(`components/ui/ProvenanceBadge.tsx`): Observed, Weather forecast (numerical weather model output), Model forecast, Derived,
Spatial estimate, Illustrative, Stale, Unavailable.

## Data flow

```
OpenAQ + Open-Meteo archive --(python -m app.history)--> history.sqlite (raw -> clean -> model_ready)
                                                              | read-only (TwinService, HistoryStore(read_only=True))
   /api/twin/{status,stations,window,estimate,regimes,thresholds}      /api/twin/{backtest,risk-windows}  <- local trained model (ml/inference.py)
                                                              |
   web: useResource / useOptional -> TwinMap (MapLibre + deck.gl) + TimelineControls + StationCharts (ECharts)
```

The twin never writes to the store (a test hashes the table before and after). If the store or the cleaned data do not exist the
API answers `503 twin_data_unavailable` with the command that builds them, and the page shows that message instead of an empty
map (seen in the browser while the data were still being cleaned).

## Layers

| Layer | Data | Kind | Notes |
|---|---|---|---|
| Observations | station-by-hour matrix, µg/m³ (`/api/twin/window`) | Observed | a missing hour is `null`, drawn as a hollow ring; one colour scale for the whole window |
| Weather wind | `wind_u/v` (m/s) at each station point, Open-Meteo archive | Weather forecast | arrows show where the air moves; labelled as wind, not pollutant transport |
| Spatial estimate | inverse-distance weighting on a 36x36 grid (`/api/twin/estimate`) | Spatial estimate | power 2, radius 12 km, at least 2 stations or the cell stays empty; leave-one-out MAE/RMSE/bias for the hour shown beside the map; never extrapolates beyond the observed range (tested) |
| Model forecast | trained model for the selected station from the timeline hour (`/api/twin/backtest`) | Model forecast | drawn with its empirical interval beside what was observed afterwards; no map-wide forecast exists |
| Transport | none | n/a | tab disabled with the reason: no validated transport model exists |

## Shared state

One page state drives everything: pollutant, replay window (72 h or 7 days), layer, timeline index, play/pause and speed, layer
opacity, selected station, reset-view token. Map, slider (IST time in `aria-valuetext`), station panel and charts read the same
index, so scrubbing moves colours, the chart marker and the estimate/forecast requests together. Estimates and forecasts are
requested only for the hour the timeline rests on (250 ms debounce) and superseded requests are aborted (`useOptional`).

## Honest limits

* Data are as ingested; the live OpenAQ/CPCB feed has been about two days behind.
* OpenAQ hourly values blend neighbouring provider hours (`docs/historical-data-pipeline.md` section 5). CO is excluded: its unit labels contradict physics.
* Weather is reanalysis/model output for a grid cell, not a station measurement.
* The spatial estimate ignores terrain, emissions and wind and is only as good as its printed leave-one-out error.
* No emission sources, plumes, transport paths or hotspots are drawn or implied.

## Tests

`tests/test_twin.py` (28): matrix shape and gaps, wind convention, validation, estimate method/coverage/radius, 503 states,
read-only guarantee, risk windows, regimes. `tests/test_ml.py` covers `/api/models/status`, `/api/twin/backtest` and risk windows
against a model trained inside the test. `web/src/lib/twin/twin.test.ts` covers the timeline helpers.


## Update: dynamic twin (Feature 03)
The twin now has a computational layer on top of the read-only data service: `twin/transport.py` (pure numpy engine), `twin/simulation.py`
(inputs, runs, validation, run registry), routes under `/api/twin/simulations`. Inputs stay real: station observations from the store, wind and
boundary-layer height from Open-Meteo. Outputs are time-indexed frames served to the existing map. See `docs/feature-03-dynamic-digital-twin.md`
for the physics, what is excluded, the run record and the validation results (interpolation and transport both fail to beat their simple
baselines on this data, and the product says so).
