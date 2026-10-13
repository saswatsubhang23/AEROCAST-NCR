from functools import lru_cache

from fastapi import Depends

from app.api.air import get_air_service
from app.api.forecast import get_forecast_service
from app.api.knowledge import get_kb_service
from app.api.weather import get_weather_service
from app.forecast.provider import ForecastService
from app.kb.service import KnowledgeBaseService
from app.reports.builder import ReportService
from app.reports.export import ExportBuilder
from app.reports.store import ReportStore
from app.services.air_quality import AirQualityService
from app.services.weather import WeatherService


@lru_cache
def get_report_store() -> ReportStore:
    return ReportStore()


def get_report_service(
    weather: WeatherService = Depends(get_weather_service), air: AirQualityService = Depends(get_air_service),
    kb: KnowledgeBaseService = Depends(get_kb_service), forecast: ForecastService = Depends(get_forecast_service),
) -> ReportService:
    return ReportService(weather, air, kb, forecast)


@lru_cache
def _export_cache() -> dict:
    return {}


def get_export_builder(reports: ReportService = Depends(get_report_service)) -> ExportBuilder:
    from app.api.air import get_cams_service
    from app.api.models import model_status
    from app.api.routes import data_availability
    from app.api.weather import get_fields_service
    from app.core.config import get_settings

    air = reports._air  # the same air-quality service the report itself uses
    return ExportBuilder(reports, get_cams_service(), get_fields_service(), air, lambda: data_availability(get_settings()), model_status, cache=_export_cache())
