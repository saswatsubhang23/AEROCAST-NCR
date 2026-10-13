# Release-readiness review (2026-10-10)

Everything below was run on the developer machine (Windows, CPU only, Python 3.14, Node 24.17.0). "Verified" means it was
executed and the result observed; anything else is listed under limitations.

## Results

| Check | Result |
|---|---|
| Backend tests (`pytest`) | 410 passed. External services are mocked (httpx `MockTransport`, fake embedder). |
| Frontend: `tsc --noEmit`, `eslint src`, `vitest run` | clean; 52 tests passed |
| `next build` (run in a copy so the running dev server was untouched) | compiled, 11 static pages, no errors |
| Live Open-Meteo | weather, grid, recent history, reports (real data) |
| Live OpenAQ (key present) | stations, history, AQI endpoint, alerts (a real rule `PM2.5 >= 40` triggered on a real 53 µg/m³ reading), reports |
| Live Ollama | embeddings (`nomic-embed-text`), chat and report summary with the `llama3.2` stand-in |
| Reports | JSON, PDF (text extracted with pypdf and compared), Markdown, expiry (`report_expired` shown in the UI), assistant-generated report linked to and exportable from the same id |
| ML interface | with no provider: "unavailable" in API, Air Quality page, Overview, reports. With a throwaway HTTP fixture speaking the contract: status, request, validation and health over real HTTP. |
| Accessibility | axe-core on all 8 routes: 0 violations after fixes (below). Keyboard focus rings and labelled controls are in place; no manual screen-reader pass. |
| Responsive | all 8 routes at 375 px: no horizontal overflow after the tooltip fix |
| Security probes (live) | no API key in any response; CORS rejects other origins (preflight 400, no allow-origin header); uploads: `.exe` 415, damaged PDF 422, 11 MB 413, bad category 422; stored upload names are `<id>.<ext>`, never user-supplied |
| Dependency audit | `npm audit --omit=dev`: 0. `pip-audit`: see limitations (chromadb) |

## Defects found in this pass and fixed

1. Report summary guard accepted invented numbers: the allowed set contained every chart point, timestamp and all pairwise sums, so 777 and 999 passed. Now scalar values only, no sums. Test added.
2. Summary label overstated the guard; it now says numbers are checked to exist, not that they are attached to the right quantity (observed in a live run).
3. `X-Request-ID` supplied by a caller was echoed and logged unchecked; now accepted only if `[A-Za-z0-9._-]{1,64}`. Test added.
4. Same value rendered differently in the web page and the server text (49.25 shown as 49.3 vs 49.2): web now rounds exact ties to even like the server.
5. Hidden tooltips widened the Weather page to 423 px on a phone (`opacity-0` still counts for overflow); now `display:none`.
6. axe: selected segmented-control button contrast 3.7:1 (now dark text on the accent colour); inline links distinguished by colour only (now underlined); timeline buttons' accessible names did not contain their visible text.
7. A freshly generated report was not in the address bar, so reload lost it; the URL now carries `?id=`.

## Known limitations

* **Cold report / air-quality loads are slow.** The first request after an API restart takes about 2-2.5 minutes (OpenAQ station inventory, 50 requests/min limit): a Delhi report took 143 s, a second city 20 s, a repeat 0.3 s; the first Air Quality page load was similar. The UI says so. Cache lasts 15 minutes. Not fixed: it is the provider's rate limit, and warming at start-up would be a new feature.
* **LLM summaries can mislabel true numbers** (see `docs/reports-and-alerts.md`). A 3B model said "highest" for the latest value. Only the deterministic key facts are authoritative.
* **Qwen3-8B (`qwen3:8b-q4_K_M`) is not installed here**, so tool selection, summaries and latency with the intended model are unmeasured. All LLM behaviour was exercised with `llama3.2`; it is erratic at tool choice, and guardrails (validated tools, retrieval-first, forecast refusal, citation and number checks) are what the tests cover.
* **PostgreSQL/PostGIS was unreachable**, so the Alembic baseline and the status probe against a live database are unverified. No feature stores data there.
* **Real CPCB data via OpenAQ is often stale or in mixed units**, so an AQI is frequently not computable; the app says so rather than estimating. Weather values are model output for a grid cell, not station measurements.
* **PDFs were checked by text extraction, not visually.** Non-Latin characters in provider names are transliterated.
* **Chart and map canvases were not inspected visually this pass**: the browser pane returned black screenshots on map-heavy pages, so verification was DOM, text, console and network based. Timeline buttons and slider were confirmed to move the shared index. Map layers and chart-marker sync were verified in the weather phase and by unit tests, not re-inspected here.
* **Dev-mode double requests**: in `next dev`, React Strict Mode runs effects twice, so each page's requests appear twice. Production builds do not.
* **Dependencies**: `pip-audit` reports five advisories for chromadb 1.5.9 with no fixed version. All concern Chroma's *server* mode (HTTP API, RBAC, `trust_remote_code`). AEROCAST uses only the embedded `PersistentClient`, starts no Chroma server and passes its own embeddings, so they do not apply; recheck when a fix ships. `npm audit` (dev tree only): `braces` ReDoS reached via `eslint-config-next`; build-time tooling, not shipped.
* **No authentication.** The API trusts its network (CORS limits browsers only). Run it on localhost or a trusted LAN; add auth before exposing it.
* **Alerts** are evaluated when a page loads; there is no background checking or notification.
* Reports are in memory (25 newest, 2 h) and are lost on restart.
* Open-Meteo's free tier is for non-commercial use.

## Remaining defects

None known that were reproducible and left unfixed, other than the limitations above.
