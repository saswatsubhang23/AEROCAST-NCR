from datetime import datetime
from functools import lru_cache
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.places import PLACES
from app.core.time import utc_now
from app.forecast.contract import (
    ForecastContractError, ForecastLocation, ForecastRequest, ForecastResponse, Pollutant, contract_schemas,
)
from app.forecast.provider import ForecastNotConfigured, ForecastService, ForecastUnavailable
from app.schemas.assistant import LocationId

router = APIRouter(prefix="/forecast", tags=["forecast (optional external service)"])


@lru_cache
def get_forecast_service() -> ForecastService:
    return ForecastService(get_settings())


class ForecastStatus(BaseModel):
    configured: bool
    available: bool | None  # None when not configured
    provider: str | None
    message: str


class ForecastQuery(BaseModel):
    location_id: LocationId
    horizon_hours: int = Field(24, ge=1, le=72)
    pollutants: list[Pollutant] = Field(default_factory=lambda: ["pm25"], min_length=1, max_length=6)


class ForecastResult(BaseModel):
    """A validated provider forecast. Everything in `forecast` came from the external service, unchanged."""

    forecast: ForecastResponse
    provider: str
    received_at: datetime
    notice: str = "Produced by an external forecasting service, not by AEROCAST."


@router.get("/status", response_model=ForecastStatus, summary="Is a forecasting service connected?")
async def status(svc: ForecastService = Depends(get_forecast_service)):
    if not svc.configured:
        return ForecastStatus(configured=False, available=None, provider=None,
                              message=ForecastNotConfigured.message)
    try:
        await svc.health()
        return ForecastStatus(configured=True, available=True, provider=svc.provider_name, message="Connected.")
    except ForecastUnavailable as exc:
        return ForecastStatus(configured=True, available=False, provider=svc.provider_name, message=exc.message)


@router.get("/contract", summary="JSON Schema of the request and response a provider must implement")
async def contract() -> dict:
    return contract_schemas()


@router.post("", response_model=ForecastResult, summary="Request a forecast from the external service (503 when none is connected)")
async def forecast(query: ForecastQuery, svc: ForecastService = Depends(get_forecast_service)):
    name, lat, lon = PLACES[query.location_id]
    request = ForecastRequest(
        location=ForecastLocation(id=query.location_id, name=name, lat=lat, lon=lon), issued_at=utc_now(),
        horizon_hours=query.horizon_hours, pollutants=query.pollutants,
    )
    try:
        response = await svc.forecast(request)
    except ForecastNotConfigured as exc:
        raise HTTPException(503, {"code": "forecast_not_configured", "message": exc.message}) from exc
    except ForecastUnavailable as exc:
        raise HTTPException(503, {"code": "forecast_unavailable", "message": exc.message}) from exc
    except ForecastContractError as exc:
        raise HTTPException(502, {"code": "forecast_invalid_response", "message": exc.message}) from exc
    local = svc.provider_name == "local-model"
    notice = ("Produced by a model AEROCAST trained offline on historical data; not validated against live conditions." if local
              else "Produced by an external forecasting service, not by AEROCAST.")
    return ForecastResult(forecast=response, provider=svc.provider_name or "external service", received_at=utc_now(), notice=notice)
