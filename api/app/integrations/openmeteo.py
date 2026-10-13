"""Open-Meteo forecast API client (see app.integrations.http for retry behaviour)."""

import httpx

from app.core.config import Settings
from app.integrations.http import UpstreamBadRequest, UpstreamError, UpstreamRateLimitError, get_json

__all__ = ["OpenMeteoClient", "UpstreamBadRequest", "UpstreamError", "UpstreamRateLimitError"]


class OpenMeteoClient:
    def __init__(self, settings: Settings, transport: httpx.AsyncBaseTransport | None = None):
        self._settings = settings
        self._transport = transport

    async def get_forecast(self, params: dict) -> dict | list:
        s = self._settings
        return await get_json(
            provider="Open-Meteo",
            url=s.open_meteo_base_url,
            params=params,
            timeout=s.weather_timeout_s,
            attempts=s.weather_max_attempts,
            backoff=s.weather_retry_backoff_s,
            transport=self._transport,
        )

    async def get_archive(self, params: dict) -> dict | list:
        """Historical archive endpoint (same retry rules). Used by the offline history pipeline only."""
        s = self._settings
        return await get_json(
            provider="Open-Meteo",
            url=s.open_meteo_archive_url,
            params=params,
            timeout=max(s.weather_timeout_s, 60.0),
            attempts=s.weather_max_attempts,
            backoff=max(s.weather_retry_backoff_s, 2.0),
            transport=self._transport,
        )

    async def get_air_quality(self, params: dict) -> dict | list:
        """Open-Meteo Air Quality API: modelled (CAMS) pollutant concentrations, past hours and a short forecast."""
        s = self._settings
        url = s.open_meteo_air_quality_url
        if params.get("apikey"):
            # Commercial Open-Meteo plans route through customer-api.open-meteo.com
            url = "https://customer-api.open-meteo.com/v1/air-quality"
        return await get_json(
            provider="Open-Meteo",
            url=url,
            params=params,
            timeout=s.weather_timeout_s,
            attempts=s.weather_max_attempts,
            backoff=s.weather_retry_backoff_s,
            transport=self._transport,
        )
