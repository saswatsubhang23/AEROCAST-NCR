"""Gridded atmospheric fields for the map: one regular lat/lon lattice of Open-Meteo point series, all hours of a window.

What this is, exactly: Open-Meteo serves *point* time series from a numerical-weather-model grid. Probing it with points 0.02 degrees apart
(2026-10-11) shows the model cells over Delhi-NCR are about 0.070 degrees tall (latitude) and about 0.103 degrees wide (longitude), i.e.
roughly 8 km x 10 km. We request a regular lattice with about the same spacing (0.073 x 0.11 degrees, so each request lands in its own model
cell, or at worst the neighbouring one) and return the values unchanged: this is the model's native resolution, nothing finer. The
frontend interpolates between lattice points only to draw; nothing is extrapolated beyond the lattice, and a missing value stays missing.

Two time modes:
  forecast    the provider's forecast endpoint with `past_days` of recent analysis/forecast and `forecast_days` ahead
  historical  the provider's archive (reanalysis) endpoint for an explicit past window; the newest days are not yet available there
"""

import asyncio
import math
import time
from datetime import date, datetime, timedelta, timezone

from app.core.config import Settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError

SOUTH, NORTH, WEST, EAST = 28.1, 29.05, 76.7, 77.8
ROWS, COLS = 14, 11
CHUNK = 36  # points per upstream request

# key -> (label, unit)
FIELDS = {
    "temperature_2m": ("Temperature (2 m)", "°C"),
    "relative_humidity_2m": ("Relative humidity (2 m)", "%"),
    "pressure_msl": ("Mean sea-level pressure", "hPa"),
    "precipitation": ("Precipitation (hourly total)", "mm"),
    "cloud_cover": ("Cloud cover", "%"),
    "boundary_layer_height": ("Boundary-layer height", "m"),
    "shortwave_radiation": ("Shortwave radiation", "W/m²"),
    "visibility": ("Visibility", "m"),
}
WIND = ("wind_speed_10m", "wind_direction_10m")

# Winds at more than one height, requested with `levels=True`. All are model output from the same provider (no balloon or tower data).
# The three pressure levels carry their own geopotential height, so their height is the model's, not an assumption.
# (suffix, nominal height above ground in m or None for a pressure level, speed variable, direction variable, geopotential-height variable)
WIND_LEVELS = [
    ("80m", 80.0, "wind_speed_80m", "wind_direction_80m", None),
    ("120m", 120.0, "wind_speed_120m", "wind_direction_120m", None),
    ("180m", 180.0, "wind_speed_180m", "wind_direction_180m", None),
    ("925hPa", None, "wind_speed_925hPa", "wind_direction_925hPa", "geopotential_height_925hPa"),
    ("850hPa", None, "wind_speed_850hPa", "wind_direction_850hPa", "geopotential_height_850hPa"),
    ("700hPa", None, "wind_speed_700hPa", "wind_direction_700hPa", "geopotential_height_700hPa"),
]
LEVEL_VARS = [v for _, _, sp, di, gp in WIND_LEVELS for v in (sp, di, gp) if v]
LIMITS = {  # physically plausible bounds; anything outside is dropped to null rather than drawn
    "temperature_2m": (-20.0, 60.0), "relative_humidity_2m": (0.0, 100.0), "pressure_msl": (850.0, 1100.0), "precipitation": (0.0, 300.0),
    "cloud_cover": (0.0, 100.0), "boundary_layer_height": (0.0, 6000.0), "wind_speed_10m": (0.0, 80.0),
    "shortwave_radiation": (0.0, 1500.0), "visibility": (0.0, 200000.0),
    **{sp: (0.0, 150.0) for _, _, sp, _, _ in WIND_LEVELS},
    **{gp: (-500.0, 20000.0) for _, _, _, _, gp in WIND_LEVELS if gp},
}
FORECAST_TTL = 1800.0
HISTORICAL_TTL = 86400.0
MAX_HOURS = 24 * 10


def lattice() -> tuple[list[float], list[float]]:
    lats = [round(SOUTH + (NORTH - SOUTH) * i / (ROWS - 1), 4) for i in range(ROWS)]
    lons = [round(WEST + (EAST - WEST) * j / (COLS - 1), 4) for j in range(COLS)]
    return lats, lons


def uv_from(speed: float | None, direction_from_deg: float | None) -> tuple[float | None, float | None]:
    """Meteorological convention: direction is where the wind comes FROM. u is eastward, v is northward (m/s)."""
    if speed is None or direction_from_deg is None:
        return None, None
    r = math.radians(direction_from_deg)
    return round(-speed * math.sin(r), 3), round(-speed * math.cos(r), 3)


def _bounded(key: str, v):
    if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
        return None
    lo, hi = LIMITS.get(key, (-1e9, 1e9))
    return float(v) if lo <= v <= hi else None


