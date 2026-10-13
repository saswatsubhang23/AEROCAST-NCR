"""Runs one assistant turn: bounded tool loop around a streaming Ollama chat.

Not an agent: at most `llm_max_tool_rounds` model calls may request tools, at most `llm_max_tool_calls` tools run in
total, only the approved tools exist, and every call is validated before it runs.

Events yielded (all dicts, sent to the browser as server-sent events):
  status | tool | token | sources | done | error
"""

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator, Callable
from datetime import datetime

from app.assistant.guards import (
    FORECAST_REFUSAL,
    ThinkFilter,
    ToolLeakFilter,
    asks_for_pollution_forecast,
    collect_numbers,
    looks_like_document_question,
    measurement_numbers,
    parse_text_tool_call,
    ungrounded_numbers,
)
from app.assistant.prompts import system_prompt
from app.assistant.tools import FORECAST_TOOL_DEF, PLACES, TOOL_DEFS, ARG_MODELS, ToolExecutor, ToolOutcome
from app.core.config import Settings
from app.core.time import utc_now
from app.integrations.ollama import LlmError
from app.schemas.assistant import ChatRequest
from app.services.llm import LlmService

logger = logging.getLogger("app.assistant")

TOOL_LABELS = {
    "get_weather_observations": "Retrieving recent weather",
    "get_weather_forecast": "Retrieving the weather forecast",
    "get_air_quality_observations": "Retrieving air-quality observations",
    "compare_locations": "Comparing locations",
    "search_knowledge_base": "Searching the knowledge base",
    "query_dataset": "Computing over an uploaded table",
    "generate_incident_report": "Building the report",
    "get_pollution_forecast": "Requesting the pollution forecast",
}


