# Environmental exposure intelligence (population level, research support)

Endpoint: `GET /api/health-intel/exposure?pollutant=&from=&to=&station_id=|zone=` (`api/app/api/health_intel.py`,
`api/app/health_intel/service.py`, tests `tests/test_health_intel.py`, 12 tests).

## What it returns

All figures come from the historical store (OpenAQ hourly aggregates, standardised to µg/m³, usable hours only):

* observed hourly mean, median and **peak** (value, time, station), and coverage of the expected station-hours;
* **daily means**: IST calendar days with at least 18 of 24 hourly values per station (excluded station-days are counted, never averaged in); for a zone, the median across stations that day;
* **days at or above documented 24-hour references** (India NAAQS, WHO 2021): valid days, days at or above, share, first and last day, with the threshold's value, kind, averaging period and source;
* scope (stations used, coordinates), spatial coverage statement ("nothing is estimated between stations"), uncertainty statement, limitations;
* **evidence**: passages from the user's indexed knowledge-base documents about health effects and guideline values, each with citation id, document, publisher, licence, location, relevance and a 500-character excerpt; with no indexed documents the section says `none` and why.

## What it refuses to be

No individual exposure, risk, probability of disease, diagnosis, treatment or causal statement about a person. Every response
carries the disclaimer and limitations ("concentrations at monitoring stations are not a person's exposure; reference values are
population-level standards; nothing here is a diagnosis"). A test scans responses for individual-risk phrasing. No patient data
exist in the application, none is accepted, and none is sent to any external service (Jev receives only assistant question text,
see `docs/jev-integration.md`).

## Evidence status (honest)

The knowledge base currently holds **0 documents**, so the evidence section returns `none`. Adding authoritative sources (for
example the WHO global air quality guidelines, CPCB/NAAQS notifications, peer-reviewed cohort studies) means obtaining files and
agreeing their licences; that is a decision for you (see `docs/NEEDS_YOUR_DECISION.md`). The pipeline for ingestion, retrieval and
citation exists and is tested.

## Not built

A UI page for exposure summaries and an assistant tool wrapping this endpoint; both are small follow-ups once evidence documents
exist. Individual- or patient-level analysis is deliberately not built (needs a privacy and governance framework).
