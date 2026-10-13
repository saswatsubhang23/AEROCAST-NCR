"""Guardrails that do not depend on the language model behaving.

1. Future-pollution requests are answered by fixed text: no ML forecasting service is connected.
2. Numbers in an answer that look like measurements are checked against the data the tools actually returned.
3. Text a small model emits instead of a structured tool call is recognised, so it can still be validated and run.
"""

import json
import re
from typing import Any

_POLLUTION = re.compile(r"pollut|\baqi\b|air[\s-]?quality|pm\s?2\.?5|pm\s?10|\bsmog\b|\bno2\b|\bso2\b|\bozone\b|\bo3\b|particulate", re.I)
_FUTURE = re.compile(
    r"forecast|predict|projection|outlook|tomorrow|tonight|next\s+(?:\d+\s+)?(?:hour|day|week|few|weekend)|upcoming|"
    r"coming\s+(?:hours?|days?|week)|later\s+(?:today|tonight)|this\s+weekend|in\s+(?:the\s+)?\d+\s*(?:hours?|days?)|"
    r"expected\s+to|going\s+to\s+(?:be|get|rise|increase|worsen)|will\s+(?:the\s+)?(?:air|pm|aqi|pollution|smog)", re.I)
_PAST = re.compile(r"\b(?:last|past|previous|yesterday|was|were|observed|coincid\w*|recent\w*|ago|during|so far|earlier|history|historical)\b", re.I)


def asks_for_pollution_forecast(text: str) -> bool:
    """True when the user wants a prediction of future pollution. Questions with a past-tense cue go to the model."""
    return bool(_POLLUTION.search(text) and _FUTURE.search(text) and not _PAST.search(text))


FORECAST_REFUSAL = (
    "I can't predict future air quality. No pollution-forecasting service is connected to AEROCAST NCR, and I won't "
    "estimate or guess future pollutant levels.\n\n"
    "What I can do instead:\n"
    "- show the latest and recent air-quality **observations** for a city,\n"
    "- give the **weather** forecast for the next 72 hours (weather only, not pollution),\n"
    "- build a report on what air quality and weather were over a past period."
)

# --------------------------------------------------------------------------------------------- document questions
_DOCUMENT = re.compile(
    r"\b(?:documents?|papers?|publications?|guidelines?|guidance|knowledge base|methodology|methods?|standards?|policy|policies|readme|"
    r"according to|cpcb|naqi|who(?:\s|'s)|says?|states?|explain(?:s|ed)?|how (?:is|are|do|does) .{0,40}(?:calculated|computed|defined|work)|"
    r"what (?:is|are) (?:the )?(?:aqi|pm\s?2\.?5|pm\s?10|sub-?index|ventilation index))\b", re.I)
_LIVE_DATA = re.compile(
    r"\b(?:current|currently|right now|now|today|tonight|latest|yesterday|last\s+\d+|past\s+\d+|this (?:morning|evening|week)|"
    r"forecast|compare|report for|weather in|air quality in|temperature in|in (?:delhi|gurugram|gurgaon|noida|ghaziabad|faridabad))\b", re.I)


def looks_like_document_question(text: str) -> bool:
    """A question that is plainly about documents or methods and not also about live data. Those are answered with a
    retrieval the server runs itself, so a small model cannot skip the knowledge base or search it badly. Mixed questions
    are left to the model, which can use several tools."""
    return bool(_DOCUMENT.search(text) and not _LIVE_DATA.search(text))


# --------------------------------------------------------------------------------------------- grounding
_UNIT = r"(?:°\s?[CF]?|%|µg/m³|μg/m³|ug/m3|mg/m³|km/h|m/s|mm|hPa|m²/s|m\b)"
_MEASURE = re.compile(rf"(?<![\w.\[])(-?\d+(?:\.\d+)?)\s?{_UNIT}")
_AQI = re.compile(r"\bAQI\b[^\d\n]{0,25}?(\d{1,3})")
_CITATION = re.compile(r"\[[A-Z]\d+\]")


def measurement_numbers(text: str) -> list[float]:
    """Numbers written as measurements (with a unit) or as an AQI value."""
    cleaned = _CITATION.sub("", text)
    out = [float(m.group(1)) for m in _MEASURE.finditer(cleaned)]
    out += [float(m.group(1)) for m in _AQI.finditer(cleaned)]
    return out


