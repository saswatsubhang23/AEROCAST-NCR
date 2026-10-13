from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class LocationInfo(BaseModel):
    requested_lat: float
    requested_lon: float
    # Open-Meteo answers with the centre of the model grid cell that contains the request.
    grid_lat: float
    grid_lon: float
    elevation_m: float | None


class VariableInfo(BaseModel):
    key: str
    label: str
    unit: str


class Attribution(BaseModel):
    provider: str
    url: str
    license: str
    text: str


class Coverage(BaseModel):
    start: datetime
    end: datetime
    hours: int
    max_hours: int
    timezone: Literal["UTC"] = "UTC"


class SourceInfo(BaseModel):
    attribution: Attribution
    retrieved_at: datetime
    cache_age_s: int
    # Newest timestamp the provider reports for its own data (its "current" block).
    latest_source_time: datetime | None
    freshness: Literal["fresh", "stale"]
    # True when the provider failed and the last good response was served instead.
    served_from_cache_after_failure: bool
    warnings: list[str]


class PointForecastResponse(BaseModel):
    location: LocationInfo
    times: list[datetime]
    variables: list[VariableInfo]
    # null entries are values the provider did not supply; they are never replaced by zero.
    series: dict[str, list[float | None]]
    unavailable: list[str]
    coverage: Coverage
    source: SourceInfo


class GridPoint(BaseModel):
    location: LocationInfo
    series: dict[str, list[float | None]]


class GridForecastResponse(BaseModel):
    times: list[datetime]
    variables: list[VariableInfo]
    points: list[GridPoint]
    unavailable: list[str]
    coverage: Coverage
    source: SourceInfo
    note: str


class ProfilePoint(BaseModel):
    pressure_hpa: float | None  # null for the 2 m surface point
    height_agl_m: float
    temperature_c: float


class Inversion(BaseModel):
    base_agl_m: float
    top_agl_m: float
    strength_c: float


class ProfileHour(BaseModel):
    time: datetime
    points: list[ProfilePoint]
    inversions: list[Inversion]


class ProfileResponse(BaseModel):
    location: LocationInfo
    hours: list[ProfileHour]
    coverage: Coverage
    source: SourceInfo
    note: str


class DerivedSeries(BaseModel):
    """A value computed by arithmetic from model values; not a measurement."""

    label: str
    unit: str
    definition: str
    values: list[float | None]


class RecentWeatherResponse(PointForecastResponse):
    """The past N hours ending at the current hour (model analysis values), plus simple derived indicators."""

    derived: dict[str, DerivedSeries]
