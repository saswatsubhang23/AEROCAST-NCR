# Items deliberately left for your decision or credentials

Everything else is implemented without asking. Each item needs something only you can provide or approve.

| Item | Why it waits | What I need |
|---|---|---|
| Pull `qwen3:8b-q4_K_M` into Ollama | multi-GB download. Installed today: `llama3.2` (3.2B, now set in `api/.env`), `qwen2.5-coder:7b`, `nomic-embed-text`. Tool selection with a 3B model is erratic; the guardrails cover it, quality is limited | your OK to download, or name another model |
| TypeSafe/Jev API key | none in `api/.env`; the real API has never been called; sending question text to an external service | `TYPESAFE_API_KEY` in `api/.env`, plus confirmation that the payload in `docs/jev-integration.md` is acceptable; then run `python -m app.jev` and a shadow period |
| Evidence documents for RAG and health intelligence | the knowledge base has 0 documents; downloading files needs your approval and a licence check | which authoritative documents (e.g. WHO air quality guidelines 2021, CPCB NAAQS notification, specific cohort studies) I may download, or upload them yourself on the Knowledge Base page |
| Skiper UI Pro components | paid (USD 129 / 549 per the site); only 37 free items are fetchable and two were suitable | a purchase decision; not needed for the current design |
| PostgreSQL/PostGIS | unreachable; everything uses SQLite | host, database and credentials if you want it used |
| Open-Meteo commercial use | the free tier is non-commercial | a subscription key if the app is used commercially |
| Individual or patient-level health features | requires a privacy and governance framework | explicit approval and a data-handling policy; not built |
| Exposing the API beyond localhost | no authentication exists | an auth decision |
| Live forecasting | the OpenAQ/CPCB feed was about two days behind, so a model that needs fresh inputs cannot answer "now" | a fresher source (for example direct CPCB access you are entitled to) or acceptance that forecasts are back-tests only |

## Your answers (2026-10-10)
| Item | Decision | Status |
|---|---|---|
| Qwen3 pull | yes | `ollama pull qwen3:8b-q4_K_M` started |
| TypeSafe/Jev | use `laya` instead (`pip install laya`) | package being installed and inspected; Jev stays optional/shadow-only until its API is understood |
| Evidence documents | you will provide later | open |
| Skiper UI | free components only | already the case; no Pro purchase |
| PostgreSQL/PostGIS | you will install later | SQLite stays |
| Open-Meteo | stay non-commercial | free tier stays |
| Patient-level features | data later | not built |
| Authentication | none now | localhost only |
| CPCB / India air quality | key supplied (`INDIA_AQI_API_KEY` in `api/.env`); endpoint `https://airquality.xkdr.org/v1/` | in use as a **history** source (CPCB CAAQM readings 2009 to 2025-09-01 for Delhi-NCR, not live); see `docs/real-data-pipeline.md`. Terms of use of the archive are not known to me; check them before redistributing any data. The key was pasted in chat: rotate it if that chat is shared |
