# Continue AEROCAST NCR (copy this into a new or resumed session)

Resume the AEROCAST NCR master implementation from the saved checkpoint. Do not start over and do not repeat finished work.

1. Read `docs/IMPLEMENTATION_STATE.md`, `docs/IMPLEMENTATION_LOG.md`, `docs/NEEDS_YOUR_DECISION.md` and `docs/DATA_PROVENANCE_AUDIT.md`.
2. Data and training are finished (run `4702878405a8`, see `docs/ML_TRAINING_AND_EVALUATION.md`). Restart the API after any `.env` change.
3. Verify: full backend suite, `npm run` vitest/tsc/eslint in `web`, axe + mobile-overflow on every page, delete `web/public/__axe.min.js`.
4. Continue: train SO2 and the other horizons; migrate Reports/Assistant/Knowledge to shared components; exposure/risk UI; performance and security review; write `docs/digital-twin-release-audit.md` updates.
5. Rules that never change: no fabricated data or scores; unavailable/stale states instead of fallbacks; training stays out of the web API; test fixtures never reach training or the UI; no secrets in code or logs; ask the user only for items in `NEEDS_YOUR_DECISION.md`.
6. Update the state, log and this file at every checkpoint.
