from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from fastapi.responses import Response

from app.core.config import get_settings
from app.integrations.http import UpstreamAuthError, UpstreamBadRequest, UpstreamError
from app.integrations.openaq import AqNotConfigured
from app.schemas.air import AqiResult, HistoryResponse, Pollutant, StationsResponse
from app.services.air_quality import AirQualityService, AqUnknownStation
from app.services.model_air_quality import ModelAirQualityService

router = APIRouter(prefix="/air", tags=["air quality"])


@lru_cache
def get_air_service() -> AirQualityService:
    # One instance per process so station and observation caches are shared between requests.
    return AirQualityService(get_settings())


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, AqNotConfigured):
        return HTTPException(503, {"code": "not_configured", "message": "The air-quality source is not configured. Set AQ_API_KEY on the API server."})
    if isinstance(exc, UpstreamAuthError):
        return HTTPException(502, {"code": "upstream_auth", "message": "The air-quality provider rejected the configured API key."})
    if isinstance(exc, UpstreamBadRequest):
        return HTTPException(502, "The air-quality provider rejected our request.")
    if isinstance(exc, AqUnknownStation):
        return HTTPException(404, "Unknown station.")
    return HTTPException(503, "Air-quality data is temporarily unavailable. Please retry shortly.")


GUARDED = (UpstreamError, AqUnknownStation)


@lru_cache
def get_model_air_service() -> ModelAirQualityService:
    return ModelAirQualityService(get_settings())


@router.get("/model-forecast", summary="Modelled pollutant concentrations (Open-Meteo atmospheric model); not measurements")
async def model_forecast(
    lat: float = Query(ge=28.1, le=29.05, description="Latitude within Delhi-NCR"),
    lon: float = Query(ge=76.7, le=77.8, description="Longitude within Delhi-NCR"),
    past_hours: int = Query(24, ge=0, le=72),
    forecast_hours: int = Query(48, ge=1, le=120),
    svc: ModelAirQualityService = Depends(get_model_air_service),
):
    try:
        return await svc.forecast(lat, lon, past_hours, forecast_hours)
    except UpstreamError as exc:
        raise HTTPException(503, "Modelled air-quality data is temporarily unavailable. Please retry shortly.") from exc


@router.get("/stations", response_model=StationsResponse, summary="Monitoring stations with their latest readings")
async def stations(svc: AirQualityService = Depends(get_air_service)):
    try:
        return await svc.stations()
    except GUARDED as exc:
        raise _http_error(exc) from exc


@router.get("/history", response_model=HistoryResponse, summary="Hourly observations for one or more stations")
async def history(
    pollutant: Pollutant,
    station_ids: str = Query(alias="stations", description="Comma-separated station ids (1 to 6)"),
    hours: int = Query(72, ge=1, le=168),
    svc: AirQualityService = Depends(get_air_service),
):
    ids = _parse_ids(station_ids)
    try:
        return await svc.history(ids, pollutant, hours)
    except GUARDED as exc:
        raise _http_error(exc) from exc


@router.get("/stations/{station_id}/aqi", response_model=AqiResult, summary="CPCB-method AQI computed from hourly observations")
async def station_aqi(station_id: int, svc: AirQualityService = Depends(get_air_service)):
    try:
        return await svc.aqi(station_id)
    except GUARDED as exc:
        raise _http_error(exc) from exc


@router.get("/stations/{station_id}/export.csv", summary="Export a station's observed hourly values as CSV")
async def export_csv(
    station_id: int,
    pollutant: Pollutant,
    hours: int = Query(72, ge=1, le=168),
    svc: AirQualityService = Depends(get_air_service),
):
    try:
        body = await svc.history_csv(station_id, pollutant, hours)
    except GUARDED as exc:
        raise _http_error(exc) from exc
    return Response(
        body, media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="station-{station_id}-{pollutant}-{hours}h.csv"'},
    )


