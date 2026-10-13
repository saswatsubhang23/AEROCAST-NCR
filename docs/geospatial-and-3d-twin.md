# Geospatial layer (Prompt 4) and 3D atmospheric twin (Prompt 5)

Instructions followed: `CLAUDE.md`, `TECH_STACK.md`, `DATASET_AUDIT.md`, `CLAUDE_PROMPTS_4_TO_6.md` in the project root. Prompt 6 (final
forecasting and model training) is **not started and stays locked** until it is explicitly authorised. No model was trained, retrained or
tuned in these two prompts.

## What already existed (preserved)
MapLibre GL JS 6 + deck.gl 9 (`@deck.gl/mapbox` overlay) on `/twin`, ECharts panels, FastAPI endpoints for the station window, spatial estimate,
back-test, risk windows, regimes, weather fields and simulations. Nothing was rebuilt; the map instance, routes and API calls are the same.

## Prompt 4: what was added
| Requirement | Implementation |
|---|---|
| Reusable layers and a registry | `web/src/lib/twin/layers/definitions.ts`: every layer is declared once (id, group, data status, help, lenses, surfaces, availability with an honest reason, builder, legend). Panel, legend, map and 3D ground all read it. Old per-view builders were deleted. |
| Variables that exist | PM2.5, PM10, NO2, SO2, CO, O3; **AQI** (CPCB method, derived by the application's existing `compute_aqi` from stored hourly values, null when the CPCB completeness rules are not met); weather model fields: temperature, humidity, precipitation, cloud cover, boundary-layer height, wind speed/direction, mean sea-level pressure |
| Station observations, aggregation, contours | observation dots; **hexagon aggregation** (4 km, mean, at least two stations per hexagon, offered only with at least 15 observations, drawn as a summary and never as interpolation); contours of the spatial estimate (documented IDW) and of model sea-level pressure (marching squares, interval chosen from the data) |
| Wind from real vectors, explicit convention, tested | `lib/twin/windVector.ts`: direction is where the wind comes FROM, u east, v north, `u = -speed sin(dir)`, `v = -speed cos(dir)`; backend `uv_from` uses the same; round-trip, calm and missing-value tests |
| Time, variable, toggles, opacity, legend with units and source time, no-data and stale states | shared timeline with play/pause/step/scrub/speed; variable selector; per-layer visibility and opacity; legends show unit, classes, source time, age and a Stale badge; unavailable layers list the reason; hollow rings for missing observations |
| Observations / forecasts / interpolated / hypothetical distinguished | one badge vocabulary (Observed, Derived, Spatial estimate, Weather forecast, Model forecast, Simulated, Hypothetical, Stale, Unavailable) on layer rows, legends and the map |
| No invented stations | invalid coordinates are dropped (never drawn at 0,0); stations with no value are rings |
| Optimisation and cleanup | one MapLibre map, one overlay, layers updated in place by stable id, one bounded particle loop (500 particles, fixed life) cancelled on input change and unmount, not started under `prefers-reduced-motion` |

New backend: `GET /api/twin/window?pollutant=aqi` (AQI as a window with dominant pollutant and lower-bound flags), an exact-endpoint test list,
a start-up warm-up of the twin inventory, and a covering index (cold window 23 s to 2.5 s). Fixed on the way: the default station could have no
observations in the displayed window; a single-column grid track could grow past a phone viewport (58 px overflow); fieldsets forced min-content width.

### Shared twin state
`lib/twin/store.ts`: lens (stations / atmosphere / simulation), display (map / 3D / compare), selected timestamp, playback and speed, variable,
selected location, layer visibility and opacity. Invalid timestamps and coordinates are refused, speed and opacity are clamped, playback
stops when the lens or variable changes. The 2D map, the 3D scene, the panels and the inspectors read and write this one store.

## Prompt 5: the 3D twin
Three.js 0.186 + React Three Fiber 9.8 + Drei 10.7 (React 19.3 compatible; checked against the packages' peer ranges before installing).
`components/twin/scene3d/`; the scene is code-split and loaded only when the 3D or Compare display is opened.

| Requirement | Implementation |
|---|---|
| Meaningful frame, camera, altitude axis, geographic context, legend | metric frame (1 unit = 1 km, x east, z south, y altitude x12), graticule every 0.25 degrees, domain boundary, five reference cities, altitude axis with 0.5/1/2/3 km levels and the exaggeration stated on it, four camera presets with smooth transitions, orbit/zoom/pan, the same legends as the map |
| Shared data and state | the scene is built by `buildSceneData(ctx, settings, scales)` from the same `LayerContext` and layer settings as the map; verified in the running app: moving the shared timeline updates map badge, scene label and slider; changing the variable updates both and the legend |
| Wind from real fields | particles follow the model wind of the selected hour, drawn 10 m above ground; no vertical wind exists in the data, so no vertical structure is implied and the notes say it is not pollutant transport |
| Concentration only where coverage supports it | ground colour is the active raster (estimate surface, weather field or simulated concentration) with unknown cells clear; station columns encode value as a bar (stated as not altitude) |
| Altitude only if defensible | **boundary-layer height surface** (model mixing depth, the one vertical quantity available); **mixed-layer slab** is explicitly ILLUSTRATIVE (it draws the model's assumption of uniform concentration up to the boundary-layer height), off by default; no vertical concentration is fabricated |
| Interaction | play/pause/speed (shared), variable selector, camera presets, hover tooltips on station columns, click to select station or ground point (shared location), Compare display (map and 3D side by side, one state) |
| Visual quality without obscuring data | ambient + directional light, fog for depth, translucent surfaces; no bloom (not needed, keeps the GPU budget) |
| Budgets and disposal | 500 particles, instanced meshes for columns and slab, `frameloop="demand"` unless particles animate, manual disposal of geometries and the ground texture |
| Forecast-ready interface | `lib/twin/contract.ts`: versioned frame schema (`aerocast.twin-forecast/1`) with target/unit, generated and valid times, horizon, spatial (station, point or grid), value and bounds, model name/version, input freshness, quality flags; strict validator (rejects wrong version, missing fields, timestamp misalignment, negative or NaN values, broken intervals, wrong grid shape); adapter from the existing validated back-test; a `Forecast at the selected station` layer that is drawn only for a frame valid at the selected hour |
| Honest states | unavailable layers state why (no fields, no run, no forecast frame, AQI not forecastable), loading and error states, stale badges, "What is data and what is illustration" panel in the scene |

### What is data-driven and what is illustrative
Data: station columns (observations or AQI derived from them), ground colour fields (estimate, weather model, simulation), boundary-layer height
surface, 10 m wind particles, pressure contours, forecast marker (only from a contract-valid frame). Illustrative or reference: the 12x
altitude exaggeration, the mixed-layer slab, the reference planes and graticule, city names. There is no basemap imagery in 3D (tile textures
are cross-origin), so geographic context is the graticule and cities.

## Verification actually performed
* `tsc --noEmit`: no errors. `eslint src`: no errors. `vitest`: **116 passed (13 files)**. `next build`: passed, `/twin` static.
* Backend suite: **682 passed** (run after Prompt 4 changes); after the later warm-up change `test_twin.py` and `test_system.py` were re-run: 42 passed.
* New tests: store (9), wind convention, registry and layer behaviour (12), contract (7), scene geometry (9), scene data (6), AQI backend (5), earlier simulation tests untouched.
* Browser (desktop and 375 px): stations, estimate with contours, hexagons, AQI, atmosphere in 2D and 3D, simulation in 2D and 3D with slab, Compare. axe-core: 0 violations on Compare; horizontal overflow 0 at 375 px after fixes.
* Production build served separately on a second port: opening the 3D view logged **0 console errors**.
* Resource cleanup: three mount/unmount cycles of the 3D view each went from 93 geometries and 2 textures to 0 and 1, with no growth.

## Known limitations
* Dev server only: React StrictMode's double mount makes R3F log "Attempted to synchronously unmount a root" about 10 times when the 3D view is mounted. The production build logs none.
* The spatial estimate does not beat a plain mean of other stations in leave-one-out (PM2.5 skill -0.05), and the transport hindcast does not beat persistence (see `feature-03-dynamic-digital-twin.md`). The twin states both.
* Observations are a history (newest stored hour 2026-10-07 14:00 UTC); every layer built from them shows Stale. The live simulation is initialised from those hours and says so.
* No wind or concentration exists above the surface in the data, so there is no volumetric measured field to show; the 3D view is honest about that rather than decorative.
* One WebGL texture remains counted on a disposed renderer after unmount (constant, not growing); the browser frees it with the context.
* `npm audit` reports 5 high advisories, all `braces` through the ESLint/Next tooling (dev-only, pre-existing, not from the 3D packages). Not force-fixed.
* The repository already contains models trained in earlier sessions (before these instructions) and the Settings page shows their recorded held-out scores. `CLAUDE.md` asks for no accuracy claims before Prompt 6; those pages were left unchanged and are flagged here for your decision.
