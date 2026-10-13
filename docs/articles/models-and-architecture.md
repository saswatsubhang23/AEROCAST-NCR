# Which models, and why: an assessment before any new training

> Candidates for station forecasting, regional prediction, weather and wind, transport and exposure, compared on what they need, what they give and what they cost. Only some were run; the report says which, and does not claim results for the rest. The recommendation is a layered system built on what already works, not a new large model.

## What was asked, and the rule followed

The questions are practical: how pollutants affect air quality across the region, how weather and transport move them, where pollution is likely to rise next, and who is exposed. The rule for answering was to measure the cheap options first. Nothing large was downloaded and no dependency was installed for this assessment; the numbers below come from the data already in the project and from live calls to the public sources.

## What was measured

Four baselines and one trained family were evaluated on the same stations and hours, so the comparison is fair.

| Approach | PM2.5 +1 h | PM2.5 +6 h | PM2.5 +24 h | PM10 +24 h | NO₂ +6 h | O₃ +6 h |
|---|---:|---:|---:|---:|---:|---:|
| Persistence (repeat the last value) | 8.7 | 17.9 | 18.5 | 41.4 | 18.5 | 14.3 |
| Trained ensemble (RF, LightGBM, XGBoost, SVR) | **8.5** | **15.1** | **17.5** | 42.4 | **12.9** | **7.7** |
| Raw CAMS at the station (60-day window) | n/a | n/a | 30.0 | 91.7 | 31.5 | 73.1 |
| Passive transport simulation (25 windows, 12 h) | worse than persistence | | | | | |
| Coupled model, deposition + washout + oxidation | worse than persistence | | | | | |

Mean absolute error in µg/m³ on the held-out period from late July to early October 2026, on 68 to 70 stations. The CAMS row is not tied to a horizon (it is a single hourly estimate) and sits in the column of its pollutant; the two simulation rows were scored over 25 historical windows of 12 hours at withheld stations. The ensemble is closer than persistence in eleven of twelve target and horizon cells, by a lot at six hours (PM2.5 is about 16 % better, O₃ about 46 % better), and by little at one hour, where yesterday's and the last hour's values are already nearly right. It does not beat persistence for PM10 a day ahead, and the application flags that cell wherever it appears. Prediction intervals were fitted from validation residuals and cover 84 to 94 % of held-out values at a nominal 80 %, which is honest but slightly wide.

Three findings shaped everything else. First, **persistence is a hard baseline** in a source-poor model: air quality has strong memory, and any method that cannot add information beyond the last observation will lose to it. Second, **raw CAMS is not a station forecaster here**: it is biased and weakly correlated at 44 km cells. Third, the physical models (transport and coupled) are valuable for understanding movement and for visualisation, and are not forecasters, because they contain no emissions.

## The candidates

| Candidate | Inputs | Output and scale | Hardware | Licence | Complexity | Verdict |
|---|---|---|---|---|---|---|
| Persistence, hour-of-day climatology | station history | station, any horizon | none | n/a | trivial | Keep as the baseline every model must beat |
| Gradient-boosted trees and forests (**in use**) | 79 features: lags, rolling stats, weather, time, neighbours | station, +1/+6/+24 h, intervals | CPU, minutes | permissive (BSD/Apache/MIT) | low | **Keep and extend** |
| Boosted trees with CAMS and weather *forecasts* as features | the above plus CAMS and Open-Meteo forecast values at the station | station, up to +72 h | CPU | permissive | low | **Recommended next experiment** |
| Quantile gradient boosting / conformal intervals | same | calibrated intervals | CPU | permissive | low | Recommended: replaces ad hoc residual bands |
| Temporal fusion / N-HiTS (neural time series) | station histories, covariates | multi-horizon, quantiles | single GPU helpful | Apache/MIT | medium | Defer: little expected gain over trees on 70 stations and one year |
| Graph or ConvLSTM spatiotemporal nets | station graph or gridded fields | regional field, hours ahead | GPU | BSD/MIT | high | Defer: needs a gridded target; 70 stations are sparse |
| CAMS global composition forecast (**in use as context**) | none (served) | 0.4°, hourly, 5 days | none | Copernicus, free with attribution | none | Use as regional background and as a feature, not alone |
| FourCastNet (NVlabs) | ERA5 initial state, 20 variables | global weather, 0.25°, 6-hourly, no chemistry | GPU (A100 class for speed) | code BSD-style; check weights terms | high | **Reject for this use**: coarser than the 9 km weather already served, no pollutants |
| Foundation models with chemistry heads (for example Aurora) | ERA5/CAMS states | global fields at 0.1 to 0.4° | GPU, large weights | check model card | high | Not evaluated; interesting later as a CAMS-like prior, not needed now |
| Passive transport (**in use**) | wind, boundary layer | 2.7 km field, hours | CPU, seconds | own code | low | Keep for visualisation and what-ifs |
| Lagrangian trajectories (NOAA HYSPLIT, FLEXPART) | meteorological archives | back-trajectories to source regions | CPU | free / GPL | medium | **Recommended**: the right tool for "where did this smoke come from" |
| WRF-Chem or similar | emissions, boundary data | 1 to 10 km chemistry | HPC cluster | open | very high | Out of scope without an emission inventory |
| Population-weighted exposure | concentration field, population raster, site list | exposure per area and group | CPU | WorldPop CC BY | low once the data are loaded | **Recommended** (data not loaded yet) |