class WeatherFieldsService:
    def __init__(self, settings: Settings, client: OpenMeteoClient | None = None, now=None):
        self._client = client or OpenMeteoClient(settings)
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def fields(self, mode: str, past_days: int = 2, forecast_days: int = 3, start: date | None = None, end: date | None = None,
                     levels: bool = False) -> dict:
        if mode not in ("forecast", "historical"):
            raise ValueError("mode must be 'forecast' or 'historical'")
        if mode == "forecast":
            if not (0 <= past_days <= 7 and 1 <= forecast_days <= 7):
                raise ValueError("past_days must be 0 to 7 and forecast_days 1 to 7")
            key, ttl = ("forecast", past_days, forecast_days, levels), FORECAST_TTL
        else:
            if start is None or end is None or end < start:
                raise ValueError("historical mode needs start and end dates (end not before start)")
            if (end - start).days + 1 > MAX_HOURS // 24:
                raise ValueError(f"at most {MAX_HOURS // 24} days per request")
            if end >= self._now().date():
                raise ValueError("the archive has no data for today or later; use forecast mode for recent hours")
            key, ttl = ("historical", start, end, levels), HISTORICAL_TTL
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < ttl:
            return hit[1]
        out = await self._build(mode, past_days, forecast_days, start, end, levels)
        self._cache[key] = (time.monotonic(), out)
        return out

    async def _fetch_chunk(self, mode: str, points: list[tuple[float, float]], past_days: int, forecast_days: int, start, end, levels: bool = False) -> list[dict]:
        hourly = ",".join([*FIELDS, *WIND, *(LEVEL_VARS if levels else [])])
        params = {
            "latitude": ",".join(str(p[0]) for p in points), "longitude": ",".join(str(p[1]) for p in points), "hourly": hourly,
            "timezone": "GMT", "temperature_unit": "celsius", "wind_speed_unit": "ms", "precipitation_unit": "mm",
        }
        if mode == "forecast":
            params |= {"past_days": past_days, "forecast_days": forecast_days}
            body = await self._client.get_forecast(params)
        else:
            params |= {"start_date": start.isoformat(), "end_date": end.isoformat()}
            body = await self._client.get_archive(params)
        items = body if isinstance(body, list) else [body]
        if len(items) != len(points) or not all(isinstance(i, dict) and isinstance(i.get("hourly"), dict) for i in items):
            raise UpstreamError("Open-Meteo returned an unexpected multi-point response.")
        return items

    async def _build(self, mode: str, past_days: int, forecast_days: int, start, end, levels: bool = False) -> dict:
        lats, lons = lattice()
        points = [(la, lo) for la in lats for lo in lons]
        chunks = [points[i:i + CHUNK] for i in range(0, len(points), CHUNK)]
        results = await asyncio.gather(*[self._fetch_chunk(mode, c, past_days, forecast_days, start, end, levels) for c in chunks])
        items = [i for r in results for i in r]
        times_raw = items[0]["hourly"].get("time")
        if not isinstance(times_raw, list) or not times_raw:
            raise UpstreamError("Open-Meteo returned no hourly times.")
        if any(i["hourly"].get("time") != times_raw for i in items):
            raise UpstreamError("Open-Meteo returned different time axes for different points.")
        times = [t + ":00Z" if len(t) == 16 else t for t in times_raw]
        n = len(times)
        if n > MAX_HOURS:
            raise UpstreamError("Open-Meteo returned more hours than expected.")
        units_in = items[0].get("hourly_units", {})

        def column(item: dict, key: str) -> list:
            v = item["hourly"].get(key)
            return v if isinstance(v, list) and len(v) == n else [None] * n

        variables: dict[str, dict] = {}
        for key, (label, unit) in FIELDS.items():
            cube = [[[None] * COLS for _ in range(ROWS)] for _ in range(n)]
            seen = 0
            for idx, item in enumerate(items):
                r, c = divmod(idx, COLS)
                col = column(item, key)
                for t in range(n):
                    val = _bounded(key, col[t])
                    if val is not None:
                        cube[t][r][c] = round(val, 2)
                        seen += 1
            variables[key] = {"label": label, "unit": unit, "values": cube, "available": seen > 0, "valid_fraction": round(seen / (n * len(items)), 3)}
        u_cube = [[[None] * COLS for _ in range(ROWS)] for _ in range(n)]
        v_cube = [[[None] * COLS for _ in range(ROWS)] for _ in range(n)]
        seen = 0
        for idx, item in enumerate(items):
            r, c = divmod(idx, COLS)
            sp, di = column(item, WIND[0]), column(item, WIND[1])
            for t in range(n):
                s, d = _bounded(WIND[0], sp[t]), (float(di[t]) % 360.0 if isinstance(di[t], (int, float)) and math.isfinite(di[t]) else None)
                u, v = uv_from(s, d)
                u_cube[t][r][c], v_cube[t][r][c] = u, v
                seen += u is not None
        variables["wind_u"] = {"label": "Wind, eastward component (10 m)", "unit": "m/s", "values": u_cube, "available": seen > 0, "valid_fraction": round(seen / (n * len(items)), 3)}
        variables["wind_v"] = {"label": "Wind, northward component (10 m)", "unit": "m/s", "values": v_cube, "available": seen > 0, "valid_fraction": round(seen / (n * len(items)), 3)}

        level_meta: list[dict] = []
        elevation = None
        if levels:
            def wind_cube(sp_key: str, di_key: str):
                uc = [[[None] * COLS for _ in range(ROWS)] for _ in range(n)]
                vc = [[[None] * COLS for _ in range(ROWS)] for _ in range(n)]
                got = 0
                for idx, item in enumerate(items):
                    r, c = divmod(idx, COLS)
                    sp, di = column(item, sp_key), column(item, di_key)
                    for t in range(n):
                        s = _bounded(sp_key, sp[t])
                        d = float(di[t]) % 360.0 if isinstance(di[t], (int, float)) and math.isfinite(di[t]) else None
                        uu, vv = uv_from(s, d)
                        uc[t][r][c], vc[t][r][c] = uu, vv
                        got += uu is not None
                return uc, vc, got

            elev_vals = [i.get("elevation") for i in items]
            if all(isinstance(e, (int, float)) for e in elev_vals):
                elevation = [[round(float(elev_vals[r * COLS + c]), 0) for c in range(COLS)] for r in range(ROWS)]
            mean_elev = (sum(e for row in elevation for e in row) / (ROWS * COLS)) if elevation else None
            for suffix, h_agl, sp_key, di_key, gp_key in WIND_LEVELS:
                uc, vc, got = wind_cube(sp_key, di_key)
                frac = round(got / (n * len(items)), 3)
                label = f"Wind at {suffix.replace('m', ' m above ground') if h_agl else suffix}"
                variables[f"wind_u_{suffix}"] = {"label": f"{label}, eastward", "unit": "m/s", "values": uc, "available": got > 0, "valid_fraction": frac}
                variables[f"wind_v_{suffix}"] = {"label": f"{label}, northward", "unit": "m/s", "values": vc, "available": got > 0, "valid_fraction": frac}
                height_agl = h_agl
                if gp_key:
                    cube_g = [[[None] * COLS for _ in range(ROWS)] for _ in range(n)]
                    seen_g, tot, cnt = 0, 0.0, 0
                    for idx, item in enumerate(items):
                        r, c = divmod(idx, COLS)
                        col = column(item, gp_key)
                        for t in range(n):
                            val = _bounded(gp_key, col[t])
                            if val is not None:
                                cube_g[t][r][c] = round(val, 0)
                                seen_g += 1
                                tot += val
                                cnt += 1
                    variables[f"gph_{suffix}"] = {"label": f"Geopotential height of {suffix}", "unit": "m", "values": cube_g, "available": seen_g > 0,
                                                  "valid_fraction": round(seen_g / (n * len(items)), 3)}
                    if cnt and mean_elev is not None:
                        height_agl = round(tot / cnt - mean_elev, 0)
                level_meta.append({"key": suffix, "kind": "height" if h_agl else "pressure", "height_agl_m": height_agl, "available": got > 0})

        snap = [(i["latitude"], i["longitude"]) for i in items if isinstance(i.get("latitude"), (int, float))]
        max_snap_km = None
        if len(snap) == len(points):
            max_snap_km = round(max(_km(a, b, c, d) for (a, b), (c, d) in zip(points, snap)), 1)
        now = self._now()
        now_idx = None
        for k, t in enumerate(times):
            if datetime.fromisoformat(t.replace("Z", "+00:00")) <= now:
                now_idx = k
        return {
            "mode": mode,
            "grid": {"lats": lats, "lons": lons, "rows": ROWS, "cols": COLS, "spacing_deg": {"lat": round((NORTH - SOUTH) / (ROWS - 1), 4), "lon": round((EAST - WEST) / (COLS - 1), 4)}},
            "times": times,
            "now_index": now_idx if mode == "forecast" else None,
            "variables": variables,
            "levels": level_meta,
            "elevation_m": elevation,
            "units_from_provider": {k: units_in.get(k) for k in [*FIELDS, *WIND]},
            "source": {
                "provider": "Open-Meteo " + ("forecast API (numerical weather model)" if mode == "forecast" else "historical archive API (reanalysis)"),
                "model_resolution": "native model cells of about 0.07 x 0.10 degrees (8 x 10 km); the lattice samples about one point per cell",
                "max_distance_from_requested_point_km": max_snap_km,
                "retrieved_at": now.isoformat().replace("+00:00", "Z"),
                "licence_note": "Open-Meteo free tier, non-commercial use.",
            },
            "notes": [
                "Values are model output at lattice points, not measurements. Colours between points are bilinear interpolation for display only.",
                "Precipitation is the model's total for the hour ending at the timestamp.",
                "Across this small area the mean sea-level pressure varies by well under 1 hPa; contours therefore use a fine, stated interval.",
            ],
        }


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    from app.core.places import distance_km

    return distance_km(lat1, lon1, lat2, lon2)
