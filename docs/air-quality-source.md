# Air-quality data source

## What was verified (9 Oct 2026) and how

| Candidate | Finding | Used |
|---|---|---|
| **OpenAQ v3** (`https://api.openaq.org/v3`) | Documented REST API. **Requires an API key** in the `X-API-Key` header (an unauthenticated request returns `401`). Endpoints, parameters and response fields were read from OpenAQ's own OpenAPI spec (`https://api.openaq.org/openapi.json`). Free tier: 60 requests/minute, 2,000/hour. | **Yes** |
| CPCB portal (`airquality.cpcb.gov.in/ccr`) | A single-page web app. No documented public API was found; reverse-engineering its internal calls would mean guessing an undocumented endpoint, so it is not used. | No |
| data.gov.in AQI resource | Documented, needs a key. `api.data.gov.in` refused connections from the development machine, so it could not be verified. | No |
| Open-Meteo air quality (CAMS) | Works without a key but is **model output, not observations**. | No |

Used from the OpenAQ spec: `GET /v3/locations` (`bbox`, `monitor`, `providers_id`, `limit`, `page`),
`GET /v3/locations/{id}/latest`, `GET /v3/sensors/{id}/hours` (`datetime_from`, `datetime_to`, `limit`).
Response fields used: `coordinates.latitude/longitude`, `sensors[].parameter.{name,units}`, `provider`, `owner`,
`licenses`, `datetimeLast.utc`, and for hourly rows `value`, `period.datetimeTo.utc`, `coverage.percentCoverage`.

### Checked against the real feed (9 Oct 2026, with a key)

* **Stations:** 69 active fixed stations in the Delhi-NCR box (39 more reported nothing in 7 days and are left out):
  67 from provider CPCB (via DPCC, UPPCB, HSPCB, ...), 1 AirNow (the US Embassy monitor) and 1 IITM. Licence shown by
  OpenAQ: US Public Domain.
* **Units are mixed, and sometimes doubtful.** PM2.5, PM10 and O₃ are in µg/m³ almost everywhere. NO₂ is in **ppb** at
  45 of 68 stations, CO in **ppb** at 40 and SO₂ in **ppb** at 39 (the rest µg/m³); one O₃ sensor is in ppm. Some CO
  values labelled ppb (for example 0.4) look implausibly low for ambient air, so the unit label itself may be wrong.
  AEROCAST therefore never converts ppb/ppm, and such pollutants are excluded from the AQI with the reason shown.
* **"Latest" can be ancient.** OpenAQ returns each sensor's last value however old: 155 of 400 readings were more than
  7 days old and some were from 2022. These are now dropped (`AQ_ACTIVE_DAYS`, default 7), so a station shows
  "No recent reading" rather than a years-old number.
* **Freshness varies by station and by hour.** At one check nearly all CPCB stations' newest data were about 51 hours old
  while the AirNow station was current; at a later check some CPCB stations had data from the same evening. The page and
  the assistant report each reading's age and flag stale ones.
* **AQI is often not computable**, correctly: the AirNow station had only 10 of the 16 required hours of PM2.5, and
  several CPCB stations had no hourly data in the last 30 hours. No AQI is shown in those cases, with the reason.

## Enabling it

1. Create a free key at <https://explore.openaq.org/register>.
2. Put `AQ_API_KEY=...` in `api/.env` (never in the frontend or git).
3. Restart the API. `GET /api/system/status` should show `aq_provider: ok`.
4. Open **Air Quality**. The first load fetches each station's latest values at ≤50 requests/minute, so it can take
   about a minute; results are cached for 15 minutes.

Optional settings: `AQ_REFERENCE_ONLY` (default `true`: regulatory-grade monitors only), `AQ_PROVIDER_IDS`
(restrict to specific OpenAQ providers, e.g. a government provider), `AQ_ACTIVE_DAYS`, `AQ_STALE_AFTER_S`.

## What is shown, and what is not

* **Concentrations** are shown exactly as reported, in each sensor's own unit, with the source timestamp.
* **AQI** is *computed by AEROCAST* with the CPCB National AQI method
  (<https://airquality.cpcb.gov.in/ccr_docs/How_AQI_Calculated.pdf>) and is always labelled as computed, never as a
  CPCB-reported value. Rules applied from that document: sub-index from the 24-hour average (8-hour for CO and O₃);
  at least 16 valid hours per pollutant; at least 3 pollutants including PM2.5 or PM10; worst sub-index wins;
  O₃ uses the 1-hour value when the 8-hour average exceeds 208 µg/m³; concentrations are truncated.
  The Severe band has no published upper breakpoint, so such values are reported as "≥ 401".
* **AEROCAST assumptions** (also returned with every result): CO/O₃ also need ≥6 valid hours in their 8-hour window
  (CPCB does not state this); ppm/ppb values are **not** converted (needs temperature and pressure), so that pollutant
  is excluded; CO in µg/m³ is converted exactly to mg/m³.
  If inputs are insufficient the AQI is **not shown**; per-pollutant sub-indices still are.
* **Map**: actual stations only, coloured by the latest concentration. No interpolation, no heatmap, no forecast.
* **History** uses OpenAQ's hourly aggregates stamped by hour-ending UTC time. Missing hours stay gaps.

## Known limitations

* Coverage depends on what each provider shares with OpenAQ; near-real-time data may be unvalidated and revised later.
* The free rate limit makes the first full load slow; a persistent cache (the database) would remove this if needed.
* The meaning of a *latest* value's timestamp (instant vs hour-ending) is whatever the source assigned; history
  timestamps are explicit hour-ending periods.
* Weather context beside air quality is weather-model output (Open-Meteo), not measured at the stations.

## Simple weather indicators (not a classifier)

* **Ventilation index** = boundary-layer height × 10 m wind speed (m²/s). Surface wind only approximates the wind
  through the mixed layer.
* **Hours since rain** = hours since the last hour ≥ 0.1 mm, counted within the window.

Both are plain arithmetic, carry no thresholds or risk labels, and neither identifies a temperature inversion.
Inversions are only discussed where vertical temperature data exist (model pressure levels, labelled as such).
