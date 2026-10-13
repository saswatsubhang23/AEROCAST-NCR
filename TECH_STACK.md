# Recommended Technical Stack

## Core visualization
- **MapLibre GL JS**: interactive basemap, geographic navigation, geographic context.
- **deck.gl**: GPU-accelerated spatial layers such as point/station layers, grid/hex aggregation, contours where supported, and custom wind-vector/particle layers.
- **Three.js + React Three Fiber + Drei**: separate 3D atmospheric scene, camera controls, altitude framing, particle rendering, and interactive 3D layers.
- **Existing chart library or Apache ECharts**: forecast timeline, uncertainty bands, time series, comparisons, and model diagnostics. Use the existing library if it is already suitable.

## Application architecture
Keep the current framework, backend, routes, state management, and data integrations unless inspection reveals a concrete reason to change them. Do not rewrite the app merely to match this recommendation.

Recommended logical modules:
1. Data adapters — Open-Meteo, OpenAQ, and any verified AQI source.
2. Data normalization — units, timestamps, quality flags, provenance, and missingness.
3. Shared twin state — selected time, variable, location, playback, and visible layers.
4. Geospatial view — MapLibre + deck.gl.
5. 3D atmospheric view — Three.js/R3F.
6. Forecast contract — typed, versioned output schema; initially no new trained model.
7. Early-warning presentation — risk windows, uncertainty, thresholds, and source timestamps.
8. Validation and observability — tests, stale-data indicators, API failures, performance.

## Why this stack
- MapLibre handles the map and map interaction.
- deck.gl handles large spatial datasets and GPU-accelerated layers.
- Three.js/R3F handles the separate three-dimensional scene and camera.
- Shared state and common data contracts synchronize the map and 3D scene without forcing all rendering into one engine.

## Data limitations to account for
The weather CSV includes hourly data for 2023–2025 and an appended daily section. The AQI CSV is a wide table with months embedded in the second column and appears to span 2017–2023. Confirm source metadata, geography, time zone, and units before training or evaluation. The PPT's stated study period is 2023, so a 2023-aligned dataset should be prepared for a fair initial evaluation, with other years considered only after validation.

## Avoid
- Replacing a real map with a decorative pseudo-map.
- Fake 3D pollutant transport.
- Treating point observations as a complete spatial field without labeling interpolation.
- Training a model before validating source data and building the app integration.
- Installing dependencies before checking existing versions and compatibility.
