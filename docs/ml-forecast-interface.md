# Pollution-forecast interface (contract only)

AEROCAST NCR contains **no forecasting model** and never produces, estimates or interpolates a pollution forecast. It
defines a typed contract so that a separately built service can supply forecasts later. With no service configured,
every forecast surface says *unavailable*.

## Configuration

| Setting | Meaning |
|---|---|
| `ML_FORECAST_URL` | Base URL of the provider. Empty (default) = no provider; forecasts are unavailable. |
| `ML_FORECAST_API_KEY` | Optional. Sent as the `X-API-Key` header. Never logged or returned by the API. |
| `ML_FORECAST_TIMEOUT_S` | Per-request timeout (default 30). |

## What the provider must implement

* `POST {ML_FORECAST_URL}/forecast`: body `ForecastRequest`, response `ForecastResponse` (JSON).
* `GET {ML_FORECAST_URL}/health` (optional): any 2xx means reachable. Used only for the status display.

The authoritative schemas are generated from the code and committed as
[`ml-forecast-contract.schema.json`](ml-forecast-contract.schema.json); the same document is served at
`GET /api/forecast/contract`. A test fails if the file and the code disagree.

### Request

```json
{
  "location": {"id": "delhi", "name": "Delhi", "lat": 28.6139, "lon": 77.209},
  "issued_at": "2026-10-09T06:00:00Z",
  "horizon_hours": 24,
  "pollutants": ["pm25"]
}
```

`horizon_hours` is 1 to 72. Pollutants are `pm25 pm10 no2 so2 co o3`. `issued_at` is a timezone-aware UTC time. The
request carries no observations: the provider is responsible for sourcing its own inputs and says which in `provenance`.

### Response

```json
{
  "model_version": "1.2.0",
  "issued_at": "2026-10-09T06:00:00Z",
  "location": {"id": "delhi", "name": "Delhi", "lat": 28.6139, "lon": 77.209},
  "horizon_hours": 24,
  "forecasts": [{
    "pollutant": "pm25", "unit": "µg/m³",
    "times": ["2026-10-09T07:00:00Z"],
    "values": [61.2],
    "intervals": [{"level": 0.8, "lower": [48.0], "upper": [75.5]}]
  }],
  "provenance": {
    "provider": "Example forecasting service", "model_name": "…", "generated_at": "2026-10-09T06:00:02Z",
    "input_data": ["OpenAQ PM2.5 hourly to 2026-10-09T05:00Z"], "training_data": null, "notes": null
  }
}
```

### Rules AEROCAST enforces before showing anything

A response that breaks any rule is rejected with `502 forecast_invalid_response`; nothing from it is shown.

* every time is timezone-aware and strictly increasing; `times`, `values` and each interval's `lower`/`upper` have equal lengths
* values are finite and non-negative; `0 <= lower <= value <= upper` at every step; interval `level` is strictly between 0 and 1
* the first forecast time is after `issued_at`, and the last is within `issued_at + horizon_hours`
* a pollutant appears at most once, and only pollutants that were requested are returned
* `horizon_hours` is not longer than requested, and the location is within 0.5° of the one requested
* `issued_at` and `provenance.generated_at` are not in the future (small clock skew tolerated)
* `model_version` and `provenance.provider` are present

AEROCAST never repairs, clips or fills a response.

## Endpoints in AEROCAST

| Endpoint | Behaviour |
|---|---|
| `GET /api/forecast/status` | `{configured, available, provider, message}`. `available` is `null` when nothing is configured. |
| `POST /api/forecast` | Validated provider output unchanged, plus a notice that it is not produced by AEROCAST. |
| `GET /api/forecast/contract` | JSON Schemas for request and response. |

Errors: `503 forecast_not_configured` (no provider), `503 forecast_unavailable` (provider down, timed out,
refused the key or returned a server error), `502 forecast_invalid_response`.

## Where forecasts appear

* **Air Quality page**: a panel that says *unavailable* with no provider; with one, a button that requests a 24 h PM2.5 table.
* **Reports**: a Forecast section, labelled as an external service's output with its model version, or an explicit absence.
* **Assistant**: forecast questions for pollution are refused in code, whether or not a provider exists.
* **Settings / Overview**: provider status; "not integrated" is normal and not an error.

## Verified

Unit tests use a mock transport. Separately, a throwaway HTTP server implementing this contract with constant placeholder
numbers was run against the real API to confirm status, request, validation and health over real HTTP; it has been removed
and is not part of the product.
