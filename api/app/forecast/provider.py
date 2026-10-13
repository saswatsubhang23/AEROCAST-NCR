"""Forecast provider interface and the optional HTTP adapter. There is deliberately no forecasting code here: with no
provider configured every call says so, and nothing else (no LLM, no statistics, no placeholder) stands in for one."""

import logging
from typing import Protocol

import httpx
from pydantic import ValidationError

from app.core.config import Settings
from app.core.time import utc_now
from app.forecast.contract import (
    ForecastContractError, ForecastRequest, ForecastResponse, check_against_request,
)

logger = logging.getLogger("app.forecast")


class ForecastNotConfigured(Exception):
    message = "No forecasting service is configured, so pollution forecasts are unavailable."


class ForecastUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ForecastProvider(Protocol):
    name: str

    async def forecast(self, request: ForecastRequest) -> ForecastResponse: ...

    async def health(self) -> None:
        """Raise ForecastUnavailable if the provider cannot be reached."""


class HttpForecastProvider:
    """Talks to an external service that implements the contract: POST /forecast and (optionally) GET /health."""

    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._base = settings.ml_forecast_url.rstrip("/")
        self._key = settings.ml_forecast_api_key.get_secret_value()
        self._timeout = settings.ml_forecast_timeout_s
        self._transport = transport
        self.name = httpx.URL(self._base).host or "external provider"

    def _headers(self) -> dict:
        return {"X-API-Key": self._key} if self._key else {}

    async def forecast(self, request: ForecastRequest) -> ForecastResponse:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                r = await c.post(f"{self._base}/forecast", json=request.model_dump(mode="json"), headers=self._headers())
        except httpx.TimeoutException:
            raise ForecastUnavailable("The forecasting service took too long to respond.") from None
        except httpx.HTTPError:
            raise ForecastUnavailable("The forecasting service is not reachable.") from None
        if r.status_code in (401, 403):
            raise ForecastUnavailable("The forecasting service rejected the configured credentials.")
        if r.status_code >= 400:
            raise ForecastUnavailable(f"The forecasting service reported an error (HTTP {r.status_code}).")
        try:
            return ForecastResponse.model_validate_json(r.content)
        except ValidationError as exc:
            first = exc.errors()[0]
            where = ".".join(str(p) for p in first["loc"]) or "response"
            logger.warning("Forecast provider response rejected: %s: %s", where, first["msg"])
            raise ForecastContractError(
                f"The forecast service's response breaks the contract ({where}: {first['msg']})."
            ) from None

    async def health(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                r = await c.get(f"{self._base}/health", headers=self._headers())
            r.raise_for_status()
        except httpx.HTTPError:
            raise ForecastUnavailable("The forecasting service is not reachable.") from None


def make_provider(settings: Settings) -> ForecastProvider | None:
    if settings.ml_forecast_url.strip():
        return HttpForecastProvider(settings)
    if settings.ml_local_model_dir.strip():
        # Imported only here: the API never imports training code, and loads model libraries only when a model is first used.
        from app.ml.inference import LocalModelProvider
        return LocalModelProvider(settings)
    return None


class ForecastService:
    def __init__(self, settings: Settings, provider: ForecastProvider | None = None, now=utc_now):
        self._provider = provider if provider is not None else make_provider(settings)
        self._now = now

    @property
    def configured(self) -> bool:
        return self._provider is not None

    @property
    def provider_name(self) -> str | None:
        return self._provider.name if self._provider else None

    async def forecast(self, request: ForecastRequest) -> ForecastResponse:
        """Ask the provider, then validate the answer against the contract and against the request."""
        if self._provider is None:
            raise ForecastNotConfigured()
        response = await self._provider.forecast(request)
        check_against_request(request, response, self._now())
        return response

    async def health(self) -> None:
        if self._provider is None:
            raise ForecastNotConfigured()
        await self._provider.health()

