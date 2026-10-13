# Early warning

Page: **Early Warning** (`/early-warning`). API: `GET /api/twin/early-warning`. Code: `api/app/twin/early_warning.py`, `api/app/api/twin.py`,
`web/src/app/early-warning/page.tsx`.

For one forecast origin and one threshold it runs the saved local model for every station that has a usable observation at that hour and
ranks the stations: **likely** (the lower end of the empirical prediction interval also reaches the threshold), **possible** (only the central
forecast does), or **below**. Thresholds are the documented NAAQS / WHO 24-hour values or the user's own number (labelled not official).

## Honesty rules
* An origin older than 6 h is marked a **replay** (the model applied to stored data, outcome already known), never a current warning.
* A station is forecast only if it reported at the origin, so each series is that station's own; failures are listed under "not forecast".
* Lead times where the served model did not beat persistence on its held-out period are listed as weak.
* Feature importance is shown with the note that it describes the model, not causes.
* The 24-hour standards are compared with single forecast values: an indicator, not an exceedance finding.

## Measured
40 stations at 2024-11-15 00:00 UTC took about 57 s (4 stations in parallel; each loads features from the 3.4 GB store). No caching yet.

## Verified
`tests/test_early_warning.py` (9): classification, ranking, stale flag, validation, no-observation 404, ranking with skipped stations (model
call stubbed). Real run in the browser at the origin above: 40 rows with sparklines, no console errors, no horizontal overflow at 800 px.
Not verified: a live (recent-origin) warning, because the stored data ends 2026-10-07 and the model's input limit is stricter.
