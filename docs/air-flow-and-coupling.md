# Air flow, the coupled model, live data and data gaps (2026-10-11)

Pages: `/flow` (Air Flow), `/data` (Data Coverage), a redesigned Overview. API: `/api/twin/coupled*`, `/api/air/model-fields`,
`/api/system/data-availability`, `/api/weather/fields?levels=true`.

## 1. Air that flows (instead of dots)

`/flow` draws particles carried by the weather-model wind and coloured by the concentration of the air they are in, over a smooth
concentration field. Station values are small markers on top, not the picture.

* **2D** (`components/flow/FlowCanvas.tsx`): one canvas over MapLibre, up to 6,000 particles, trails by fading the previous frame, a halo so
  streaks stay readable over a field of the same colours. A particle is created only inside the data lattice and re-created when it leaves
  it or finds no wind; air whose concentration is unknown is drawn faintly in grey (the wind is real there, the value is not).
* **3D** (`components/flow/AirFlow3D.tsx`): real terrain and the Sentinel-2 imagery, the concentration draped on the ground, and particles at
  **seven real model heights** (10, 80, 120, 180 m and the 925, 850, 700 hPa surfaces, about 0.8, 1.5 and 3.2 km), blended linearly in
  height between levels. Colours apply inside the model's mixed layer, which is an assumption stated on screen (there are no vertical
  concentration measurements); above it the air is grey. There is no vertical velocity in the flow, so particles hold their height.
* Wind convention is the app's single one (direction FROM; u = −s·sin, v = −s·cos); the same conversion is used at every height.

### Sources of the picture (the "Data source" switch)

| Source | What it is | Honest label |
|---|---|---|
| Stored replay | Station observations from the history store, 72 h, interpolated between stations (inverse distance, power 2, 12 km, ≥2 stations) with the weather-model wind of each hour | *Spatial estimate* |
| Live model | ECMWF CAMS via Open-Meteo, hourly, whole area, past 6 h to +36 h, refreshed every 10 min | *Atmospheric model*: not a measurement |
| Coupled model | The coupled run (below), started from CAMS now, live OpenAQ readings, the trained model's forecasts, or a stored hour | *Simulated* |

**Measured facts that shaped this** (2026-10-11): the OpenAQ live feed for Delhi lags by about 3.3 days (1 of 33 PM2.5 stations was
under 3 h old), so "live stations" is usually not live; and CAMS cells here are about 0.4° (44 km), so NCR holds only about 3×3 cells and the
live field is made of a few large blocks. Both are stated in the interface.

## 2. The coupled model (no training)

`api/app/twin/coupled.py` (engine), `coupled_run.py` (service), `POST /api/twin/coupled`. Five transported species: PM2.5, coarse PM
(PM10 − PM2.5), NO₂, O₃, SO₂; PM10 = PM2.5 + coarse (so PM10 ≥ PM2.5 by construction) and Ox = O₃ + NO₂ (ppb) are derived.

| Process | Couples | Default | Basis |
|---|---|---|---|
| Dry deposition / settling | weather (boundary-layer depth) → each species | on | rate v/H with literature-order v (cm/s): PM2.5 0.10, coarse 0.60, NO₂ 0.15, O₃ 0.40, SO₂ 0.50 |
| Rain scavenging | model rain → PM and (weakly) SO₂ | on | rate 1e-4·P^0.79 per second × efficiency (coarse 2, PM2.5 1, SO₂ 0.3); NO₂/O₃ untouched |
| SO₂ → sulfate | SO₂ → PM2.5, scaled by radiation | on | 2 %/h at 800 W/m²; each unit of SO₂ lost adds 1.5 of PM2.5 (96/64), only where PM2.5 is known |
| Ventilation (H × wind) | weather → primary species | **off** | steady-emissions rule C ∝ 1/(H·u); lowered skill in the hindcast |
| Mixed-layer dilution | weather → all | **off** | one-sided (nothing refills it); biases low |

**Not modelled** (shown with every run): emissions, NO titration of O₃ (NO is not observed), NO₂ → nitrate and organic aerosol,
vertical structure, terrain and street scale. With no source term the model can only carry, dilute or remove air that is already there.

### Verification

* Physics tests (`tests/test_coupled.py`): with every coupling off it reproduces the passive engine exactly; deposition, washout,
  oxidation, dilution and ventilation each match their analytic expectations; mass transferred SO₂ → PM2.5 is exactly 1.5×; unknown air
  stays unknown; missing rain/radiation stops the run instead of assuming dry and dark.
* **Hindcast** (`python -m app.twin.coupled_eval`, results in `docs/coupled-evaluation.md`): 25 historical windows of 12 h
  (4 Aug to 4 Oct 2026, every 60 h), run with the stated defaults and scored at stations withheld from the initial field against later
  observations, with persistence and passive transport as baselines. Median skill of the defaults (deposition + washout + oxidation):

  | | PM2.5 | PM10 | NO₂ | O₃ | SO₂ |
  |---|---|---|---|---|---|
  | against passive transport | −0.09 (24 % of windows better) | −0.39 (8 %) | −0.06 (20 %) | +0.02 (52 %) | −0.02 (44 %) |
  | against persistence | −0.38 (16 %) | −0.84 (8 %) | −0.82 (4 %) | −0.19 (32 %) | −1.87 (0 %) |

  **The couplings did not reliably beat plain transport (only O₃ is marginally positive), and nothing beat simply holding the starting
  value.** That is expected of a model with no emissions, and it is why the interface says "not validated as a forecast". The ventilation
  rule, which I expected to help, was clearly worse (PM2.5 −0.30), so it was moved to opt-in; that decision used these same windows,
  so the table is in-sample for that one choice. Dry deposition lowers PM10 skill (−0.13): its velocities are probably too high for a
  source-free model that also lacks resuspension. The first run (ventilation on by default, 22 windows) is kept as
  `coupled-evaluation-run1-ventilation-default.md`.
* The interface repeats this: a standing "not validated as a forecast" note on every coupled run and a "Track record" tab.

## 3. Prediction from the trained model

"Start from: Trained model" asks the local ML model for every reporting station's forecast at origin + lead (+1, +6 or +24 h, the trained
horizons; SO₂ has no model and is left uninitialised), interpolates it, and carries it with the coupled model. The per-station forecasts
are cached per (pollutant, origin, stations, active model); **activating a new model changes the cache key**, so the next run uses it
without any other action. Training itself stays your button on `/training`; nothing here trains.

## 4. What is not available

`/data` lists 27 sources with live status and, for every gap, what it prevents and where it could come from (emissions inventory, fire
detections, NO/NOx/VOC/NH₃ observations, PM speciation, vertical profiles, satellite AOD/NO₂, observed meteorology, radar, a
high-resolution regional model, traffic, land use, health data). Statuses are computed from the running system (store age, provider probes,
keys, the trained model), the rest is a written catalogue.

## 5. Interface changes

Grouped navigation (Explore / Observe / Assist / System), wide layout for map pages, a Data coverage link in the top bar, glass panels,
segmented controls and status chips, a redesigned Overview (live model number, station-feed age, trained model, data gaps, where to go).
New primitives in `components/ui/Glass.tsx`; tokens and `.glass`/`.card` utilities in `app/globals.css`.

## Limits

* The flow is horizontal and uses model winds; it is not pollutant transport unless it is the coupled run, and that run has no sources.
* The 3D concentration colouring inside the mixed layer assumes uniform concentration with height (the model's own assumption).
* Open-Meteo's free tier is non-commercial and rate-limited (the evaluation needed retries).
