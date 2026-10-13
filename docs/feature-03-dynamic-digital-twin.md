# Feature 03: dynamic environmental digital twin (2026-10-10)

The `/twin` page now has a **Simulation** view on the same map instance. It is a computational engine plus an API plus map layers, not an
animated heatmap. Nothing here retrains a model, invents an emission source, or claims chemistry.

## The five modes and what each one is
| Mode | Where | What it is | Label |
|---|---|---|---|
| Historical replay | Stations view, Observations layer | Stored station observations, hour by hour; gaps stay gaps | Observed |
| Spatial estimate | Stations view, Spatial estimate layer; also the initial field of every run | Inverse-distance weighting (power 2, radius 12 km, at least 2 stations) with its leave-one-out error; one shared function (`idw_point`, vectorised twin `idw_grid`, equality asserted by a test) | Spatial estimate |
| Forecast provider | Stations view, Model forecast layer | The trained model's forecast for one station, next to later observations, only when valid inputs exist | Model forecast |
| Transport | Simulation view, "Transport (baseline)" and "Live" | Observed air carried by the weather-model wind (advection-diffusion) | Simulated |
| Scenario | Simulation view, "Scenario (hypothetical)" | The same engine with explicitly modified parameters, shown with the unmodified baseline and the difference | Hypothetical |

## Computational engine (`api/app/twin/transport.py`)
2-D passive-scalar advection-diffusion on a 40 x 40 grid (about 2.8 km) over 28.10-29.05 N, 76.70-77.80 E:

`dC/dt + u . grad C = div(K grad C) - lambda C`

* **Inputs actually used:** the interpolated station observations at the initialisation hour (initial field), the Open-Meteo 10 m wind on its 0.14 degree lattice (bilinear in space, linear in time between hourly frames), the boundary-layer height (only when a scenario switches column dilution on).
* **Numerics:** advective form with a minmod-limited MUSCL upwind reconstruction (second order, non-negative), explicit Euler, time step limited by an unsplit CFL of 0.4 and by the diffusion limit, open boundaries. Deterministic: no randomness.
* **Knowledge is carried, not invented:** the field is transported as P = C*M with a validity field M; C = P/M where M >= 0.5, otherwise the cell is "no information". Air entering through an inflow boundary has M = 0, so the known area honestly shrinks.
* **Not modelled, and said so in every run:** emissions, chemistry, deposition, secondary aerosol, vertical structure, terrain. A concentration field from this engine shows where the observed air is carried; it does not locate sources.
* **Diffusivity** (50 m2/s baseline) is a documented parameter, not a measurement. First-order loss and column dilution are off in the baseline and exist only as scenario parameters.
* **Uncertainty:** a 5-member parameter-sensitivity spread (diffusivity x0.5 and x2, wind turned +/-20 degrees). It is explicitly not a probability and not calibrated.

## Run record (what every run states)
Initialisation time, valid timestamps, extent and grid resolution, input timestamps and ages (observations, wind retrieval), freshness status
(stale after 6 h), model name and version, scheme, configuration, execution status (completed / limited when the wind data are shorter than
asked), steps and time step, limitations, uncertainty description, and (where later observations are stored) a hindcast validation. The run id
is a hash of the model version, configuration, initialisation hour and the digests of the observation and wind arrays: the same inputs give
the same id and the same arrays; runs are also written to `data/twin_runs/` and can be fetched by id.

## API
* `POST /api/twin/simulations` (`mode` transport | scenario | live, `pollutant`, `hours` 6-48, `init_time`, `scenario`)
* `GET /api/twin/simulations/live` re-creates the live run; because the run id comes from the inputs, **the map changes only when observations or wind data actually change** (the page asks every 5 minutes)
* `GET /api/twin/simulations/{run_id}`
* `GET /api/twin/validation/estimates` multi-hour withheld-station check of the spatial estimate

## Map integration
One MapLibre map, one deck.gl overlay. Layers (stable ids): `sim-concentration`, `sim-difference`, `sim-spread`, `sim-stations-observed`,
`sim-stations-missing`, `inspect-point`, `wind-particles`. Station dots carry the observed value of the selected hour in the same colours as
the simulated field (white outline), hollow rings mean no observation. Provenance badges: Simulated, Hypothetical, Stale, Observed,
Unavailable. Timeline play/pause/step/scrub and pollutant selection are shared with the other views; clicking the map gives simulated value,
spread, baseline, wind and the nearest station's observation with an ECharts series (click to seek).

## Validation results (real data, 2026-10-10)
**Spatial estimate against withheld stations**, 48 hours sampled between 2026-07-01 and 2026-10-07, leave-one-out:

| Pollutant | Interpolation MAE | Mean of other stations MAE | Skill |
|---|---|---|---|
| PM2.5 | 17.08 | 16.30 | -0.05 |
| PM10 | 36.82 | 36.52 | -0.01 |
| NO2 | 26.84 | 24.00 | -0.12 |

The interpolation does **not** beat a plain mean. A radius/power/blend search tuned on half of the hours and tested on the other half gave
at best PM2.5 17.05 vs 17.67 (about 3.5% better) and no gain for NO2. Between-station differences here are mostly local, so the spatial
estimate adds little beyond the average; the product says so in the "Spatial estimate check" card. The documented method was left unchanged
rather than re-tuned for a marginal gain.

**Transport hindcast**, PM2.5, initialised 2026-10-05 06:00 UTC, 24 h: all stations MAE 34.1 vs 28.0 for holding the first observation
(skill -0.22); 20 withheld stations MAE 26.6 vs 22.3 (skill -0.19). The passive transport run **does not beat persistence** (concentrations
change through emissions and chemistry that the model does not contain), and the run's `verdict` states that in plain words. Known
(observed-air) cover falls from 35% of cells to about 6% after 12 h and 0% after 24 h at typical wind, because the 107 km domain is flushed.
This is a real limitation of a regional-box passive model with 3-5 m/s wind, not a bug.

Engine numerics (12 tests): translation within 5% of u*t (1.7% measured), non-negativity, no new maxima, stability at 30 m/s, diffusion conserves total,
inflow is unknown not assumed, unknown cells stay unknown, bit-for-bit reproducibility, parameters do what they say, column dilution only when
the layer deepens, missing wind refused.

## Defects found and fixed on the way
* Synthetic station ids (9e9+) overflowed int32 in training data loading (found at the start of this session).
* The station inventory re-aggregated millions of rows per request; covering index plus cached result (see Feature 02 notes).

## Not done / limits
* No data assimilation: observations after the initialisation hour are only used to check the run, not to correct it.
* No transport outside the 107 km box; inflow is unknown by design. A larger domain needs wind and observations beyond the lattice.
* The live mode is bounded by the stored observations: the store is a history (newest hour 2026-10-07 14:00 UTC), so the live run is stale and says so. A fresher observation feed would make it current without code changes.
* Forecast-provider output is shown per station (existing view); it is deliberately not fused into the transport run.
