"""The contract between AEROCAST NCR and an external pollution-forecasting service.

AEROCAST contains NO forecasting model. This file only defines what a provider must send, and checks every response
against it before anything is shown. A response that breaks the contract is rejected, never repaired or filled in.

Conventions: all timestamps are timezone-aware ISO-8601 (UTC recommended); a forecast time is the *hour-ending* time;
concentrations are non-negative and carry their own unit string.

Contract version 2 adds, per pollutant, three optional blocks that say *what the number is about and how fresh its inputs were*:
`spatial` (a station, a point or a grid, and how far the requested place is from it), `freshness` (age of the newest input) and
`quality_flags` (machine-readable cautions). A response without them is still valid; a response that carries them is checked.
"""

import math
from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Pollutant = Literal["pm25", "pm10", "no2", "so2", "co", "o3"]
MAX_HORIZON_HOURS = 72
CLOCK_SKEW = timedelta(minutes=5)
CONTRACT_VERSION = "2"
FRESHNESS_STATUSES = ("fresh", "stale", "unknown")


def _aware(v: datetime) -> datetime:
    if v.tzinfo is None or v.utcoffset() is None:
        raise ValueError("timestamps must include a timezone offset (e.g. 2026-10-09T06:00:00Z)")
    return v


class ForecastLocation(BaseModel):
    id: str | None = Field(None, max_length=40, description="AEROCAST location id (e.g. 'delhi'), if known")
    name: str | None = Field(None, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class ForecastRequest(BaseModel):
    """Sent by AEROCAST to the provider (POST {ML_FORECAST_URL}/forecast)."""

    location: ForecastLocation
    # When AEROCAST asks for the forecast. A provider must base its forecast on data available at or before this time.
    issued_at: datetime
    horizon_hours: int = Field(ge=1, le=MAX_HORIZON_HOURS)
    pollutants: list[Pollutant] = Field(min_length=1, max_length=6)

    _tz = field_validator("issued_at")(lambda cls, v: _aware(v))

    @field_validator("pollutants")
    @classmethod
    def _unique(cls, v: list[str]) -> list[str]:
        if len(set(v)) != len(v):
            raise ValueError("pollutants must not repeat")
        return v


class PredictionInterval(BaseModel):
    """Optional uncertainty band. `level` is its coverage, e.g. 0.8 for an 80% interval."""

    level: float = Field(gt=0, lt=1)
    lower: list[float]
    upper: list[float]


class SpatialResolution(BaseModel):
    """What place a forecast describes. A forecast for one station is NOT a city-wide field, and says so here."""

    kind: Literal["station", "point", "grid"]
    station_id: str | None = Field(None, max_length=40)
    station_name: str | None = Field(None, max_length=120)
    lat: float | None = Field(None, ge=-90, le=90)
    lon: float | None = Field(None, ge=-180, le=180)
    distance_km: float | None = Field(None, ge=0, description="distance between the requested location and the place the forecast is for")
    resolution_km: float | None = Field(None, gt=0, description="grid spacing when kind is 'grid'; absent for a station or a point")

    @model_validator(mode="after")
    def _kind_matches_fields(self) -> "SpatialResolution":
        if self.kind == "grid" and self.resolution_km is None:
            raise ValueError("a grid forecast must state its resolution_km")
        if self.kind != "grid" and self.resolution_km is not None:
            raise ValueError("resolution_km applies only to a grid forecast")
        return self


class DataFreshness(BaseModel):
    """How old the newest input was when the forecast was made."""

    newest_input_at: datetime | None = None
    input_age_hours: float | None = Field(None, ge=0)
    max_age_hours: float | None = Field(None, gt=0, description="the age beyond which the provider refuses to forecast")
    status: Literal["fresh", "stale", "unknown"]

    @model_validator(mode="after")
    def _consistent(self) -> "DataFreshness":
        if self.newest_input_at is not None:
            _aware(self.newest_input_at)
        if self.status == "fresh":
            if self.input_age_hours is None:
                raise ValueError("a 'fresh' forecast must state input_age_hours")
            if self.max_age_hours is not None and self.input_age_hours > self.max_age_hours + 1e-9:
                raise ValueError("input_age_hours exceeds max_age_hours, so the status cannot be 'fresh'")
        return self


class PollutantForecast(BaseModel):
    pollutant: Pollutant
    unit: str = Field(min_length=1, max_length=20, description="e.g. 'µg/m³'; AEROCAST never converts units")
    times: list[datetime] = Field(min_length=1, description="hour-ending times, strictly increasing")
    values: list[float] = Field(min_length=1)
    intervals: list[PredictionInterval] = Field(default_factory=list, description="prediction intervals, when available")
    spatial: SpatialResolution | None = None
    freshness: DataFreshness | None = None
    quality_flags: list[str] = Field(default_factory=list, max_length=20, description="short machine-readable cautions, e.g. 'weak_horizon:+24h'")

    @model_validator(mode="after")
    def _consistent(self) -> "PollutantForecast":
        n = len(self.times)
        for t in self.times:
            _aware(t)
        if len(self.values) != n:
            raise ValueError(f"{self.pollutant}: times and values must have the same length")
        if any(b <= a for a, b in zip(self.times, self.times[1:])):
            raise ValueError(f"{self.pollutant}: times must be strictly increasing")
        if any(not math.isfinite(v) or v < 0 for v in self.values):
            raise ValueError(f"{self.pollutant}: values must be finite and non-negative")
        for iv in self.intervals:
            if len(iv.lower) != n or len(iv.upper) != n:
                raise ValueError(f"{self.pollutant}: interval bounds must match the number of times")
            for lo, v, hi in zip(iv.lower, self.values, iv.upper):
                if not (math.isfinite(lo) and math.isfinite(hi)) or lo < 0 or not (lo - 1e-9 <= v <= hi + 1e-9):
                    raise ValueError(f"{self.pollutant}: each interval must satisfy 0 <= lower <= value <= upper")
        return self


class Provenance(BaseModel):
    """Where the forecast came from, so it can be audited."""

    provider: str = Field(min_length=1, max_length=80)
    model_name: str | None = Field(None, max_length=80)
    generated_at: datetime
    input_data: list[str] = Field(min_length=1, description="the observations/weather inputs used, with their timestamps or sources")
    training_data: str | None = Field(None, max_length=500)
    notes: str | None = Field(None, max_length=1000)

    _tz = field_validator("generated_at")(lambda cls, v: _aware(v))


class ForecastResponse(BaseModel):
    """Returned by the provider. Validated in full before use."""

    contract_version: str | None = Field(None, max_length=10, description="'2' when the spatial/freshness/quality blocks are populated")
    model_version: str = Field(min_length=1, max_length=80)
    issued_at: datetime
    location: ForecastLocation
    horizon_hours: int = Field(ge=1, le=MAX_HORIZON_HOURS)
    forecasts: list[PollutantForecast] = Field(min_length=1, max_length=6)
    provenance: Provenance

    _tz = field_validator("issued_at")(lambda cls, v: _aware(v))

    @model_validator(mode="after")
    def _within_horizon(self) -> "ForecastResponse":
        names = [f.pollutant for f in self.forecasts]
        if len(set(names)) != len(names):
            raise ValueError("a pollutant may appear only once")
        end = self.issued_at + timedelta(hours=self.horizon_hours)
        for f in self.forecasts:
            if f.times[0] <= self.issued_at:
                raise ValueError(f"{f.pollutant}: a forecast must start after its issue time")
            if f.times[-1] > end:
                raise ValueError(f"{f.pollutant}: forecast times extend beyond the stated horizon")
        return self


class ForecastContractError(Exception):
    """The provider answered, but not in the agreed form (or not for what was asked)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def check_against_request(req: ForecastRequest, res: ForecastResponse, now: datetime) -> None:
    """Cross-checks that go beyond the response's own consistency: it must answer *this* request."""
    if res.issued_at > now + CLOCK_SKEW:
        raise ContractViolation("the forecast claims to be issued in the future")
    if res.provenance.generated_at > now + CLOCK_SKEW:
        raise ContractViolation("the provenance timestamp is in the future")
    if res.horizon_hours > req.horizon_hours:
        raise ContractViolation("the forecast horizon is longer than requested")
    if abs(res.location.lat - req.location.lat) > 0.5 or abs(res.location.lon - req.location.lon) > 0.5:
        raise ContractViolation("the forecast is for a different location than requested")
    extra = {f.pollutant for f in res.forecasts} - set(req.pollutants)
    if extra:
        raise ContractViolation(f"the forecast includes pollutants that were not requested: {', '.join(sorted(extra))}")
    for f in res.forecasts:
        if f.freshness and f.freshness.newest_input_at and f.freshness.newest_input_at > res.issued_at + CLOCK_SKEW:
            raise ContractViolation(f"{f.pollutant}: the newest input is dated after the forecast was issued")
        if f.spatial and f.spatial.kind == "station" and f.spatial.station_id is None:
            raise ContractViolation(f"{f.pollutant}: a station forecast must name its station")


def ContractViolation(message: str) -> ForecastContractError:  # noqa: N802 (reads like an exception class at call sites)
    return ForecastContractError(f"The forecast service's response breaks the contract: {message}.")


def contract_schemas() -> dict:
    return {"request": ForecastRequest.model_json_schema(), "response": ForecastResponse.model_json_schema()}
