# Feature 01: existing feature completion and integration (2026-10-10)

Scope: complete and verify the existing application; no model retraining, no new unvalidated predictions. A background training run
(`real_v2`) that was in progress was **stopped and its partial output deleted** to respect that; the serving model is still run `4702878405a8`.

## Method
Every page was loaded in the browser (desktop and 375 px), every frontend-consumed endpoint was called against the real backend, the
frontend's API paths were enumerated and matched to backend routes, and the main workflows were driven end to end through the API
(reports, PDF/Markdown, alerts, assistant). Results below are what was observed, not assumed.

## Defects found and fixed
| # | Defect | Effect | Fix | Test |
|---|---|---|---|---|
| 1 | `AssistantStatus.pollution_forecast` was `Literal["unavailable"]`; with a model configured it was `"available"` | `/api/assistant/status` returned HTTP 500; the Assistant page showed "Cannot reach the AEROCAST API" | schema allows `available`/`unavailable` | `test_assistant_status_does_not_crash_when_a_forecaster_is_configured` |
| 2 | `/api/system/status` took 9 to 60 s (database connect timeout, model checksum verification on every call) | Settings stuck on "Checking…", Assistant banner offline | 15 s result cache, `?refresh=true` for the Recheck button, model probe cached by the run pointer's mtime | `test_status_is_reused_within_the_ttl_and_refresh_bypasses_it` |
| 3 | Four near-duplicate frontend request helpers; only one had a timeout, only some carried the request id, 204 handling differed | A hung API left spinners forever; inconsistent error detail | one `lib/http.ts` (`request`, `ApiError`, 30 s default, 180 s for report generation and uploads); weather, alerts, KB, reports and the forecast panel use it | tsc, eslint, vitest |
| 4 | Scrollable tables on Settings were not keyboard-focusable (axe `scrollable-region-focusable`) | keyboard users could not scroll the model table | `tabIndex=0`, `role=region`, label | axe re-run: 0 violations |
| 5 | The new modelled-pollution panel waited for the (slow) OpenAQ station list | no content for up to a minute | panel is independent of stations | seen in the browser |
| 6 | The exact-endpoint OpenAPI test did not list `/api/air/model-forecast` | suite failure | added | `test_openapi_lists_exactly_the_implemented_endpoints` |

## Verified working (observed)
* Reports: create, PDF (8.8 kB) and Markdown (4.6 kB) downloads.
* Alerts: create, evaluate (status "triggered" from observed values), disable, delete.
* Assistant: tool call `get_pollution_forecast` returned an honest refusal ("newest observation 14 h old, limit 6 h"); unknown citations are flagged in the done event and in the UI.
* No console errors on any page; no "NaN/undefined/null" text on any page; no horizontal overflow at 375 px on all 9 pages; axe 0 violations on all 9 pages after fix 4.
* No placeholder or hard-coded production data in `web/src` (searched for mock, dummy, fake, lorem, TODO).

## Known gaps (not defects of existing features)
* `/api/health-intel/exposure`, `/api/jev/shadow` and `/api/forecast/contract` have no UI consumer.
* The assistant answers in about 3.5 minutes on this CPU with Qwen3 8B (the forecast question above took 216 s); the interface streams, but the wait is long.
* PostgreSQL/PostGIS are not installed; the status table shows them as unreachable (SQLite is used).
* Knowledge base is empty until evidence documents are provided.

## Tests (actual)
Backend: 644 passed (2 min 55 s). Frontend: vitest 56 passed; tsc and eslint report nothing.
