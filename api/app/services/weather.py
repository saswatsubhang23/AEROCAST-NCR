"""Weather domain logic: request building, validation, normalization, caching and freshness.

Rules enforced here:
  * times are parsed as UTC (the request pins timezone=GMT and the response is checked);
  * units are requested explicitly and the response units are verified, never assumed;
  * a missing value stays None; it is never replaced with zero or an estimate;
  * a variable the provider omits or returns entirely empty is reported as unavailable.
"""

import itertools
import logging
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.time import utc_now
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError
from app.schemas.weather import (
    Attribution,
    Coverage,
    GridForecastResponse,
    GridPoint,
    LocationInfo,
    DerivedSeries,
    PointForecastResponse,
    ProfileResponse,
    RecentWeatherResponse,
    SourceInfo,
    VariableInfo,
)
from app.services.indicators import hours_since_rain, ventilation_index
from app.services.profile import build_profile_hours

logger = logging.getLogger("app.weather")

MAX_HOURS = 72
FORECAST_DAYS = 4  # 96 h from 00:00 UTC today, enough to cover 72 h from any current hour

# key -> (label, expected unit, plausible min, plausible max)
VARIABLES: dict[str, tuple[str, str, float, float]] = {
    "temperature_2m": ("Temperature", "°C", -60, 65),
    "relative_humidity_2m": ("Relative humidity", "%", 0, 100),
    "dew_point_2m": ("Dew point", "°C", -80, 45),
    "wind_speed_10m": ("Wind speed", "km/h", 0, 400),
    "wind_direction_10m": ("Wind direction", "°", 0, 360),
    "precipitation": ("Precipitation", "mm", 0, 500),
    "surface_pressure": ("Surface pressure", "hPa", 300, 1100),
    "cloud_cover": ("Cloud cover", "%", 0, 100),
    "boundary_layer_height": ("Boundary layer height", "m", 0, 10000),
}
GRID_VARIABLES = [
    "temperature_2m", "relative_humidity_2m", "wind_speed_10m",
    "wind_direction_10m", "precipitation", "boundary_layer_height",
]
PROFILE_LEVELS = [1000, 925, 850, 700]
PROFILE_VARIABLES = [
    "temperature_2m", "surface_pressure",
    *[f"temperature_{lv}hPa" for lv in PROFILE_LEVELS],
    *[f"geopotential_height_{lv}hPa" for lv in PROFILE_LEVELS],
]
PROFILE_UNITS = {k: "hPa" if k == "surface_pressure" else "m" if k.startswith("geopot") else "°C" for k in PROFILE_VARIABLES}

# Delhi-NCR sampling box (west, south, east, north) and the grid laid over it: 4 x 4 points.
NCR_BBOX = (76.8, 28.2, 77.7, 28.95)
GRID_COLS, GRID_ROWS = 4, 4

ATTRIBUTION = Attribution(
    provider="Open-Meteo",
    url="https://open-meteo.com/",
    license="CC BY 4.0 (free API: non-commercial use)",
    text="Weather data by Open-Meteo.com",
)


@dataclass
class Normalized:
    """A provider response after validation. Holds the full returned window (all hours)."""

    location: LocationInfo
    times: list[datetime]
    series: dict[str, list[float | None]]
    unavailable: list[str]
    warnings: list[str]
    latest_source_time: datetime | None
    retrieved_at: datetime
    extra: dict = field(default_factory=dict)


