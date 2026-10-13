# AI orchestration: data, ML, RAG, Jev and Ollama

Boundaries (each is enforced in code and tested):

| Component | Responsibility | Never |
|---|---|---|
| Data services (`services/`, `integrations/`) | observations, weather, station metadata | invent or fill values |
| ML (`app/ml`, loaded by `ml/inference.py`) | numerical forecasts, intervals, held-out scores | run inside a request unless a validated model exists |
| RAG (`kb/`, `search_knowledge_base`) | passages from user-indexed documents, with citations | produce numbers about the atmosphere |
| Jev (`app/jev`, optional, shadow only) | records a routing decision beside the deterministic router | change an answer, forecast or number |
| Ollama (`services/llm.py`, `assistant/`) | explain validated tool results in text | supply measurements, forecasts or citations |
| Frontend | show outputs with provenance and limits | substitute data when a source fails |

## Request flow (`assistant/orchestrator.py`)

1. Validate the request (size, roles). Optionally start the Jev **shadow** observation (fire and forget).
2. If the question asks for future pollution and **no forecasting model is configured**, answer with the fixed refusal, without calling the language model. If a model is configured, the question goes on.
3. The language model may call only validated tools (strict argument models, call budget): weather observations/forecast, air-quality observations, comparison, knowledge-base search, incident report, and, only when a forecaster is configured, `get_pollution_forecast`.
4. `get_pollution_forecast` calls the same `ForecastService` as `/api/forecast` (external service or the local trained model). Its failure text is returned to the model with an instruction not to estimate; it never returns a number it did not get from the provider. Real use is currently limited by data freshness (see `docs/ml-training-pipeline.md` §7): with the feed about two days behind, the tool will normally report "no forecast".
5. After retrieving untrusted document text, no further tools are allowed (prompt-injection guard); document questions are retrieval-first.
6. The answer is streamed through filters (thinking blocks, leaked tool JSON), then checked: numbers must appear in the tool results (or be a sum/difference of two), citations must refer to real sources, measurements without any retrieved data are flagged. The `done` event carries `ungrounded_numbers`, `unknown_citations`, `uncited`, `answered_without_data`.
7. Reports use the same builder as the Reports page; their optional LLM summary is accepted only if every number is in the report (`reports/summary.py`).

## What is verified, and on what

* Ollama on this machine has `nomic-embed-text`, `llama3.2` (3.2B) and `qwen2.5-coder:7b`; **`qwen3:8b-q4_K_M` (the configured default) is not installed**. Set `OLLAMA_MODEL` to an installed model (the local `.env` points to `llama3.2`) or pull Qwen3 (listed in `docs/NEEDS_YOUR_DECISION.md`). A 3B model is erratic at choosing tools; the guards above are what make its output safe, not its judgement.
* The forecast tool, refusal gating, grounding of forecast numbers, tool-failure handling and argument validation: `tests/test_assistant_forecast.py` (5 tests, mock Ollama and a mock forecasting service).
* Jev: documented schema and mock-server tests only; the real service has not been called.
* The health-exposure endpoint is a data endpoint, not an assistant tool, so the assistant cannot make individual health statements from it. See `docs/environmental-health-intelligence.md`.

## Not done

Wiring the exposure summary and the twin's risk windows into assistant tools (they are API endpoints today); Jev evidence-sufficiency and report-completeness questions; Jev "active" mode. All are deliberate follow-ups, the last two pending shadow-mode results.
