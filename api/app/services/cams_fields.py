"""Modelled pollutant fields over Delhi-NCR on a regular lattice, from the Open-Meteo Air Quality API (ECMWF CAMS).

Why it exists: it is the only source here that is genuinely updated every hour and covers the whole domain without gaps. It is a
chemistry-transport MODEL on a coarse grid (measured 2026-10-11: cells of about 0.4 degrees, 44 km, so Delhi-NCR holds only about 3 x 3 distinct cells), not a measurement; it can differ strongly from the stations and is always labelled
`atmospheric_model`. Values are passed through unchanged; implausible or missing values become null, never filled.
"""

from __future__ import annotations

import asyncio
import math
import time
from datetime import datetime, timezone

import numpy as np

from app.core.config import Settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError

SOUTH, NORTH, WEST, EAST = 28.1, 29.05, 76.7, 77.8
ROWS, COLS = 10, 12  # a 0.1 degree lattice, finer than the model's 0.4 degree cells: neighbouring points repeat one cell's value
CHUNK = 40
CACHE_SECONDS = 900
MAX_PAST, MAX_FORECAST = 48, 96

# our code -> (Open-Meteo variable, label, plausible range)
VARIABLES = {
    "pm25": ("pm2_5", "PM2.5", (0.0, 2000.0)),
    "pm10": ("pm10", "PM10", (0.0, 4000.0)),
    "no2": ("nitrogen_dioxide", "NO2", (0.0, 1500.0)),
    "o3": ("ozone", "O3", (0.0, 1000.0)),
    "so2": ("sulphur_dioxide", "SO2", (0.0, 3000.0)),
    "co": ("carbon_monoxide", "CO", (0.0, 60000.0)),
    "no": ("nitrogen_monoxide", "NO", (0.0, 1500.0)),
    "dust": ("dust", "Dust", (0.0, 5000.0)),
}


def lattice() -> tuple[list[float], list[float]]:
    return ([round(SOUTH + (NORTH - SOUTH) * i / (ROWS - 1), 4) for i in range(ROWS)], [round(WEST + (EAST - WEST) * j / (COLS - 1), 4) for j in range(COLS)])


class CamsFieldsService:
    def __init__(self, settings: Settings, client: OpenMeteoClient | None = None, now=None):
        self._client = client or OpenMeteoClient(settings)
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def fields(self, past_hours: int = 12, forecast_hours: int = 48) -> dict:
        if not (0 <= past_hours <= MAX_PAST and 1 <= forecast_hours <= MAX_FORECAST):
            raise ValueError(f"past_hours must be 0 to {MAX_PAST} and forecast_hours 1 to {MAX_FORECAST}")
        key = (past_hours, forecast_hours)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        lats, lons = lattice()
        points = [(la, lo) for la in lats for lo in lons]
        chunks = [points[i:i + CHUNK] for i in range(0, len(points), CHUNK)]

        async def one(pts: list[tuple[float, float]]) -> list[dict]:
            body = await self._client.get_air_quality({
                "latitude": ",".join(str(p[0]) for p in pts), "longitude": ",".join(str(p[1]) for p in pts),
                "hourly": ",".join(v[0] for v in VARIABLES.values()), "timezone": "GMT", "past_hours": past_hours, "forecast_hours": forecast_hours,
            })
            items = body if isinstance(body, list) else [body]
            if len(items) != len(pts) or not all(isinstance(i, dict) and isinstance(i.get("hourly"), dict) for i in items):
                raise UpstreamError("Open-Meteo returned an unexpected multi-point air-quality response.")
            return items

        items = [i for r in await asyncio.gather(*[one(c) for c in chunks]) for i in r]
        times_raw = items[0]["hourly"].get("time")
        if not isinstance(times_raw, list) or not times_raw:
            raise UpstreamError("Open-Meteo returned no hourly times.")
        if any(i["hourly"].get("time") != times_raw for i in items):
            raise UpstreamError("Open-Meteo returned different time axes for different points.")
        times = [t + ":00Z" if len(t) == 16 else t for t in times_raw]
        n = len(times)
        units = items[0].get("hourly_units", {})
        variables: dict[str, dict] = {}
        for code, (var, label, (lo, hi)) in VARIABLES.items():
            cube = np.full((n, ROWS, COLS), np.nan)
            for idx, item in enumerate(items):
                r, c = divmod(idx, COLS)
                col = item["hourly"].get(var)
                if isinstance(col, list) and len(col) == n:
                    for t, v in enumerate(col):
                        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and lo <= v <= hi:
                            cube[t, r, c] = v
            seen = int(np.isfinite(cube).sum())
            variables[code] = {
                "label": label, "unit": str(units.get(var, "µg/m³")).replace("μ", "µ"), "available": seen > 0,
                "valid_fraction": round(seen / cube.size, 3),
                "values": np.where(np.isnan(cube), None, np.round(cube, 1)).tolist(),
            }
        now = self._now()
        now_idx = None
        for k, t in enumerate(times):
            if datetime.fromisoformat(t.replace("Z", "+00:00")) <= now:
                now_idx = k
        out = {
            "grid": {"lats": lats, "lons": lons, "rows": ROWS, "cols": COLS},
            "times": times, "now_index": now_idx, "variables": variables,
            "source": {
                "provider": "Open-Meteo Air Quality API (ECMWF CAMS atmospheric-chemistry model)", "kind": "atmospheric_model",
                "resolution": "model cells of about 0.4 degrees (44 km); the 0.1 degree lattice repeats a cell value, so the field is made of a few large blocks and carries no sub-cell detail",
                "retrieved_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "licence_note": "Open-Meteo free tier, non-commercial use.",
            },
            "notes": [
                "Modelled concentrations, not measurements. They are updated every hour (unlike the station feed, which currently lags by days) but can differ strongly from the stations.",
                "The model includes emissions and chemistry that the coupled model here does not, so the two are expected to differ.",
            ],
        }
        self._cache[key] = (time.monotonic(), out)
        return out
