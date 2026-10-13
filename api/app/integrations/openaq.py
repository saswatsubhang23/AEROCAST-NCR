"""OpenAQ v3 client. Endpoints and fields were checked against OpenAQ's published OpenAPI spec
(https://api.openaq.org/openapi.json): GET /v3/locations (bbox, monitor, providers_id, limit, page),
GET /v3/locations/{id}/latest, GET /v3/sensors/{id}/hours (datetime_from, datetime_to, limit).
Authentication is a key in the X-API-Key header.
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from datetime import datetime

import httpx

from app.core.config import Settings
from app.integrations.http import UpstreamError, get_json

MAX_PAGES = 5


class AqNotConfigured(UpstreamError):
    """No OpenAQ API key is set."""


class OpenAQClient:
    def __init__(
        self,
        settings: Settings,
        transport: httpx.AsyncBaseTransport | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self._s = settings
        self._transport = transport
        self._clock, self._sleep = clock, sleep
        self._lock = asyncio.Lock()
        self._next_slot = 0.0
        self._interval = 60.0 / max(1, settings.aq_rate_per_minute)

    @property
    def configured(self) -> bool:
        return bool(self._s.aq_api_key.get_secret_value())

    async def _get(self, path: str, params: dict | None = None) -> dict:
        if not self.configured:
            raise AqNotConfigured("AQ_API_KEY is not set")
        # Space requests out so a burst of station look-ups cannot exceed the provider's rate limit.
        async with self._lock:
            wait = self._next_slot - self._clock()
            if wait > 0:
                await self._sleep(wait)
            self._next_slot = max(self._clock(), self._next_slot) + self._interval
        body = await get_json(
            provider="OpenAQ",
            url=f"{self._s.aq_api_base_url.rstrip('/')}{path}",
            params=params,
            headers={"X-API-Key": self._s.aq_api_key.get_secret_value()},
            timeout=self._s.aq_timeout_s,
            attempts=self._s.aq_max_attempts,
            backoff=self._s.aq_retry_backoff_s,
            transport=self._transport,
        )
        if not isinstance(body, dict) or not isinstance(body.get("results"), list):
            raise UpstreamError("OpenAQ returned an unexpected response shape")
        return body

    async def locations(self, bbox: tuple[float, float, float, float]) -> list[dict]:
        s = self._s
        params: dict = {"bbox": ",".join(str(v) for v in bbox), "limit": 1000}
        if s.aq_reference_only:
            params["monitor"] = "true"
        if s.aq_provider_ids.strip():
            params["providers_id"] = s.aq_provider_ids.strip()
        out: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            results = (await self._get("/locations", {**params, "page": page}))["results"]
            out.extend(results)
            if len(results) < params["limit"]:
                break
        return out

    async def latest(self, location_id: int) -> list[dict]:
        return (await self._get(f"/locations/{location_id}/latest", {"limit": 1000}))["results"]

    async def hours(self, sensor_id: int, start: datetime, end: datetime) -> list[dict]:
        params = {
            "datetime_from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datetime_to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": 1000,
        }
        return (await self._get(f"/sensors/{sensor_id}/hours", params))["results"]

    async def sensors(self, location_id: int) -> list[dict]:
        """GET /v3/locations/{id}/sensors: every sensor of a station with its own first/last datetimes."""
        return (await self._get(f"/locations/{location_id}/sensors", {"limit": 1000}))["results"]

    async def hours_page(self, sensor_id: int, start: datetime, end: datetime, page: int = 1, limit: int = 1000) -> list[dict]:
        """One page of GET /v3/sensors/{id}/hours for the history pipeline (the live service uses `hours`)."""
        params = {
            "datetime_from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datetime_to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "limit": limit,
            "page": page,
        }
        return (await self._get(f"/sensors/{sensor_id}/hours", params))["results"]

    async def probe(self) -> None:
        await self._get("/locations", {"limit": 1})
