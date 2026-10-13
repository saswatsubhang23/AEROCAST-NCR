"""Modelled air quality from the Open-Meteo Air Quality API (atmospheric-chemistry model output, not measurements).

This is the one source here that gives a pollution *forecast* with no station data and no trained model of ours. It is
chemistry-transport model output on a coarse grid (about 11 to 40 km), so it is smooth, can be biased against ground stations in a
city like Delhi, and must never be shown as an observation. Values are passed through unchanged, validated, and labelled.
"""

import time

from app.core.config import Settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError

# our pollutant code -> Open-Meteo variable
VARIABLES = {"pm25": "pm2_5", "pm10": "pm10", "no2": "nitrogen_dioxide", "so2": "sulphur_dioxide", "co": "carbon_monoxide", "o3": "ozone"}
CACHE_SECONDS = 900


class ModelAirQualityService:
    def __init__(self, settings: Settings, client: OpenMeteoClient | None = None):
        self._client = client or OpenMeteoClient(settings)
        self._cache: dict[tuple, tuple[float, dict]] = {}

    async def forecast(self, lat: float, lon: float, past_hours: int = 24, forecast_hours: int = 48) -> dict:
        key = (round(lat, 2), round(lon, 2), past_hours, forecast_hours)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        body = await self._client.get_air_quality({
            "latitude": lat, "longitude": lon, "hourly": ",".join(VARIABLES.values()), "timezone": "GMT",
            "past_hours": past_hours, "forecast_hours": forecast_hours,
        })
        hourly = body.get("hourly") if isinstance(body, dict) else None
        times = hourly.get("time") if isinstance(hourly, dict) else None
        if not isinstance(times, list) or not times:
            raise UpstreamError("Open-Meteo returned an air-quality response without hourly data.")
        series = {}
        for code, var in VARIABLES.items():
            vals = hourly.get(var)
            if isinstance(vals, list) and len(vals) == len(times):
                series[code] = {"unit": (body.get("hourly_units") or {}).get(var, "µg/m³").replace("μ", "µ"),
                                "values": [float(v) if isinstance(v, (int, float)) else None for v in vals]}
        if not series:
            raise UpstreamError("Open-Meteo returned no usable pollutant series.")
        out = {
            "source": "Open-Meteo Air Quality API (atmospheric-chemistry model)", "kind": "atmospheric_model_forecast",
            "location": {"lat": body.get("latitude", lat), "lon": body.get("longitude", lon), "elevation_m": body.get("elevation")},
            "times_utc": [t if t.endswith("Z") else t + ":00Z" if len(t) == 16 else t for t in times],
            "pollutants": series,
            "notes": "Modelled concentrations on a coarse grid; not measurements and not our trained model. Expect differences from station readings, "
                     "especially for PM and NO2 near sources. Provider free tier is non-commercial.",
        }
        self._cache[key] = (time.monotonic(), out)
        return out
