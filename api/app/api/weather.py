from functools import lru_cache

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.config import get_settings
from app.integrations.openmeteo import UpstreamBadRequest, UpstreamError
from app.schemas.weather import GridForecastResponse, PointForecastResponse, ProfileResponse, RecentWeatherResponse
from app.services.weather import WeatherService
from app.services.weather_fields import WeatherFieldsService

router = APIRouter(prefix="/weather", tags=["weather"])

# Padded Delhi-NCR box: requests outside it are rejected rather than silently forwarded.
LAT = Query(ge=28.1, le=29.05, description="Latitude within Delhi-NCR (28.1 to 29.05)")
LON = Query(ge=76.7, le=77.8, description="Longitude within Delhi-NCR (76.7 to 77.8)")


@lru_cache
def get_weather_service() -> WeatherService:
    # One instance per process so the response cache is shared between requests.
    return WeatherService(get_settings())


def _upstream_http_error(exc: UpstreamError) -> HTTPException:
    if isinstance(exc, UpstreamBadRequest):
        return HTTPException(502, "The weather provider rejected our request.")
    return HTTPException(503, "Weather data is temporarily unavailable. Please retry shortly.")


@router.get("/point", response_model=PointForecastResponse, summary="Hourly forecast for one location")
async def weather_point(lat: float = LAT, lon: float = LON, svc: WeatherService = Depends(get_weather_service)):
    try:
        return await svc.point(lat, lon)
    except UpstreamError as exc:
        raise _upstream_http_error(exc) from exc


@router.get("/grid", response_model=GridForecastResponse, summary="Hourly forecast on a Delhi-NCR sample grid")
async def weather_grid(svc: WeatherService = Depends(get_weather_service)):
    try:
        return await svc.grid()
    except UpstreamError as exc:
        raise _upstream_http_error(exc) from exc


@router.get("/profile", response_model=ProfileResponse, summary="Model vertical temperature profile")
async def weather_profile(lat: float = LAT, lon: float = LON, svc: WeatherService = Depends(get_weather_service)):
    try:
        return await svc.profile(lat, lon)
    except UpstreamError as exc:
        raise _upstream_http_error(exc) from exc


@router.get("/recent", response_model=RecentWeatherResponse, summary="Past hours of weather-model values plus simple derived indicators")
async def weather_recent(
    lat: float = LAT,
    lon: float = LON,
    hours: int = Query(72, ge=1, le=168),
    svc: WeatherService = Depends(get_weather_service),
):
    try:
        return await svc.recent(lat, lon, hours)
    except UpstreamError as exc:
        raise _upstream_http_error(exc) from exc


@lru_cache
def get_fields_service() -> WeatherFieldsService:
    return WeatherFieldsService(get_settings())


@router.get("/fields", summary="Gridded atmospheric fields over Delhi-NCR for map layers (model output, hourly)")
async def weather_fields(
    mode: str = Query("forecast", pattern="^(forecast|historical)$"),
    past_days: int = Query(2, ge=0, le=7),
    forecast_days: int = Query(3, ge=1, le=7),
    start: date | None = Query(None, description="historical mode: first day (UTC)"),
    end: date | None = Query(None, description="historical mode: last day (UTC), before today"),
    levels: bool = Query(False, description="also return model winds at 80, 120, 180 m and on the 925, 850 and 700 hPa levels (a larger response)"),
    svc: WeatherFieldsService = Depends(get_fields_service),
):
    try:
        return await svc.fields(mode, past_days, forecast_days, start, end, levels)
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_window", "message": str(exc)}) from exc
    except UpstreamError as exc:
        raise _upstream_http_error(exc) from exc
