"""Client for TypeSafe's documented API (https://api.typesafe.ai/docs, OpenAPI 0.2.0).

Documented endpoints, as published in the service's own OpenAPI document:
  GET  /v1/models      list model names/aliases available to the account (names are never guessed)
  POST /v1/systemone   body {state, model, questions: {name: noul|choice|score question}} ->
                       {model, answers: {name: answer of the same type}, usage}
Authentication is `Authorization: Bearer <API_KEY>`. The key comes from the environment, is sent only in that header, and is
never logged. Responses are validated; anything that does not match the documented shape or the question that was asked is an
error, never a guess.
"""

import asyncio
import logging
import time
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.core.config import Settings

logger = logging.getLogger("app.jev")


class JevError(Exception):
    """Base class: the decision-support service could not give a usable answer. Callers fall back to deterministic behaviour."""

    def __init__(self, message: str, kind: str = "error"):
        super().__init__(message)
        self.message = message
        self.kind = kind


class JevDisabled(JevError):
    def __init__(self):
        super().__init__("Jev decision support is switched off (JEV_MODE=off).", "disabled")


# ---------------------------------------------------------------------------------------------- documented schemas
class NoulAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


class ChoiceAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["choice"]
    choice: str
    confidence: float = Field(ge=0, le=1)
    probabilities: dict[str, float]

    @model_validator(mode="after")
    def _probs(self):
        if any(not 0 <= v <= 1 for v in self.probabilities.values()):
            raise ValueError("probabilities must be between 0 and 1")
        return self


class ScoreAnswer(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: Literal["score"]
    score: float
    confidence: float = Field(ge=0, le=1)
    legend: dict[str, Any]
    probabilities: dict[str, float]


class Usage(BaseModel):
    model_config = ConfigDict(extra="ignore")
    input_tokens: int
    output_tokens: int


class SystemOneResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    model: str
    answers: dict[str, NoulAnswer | ChoiceAnswer | ScoreAnswer] = Field(min_length=1)
    usage: Usage


def noul_question(instructions: str, true: str | None = None, false: str | None = None) -> dict:
    q: dict[str, Any] = {"type": "noul", "instructions": instructions}
    if true or false:
        q["criteria"] = {k: v for k, v in (("true", true), ("false", false)) if v}
    return q


def choice_question(instructions: str, criteria: dict[str, str]) -> dict:
    return {"type": "choice", "instructions": instructions, "criteria": criteria}


# ---------------------------------------------------------------------------------------------- client
class JevClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._s = settings
        self._transport = transport
        self._model: str | None = settings.jev_model.strip() or None
        self.stats = {"requests": 0, "failures": 0, "rate_limited": 0}

    @property
    def mode(self) -> str:
        return self._s.jev_mode.strip().lower()

    @property
    def enabled(self) -> bool:
        return self.mode in ("shadow",) and bool(self._s.typesafe_api_key.get_secret_value())

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._s.typesafe_api_key.get_secret_value()}", "Content-Type": "application/json"}

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict:
        if self.mode == "off":
            raise JevDisabled()
        if not self._s.typesafe_api_key.get_secret_value():
            raise JevError("No TypeSafe API key is configured (TYPESAFE_API_KEY).", "not_configured")
        last: JevError | None = None
        for attempt in range(1, max(1, self._s.jev_max_attempts) + 1):
            self.stats["requests"] += 1
            try:
                async with httpx.AsyncClient(timeout=self._s.jev_timeout_s, transport=self._transport) as c:
                    r = await c.request(method, f"{self._s.jev_base_url.rstrip('/')}{path}", json=json, headers=self._headers())
            except httpx.TimeoutException:
                last = JevError("Jev timed out.", "timeout")
            except httpx.HTTPError as exc:
                last = JevError(f"Jev is not reachable ({type(exc).__name__}).", "unreachable")
            else:
                if r.status_code in (401, 403):
                    self.stats["failures"] += 1
                    raise JevError("Jev rejected the configured API key.", "auth")  # not retried
                if r.status_code == 429:
                    self.stats["rate_limited"] += 1
                    last = JevError("Jev rate limit reached.", "rate_limited")
                    delay = min(float(r.headers.get("retry-after", "1") or 1), 5.0) if r.headers.get("retry-after", "1").replace(".", "", 1).isdigit() else 1.0
                    if attempt < self._s.jev_max_attempts:
                        await asyncio.sleep(delay)
                    continue
                if r.status_code >= 500:
                    last = JevError(f"Jev reported a server error (HTTP {r.status_code}).", "server_error")
                elif r.status_code >= 400:
                    self.stats["failures"] += 1
                    raise JevError(f"Jev rejected the request (HTTP {r.status_code}).", "bad_request")  # a bug on our side; not retried
                else:
                    try:
                        return r.json()
                    except ValueError:
                        last = JevError("Jev returned something that is not JSON.", "bad_response")
            if attempt < self._s.jev_max_attempts:
                await asyncio.sleep(0.3 * attempt)
        self.stats["failures"] += 1
        assert last is not None
        logger.warning("Jev call failed: %s", last.kind)  # kind only: never bodies, headers or keys
        raise last

    async def models(self) -> list[dict]:
        body = await self._request("GET", "/v1/models")
        items = body.get("models") if isinstance(body, dict) else None
        if not isinstance(items, list) or not all(isinstance(m, dict) and isinstance(m.get("name"), str) for m in items):
            raise JevError("Jev returned an unexpected model list.", "bad_response")
        return items

    async def model_name(self) -> str:
        """The configured model, else the first one the service itself lists. Names are discovered, never invented."""
        if self._model:
            return self._model
        names = [m["name"] for m in await self.models()]
        if not names:
            raise JevError("The service lists no models for this account.", "no_models")
        self._model = names[0]
        return self._model

    async def ask(self, state: str | dict | list, questions: dict[str, dict]) -> SystemOneResponse:
        if not questions:
            raise ValueError("at least one question is required")
        started = time.perf_counter()
        model = await self.model_name()
        body = await self._request("POST", "/v1/systemone", {"state": state, "model": model, "questions": questions})
        try:
            res = SystemOneResponse.model_validate(body)
        except ValidationError:
            self.stats["failures"] += 1
            raise JevError("Jev's answer does not match the documented response format.", "bad_response") from None
        for name, q in questions.items():  # every answer must exist, match its question's type, and (for choices) name a real option
            a = res.answers.get(name)
            if a is None or a.type != q["type"]:
                self.stats["failures"] += 1
                raise JevError(f"Jev's answer for '{name}' is missing or of the wrong type.", "bad_response")
            if isinstance(a, ChoiceAnswer) and a.choice not in q["criteria"]:
                self.stats["failures"] += 1
                raise JevError(f"Jev chose '{a.choice}', which is not one of the offered options.", "bad_response")
        self.last_latency_ms = round((time.perf_counter() - started) * 1000)
        return res

    last_latency_ms: int | None = None