def fit_result(data: dict, limit: int) -> str:
    """Serialise a tool result within the character budget, dropping bulky parts before ever cutting JSON."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    while len(text) > limit and len(data.get("passages", [])) > 1:  # fewer passages beat cut-off JSON
        data = {**data, "passages": data["passages"][:-1], "note_truncated": "lower-ranked passages omitted to fit the context budget"}
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    for bulky in ("timeline_every_3h", "variables"):
        if len(text) <= limit:
            break
        data = {k: v for k, v in data.items() if k != bulky}
        data["note_truncated"] = f"'{bulky}' omitted to fit the context budget"
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text if len(text) <= limit else text[: limit - 40] + '..."[truncated]"'


def _failure_note(outcome: ToolOutcome) -> str:
    if outcome.arg_error:  # the model can fix this itself
        return "The arguments were invalid. Call the tool again with corrected arguments, using the allowed values."
    return "No data was retrieved. Do not guess values."


def trim_history(history: list[dict], max_messages: int, budget_chars: int) -> list[dict]:
    """Keeps the most recent turns that fit. Always keeps the newest user message and starts on a user turn."""
    msgs = history[-max_messages:]
    while len(msgs) > 1 and (msgs[0]["role"] != "user" or sum(len(m["content"]) for m in msgs) > budget_chars):
        msgs = msgs[1:]
    return msgs


class AssistantOrchestrator:
    def __init__(self, settings: Settings, llm: LlmService, executor_factory: Callable[[], ToolExecutor],
                 now: Callable[[], datetime] = utc_now, shadow=None,
                 forecast_available: Callable[[], bool] = lambda: False):
        self._s, self._llm, self._factory, self._now = settings, llm, executor_factory, now
        self._forecast_available = forecast_available  # True when a forecasting model or service is configured
        self._shadow = shadow  # optional Jev shadow observer: records its routing decision, never changes the answer

    # ------------------------------------------------------------------------------------------------
    async def run(self, req: ChatRequest) -> AsyncIterator[dict]:
        started = time.perf_counter()
        last_user = next(m.content for m in reversed(req.messages) if m.role == "user")
        if self._shadow is not None and self._shadow.active:
            self._shadow_task = asyncio.create_task(self._shadow.observe(last_user))  # fire and forget; errors are swallowed inside

        if asks_for_pollution_forecast(last_user) and not self._forecast_available():
            # No forecasting model is configured, so this is answered without the language model: this must hold even when Ollama is down or misbehaving.
            yield {"type": "token", "text": FORECAST_REFUSAL}
            yield self._done(started, tools=[], ungrounded=[], no_data=False, usage={}, note="pollution_forecast_unavailable")
            return

        try:
            status = await self._llm.status(fresh=True)
            if not status.available:
                yield {"type": "error", "code": status.code or "llm_unavailable", "message": status.message or "The language model is not available."}
                return
            async for event in self._conversation(req, started):
                yield event
        except LlmError as exc:
            yield {"type": "error", "code": exc.code, "message": exc.message}
        except Exception:
            logger.exception("Assistant turn failed")
            yield {"type": "error", "code": "assistant_error", "message": "The assistant hit an unexpected problem. Please try again."}

    # ------------------------------------------------------------------------------------------------
    async def _conversation(self, req: ChatRequest, started: float) -> AsyncIterator[dict]:
        s = self._s
        executor = self._factory()
        place = PLACES[req.location_id][0] if req.location_id else None
        system = system_prompt(self._now(), place)
        reserve = len(system) + 3500 + s.llm_max_tokens * 3 + s.llm_max_tool_calls * s.llm_tool_result_chars
        budget = max(2000, s.llm_num_ctx * 3 - reserve)
        history = trim_history([{"role": m.role, "content": m.content[: s.llm_max_message_chars]} for m in req.messages],
                               s.llm_max_history_messages, budget)
        user_numbers = collect_numbers([m["content"] for m in history if m["role"] == "user"])
        messages: list[dict] = [{"role": "system", "content": system}, *history]

        outcomes: list[ToolOutcome] = []
        document_text_in_context = False  # once untrusted document text is in context, no more tools this turn
        calls_made = 0
        final_text = ""
        usage: dict = {}
        allowed_tools = set(ARG_MODELS)

        last_user = next(m["content"] for m in reversed(history) if m["role"] == "user")
        if looks_like_document_question(last_user) and getattr(executor.kb, "ready", False):
            # Retrieval first: search with the user's own words and hand the passages to the model.
            yield {"type": "status", "message": TOOL_LABELS["search_knowledge_base"] + "…"}
            args = {"query": last_user[:300], "top_k": 4}
            outcome = await executor.run("search_knowledge_base", args)
            outcomes.append(outcome)
            calls_made += 1
            yield {"type": "tool", "name": outcome.name, "ok": outcome.ok, "args": outcome.args, "error": outcome.error,
                   "source_ids": [x.id for x in outcome.sources]}
            body = outcome.data if outcome.ok else {"error": outcome.error, "note": _failure_note(outcome)}
            document_text_in_context = bool(outcome.ok and outcome.data.get("passages"))
            messages.append({"role": "assistant", "content": "", "tool_calls": [{"function": {"name": outcome.name, "arguments": args}}]})
            messages.append({"role": "tool", "tool_name": outcome.name, "content": fit_result(body, s.llm_tool_result_chars)})

        for round_no in range(s.llm_max_tool_rounds + 1):
            can_use_tools = round_no < s.llm_max_tool_rounds and calls_made < s.llm_max_tool_calls and not document_text_in_context
            payload = self._payload(messages, with_tools=can_use_tools)
            text, tool_calls, usage = "", [], {}
            think = ThinkFilter()
            gate = ToolLeakFilter(allowed_tools)  # used only when no tools are offered
            holding = ""  # content that might turn out to be a text-form tool call; released only if it is not
            async for chunk in self._llm.client.chat_stream(payload):
                msg = chunk.get("message") or {}
                if msg.get("tool_calls"):
                    tool_calls.extend(msg["tool_calls"])
                delta = think.feed(msg.get("content") or "")
                if not can_use_tools:
                    delta = gate.feed(delta)  # a printed tool call is meaningless here: never show it
                if delta:
                    text += delta
                    if can_use_tools and not tool_calls and (holding or text.lstrip().startswith(("{", "<"))):
                        holding += delta
                    else:
                        yield {"type": "token", "text": delta}
                if chunk.get("done"):
                    usage = {"prompt_tokens": chunk.get("prompt_eval_count"), "completion_tokens": chunk.get("eval_count")}
            tail = think.flush()
            if not can_use_tools:
                tail = gate.feed(tail) + gate.flush()
            if tail:
                text += tail
                holding += tail if holding else ""
                if not holding:
                    yield {"type": "token", "text": tail}

            if not can_use_tools:
                # Tools were not offered this round, so a call the model emits anyway is ignored, never run.
                tool_calls = []
            if not tool_calls and can_use_tools and holding:
                tool_calls = parse_text_tool_call(text, allowed_tools) or []
                if not tool_calls:  # it was ordinary text after all
                    yield {"type": "token", "text": holding}

            if not tool_calls:
                final_text = text
                break

            # Record what the model asked for, then run each call (validated) within the overall budget.
            messages.append({"role": "assistant", "content": text if not holding else "", "tool_calls": [
                {"function": {"name": c["function"]["name"], "arguments": c["function"].get("arguments", {})}} for c in tool_calls]})
            for call in tool_calls:
                name = call["function"]["name"]
                if calls_made >= s.llm_max_tool_calls:
                    messages.append({"role": "tool", "tool_name": name, "content": json.dumps({"error": "Tool-call budget for this answer is used up. Answer with the data already retrieved."})})
                    continue
                calls_made += 1
                yield {"type": "status", "message": TOOL_LABELS.get(name, "Retrieving data") + "…"}
                outcome = await executor.run(name, call["function"].get("arguments", {}))
                outcomes.append(outcome)
                yield {"type": "tool", "name": name, "ok": outcome.ok, "args": outcome.args,
                       "error": outcome.error, "source_ids": [x.id for x in outcome.sources]}
                if outcome.ok and (outcome.data.get("passages") or outcome.data.get("untrusted_text")):
                    document_text_in_context = True
                body = outcome.data if outcome.ok else {"error": outcome.error, "note": _failure_note(outcome)}
                messages.append({"role": "tool", "tool_name": name, "content": fit_result(body, s.llm_tool_result_chars)})

            report = next((o for o in outcomes if o.ok and o.final_markdown), None)
            if report:  # shown verbatim: nothing a model writes can alter its numbers
                for line in report.final_markdown.splitlines(keepends=True):  # type: ignore[union-attr]
                    yield {"type": "token", "text": line}
                final_text = ""
                break
        else:
            final_text = ""

        if not final_text and not any(o.final_markdown for o in outcomes if o.ok):
            final_text = "I wasn't able to put together an answer from the data. Please try rephrasing the question."
            yield {"type": "token", "text": final_text}

        ok_outcomes = [o for o in outcomes if o.ok]
        allowed = collect_numbers([o.data for o in ok_outcomes]) | collect_numbers([o.args for o in ok_outcomes]) | user_numbers
        flagged = ungrounded_numbers(final_text, allowed) if final_text else []
        no_data = not ok_outcomes and bool(measurement_numbers(final_text))
        known_ids = {x.id for x in executor.sources}
        cited_any = bool(re.search(r"\[[A-Z]\d+\]", final_text))
        uncited = bool(executor.sources) and bool(final_text) and not cited_any
        unknown_citations = sorted({c for c in re.findall(r"\[([A-Z]\d+)\]", final_text) if c not in known_ids})

        if executor.sources:
            yield {"type": "sources", "sources": [x.model_dump(mode="json") for x in executor.sources]}
        yield self._done(started, tools=[{"name": o.name, "ok": o.ok} for o in outcomes], ungrounded=flagged, no_data=no_data,
                         usage=usage, unknown_citations=unknown_citations, uncited=uncited)

    # ------------------------------------------------------------------------------------------------
    def _payload(self, messages: list[dict], *, with_tools: bool) -> dict:
        s = self._s
        payload: dict = {
            "model": s.ollama_model, "messages": messages, "stream": True, "think": s.llm_think, "keep_alive": s.llm_keep_alive,
            "options": {"temperature": s.llm_temperature, "top_p": s.llm_top_p, "num_ctx": s.llm_num_ctx, "num_predict": s.llm_max_tokens},
        }
        if with_tools:
            payload["tools"] = [*TOOL_DEFS, FORECAST_TOOL_DEF] if self._forecast_available() else TOOL_DEFS
        return payload

    def _done(self, started: float, *, tools: list[dict], ungrounded: list[float], no_data: bool, usage: dict, note: str | None = None,
              unknown_citations: list[str] | None = None, uncited: bool = False) -> dict:
        return {
            "type": "done", "model": self._s.ollama_model, "tools": tools, "ungrounded_numbers": ungrounded,
            "unknown_citations": unknown_citations or [], "uncited": uncited,
            "answered_without_data": no_data, "usage": usage, "note": note,
            "duration_ms": round((time.perf_counter() - started) * 1000), "finished_at": self._now().isoformat().replace("+00:00", "Z"),
        }