def grid_points() -> list[tuple[float, float]]:
    west, south, east, north = NCR_BBOX
    lons = [round(west + (east - west) * i / (GRID_COLS - 1), 4) for i in range(GRID_COLS)]
    lats = [round(south + (north - south) * i / (GRID_ROWS - 1), 4) for i in range(GRID_ROWS)]
    return list(itertools.product(lats, lons))


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def normalize(
    raw: dict,
    wanted: list[str],
    units: dict[str, str],
    requested: tuple[float, float],
    retrieved_at: datetime,
) -> Normalized:
    """Validate one location's provider response. Raises UpstreamError if it is structurally unusable."""
    try:
        hourly = raw["hourly"]
        times = [_parse_time(t) for t in hourly["time"]]
        returned_units = raw.get("hourly_units", {})
        lat, lon = float(raw["latitude"]), float(raw["longitude"])
    except (KeyError, TypeError, ValueError) as exc:
        raise UpstreamError(f"Malformed Open-Meteo response ({type(exc).__name__})") from exc

    if raw.get("utc_offset_seconds", 0) != 0:
        raise UpstreamError("Open-Meteo returned non-UTC timestamps; refusing to guess the offset")
    if not times:
        raise UpstreamError("Open-Meteo returned no hourly timestamps")

    series: dict[str, list[float | None]] = {}
    unavailable: list[str] = []
    warnings: list[str] = []
    for key in wanted:
        values = hourly.get(key)
        if values is None:
            unavailable.append(key)
            warnings.append(f"{key}: not returned by the provider")
            continue
        if len(values) != len(times):
            unavailable.append(key)
            warnings.append(f"{key}: length does not match the timestamps")
            continue
        if returned_units.get(key) != units[key]:
            unavailable.append(key)
            warnings.append(f"{key}: unit '{returned_units.get(key)}' differs from expected '{units[key]}'")
            continue
        lo, hi = (VARIABLES[key][2], VARIABLES[key][3]) if key in VARIABLES else (-1e9, 1e9)
        clean: list[float | None] = []
        rejected = 0
        for v in values:
            if v is None or not isinstance(v, (int, float)):
                clean.append(None)
            elif lo <= v <= hi:
                clean.append(float(v))
            else:
                clean.append(None)
                rejected += 1
        if rejected:
            warnings.append(f"{key}: {rejected} value(s) outside the physically plausible range were discarded")
        if all(v is None for v in clean):
            unavailable.append(key)
            warnings.append(f"{key}: no values available")
            continue
        series[key] = clean

    latest = None
    current = raw.get("current") or {}
    if current.get("time"):
        try:
            latest = _parse_time(current["time"])
        except ValueError:
            warnings.append("current.time could not be parsed")

    return Normalized(
        location=LocationInfo(
            requested_lat=requested[0], requested_lon=requested[1],
            grid_lat=lat, grid_lon=lon, elevation_m=raw.get("elevation"),
        ),
        times=times, series=series, unavailable=unavailable, warnings=warnings,
        latest_source_time=latest, retrieved_at=retrieved_at,
    )


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


