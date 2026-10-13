# Historical data pipeline

An offline, reproducible pipeline that turns provider history into audited, model-ready tables. **It trains no model and
produces no forecast.** It lives in `api/app/history/` and reuses the application's existing clients
(`integrations/openaq.py`, `integrations/openmeteo.py`, `integrations/http.py`), station inventory bounds
(`services/air_quality.py:AQ_BBOX`), city geography (`core/places.py`) and time helpers (`core/time.py`).

## 1. Sources: what was verified and what was not

Checked live with `python -m app.history sources` (HTTP status and one-line evidence) and during development:

| Source | Status | What it provides | Used? |
|---|---|---|---|
| OpenAQ v3 API (`/locations`, `/locations/{id}/sensors`, `/sensors/{id}/hours`) | verified, key accepted; header `X-Ratelimit-Limit: 60` per minute | hourly aggregates per sensor with period start/end in UTC and local time, coverage counts, per-sensor first/last dates; 1,000 rows per page | **yes** (all air quality) |
| Open-Meteo archive API (`archive-api.open-meteo.com/v1/archive`) | verified, no key | hourly UTC values for the 11 variables below, the grid cell used, elevation; no nulls for the variables tested | **yes** (all weather) |
| Open-Meteo historical-forecast API | reachable, 24 rows returned for one day | what a weather *forecast* said at the time | no (needed later for honest forecast-time weather inputs) |
| OpenAQ public S3 archive (`openaq-data-archive`) | reachable and listable | per-location, per-day `csv.gz` of raw sub-hourly records (`location_id, sensors_id, datetime (IST), lat, lon, parameter, units, value`) | no. Used once to cross-check the API (section 5) |
| CPCB portals (cpcb.nic.in / CCR) | not used | no documented public data API was verified | no. CPCB data arrives through OpenAQ |
| PostgreSQL/PostGIS | **unreachable** (`python -m app.history check-db`: OperationalError, `localhost:5432` placeholder default; `DATABASE_URL` is not set in `.env`) | none | no. The pipeline stores to SQLite |

Nothing is fetched from any endpoint that was not exercised.

## 2. Storage and layers

SQLite file `DATA_DIR/history.sqlite` (default `api/data/history.sqlite`, git-ignored). SQLite follows the project's existing
local-state pattern (`alerts/store.py`, `kb/registry.py`) and PostgreSQL was not reachable. The tables are plain SQL and no
PostGIS feature is used, so the same schema can be created in PostgreSQL once it is available and verified.

| Layer | Tables | Rule |
|---|---|---|
| Raw | `raw_air`, `raw_weather`, `raw_weather_meta`, `raw_*_progress`, `ingest_runs` | exactly what the provider returned; append-only (`INSERT OR IGNORE` on a content hash); a revised value becomes a second row, never an overwrite |
| Reference | `stations`, `sensors` | coordinates, owner, licence, provider, region; per-sensor unit and first/last dates; one row per sensor |
| Clean | `clean_air`, `clean_weather`, `sensor_unit_checks` | derived only from raw; **rebuilt from scratch on every run**; values never edited |
| Model-ready | `model_ready`, `feature_sets` | derived only from clean; rebuilt on every run; `feature_sets` stores parameters, column list, row count and a SHA-256 of the content |

Provenance kept per raw air row: sensor id, station id, parameter name, **unit as received**, period start and end in UTC,
the provider's local period end, the value, summary min/max/sd, expected/observed sample counts, percent coverage, the
provider's flag indicator, fetch time and run id. Per weather point: requested coordinates, provider grid latitude and
longitude, elevation, units and the request parameters. Station coordinates, provider, owner and licence are in `stations`.

## 3. Running it

```bash
cd api
python -m app.history check-db                 # PostgreSQL/PostGIS reachable?
python -m app.history sources                  # live source probes
python -m app.history discover                 # 108 stations, sensors with their own first/last dates
python -m app.history ingest-air  --concurrency 5 --rate 55
python -m app.history ingest-weather
python -m app.history clean
python -m app.history features --pollutants pm25,pm10 --latency-hours 0
python -m app.history report                   # writes ../docs/data/coverage-report.{md,json}
python -m app.history all                      # all of the above
```

* **Resumable and idempotent.** Each (sensor, 40-day window) is recorded in `raw_air_progress`; re-running skips finished
  windows. Windows ending within 10 days of the fetch (air) are always fetched again, because providers revise recent data;
  old windows are final. Weather works the same way (90-day windows, 5 locations per request).