def _parse_ids(raw: str) -> list[int]:
    try:
        ids = [int(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(422, "stations must be comma-separated integers") from None
    if not 1 <= len(ids) <= 6:
        raise HTTPException(422, "Provide between 1 and 6 station ids")
    return list(dict.fromkeys(ids))


@lru_cache
def get_cams_service():
    from app.services.cams_fields import CamsFieldsService

    return CamsFieldsService(get_settings())


@router.get("/model-fields", summary="Modelled pollutant fields on a lattice over Delhi-NCR, hourly (CAMS via Open-Meteo); not measurements")
async def model_fields(
    past_hours: int = Query(12, ge=0, le=48),
    forecast_hours: int = Query(48, ge=1, le=96),
    svc=Depends(get_cams_service),
):
    try:
        return await svc.fields(past_hours, forecast_hours)
    except UpstreamError as exc:
        raise HTTPException(503, "Modelled air-quality data is temporarily unavailable. Please retry shortly.") from exc


class BatchCsvRequest(BaseModel):
    csv_text: str
    forecast_hours: int = Field(24, ge=1, le=72)
    batch_size: int = Field(100, ge=10, le=100, description="Chunk size per Open-Meteo multi-coordinate request (max 100)")
    api_key: str = Field("", description="Optional Open-Meteo API key for commercial/high-volume batches")
    start_date: str | None = Field(None, description="Optional start date/hour (e.g. 2026-10-12 or 2026-10-12T00:00)")
    end_date: str | None = Field(None, description="Optional end date/hour (e.g. 2026-10-13 or 2026-10-13T23:00)")
    force_refresh: bool = Field(False, description="Bypass local hourly cache and force re-fetching from Open-Meteo")


class BatchPdfExportRequest(BaseModel):
    summary: dict[str, Any]
    rows: list[dict[str, Any]]
    title: str = "Batch PM2.5 Coordinate Analysis Report"


@lru_cache
def get_batch_air_service():
    from app.services.batch_air_quality import BatchAirQualityService

    return BatchAirQualityService(get_settings())


@router.post("/batch-csv", summary="Upload CSV of coordinates and retrieve PM2.5 from Open-Meteo")
async def batch_csv_upload(
    file: UploadFile = File(...),
    forecast_hours: int = Query(24, ge=1, le=72),
    batch_size: int = Query(100, ge=10, le=100, description="Locations per request chunk (max 100 per Open-Meteo limit)"),
    api_key: str = Query("", description="Optional Open-Meteo API key"),
    start_date: str | None = Query(None, description="Optional start date/hour (e.g. 2026-10-12)"),
    end_date: str | None = Query(None, description="Optional end date/hour (e.g. 2026-10-13)"),
    force_refresh: bool = Query(False, description="Bypass local hourly cache and force re-fetching from Open-Meteo"),
    svc=Depends(get_batch_air_service),
):
    try:
        content = (await file.read()).decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(400, f"Could not read uploaded file: {exc}") from exc

    try:
        rows, fieldnames = svc.parse_csv_content(content)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err

    try:
        enriched_rows = await svc.fetch_pm25_for_batch(
            rows,
            forecast_hours=forecast_hours,
            batch_size=batch_size,
            api_key=api_key,
            start_date=start_date,
            end_date=end_date,
            force_refresh=force_refresh,
        )
    except UpstreamError as exc:
        raise HTTPException(502, f"Open-Meteo Air Quality API request failed: {exc}") from exc

    summary = svc.calculate_summary(enriched_rows)
    return {"summary": summary, "rows": enriched_rows, "fieldnames": fieldnames}


@router.post("/batch-text", summary="Post CSV text of coordinates and retrieve PM2.5 from Open-Meteo")
async def batch_csv_text(
    body: BatchCsvRequest,
    svc=Depends(get_batch_air_service),
):
    try:
        rows, fieldnames = svc.parse_csv_content(body.csv_text)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err

    try:
        enriched_rows = await svc.fetch_pm25_for_batch(
            rows,
            forecast_hours=body.forecast_hours,
            batch_size=body.batch_size,
            api_key=body.api_key,
            start_date=body.start_date,
            end_date=body.end_date,
            force_refresh=body.force_refresh,
        )
    except UpstreamError as exc:
        raise HTTPException(502, f"Open-Meteo Air Quality API request failed: {exc}") from exc

    summary = svc.calculate_summary(enriched_rows)
    return {"summary": summary, "rows": enriched_rows, "fieldnames": fieldnames}


@router.post("/batch-export-csv", summary="Export enriched CSV with PM2.5 data from Open-Meteo")
async def batch_csv_export(
    body: BatchCsvRequest,
    svc=Depends(get_batch_air_service),
):
    try:
        rows, fieldnames = svc.parse_csv_content(body.csv_text)
    except ValueError as err:
        raise HTTPException(400, str(err)) from err

    try:
        enriched_rows = await svc.fetch_pm25_for_batch(
            rows,
            forecast_hours=body.forecast_hours,
            batch_size=body.batch_size,
            api_key=body.api_key,
            start_date=body.start_date,
            end_date=body.end_date,
            force_refresh=body.force_refresh,
        )
    except UpstreamError as exc:
        raise HTTPException(502, f"Open-Meteo Air Quality API request failed: {exc}") from exc

    csv_output = svc.generate_enriched_csv(enriched_rows, fieldnames)
    return Response(
        content=csv_output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pm25_enriched_data.csv"},
    )


@router.post("/batch-export-pdf", summary="Export batch PM2.5 results as an executive PDF report")
async def batch_pdf_export(
    body: BatchPdfExportRequest,
    svc=Depends(get_batch_air_service),
):
    try:
        pdf_bytes = svc.generate_pdf_report(body.summary, body.rows, title=body.title)
    except Exception as exc:
        raise HTTPException(500, f"Failed to generate PDF report: {exc}") from exc

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=pm25_batch_analysis_report.pdf"},
    )

