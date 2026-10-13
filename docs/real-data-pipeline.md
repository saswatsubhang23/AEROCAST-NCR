# Real-data pipeline: results of the run on 2026-10-09/10

Design, sources, alignment, units, flags and the leakage rules are in **`docs/historical-data-pipeline.md`** (this is the
real-data pipeline document; it is not duplicated). This file records what the pipeline actually produced, and is generated from
`docs/data/coverage-report.{md,json}` (`python -m app.history report`).

## What was acquired

| Source | Endpoint | Amount | Notes |
|---|---|---|---|
| OpenAQ v3 | `/locations`, `/locations/{id}/sensors`, `/sensors/{id}/hours` | 2,263 + about 1,750 earlier requests, 404 sensors, **3,009,696 hourly rows**, 70 stations | 2025-10-09 to 2026-10-10; free tier 60 requests/min; key from `api/.env`; a refresh of 90 recent windows found 0 revised rows |
| Open-Meteo archive | `archive-api.open-meteo.com/v1/archive` | **614,810 hourly rows**, 70 station points, 11 variables | UTC; future hours of the current day dropped; 11,830 rows within 7 days of fetch flagged provisional |
| Not used | OpenAQ S3 archive, Open-Meteo historical-forecast, CPCB portals | | reachable (S3, historical-forecast) or no documented API (CPCB) |

Licences: OpenAQ data carry the provider's licence per station (`stations.license`, often unset); Open-Meteo free tier is
non-commercial. Files are in `api/data/history.sqlite` (git-ignored).

## Quality findings (all computed)

* **Coverage:** about 86% of active station-hours are usable for PM2.5, PM10, NO₂, SO₂ and O₃ (coverage by region 78 to 88%; by month 63 to 93%, lowest in 2026-01 at about 64%).
* **Flags:** LOW_COVERAGE 393,887 hours (13%), FLATLINE 16,696, NEGATIVE 155, NULL_VALUE 2,315, OUT_OF_RANGE 10, UNIT_CONVERTED 1,466,224, UNIT_SUSPECT 510,500 (all CO).
* **CO is unusable.** All 68 active CO sensors are labelled ppb with median values around 1. That is physically impossible for ppb; the values behave like mg/m³. The pipeline neither guesses nor rescales: the rows are flagged `UNIT_SUSPECT` and CO is "insufficient" for modelling.
* **Duplicates:** 3,009,696 raw rows became 3,009,696 clean rows; **0 hours had more than one candidate sensor** (the window gate leaves one active sensor per station and pollutant), and a refresh of 90 recent windows produced no revised values.
* **Timestamp convention:** OpenAQ's CPCB hours end at :30 UTC (IST hour boundaries); labels use the period midpoint. OpenAQ's hourly value was verified against raw 15-minute samples for one sensor-day: it blends neighbouring provider hours (about 45 minutes of smoothing).
* **Newest data / publication latency:** age of each station's newest hour at fetch time: median **55.4 h**, minimum 1.6 h, maximum 6,880 h (a station that stopped reporting). The CPCB-sourced series end on 2026-10-07 14:00 UTC; one non-CPCB station reports later.
* **Weather:** the 70 station points are served by **34 distinct provider grid cells**; neighbouring stations share identical weather. No weather variable had missing values in the stored window.

## Which targets and horizons the data supports

By the pipeline's own thresholds (at least 1,500 usable origin/target pairs with weather and 120 days of span per station; 20 qualifying stations): **PM2.5 (69 stations), PM10 (68), NO₂ (68), SO₂ (59), O₃ (68) are "supported" at +1, +3, +6, +12, +24, +48 and +72 h; CO is "insufficient".**
This says a station-level model *can be trained and tested*. It does not say how accurate it is (see `docs/ml-model-comparison.md`), and it
does not support operational use, because the feed lags by about two days.

## Spatial suitability

About 70 stations, median nearest-neighbour spacing about 3 km, concentrated in Delhi. Supports station-level forecasts and a
documented interpolation; does not support a high-resolution map-wide forecast (`docs/spatial-forecasting.md`).

## Reproduce

`python -m app.history discover && python -m app.history ingest-air --rate 45 --concurrency 7 && python -m app.history ingest-weather && python -m app.history clean && python -m app.history report` (resumable; about 70 minutes of OpenAQ requests at the free rate limit; `clean` about 5 minutes with the `raw_air(station_id, parameter, period_to_utc)` index).

## Second source added 2026-10-10: XKDR India air-quality archive (CPCB history)
`python -m app.history ingest-xkdr` (module `app/history/ingest_xkdr.py`, key `INDIA_AQI_API_KEY`). The service's `/v1/meta` describes it as CPCB CAAQM
(and US-embassy) readings from 2009-01, hourly (`n` = 1), timestamps in naive IST, tier "full". For Delhi-NCR the data **end on 2025-09-01**, so it is a
history, not a live feed: it does not fix the two-day lag, but it extends training from one year to about three and a half (default window 2022-01-01 to 2025-09-01),
covering several winters and monsoons. Stations matching an OpenAQ station (same normalised name or within 300 m) keep its id, so one station is one series.
Assumptions and limits: `period_start` is read as the start of an IST hour (not verifiable: no period overlaps the OpenAQ data, whose window starts 2025-10-09; at most one hour of misalignment);
no coverage percentage is available; a gap of about five weeks (2025-09-02 to 2025-10-08) separates the two sources; the archive's own licence terms are unknown.