def collect_numbers(obj: Any, into: set[float] | None = None) -> set[float]:
    into = set() if into is None else into
    if isinstance(obj, bool):
        return into
    if isinstance(obj, (int, float)):
        into.add(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            collect_numbers(v, into)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            collect_numbers(v, into)
    elif isinstance(obj, str):
        into.update(float(x) for x in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?(?![\w.])", obj))
    return into


def numbers_close(a: float, b: float) -> bool:
    if abs(a - b) <= 0.06:
        return True
    if float(a).is_integer() and abs(a - b) <= 0.5 + 1e-9:  # the answer rounded a retrieved value
        return True
    return b != 0 and abs(a - b) / abs(b) <= 0.005


_close = numbers_close


def ungrounded_numbers(answer: str, allowed: set[float]) -> list[float]:
    """Measurement-like numbers in `answer` that match no retrieved value, nor a sum or difference of two of them
    (so a model-computed delta between two retrieved numbers is accepted)."""
    pool = sorted(allowed)
    pairs: set[float] = set()
    if len(pool) <= 400:
        for i, x in enumerate(pool):
            for y in pool[i:]:
                pairs.add(round(abs(x - y), 3))
                pairs.add(round(x + y, 3))
    bad: list[float] = []
    for n in measurement_numbers(answer):
        if any(_close(abs(n), a) for a in pool) or any(_close(abs(n), p) for p in pairs):
            continue
        if n not in bad:
            bad.append(n)
    return bad


# --------------------------------------------------------------------------------------------- text tool calls
_TAGGED = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.S)


def parse_text_tool_call(text: str, allowed: set[str]) -> list[dict] | None:
    """Some models print a tool call as text instead of using the structured field. Recognise only calls to approved
    tools; anything else is ordinary text."""
    candidates = [m.group(1) for m in _TAGGED.finditer(text)] or ([text.strip()] if text.strip().startswith("{") else [])
    calls: list[dict] = []
    for c in candidates:
        try:
            obj = json.loads(c)
        except ValueError:
            return None
        name = obj.get("name") or (obj.get("function") or {}).get("name")
        args = obj.get("arguments", obj.get("parameters", (obj.get("function") or {}).get("arguments", {})))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return None
        if name not in allowed:
            return None
        calls.append({"function": {"name": name, "arguments": args}})
    return calls or None


class ToolLeakFilter:
    """Drops lines that are a printed tool call (`{"name": ...}` or `<tool_call>`) from a stream where tools are not
    available, so they never reach the user. Ordinary lines pass straight through; only a line that starts with `{` or `<`
    is held until it ends, to see whether it is a leaked call."""

    def __init__(self, allowed: set[str]) -> None:
        self._allowed = allowed
        self._pending = ""
        self._at_start = True

    def feed(self, chunk: str) -> str:
        out = ""
        for ch in chunk:
            if self._pending:
                self._pending += ch
                if ch == "\n":
                    out += self._resolve()
                continue
            if self._at_start and ch in "{<":
                self._pending, self._at_start = ch, False
                continue
            out += ch
            self._at_start = ch == "\n" or (self._at_start and ch in " \t")
        return out

    def flush(self) -> str:
        return self._resolve() if self._pending else ""

    def _resolve(self) -> str:
        line, self._pending, self._at_start = self._pending, "", True
        return "" if parse_text_tool_call(line.strip(), self._allowed) else line


class ThinkFilter:
    """Removes <think>...</think> blocks from a token stream, even when a tag is split across chunks."""

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, chunk: str) -> str:
        self._buf += chunk
        out = ""
        while True:
            if self._inside:
                end = self._buf.find("</think>")
                if end == -1:
                    self._buf = self._buf[-8:]  # keep a possible partial closing tag
                    return out
                self._buf = self._buf[end + len("</think>"):].lstrip("\n")
                self._inside = False
            else:
                start = self._buf.find("<think>")
                if start == -1:
                    keep = _partial_tail(self._buf)
                    out += self._buf[: len(self._buf) - keep]
                    self._buf = self._buf[len(self._buf) - keep:]
                    return out
                out += self._buf[:start]
                self._buf = self._buf[start + len("<think>"):]
                self._inside = True

    def flush(self) -> str:
        out, self._buf = ("" if self._inside else self._buf), ""
        return out


def _partial_tail(s: str) -> int:
    for n in range(min(len("<think>") - 1, len(s)), 0, -1):
        if "<think>".startswith(s[-n:]):
            return n
    return 0