Items marked "not evaluated" were assessed from their published descriptions only, not run, and nothing here claims a result for them.

## Why not FourCastNet, specifically

FourCastNet is a data-driven global weather emulator. It forecasts atmospheric variables such as wind at 0.25° (about 28 km) every six hours from an ERA5 starting state. For this project that is the wrong tool in three ways: Open-Meteo already serves hourly, 9 km forecasts from operational models at no cost; it has no pollutant channels, so it cannot say anything about concentration; and running it needs ERA5 initial conditions and a GPU. A justified weather use would be a *regional ensemble of winds with quantified uncertainty*, which is a research project, not a prerequisite. It is therefore not installed and its weights were not downloaded.

## Recommended architecture

The system is five layers, each of which exists or can be built from what is already here.

**1. Data layer.** One typed, normalised record for every value (observation, forecast, analysis, interpolation, simulation), stored in PostgreSQL with PostGIS where available and SQLite for development. Provenance, units, periods, quality flags and licences travel with every row. This is implemented; the migration is `0002`.

**2. Observation and background fusion.** Station observations interpolated between stations, with CAMS as the regional background and boundary condition. The interpolation's leave-one-out error is shown; CAMS is never presented as a measurement.

**3. Station forecaster.** Gradient-boosted models per pollutant and horizon, with CAMS and weather forecasts at the station as additional inputs, evaluated against persistence and climatology with the same time-ordered split. The one experiment worth running next is the CAMS-feature ablation: does adding CAMS reduce the 6 h and 24 h error? It is cheap and decides whether any heavier model is needed.

**4. Movement and what-if.** The transport and coupled models, labelled as simulations, for showing where the air goes and for scenario questions, with trajectories added for source attribution.

**5. Exposure.** Population-weighted concentration and a sensitive-site layer, produced from the station forecast and the interpolated field, once the population raster and site list are loaded.

## How each model is evaluated

Every candidate is run on time-ordered splits with the training period strictly before the validation period, which is strictly before the test period; features are computed by the same function in training and serving, with a latency parameter, so a feature can never see the future. Scores are MAE, RMSE, R² and bias per pollutant and horizon, stratified by season and concentration band where the sample allows, always beside persistence and climatology. A candidate is adopted per cell only where it beats persistence on held-out data, and cells that do not are flagged in the interface. Intervals are checked for coverage. Spatial claims are tested leave-one-station-out. Simulations are scored against later observations at stations withheld from their starting field.

## What would change the recommendation

A fresh, gap-free observation feed would make the station forecaster usable for the present and would let the physical models be started from measurements. An emissions inventory would turn the transport model into something that can forecast concentration changes rather than only carry them. A gridded observation product (satellite aerosol) would make a spatiotemporal network worth training. Until then the cheapest, most defensible improvements are the data repairs, the missing parameters, retraining on the corrected series, and the CAMS-feature ablation.
