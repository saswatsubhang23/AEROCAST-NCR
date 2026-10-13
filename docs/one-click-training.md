# One-click model training

Page: **Model Training** (`/training`). API: `/api/training/*`. Code: `api/app/training/jobs.py`, `api/app/api/training.py`,
`web/src/app/training/page.tsx`.

## What the button does
Starts a local job: a fixed sequence of the project's own command-line steps, each run as a separate process.

| Step | Command | When |
|---|---|---|
| Check | in-process: store exists, at least 3 GB free, `AQ_API_KEY` present when downloading | always |
| Find sensors | `python -m app.history discover` | "download the newest hours" ticked |
| Newest air quality | `python -m app.history ingest-air --from <latest hour minus 10 days> --to tomorrow` | ticked |
| Newest weather | `python -m app.history ingest-weather` (same window) | ticked |
| Clean | `python -m app.history clean` | ticked |
| Features | `python -m app.history features --pollutants ...` | ticked |
| Train | `python -m app.ml train --config <preset> --out data/models_candidates/<job>` | always |
| Report | `python -m app.ml report` into the job folder | always |

Presets: **standard** (`app/ml/configs/real_v2.json`: PM2.5, PM10, NO2, O3 at +1/+6/+24 h, random forest, XGBoost, LightGBM, SVR; hours) and
**quick** (`quick.json`: PM2.5, random forest and LightGBM; minutes). Pollutants can be narrowed (PM2.5, PM10, NO2, SO2, O3).

## Cost and compute
Everything runs on this computer with Python, scikit-learn, XGBoost and LightGBM. **No language model and no Claude tokens are used.** The
network is used only by the optional data refresh (OpenAQ and Open-Meteo, the same free providers as the rest of the application).

## Safety rules (tested in `tests/test_training_jobs.py`)
* Options are validated against allow-lists (preset name, pollutants, horizons); no caller-supplied command, path or flag is executed; arguments
  are built from constants and checked values (a pollutant such as `pm25; rm -rf /` is rejected with HTTP 422).
* One job at a time (HTTP 409 otherwise). Training runs in a child process, so training libraries never load into the web API and a crash
  cannot take it down. Cancel kills the whole process tree.
* A job writes only to its own candidate folder. **Finishing never changes the active model.** "Use this model" is a separate click: the
  candidate is loaded first (every artifact checksum and library version is verified), then copied and the registry pointer is switched
  atomically; the previous pointer is kept so "Return to the previous model" works. A tampered candidate is refused.
* Job state and the log are persisted under `data/training_jobs/<job>`; a job running when the API died is shown as *interrupted*.
* The page shows recorded held-out scores with a persistence baseline for every pollutant/horizon, and says when the test period differs from
  the active model's (so scores are not like-for-like).

## Limits you should know
* "Live data" means the newest hours the providers have published. OpenAQ lags by days for many stations and the Open-Meteo archive by about
  two days; the CPCB history archive ended in September 2025 and is not refreshed. The refresh therefore adds recent days, not a real-time feed.
* A standard run rebuilds a feature table of about 9 million rows and trains four model types per pollutant and horizon: expect hours and
  a busy processor. Other pages stay usable but slower.
* Training on more data does not guarantee better scores. The earlier model did not beat persistence for PM10 at +24 h; a new run may or may
  not, and the table says which.
* The API picks up an activated model on its next request (the model cache follows the registry file's modification time), no restart needed.

## Verified
Backend: 12 tests (`test_training_jobs.py`): options, commands, success path, failure stops and skips, one-at-a-time, cancel, interrupted
jobs, missing store, id validation, activation with a real fixture model, tamper refusal, HTTP validation. Frontend: type-check and lint clean.
A real quick job was started from the button in the browser and ran as the steps above.

## Stratified results (added)
Each trained cell now also records held-out error by season (IMD seasons, month taken in IST) and by observed concentration band (the CPCB
bands of the pollutant), each next to the persistence baseline. A stratum with fewer than 30 scored rows shows its size and no score. The
Training page shows them under "Performance by season and by concentration range"; the Markdown report has the same table. Range strata
use the observed value, so they partly reflect regression to the mean. Tests: `tests/test_ml.py` (season/IST boundary, band edges, hidden
small strata, results carry the block).
