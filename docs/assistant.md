# AEROCAST AI (local assistant)

A chat assistant that answers questions about the weather and air-quality data AEROCAST NCR can actually retrieve.
It runs on a local [Ollama](https://ollama.com) model. There are no paid or cloud LLM dependencies.

## Setup

On the machine that runs Ollama:

```bash
ollama pull qwen3:8b-q4_K_M        # the initial model (about 5.2 GB, 40K context, supports tools)
```

In `api/.env` on the API server:

```
OLLAMA_BASE_URL=http://<ollama-host>:11434
OLLAMA_MODEL=qwen3:8b-q4_K_M
```

Ollama listens on localhost only by default; set `OLLAMA_HOST=0.0.0.0` on the Ollama machine to reach it remotely.
The **AI Assistant** page and `GET /api/assistant/status` say exactly what is missing (unreachable host, model not
installed, model without tool support).

### Choosing a smaller model

Any Ollama model that lists the **tools** capability works. If answers are too slow, set `OLLAMA_MODEL` to a smaller
one (for example `qwen3:4b`). Speed is dominated by prompt processing: each question sends about 1,000 tokens of
instructions and tool definitions plus the retrieved data. Measured on a CPU-only laptop with a 3B model that is about
30 prompt tokens per second, so a two-step answer took 45–90 s; a GPU host should answer in seconds. If your hardware is
slow, raise `LLM_TIMEOUT_S` (longest silent wait for the model, default 180).

Only the one chat model is used and it stays loaded for `LLM_KEEP_ALIVE` (default 10 minutes). Embedding models are
only needed by the future knowledge-base phase.

| Setting | Default | Meaning |
|---|---|---|
| `OLLAMA_MODEL` | `qwen3:8b-q4_K_M` | chat model |
| `LLM_TEMPERATURE` / `LLM_TOP_P` | 0.2 / 0.9 | low temperature keeps answers close to the data |
| `LLM_NUM_CTX` | 8192 | context window requested from Ollama |
| `LLM_MAX_TOKENS` | 800 | hard cap on generated tokens per model call |
| `LLM_THINK` | false | Qwen3 "thinking" mode; slower, usually unnecessary |
| `LLM_MAX_TOOL_ROUNDS` / `LLM_MAX_TOOL_CALLS` | 3 / 4 | bounds on tool use per answer |
| `LLM_MAX_HISTORY_MESSAGES` / `LLM_MAX_MESSAGE_CHARS` | 12 / 2000 | context management |
| `LLM_TOOL_RESULT_CHARS` | 4000 | cap on each tool result sent to the model |

## How an answer is produced

1. The browser posts the conversation and the selected location to `POST /api/assistant/chat`.
2. Future-pollution requests ("what will PM2.5 be tomorrow") are answered with fixed text, without the model. No
   forecasting service is connected, so this holds even if Ollama is down.
3. Otherwise the model may call the **approved tools** (below). Each call is validated against a strict schema first;
   a rejected call is reported back to the model (invalid arguments can be corrected, up to the round limit) and
   nothing runs. Unknown tools never run, and tools are only executed when they were offered in that round.
4. The final answer streams to the browser as server-sent events (`status`, `tool`, `token`, `sources`, `done`, `error`).
5. Numbers written as measurements in the answer are checked against the data the tools returned. Anything not found
   (allowing rounding and the difference/sum of two retrieved values) is flagged in the UI.

## Approved tools

| Tool | Returns |
|---|---|
| `get_weather_observations` | past weather-model values for a city: latest, min/max/mean, simple derived indicators |
| `get_weather_forecast` | weather forecast (never pollution), up to 72 h |
| `get_air_quality_observations` | observed concentrations at stations within 20 km; optional computed AQI |
| `compare_locations` | 2–5 cities side by side, with differences precomputed |
| `search_knowledge_base` | passages from indexed documents; **currently reports that none are indexed** |
| `generate_incident_report` | a factual report built by code and shown verbatim (no model-written numbers) |

Locations are limited to Delhi, Gurugram, Noida, Ghaziabad and Faridabad; hours, pollutant names and list lengths
are range-checked. Provider-supplied text (station names) is stripped of control characters and truncated before
it reaches the model, and the system prompt tells the model that tool results are data, not instructions.

## What the assistant will not do

* Predict future air quality (no ML forecasting service is connected).
* State a measurement that no tool returned, claim a temperature inversion, or name a pollution source. Reports list
  the weather that coincided with an observed rise and say that coincidence is not cause.
* Run anything other than the six tools above. It is not an agent: at most 3 model rounds and 4 tool calls per answer.

## Known limitations

* **Knowledge base:** the interface exists (`app/assistant/kb.py`) but no documents are ingested yet, so
  "explain a document" questions are answered with "unavailable". The RAG phase plugs in here.
* **Small models are weaker at tool use.** In testing, a 3B model sent `hours: 0` for "current weather"; validation
  rejected it. The tool description now says to use `hours=1` for "now", which fixed it. Qwen3-8B was **not** tested
  because it is not installed on the development machine.
* The number check catches figures that match no retrieved value; it cannot judge wording (for example an
  over-confident paraphrase), so the instructions and the cited sources remain the main safeguard.
* Conversation history is stored in the browser (localStorage), not on the server.