* **One window per dataset.** Steps after the first reuse the window of the most recent `ingest-air` run unless
  `--from/--to` are given, so the chunk boundaries cannot drift when the date changes.
* **Reproducible.** Cleaning, features and the report are pure functions of the raw tables (tests prove two runs give
  identical digests). Re-running ingestion later adds newly published or revised rows; it never changes what was stored.

## 4. Timestamp alignment

* Everything is stored in UTC; IST is a display conversion (`period_to_ist`, `origin_ist`).
* OpenAQ's CPCB hours run on India's local hour: 05:00-06:00 IST is **23:30-00:30 UTC**, so periods end at :30 UTC.
* `label_utc` = the **midpoint** of the period rounded half-up to the hour (23:30-00:30 UTC → 00:00 UTC). It lines up with
  Open-Meteo's hourly stamps. A period whose midpoint is not on the hour is rounded and flagged `ALIGN_ROUNDED`; a period
  that is not one hour long is flagged `PERIOD_IRREGULAR` and is unusable.
* Residual mismatch: Open-Meteo precipitation is a sum over the *preceding* hour while the air-quality hour is centred on
  the label, so precipitation leads the air-quality hour by about half an hour. Other variables are instantaneous.

## 5. What the hourly air-quality values really are (checked against raw samples)

OpenAQ's hourly value was compared with the raw 15-minute records of the same sensor in the public S3 archive (Alipur PM10,
2026-10-03, 21 hours): the hourly value equals the **mean of the four 15-minute samples stamped inside (from, to]**, rounded
to an integer, to within rounding in every hour. In those records each underlying value is repeated in three consecutive
15-minute rows before it changes (for example `310, 310, 310, 278`), so the hourly aggregate is **three quarters of the
previous hour's published value and one quarter of the next**. The series is therefore smoothed and lags the instrument by
roughly 45 minutes. This was verified for one sensor and one day only; it is [unverified] for the rest of the network.
Use S3 ingestion (not implemented) if exact hourly values matter.

## 6. Units

`orig_value` and `orig_unit` always hold the provider's number and unit. `value_std` is in **µg/m³**:

| Received | Treatment |
|---|---|
| µg/m³ | unchanged |
| mg/m³ | x1000, flag `UNIT_CONVERTED` |
| ppb / ppm (NO₂, SO₂, CO, O₃) | molar mass / 24.45 L/mol (25 °C, 101.325 kPa), flag `UNIT_CONVERTED`. Real temperature and pressure differ from these reference conditions by a few percent |
| ppb for PM, or an unknown unit | no conversion, `UNIT_UNKNOWN`, unusable |

**Unit sanity check.** After conversion, a sensor whose median differs by more than 20x from the median of sensors that
report the same pollutant natively in µg/m³ (at least 3 such references required) is flagged `UNIT_SUSPECT` and excluded.
The first data pulled showed CO sensors labelled "ppb" with values around 1, about a thousand times too small for ppb and
consistent with mg/m³ or ppm. The pipeline does not guess the real unit and does not rescale: the rows stay in raw,
are listed in the report and are not used. The list is in section "Sensors whose labelled unit contradicts their
magnitude" of the generated coverage report.

## 7. Quality flags

Hard (value unusable): `NULL_VALUE`, `NEGATIVE`, `OUT_OF_RANGE` (physical-plausibility limits in `history/units.py`, not
regulatory standards), `UNIT_UNKNOWN`, `UNIT_SUSPECT`, `PERIOD_IRREGULAR`. Soft (value kept): `LOW_COVERAGE` (< 75% of the
expected samples), `FLATLINE` (6 or more identical consecutive hourly values), `UNIT_CONVERTED`, `REVISED` (same sensor
fetched again with a different value; the later fetch is used), `MULTI_SENSOR` / `SENSOR_CONFLICT` (several sensors reported
the same hour; the better covered one is used, a >10% and >2 µg/m³ disagreement is a conflict), `ALIGN_ROUNDED`, `PROVISIONAL`
(weather fetched within 7 days of its time; a conservative choice of this pipeline, not a provider statement).
Weather values outside physical limits get `OUT_OF_RANGE:<variable>` and are masked in `model_ready`.

