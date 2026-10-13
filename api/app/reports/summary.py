"""Optional LLM summary of a report.

The model sees only the report's own sentences and writes a short summary. Its output is checked in code before anyone
sees it: every number must trace to the report (rounding, or the sum/difference of two report numbers, is accepted), and
statements about causes, forecasts or inversions are refused. A summary that fails is discarded, never edited, and the
deterministic key facts remain.
"""

import logging
import re
import time

from app.assistant.guards import ThinkFilter, collect_numbers, numbers_close as _close
from app.core.config import Settings
from app.core.time import utc_now
from app.integrations.ollama import LlmError
from app.reports.models import LlmSummary, Report
from app.services.llm import LlmService

logger = logging.getLogger("app.reports")

SYSTEM = (
    "You write a short plain-English summary of an environmental data report for a general reader. Use ONLY the facts "
    "given. Never add, estimate, round differently or infer a number. Do not state causes or sources of pollution, give "
    "health advice, or say anything about the future or about temperature inversions. If the facts mention missing or "
    "stale data, say so. At most 110 words. No headings, lists or citations."
)
_NUM = re.compile(r"(?<![\w.])\d+(?:\.\d+)?(?![\w])")
_FORBIDDEN = re.compile(
    r"\b(?:caused?|causing|due to|because of|resulted? from|blame[ds]?|inversions?|will|forecasts?(?:ed)?|predict\w*|expected to|likely to|"
    r"should|safe|unsafe|dangerous|harmful)\b", re.I)
MAX_CHARS = 1100


def facts_for_model(r: Report) -> str:
    lines = [*r.facts_summary]
    lines += [x for x in r.limitations if any(k in x for k in ("no data", "out of date", "No ", "did not supply"))]
    lines += [f"{f.label}: data {f.status}." for f in r.freshness]
    return "\n".join(f"- {x}" for x in lines)


_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}T")
_SERIES_KEYS = {"times", "values", "series", "lower", "upper"}


def report_numbers(obj, into: set[float] | None = None) -> set[float]:
    """Numbers a summary may repeat: the report's scalar values. Chart series, timestamps and ids are left out, because
    a pool that large would make nearly any invented number 'close' to something."""
    into = set() if into is None else into
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k not in _SERIES_KEYS and k not in ("id", "lat", "lon", "grid_lat", "grid_lon"):
                report_numbers(v, into)
    elif isinstance(obj, list):
        for v in obj:
            report_numbers(v, into)
    elif isinstance(obj, str):
        if not _ISO.match(obj):
            collect_numbers(obj, into)
    else:
        collect_numbers(obj, into)
    return into


def check_summary(text: str, r: Report) -> str | None:
    """Return the reason a summary must be refused, or None if it passes."""
    if not text.strip():
        return "The model returned nothing."
    if len(text) > MAX_CHARS:
        return "The model's summary was too long."
    bad = _FORBIDDEN.search(text)
    if bad:
        return f"The model's summary used a claim the report cannot support ('{bad.group(0)}')."
    allowed = report_numbers(r.model_dump(mode="json")) | collect_numbers(facts_for_model(r))
    pool = sorted(allowed)  # no sums/differences: the facts already carry every derived value, and unrelated pairs would match almost anything
    stray = []
    for m in _NUM.finditer(text):
        n = float(m.group(0))
        if not any(_close(n, a) for a in pool):
            stray.append(m.group(0))
    if stray:
        return f"The model's summary contained numbers that are not in the report ({', '.join(dict.fromkeys(stray))})."
    return None


class ReportSummarizer:
    def __init__(self, llm: LlmService, settings: Settings, now=utc_now):
        self._llm, self._s, self._now = llm, settings, now

    async def summarize(self, r: Report) -> LlmSummary:
        started = time.perf_counter()
        status = await self._llm.status(fresh=True)
        if not status.available:
            return LlmSummary(status="unavailable", reason=status.message or "The language model is not available.", model=status.model)
        payload = {
            "model": self._s.ollama_model, "stream": True, "think": False, "keep_alive": self._s.llm_keep_alive,
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Facts about {r.location.name}, {r.period.hours} hours:\n{facts_for_model(r)}\n\nWrite the summary."}],
            "options": {"temperature": 0.1, "top_p": 0.9, "num_ctx": self._s.llm_num_ctx, "num_predict": 300},
        }
        think, text = ThinkFilter(), ""
        try:
            async for chunk in self._llm.client.chat_stream(payload):
                text += think.feed((chunk.get("message") or {}).get("content") or "")
            text += think.flush()
        except LlmError as exc:
            return LlmSummary(status="unavailable", reason=exc.message, model=self._s.ollama_model)
        ms = round((time.perf_counter() - started) * 1000)
        text = " ".join(text.split())
        problem = check_summary(text, r)
        if problem:
            logger.warning("Report summary refused: %s", problem)
            return LlmSummary(status="rejected", reason=problem + " It was discarded; the key facts above are unaffected.",
                              model=self._s.ollama_model, generated_at=self._now(), duration_ms=ms)
        return LlmSummary(status="ok", text=text, model=self._s.ollama_model, generated_at=self._now(), duration_ms=ms)
