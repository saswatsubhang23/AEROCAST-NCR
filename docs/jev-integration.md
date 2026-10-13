# Jev (TypeSafe) decision-support integration

Optional, **off by default**, and **shadow-only**: it can record a routing decision beside the deterministic one, and it
cannot change any answer, forecast or number. Code: `api/app/jev/`, API: `api/app/api/jev.py`, tests: `api/tests/test_jev.py`
(32 tests, all with a mock transport).

## Verified against the service's own documentation

Read on 2026-10-10 from `https://api.typesafe.ai/openapi.json` (OpenAPI 0.2.0, title "TypeSafe"); the Swagger page is at
`/docs`. Without a key the API answers `403 authentication_error` ("Must supply an API key") on `GET /v1/models`, and `405` on `GET
/v1/systemone` (it is POST-only), which matches the document.

| Item | Documented behaviour |
|---|---|
| Auth | `Authorization: Bearer <API_KEY>` |
| `GET /v1/models` | `{models: [{name, description, release_date}]}`; "pass a returned model name as `model`" |
| `POST /v1/systemone` | body `{state, model, questions: {name: question}}`; question types `noul` (yes/no probability), `choice` (one of `criteria`, with `confidence` and `probabilities`), `score` (ordered rubric) |
| Response | `{model, answers: {name: answer of the same type}, usage: {input_tokens, output_tokens}}` |
| Errors | `422 Validation Error` for bad requests |

Not found in the document: rate-limit numbers, usage terms, calibration of the probabilities. They are therefore **not assumed**:
rate limits are handled generically (HTTP 429, bounded retry), and probabilities are never treated as calibrated.
**The real service has not been called from this project (no API key is configured), so everything below is verified against
the documented schema and a mock server only.**

## What it does and does not do

Allowed use (implemented): classify an assistant question into one of seven fixed categories (observation, forecast request,
weather-pollution relationship, document question, report request, health-exposure question, other) with a `choice` question.
Not allowed and not implemented: numerical forecasts, measurements, replacing ML inference or deterministic validation,
diagnosing anyone. Evidence-sufficiency and report-completeness questions are *designed for* (the client supports `noul` and
`score` questions) but are **not wired in**; adding them is a decision to take after the shadow evaluation.

## Safety design

* **Kill switch and flag.** `JEV_MODE=off` (default) makes the client refuse to open any connection (tested: zero calls). `shadow` needs `TYPESAFE_API_KEY`; without it nothing is sent.
* **Secrets.** Key from the environment only, sent only in the Authorization header, never logged (tested against log capture and error text), never returned by `/api/jev/status`.
* **Validation, never repair.** The response must match the documented shape, contain an answer of the asked type for each question, and a `choice` must be one of the offered options; probabilities and confidence must be in [0, 1]. Anything else is an error that falls back to the deterministic router.
* **Bounded.** Timeout 8 s, at most 2 attempts, 429 honoured with a capped wait, 401/403 and 4xx never retried. Shadow observation is fire-and-forget with an overall timeout and swallows every exception (tested: the assistant's events are identical with and without it).
* **Minimal data.** Only the user's question text is sent, as the `state` of one choice question whose options are the fixed category descriptions. No measurements, retrieved passages, document text, identities or conversation history. `JEV_SEND_EXCERPTS` is reserved for a future evidence question and defaults to false. **No patient or personal data is ever sent**; do not type any into the assistant while shadow mode is on, because the question text is sent.
* **Local records.** `DATA_DIR/jev_shadow.sqlite` stores the question (truncated to 200 characters), both decisions, Jev's confidence, latency and error kind.

## Measuring it before trusting it

* Shadow statistics: `GET /api/jev/shadow` (agreement with the deterministic router, confusion matrix, failure rate and kinds, latency). Agreement is not accuracy.
* Labelled evaluation: `python -m app.jev` scores the deterministic router and (with a key) Jev on 42 hand-labelled questions (`app/jev/evaluate.py`); reports accuracy and per-category precision/recall, fallback rate, latency, and mean confidence when right versus wrong (a calibration check, no calibration assumed).
* Recorded result for the deterministic router on those examples: **40 of 42 correct (95.2%)** at the first run; the two misses were a regex that matched "who" in "who are you" (fixed: the WHO keyword is now case-sensitive) and a rain-washout question classed as an observation question. The labels and the rules were written by the same person, so this number is optimistic. **Jev has not been scored: no key.**

## Configuration

`JEV_MODE` (`off`|`shadow`), `TYPESAFE_API_KEY`, `JEV_BASE_URL` (default `https://api.typesafe.ai`), `JEV_MODEL` (empty: first name from `GET /v1/models`), `JEV_TIMEOUT_S`, `JEV_MAX_ATTEMPTS`, `JEV_SEND_EXCERPTS`.

## What is left (needs you)

An API key; your confirmation that sending the question text to an external service is acceptable; then run `python -m app.jev`
and a period of shadow mode before any "active" use is considered. Active mode is intentionally not implemented.
