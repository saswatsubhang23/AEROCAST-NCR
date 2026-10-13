"""LLM service: connection management and model availability for the one configured chat model."""

import time
from dataclasses import dataclass

from app.core.config import Settings
from app.integrations.ollama import LlmError, LlmModelMissing, LlmNoTools, OllamaClient


@dataclass
class LlmStatus:
    available: bool
    model: str
    code: str | None  # why it is not available
    message: str | None
    tools_supported: bool
    thinking_supported: bool
    context_length: int | None


def _installed(model: str, names: list[str]) -> bool:
    # "name" matches "name:latest"; "name:tag" must match exactly.
    return any(n == model or (":" not in model and n == f"{model}:latest") for n in names)


class LlmService:
    def __init__(self, settings: Settings, client: OllamaClient | None = None, clock=time.monotonic):
        self._s = settings
        self.client = client or OllamaClient(settings)
        self._clock = clock
        self._cache: tuple[float, LlmStatus] | None = None

    @property
    def model(self) -> str:
        return self._s.ollama_model

    async def status(self, *, fresh: bool = False) -> LlmStatus:
        """Cached for a few seconds so the UI can poll without hammering Ollama."""
        now = self._clock()
        if not fresh and self._cache and now - self._cache[0] < 5:
            return self._cache[1]
        status = await self._probe()
        self._cache = (now, status)
        return status

    async def _probe(self) -> LlmStatus:
        model = self._s.ollama_model
        bad = lambda e: LlmStatus(False, model, e.code, e.message, False, False, None)  # noqa: E731
        try:
            names = await self.client.tags()
            if not _installed(model, names):
                return bad(LlmModelMissing(f"The model '{model}' is not installed on the Ollama host. Run: ollama pull {model}"))
            info = await self.client.show(model)
        except LlmError as exc:
            return bad(exc)
        caps = info.get("capabilities") or []
        ctx = next((v for k, v in (info.get("model_info") or {}).items() if k.endswith("context_length")), None)
        tools = "tools" in caps
        status = LlmStatus(tools, model, None if tools else LlmNoTools.code,
                           None if tools else f"The model '{model}' does not support tool calling, which the assistant needs to retrieve data.",
                           tools, "thinking" in caps, ctx if isinstance(ctx, int) else None)
        return status