**Duplicates.** Several raw rows for one (station, pollutant, hour) are reduced to one by a fixed rule: per sensor the latest
fetch; across sensors (usable first, higher coverage, later sensor end date, higher id). The number of candidates is kept
(`n_candidates`). Legacy sensors that stopped reporting before the window are never requested (their dates come from the
provider's own `/locations/{id}/sensors`).

**Missing values.** A missing hour has no row and is never filled; counts of observed hours appear in every rolling window
(`target_n_*`) and in the coverage report. Weather features are null, never zero, when weather is missing.

## 8. Features and the no-leakage rule

`model_ready` has one row per (station, target pollutant, origin hour `o`). Default targets: PM2.5 and PM10. A row exists
only where the target pollutant has a usable value at the cutoff hour.

* **Time (IST):** hour, weekday, month, weekend flag, sin/cos of hour and day of year. No holiday calendar exists in the data.
* **Target history:** lags 0, 1, 2, 3, 6, 12, 24, 48, 168 h; rolling mean/std/min/max/count over 3, 6, 12, 24, 72 h (reported unknown if fewer than half the window's hours were observed); the latest value of each of the six pollutants.
* **Weather at the origin:** temperature, humidity, dew point, pressure and its 3 h tendency, wind speed (m/s), **wind vector components** `u` (east) and `v` (north) from speed and the direction the wind blows *from* (0° wind: `v < 0`), gusts, precipitation, cloud, boundary layer height, shortwave radiation; 3 h and 6 h lags of temperature, humidity, `u`, `v`, boundary layer height; 24 h precipitation sum, 6/24 h means of wind speed and boundary layer height, hours since rain (null when no rain has been seen yet, which is *unknown*, not zero).
* **Quality:** whether weather is provisional; whether the origin hour had low coverage.
* **Targets:** `y_h1, y_h3, y_h6, y_h12, y_h24, y_h48, y_h72`: the usable value at `o + h`, null if missing. They are the only values taken from after the origin and are never inputs.

Leakage rules, each covered by a test that perturbs the future and requires identical features for the past:
1. pollutant features use hours <= `o - latency_hours`; weather features use hours <= `o`;
2. rolling statistics and lags look backwards only and never fill gaps;
3. weather at or after `o` is **not provided at all**. Archive weather for the target hours is a perfect forecast; a real system would have a weather *forecast* there. The historical-forecast API exists for that purpose and is not yet ingested;
4. only flags that depend on the row itself (low coverage) are features. `FLATLINE` (needs later hours) and `REVISED` (needs a later fetch) stay in `clean_air` but are excluded from `model_ready`;
5. no scaling, imputation or encoding is learned in this phase, so nothing is fitted on the whole history.

**What is *not* leak-free by construction.** `UNIT_SUSPECT` and the physical-range exclusions are decided with whole-history
information (a sensor median). That is dataset curation, not a use of future *target* values for a particular row, but a
strict backtest should know that the usable/unusable decision was made once, over the entire window.

**Publication latency.** `latency_hours` (default 0) shifts pollutant features back by that many hours. The feed's observed
delay is reported in the coverage report ("Publication latency"); with `latency_hours = 0` the rows describe an instantaneous
feed that does not exist operationally.

## 9. Coverage report

`python -m app.history report` writes `docs/data/coverage-report.md` and `.json` with coverage **by pollutant, by station,
by month (IST) and by region** (nearest of the five NCR city centres within 30 km, else "Other NCR"; plus region x month),
flag counts, units received vs standardised, duplicates, unit-suspect sensors, weather null rates and monthly coverage,
publication latency, and the target/horizon support table. Definitions:

* *active hours*: hours inside the window during which the provider says a sensor existed (its first to last datetime), so a sensor that had not started yet is not counted as a gap;
* *usable hour*: a `clean_air` row with no hard flag; `coverage = usable / active`; per-station gaps and longest gap are listed.

**Target and horizon support.** A station counts toward a (pollutant, horizon) cell if it has at least 1,500 origin/target
pairs with weather present over a span of at least 120 days. A cell is *supported* with at least 20 such stations, *limited*
with at least 5, otherwise *insufficient*. These thresholds are this pipeline's own conservative choices, not statistical
guarantees. The table says whether a model could be trained and tested; using it live also needs the feed latency to be
smaller than the horizon.

RESULTS_PLACEHOLDER

## 10. Tests

`tests/test_history_core.py` (units, alignment, wind vectors, rolling statistics against a brute-force version, leakage by
future perturbation for latencies 0/1/6/24) and `tests/test_history_pipeline.py` (mocked OpenAQ/Open-Meteo ingestion:
discovery, provenance, idempotence, resume, failed windows, pagination, rejected key, revisions, refresh rules; cleaning
rules; unit sanity; weather future-row dropping; model-ready tables; reproducible digests; coverage numbers checked by
hand; CLI end to end; PostgreSQL check). They use in-memory SQLite and mocked transports; no network.
