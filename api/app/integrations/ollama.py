"""Ollama HTTP client. Every failure is mapped to a typed LlmError with a safe, user-presentable message
(no host names, no raw server text beyond a short Ollama error string)."""

import json
import logging
from collections.abc import AsyncIterator

import httpx

from app.core.config import Settings

logger = logging.getLogger("app.ollama")


class LlmError(Exception):
    code = "llm_error"

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class LlmUnavailable(LlmError):
    code = "llm_unavailable"


class LlmModelMissing(LlmError):
    code = "model_missing"


class LlmNoTools(LlmError):
    code = "model_no_tools"


class LlmBadResponse(LlmError):
    code = "llm_bad_response"


class OllamaClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._s = settings
        self._base = settings.ollama_base_url.rstrip("/")
        self._transport = transport
        self._timeout = httpx.Timeout(
            connect=settings.llm_connect_timeout_s, read=settings.llm_timeout_s, write=10.0, pool=10.0
        )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport)

    async def tags(self) -> list[str]:
        try:
            async with self._client() as c:
                r = await c.get(f"{self._base}/api/tags", timeout=self._s.ollama_timeout_s)
            r.raise_for_status()
            return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise LlmBadResponse("Ollama returned an unreadable model list.") from exc

    async def show(self, model: str) -> dict:
        try:
            async with self._client() as c:
                r = await c.post(f"{self._base}/api/show", json={"model": model}, timeout=self._s.ollama_timeout_s)
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc
        if r.status_code == 404:
            raise LlmModelMissing(_missing_message(model))
        if r.status_code >= 400:
            raise LlmBadResponse(f"Ollama could not describe the model (HTTP {r.status_code}).")
        try:
            return r.json()
        except ValueError as exc:
            raise LlmBadResponse("Ollama returned an unreadable model description.") from exc

    async def chat_stream(self, payload: dict) -> AsyncIterator[dict]:
        """Yields one parsed JSON object per streamed line. The last has done=true and carries token counts."""
        try:
            async with self._client() as c:
                async with c.stream("POST", f"{self._base}/api/chat", json=payload) as r:
                    if r.status_code >= 400:
                        body = (await r.aread()).decode("utf-8", "replace")
                        raise self._http_error(payload.get("model", ""), r.status_code, body)
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        try:
                            obj = json.loads(line)
                        except ValueError as exc:
                            raise LlmBadResponse("Ollama sent a malformed streaming line.") from exc
                        if "error" in obj:
                            raise self._http_error(payload.get("model", ""), 500, json.dumps(obj))
                        yield obj
        except httpx.HTTPError as exc:
            raise self._unavailable(exc) from exc

    # -------------------------------------------------------------------------------------------
    @staticmethod
    def _unavailable(exc: Exception) -> LlmUnavailable:
        logger.warning("Ollama request failed: %s", type(exc).__name__)
        if isinstance(exc, httpx.ReadTimeout):
            return LlmUnavailable("The language model took too long to respond. It may still be loading; try again shortly.")
        return LlmUnavailable("The language model service is not reachable.")

    @staticmethod
    def _http_error(model: str, status: int, body: str) -> LlmError:
        try:
            text = str(json.loads(body).get("error", ""))
        except (ValueError, AttributeError):
            text = ""
        if status == 404 or "not found" in text.lower():
            return LlmModelMissing(_missing_message(model))
        logger.warning("Ollama error %s: %s", status, text[:200])
        return LlmBadResponse(f"The language model reported an error: {text[:200] or f'HTTP {status}'}")


def _missing_message(model: str) -> str:
    return f"The model '{model}' is not installed on the Ollama host. Run: ollama pull {model}"
