# Reports and alerts

## Reports

A report is assembled by code from the same services the rest of the app uses (`ReportService` in
`api/app/reports/builder.py`). The language model never writes a measurement.

**Contents:** location and period; Observations of the chosen pollutant (nearest station within 20 km that actually reported,
with min/max/mean, hours observed vs missing, largest 6-hour rise, trend); weather-model statistics; descriptive
atmospheric indicators; weather that coincided with the largest rise (explicitly *not* a cause); up to three passages from
the knowledge base as references (with publisher, licence and excerpt); the external forecast if a provider exists;
data freshness per source; a "what this report cannot say" list; and a numbered source list (provider, URL, retrieval time).

**Missing data is stated, never filled.** A source that fails becomes an *unavailable* section with its reason and an entry
in the limitations list; the rest of the report is still produced. Missing hours are gaps in charts and tables.

**Formats**

| Endpoint | Result |
|---|---|
| `POST /api/reports` `{location_id, hours (6-168), pollutant}` | Builds the report (synchronously), returns it as JSON, keeps it in memory for 2 h (25 most recent). |
| `GET /api/reports/{id}` | The stored report. `404 report_expired` after expiry or a restart. |
| `GET /api/reports/{id}/pdf` | PDF with the same content, chart gaps preserved, page numbers. |
| `GET /api/reports/{id}/markdown` | Markdown with the same content. |
| `POST /api/reports/{id}/summary` | Optional LLM summary (below). |

The web page is `/reports` (generate) or `/reports?id=…` (open). The assistant's `generate_incident_report` tool uses the
same builder, stores the report, and links to its page, so chat, page, PDF and Markdown always show the same numbers.

### The LLM summary

Requested separately (button / endpoint). The model receives only the report's own key-fact sentences. Code then checks
the output and **discards** (never edits) a summary that:

* contains a number that does not appear in the report's scalar values or key facts (chart series, timestamps and ids are excluded so the allowed set stays small);
* uses words claiming a cause, a forecast, an inversion, safety or advice (`caused`, `will`, `forecast`, `safe`, …);
* is empty or longer than 1,100 characters.

**What this does not guarantee.** It checks that numbers exist in the report, not that the model attached each to the right
quantity. In a live run with a 3B model, one accepted summary called the *latest* value (53.0) "the highest" (63.0) and
described a boundary layer height as lower than average when it was above. The summary is therefore labelled as such and
the key facts printed above it are authoritative. Treat the summary as a convenience.

### Measured timings (this machine, live services)

| Case | Time |
|---|---|
| First report after an API restart (Delhi; includes OpenAQ's station inventory, rate-limited to 50 req/min) | 143 s |
| A different city, inventory cached | 20 s |
| Same report again (caches warm) | 0.3 s |
| LLM summary, `llama3.2` (3B) on CPU | 24 - 44 s |

The cold figure is dominated by OpenAQ's rate limit, not by report logic. The request is synchronous as specified and runs
inside the API's event loop without blocking other requests. If cold starts of this length are unacceptable, the
mitigation within the current architecture is to warm the station cache at start-up (not implemented) rather than add a
worker. The summary with Qwen3-8B has not been timed (not installed here).

## Alerts

Rules compare the **latest observed** value at the nearest station with a threshold *you* define.

* A rule has a location, pollutant, operator (`>` or `≥`), threshold, unit (µg/m³, mg/m³, ppb, ppm) and optional name. Up to 50 rules; stored in SQLite at `DATA_DIR/alerts.sqlite`.
* Each status carries location, measurement, threshold, the observation (value, unit, station, distance, timestamp), source (OpenAQ), state and message, and states: *triggered, not triggered, no data, stale, unit differs, source unavailable, off*.
* Data older than the stale limit (3 h) never triggers; it is reported as stale. Values are **not** unit-converted: a station reporting in another unit than the rule is reported as "unit differs".
* Every alert shows: "A user-defined threshold. It is not an official health standard." There are no predictive alerts and no built-in thresholds.

Endpoints: `GET /api/alerts`, `POST /api/alerts/rules`, `PATCH /api/alerts/rules/{id}` (`{enabled}`), `DELETE /api/alerts/rules/{id}`.
UI: Air Quality page (manage) and Overview (status list). Alerts are evaluated when the page loads or is changed; nothing
runs in the background and nothing is sent anywhere.
