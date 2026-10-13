# Feature 02: operational weather map and timeline (2026-10-10)

The existing `/twin` map (one MapLibre map, one deck.gl overlay, one `useBaseMap`) gained an **Atmosphere** view. Nothing was
rebuilt: the station view is unchanged and both views share the same map instance, timeline controls and ECharts.

## What the data supports (inspected before building)
Real Open-Meteo responses were fetched and read first. Findings that drove the design:

| Question | Finding |
|---|---|
| Variables available hourly with units | temperature 2 m (°C), relative humidity (%), `pressure_msl` (hPa), precipitation (mm, hourly total), cloud cover (%), boundary-layer height (m), wind speed (m/s) and direction (°). All non-null for the lattice, in forecast and archive. |
| Time span | forecast API: 7 past days and up to 16 forecast days in one request (the app uses 2 past + 3 ahead, 120 hourly frames). Archive API: past days only, trailing real time by a few days; the app refuses today and later. |
| Spatial resolution | Point series from a model grid. At this location the default model is ECMWF IFS with cells of about 0.07° (8 km), measured from the snapped coordinates of 26 closely spaced probes. Not a raster product. |
| MSL pressure gradient | A real but small gradient: 1.9 hPa across the area at the time of testing, about 0.2 hPa over 1° in one probe. Contours therefore use a fine interval chosen from the data and state it. |
| Precipitation | Hourly totals in mm for the hour ending at the timestamp; mostly 0, sporadic light amounts. |

## Backend: `GET /api/weather/fields`
`app/services/weather_fields.py`. An 8 x 9 lattice over Delhi-NCR (0.136° x 0.138°, every second model cell, so each point is a distinct
cell), values passed through unchanged, in two request chunks. Out-of-range or missing values become `null`, never filled. Wind is
returned as u/v components (m/s) from speed and "from" direction. The response carries `grid`, `times` (UTC), `now_index`, per-variable
units and `valid_fraction`, `source` (provider, resolution, maximum distance between a requested point and the cell served, retrieval
time) and `notes`. Modes: `forecast` (30 min cache) and `historical` (start/end dates, at most 10 days, 24 h cache). Invalid windows are
HTTP 422 with a reason; upstream failures are 503.

## Frontend
* `lib/twin/fields.ts` (pure, 15 unit tests): nearest-time index, bilinear sampling (null if any corner is missing), marching-squares
  contours (no line across a gap), contour interval selection, raster generation in Web-Mercator rows, documented colour scales, wind
  advection.
* `components/twin/atmosphereLayers.ts`: deck.gl layers with **stable ids**: `field-raster` (BitmapLayer), `pressure-contours` and
  `pressure-labels`, `wind-arrows`, `wind-particles`, `inspect-point`. Deck.gl updates them in place.
* `TwinMap`: the same map; `atmosphere` prop adds the field layers; stations become neutral rings. The particle loop is a single
  `requestAnimationFrame` effect that is cancelled when its inputs change or the component unmounts, runs at about 20 frames/s, and is not
  started when the user prefers reduced motion (arrows remain).
* `AtmosphereLayerManager`: one colour field at a time (precipitation, temperature, humidity, cloud cover, boundary-layer height, none),
  overlays for contours, particles, arrows and stations, per-layer opacity, legend with unit, help text per layer, "no data" when a
  variable has no valid values.
* `FieldInspector`: click the map to get every variable at that point and hour (value, unit, timestamp, provenance badge) and a time series;
  clicking the chart moves the timeline.
* Time: one `selectedTime` drives the station timeline, the field timeline, the map and the charts, so switching view or mode keeps the same
  instant (nearest frame). Play, pause, step, scrub and 1x/2x/4x speed work on whichever axis is active. Modes: recent and forecast
  (with a "now" indicator: hours ahead or ago) and historical (archive, 3-day window from a chosen date).

## Colour scales (documented)
| Layer | Scale |
|---|---|
| Precipitation | mm per hour; classes 0.1-0.5, 0.5-1, 1-2.5, 2.5-5, 5-7.6, 7.6-15, 15-50, >50 following standard hourly rain-rate classes (slight below 2.5, moderate 2.5-7.6, heavy 7.6-50, violent above 50); below 0.1 mm not drawn |
| Temperature | 2 °C bins from the window minimum to maximum, one scale for the whole loaded window |
| Humidity, cloud cover | 0 to 100 % in 20 % bins |
| Boundary-layer height | 500 m bins from 0 to the window maximum (at least 1500 m) |

## Honest limits (also shown in the product)
* Values are model output at lattice points; the raster between points is bilinear interpolation for display, at the model's own resolution.
* Wind particles follow the model wind of the selected hour; one second of animation is about 30 minutes of drift. It is **not** pollutant transport.
* Pressure differs by only a few hPa across the area; contour lines show a gentle gradient, not fronts.
* The archive trails real time by a few days; the newest days exist only in forecast mode. An unavailable window shows an error, never an empty or invented frame.
* The Atmosphere view still opens the station window first (the page's data gate); if the historical store is missing, the view is unavailable.

## Verification (observed in the running application)
Forecast mode: 120 frames, now marker, precipitation raster, labelled contours, animated particles, layer switch to temperature and
boundary-layer height updating legends from real ranges, inspector values with units and times, play/pause/step, chart-click seeks the
timeline. Historical mode: 72 frames for 2026-10-04 to 2026-10-06. Error state: a window that includes today shows the provider-independent
reason and hides the timeline. Axe: 0 violations; no horizontal overflow at 375 px. Tests: backend 8 new (`test_weather_fields.py`),
frontend 15 new in `fields.test.ts` (67 total, all passing); tsc and eslint report nothing.

## Defects found on the way and fixed
* Station inventory aggregated millions of rows per request (22 s cold). Added a covering index `ix_clean_air_usable`, a result cache keyed by file modification time and a background warm-up; cold window request 2.5 s, warm 0.4 s.
* The trained model was re-loaded (checksums and deserialisation) on every `/api/models/status` call and slowly grew the API process to 3 GB and 277 threads, which starved outbound HTTP. `load_run` is now cached by the run pointer's modification time; the process stays near 520 MB and warm endpoints answer in about 0.2 s.
* Tab triggers without matching panels (axe `aria-valid-attr-value`): panels added.