class WeatherService:
    def __init__(
        self,
        settings: Settings,
        client: OpenMeteoClient | None = None,
        now: Callable[[], datetime] = utc_now,
    ):
        self._settings = settings
        self._client = client or OpenMeteoClient(settings)
        self._now = now
        self._cache: dict[str, list[Normalized]] = {}

    # ---- cache -------------------------------------------------------------------------------
    async def _load(self, key: str, fetch: Callable[[datetime], "list[Normalized] | object"]) -> tuple[list[Normalized], bool]:
        """Returns (data, from_stale_cache). Fresh cache hit -> no request; failure -> last good data if any."""
        now = self._now()
        cached = self._cache.get(key)
        ttl = timedelta(seconds=self._settings.weather_cache_ttl_s)
        if cached and now - cached[0].retrieved_at < ttl:
            return cached, False
        try:
            data = await fetch(now)
        except UpstreamError as exc:
            if cached:
                logger.warning("Serving cached weather for %s after upstream failure: %s", key, exc)
                return cached, True
            raise
        if len(self._cache) >= 256:  # bound memory: drop the oldest entry
            self._cache.pop(min(self._cache, key=lambda k: self._cache[k][0].retrieved_at))
        self._cache[key] = data
        return data, False  # type: ignore[return-value]

    # ---- response assembly -------------------------------------------------------------------
    def _window(self, times: list[datetime], now: datetime) -> tuple[int, int]:
        start_at = _floor_hour(now)
        start = next((i for i, t in enumerate(times) if t >= start_at), None)
        if start is None:
            raise UpstreamError("Provider data does not cover the current time")
        return start, min(start + MAX_HOURS, len(times))

    def _source(self, first: Normalized, now: datetime, stale_cache: bool, extra_warnings: list[str]) -> SourceInfo:
        stale_after = timedelta(seconds=self._settings.weather_stale_after_s)
        old = first.latest_source_time is not None and now - first.latest_source_time > stale_after
        warnings = [*first.warnings, *extra_warnings]
        if first.latest_source_time is None:
            warnings.append("Provider did not report a source timestamp; freshness cannot be confirmed")
        if stale_cache:
            warnings.append("Provider request failed; showing the most recent successful response")
        return SourceInfo(
            attribution=ATTRIBUTION,
            retrieved_at=first.retrieved_at,
            cache_age_s=max(0, int((now - first.retrieved_at).total_seconds())),
            latest_source_time=first.latest_source_time,
            freshness="stale" if (old or stale_cache) else "fresh",
            served_from_cache_after_failure=stale_cache,
            warnings=warnings,
        )

    @staticmethod
    def _coverage(times: list[datetime]) -> Coverage:
        return Coverage(start=times[0], end=times[-1], hours=len(times), max_hours=MAX_HOURS)

    @staticmethod
    def _slice(series: dict[str, list[float | None]], lo: int, hi: int) -> tuple[dict, list[str]]:
        sliced, empty = {}, []
        for k, v in series.items():
            part = v[lo:hi]
            if all(x is None for x in part):
                empty.append(k)
            else:
                sliced[k] = part
        return sliced, empty

    @staticmethod
    def _variables(keys: list[str]) -> list[VariableInfo]:
        return [VariableInfo(key=k, label=VARIABLES[k][0], unit=VARIABLES[k][1]) for k in keys]

    # ---- public API --------------------------------------------------------------------------
    async def point(self, lat: float, lon: float) -> PointForecastResponse:
        lat, lon = round(lat, 2), round(lon, 2)
        keys = list(VARIABLES)
        units = {k: VARIABLES[k][1] for k in keys}

        async def fetch(now: datetime):
            raw = await self._client.get_forecast(self._params([(lat, lon)], keys))
            return [normalize(raw, keys, units, (lat, lon), now)]  # type: ignore[arg-type]

        (norm,), stale = await self._load(f"point:{lat}:{lon}", fetch)  # type: ignore[misc]
        now = self._now()
        lo, hi = self._window(norm.times, now)
        series, empty = self._slice(norm.series, lo, hi)
        unavailable = sorted({*norm.unavailable, *empty})
        times = norm.times[lo:hi]
        return PointForecastResponse(
            location=norm.location, times=times,
            variables=self._variables([k for k in keys if k in series]),
            series=series, unavailable=unavailable,
            coverage=self._coverage(times), source=self._source(norm, now, stale, []),
        )

    async def recent(self, lat: float, lon: float, hours: int) -> RecentWeatherResponse:
        """The `hours` hours ending at the current hour. Uses the same hourly grid as the air-quality history."""
        lat, lon = round(lat, 2), round(lon, 2)
        keys = list(VARIABLES)
        units = {k: VARIABLES[k][1] for k in keys}
        past_days = -(-hours // 24) + 1  # whole days covering the window

        async def fetch(now: datetime):
            params = {**self._params([(lat, lon)], keys), "past_days": past_days, "forecast_days": 1}
            raw = await self._client.get_forecast(params)
            return [normalize(raw, keys, units, (lat, lon), now)]  # type: ignore[arg-type]

        (norm,), stale = await self._load(f"recent:{lat}:{lon}:{past_days}", fetch)  # type: ignore[misc]
        now = self._now()
        end_at = _floor_hour(now)
        start_at = end_at - timedelta(hours=hours - 1)
        picked = [i for i, t in enumerate(norm.times) if start_at <= t <= end_at]
        if not picked:
            raise UpstreamError("Provider data does not cover the requested recent window")
        lo, hi = picked[0], picked[-1] + 1
        series, empty = self._slice(norm.series, lo, hi)
        times = norm.times[lo:hi]

        derived: dict[str, DerivedSeries] = {}
        blh, wind, rain = series.get("boundary_layer_height"), series.get("wind_speed_10m"), series.get("precipitation")
        if blh and wind:
            derived["ventilation_index"] = DerivedSeries(
                label="Ventilation index", unit="m²/s",
                definition="Boundary layer height × 10 m wind speed. A descriptive guide to how strongly near-surface air "
                           "is mixed and carried away; surface wind only approximates the wind through the mixed layer. "
                           "Derived arithmetic, not a measurement or a classification.",
                values=ventilation_index(blh, wind),
            )
        if rain:
            derived["hours_since_rain"] = DerivedSeries(
                label="Hours since rain", unit="h",
                definition="Hours since the last hour with at least 0.1 mm of precipitation, counted inside the window. "
                           "Blank when no rain has appeared in the window yet or a gap in the data hides whether it rained.",
                values=hours_since_rain(rain),  # type: ignore[arg-type]
            )
        return RecentWeatherResponse(
            location=norm.location, times=times, variables=self._variables([k for k in keys if k in series]),
            series=series, unavailable=sorted({*norm.unavailable, *empty}),
            coverage=Coverage(start=times[0], end=times[-1], hours=len(times), max_hours=hours),
            source=self._source(norm, now, stale, []), derived=derived,
        )

    async def grid(self) -> GridForecastResponse:
        points = grid_points()
        keys = GRID_VARIABLES
        units = {k: VARIABLES[k][1] for k in keys}

        async def fetch(now: datetime):
            raw = await self._client.get_forecast(self._params(points, keys))
            items = raw if isinstance(raw, list) else [raw]
            if len(items) != len(points):
                raise UpstreamError(f"Expected {len(points)} grid locations, received {len(items)}")
            return [normalize(item, keys, units, pt, now) for item, pt in zip(items, points)]

        norms, stale = await self._load("grid", fetch)
        now = self._now()
        times0 = norms[0].times
        if any(n.times != times0 for n in norms):
            raise UpstreamError("Grid locations returned differing timestamps")
        lo, hi = self._window(times0, now)
        times = times0[lo:hi]

        out_points, per_var_has = [], {k: False for k in keys}
        for n in norms:
            series, _ = self._slice(n.series, lo, hi)
            for k in series:
                per_var_has[k] = True
            out_points.append(GridPoint(location=n.location, series=series))
        unavailable = [k for k in keys if not per_var_has[k]]
        warnings = sorted({w for n in norms for w in n.warnings})
        src_norm = replace(norms[0], warnings=warnings)
        return GridForecastResponse(
            times=times,
            variables=self._variables([k for k in keys if per_var_has[k]]),
            points=out_points, unavailable=unavailable,
            coverage=self._coverage(times), source=self._source(src_norm, now, stale, []),
            note=(
                f"{len(points)} model grid cells sampled across Delhi-NCR. Values are the provider's forecast for "
                "each cell; nothing is interpolated between them. Coordinates are the model cell centres."
            ),
        )

    async def profile(self, lat: float, lon: float) -> ProfileResponse:
        lat, lon = round(lat, 2), round(lon, 2)

        async def fetch(now: datetime):
            raw = await self._client.get_forecast(self._params([(lat, lon)], PROFILE_VARIABLES))
            return [normalize(raw, PROFILE_VARIABLES, PROFILE_UNITS, (lat, lon), now)]  # type: ignore[arg-type]

        (norm,), stale = await self._load(f"profile:{lat}:{lon}", fetch)  # type: ignore[misc]
        now = self._now()
        lo, hi = self._window(norm.times, now)
        hours = build_profile_hours(norm.times, norm.series, norm.location.elevation_m, PROFILE_LEVELS, lo, hi)
        times = norm.times[lo:hi]
        return ProfileResponse(
            location=norm.location, hours=hours, coverage=self._coverage(times),
            source=self._source(norm, now, stale, []),
            note=(
                "Model-forecast temperatures on pressure levels, not balloon soundings. Only levels above the "
                "ground are used; levels below the surface are extrapolated by the model and are excluded. "
                "Four coarse levels can miss shallow near-surface inversions."
            ),
        )

    def _params(self, points: list[tuple[float, float]], keys: list[str]) -> dict:
        return {
            "latitude": ",".join(str(p[0]) for p in points),
            "longitude": ",".join(str(p[1]) for p in points),
            "hourly": ",".join(keys),
            "current": "temperature_2m",
            "timezone": "GMT",
            "forecast_days": FORECAST_DAYS,
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }

    async def probe(self) -> None:
        """Cheap reachability check used by the system status page."""
        await self._client.get_forecast(
            {"latitude": 28.61, "longitude": 77.21, "current": "temperature_2m", "timezone": "GMT"}
        )
