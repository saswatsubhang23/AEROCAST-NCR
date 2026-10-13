from datetime import datetime
from typing import Literal

from pydantic import BaseModel

Pollutant = Literal["pm25", "pm10", "no2", "so2", "co", "o3"]
POLLUTANTS: tuple[str, ...] = ("pm25", "pm10", "no2", "so2", "co", "o3")


class AqSource(BaseModel):
    provider: str
    url: str
    attribution: str
    retrieved_at: datetime
    cache_age_s: int
    reference_only: bool
    limitations: list[str]


class Reading(BaseModel):
    """A concentration as reported by the source, in the source's own unit. Not an AQI."""

    pollutant: Pollutant
    value: float
    unit: str
    observed_at: datetime
    age_s: int
    stale: bool


class Station(BaseModel):
    id: int
    name: str
    locality: str | None
    lat: float
    lon: float
    provider: str | None
    owner: str | None
    license: str | None
    is_reference_monitor: bool
    # Supported pollutants this station has a sensor for, with each sensor's unit.
    pollutants: dict[str, str]
    other_parameters: int
    last_observation: datetime | None
    latest: dict[str, Reading]
    # Why `latest` may be empty for a station that should have data.
    latest_status: Literal["ok", "none_reported", "unavailable"]


class StationsResponse(BaseModel):
    stations: list[Station]
    source: AqSource
    warnings: list[str]


class SeriesInfo(BaseModel):
    station_id: int
    station_name: str
    unit: str | None
    # One value per hour on the shared grid; null = the source has no value for that hour.
    values: list[float | None]
    coverage_percent: list[float | None]
    observed_hours: int
    missing_hours: int


class HistoryResponse(BaseModel):
    pollutant: Pollutant
    # Hour-ending timestamps (UTC) of the shared grid, oldest first.
    times: list[datetime]
    series: list[SeriesInfo]
    source: AqSource
    warnings: list[str]


class AqiPollutant(BaseModel):
    pollutant: Pollutant
    used: bool
    reason: str | None
    averaging: Literal["24h", "8h"]
    average: float | None
    unit: str | None
    valid_hours: int
    sub_index: int | None
    category: str | None
    lower_bound_only: bool = False
    note: str | None = None


class AqiResult(BaseModel):
    station_id: int
    station_name: str
    status: Literal["available", "insufficient_data"]
    aqi: int | None
    category: str | None
    lower_bound_only: bool
    dominant: Pollutant | None
    as_of: datetime | None
    stale: bool
    reason: str | None
    pollutants: list[AqiPollutant]
    label: str
    assumptions: list[str]
    source: AqSource
