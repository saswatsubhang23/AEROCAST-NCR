import math
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.assistant import LocationId

Pollutant = Literal["pm25", "pm10", "no2", "so2", "co", "o3"]
Operator = Literal["gt", "gte"]
OPERATOR_TEXT = {"gt": ">", "gte": "≥"}
LABELS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "co": "CO", "o3": "O₃"}
UNITS = ["µg/m³", "mg/m³", "ppb", "ppm"]
MAX_RULES = 50

# The honest description of every threshold, shown with every alert.
THRESHOLD_NOTE = "A user-defined threshold. It is not an official health standard."


def unit_key(u: str) -> str:
    return u.lower().replace("µ", "u").replace("μ", "u").replace("³", "3").replace(" ", "")


def canonical_unit(u: str) -> str | None:
    return next((x for x in UNITS if unit_key(x) == unit_key(u)), None)


class AlertRuleCreate(BaseModel):
    location_id: LocationId
    pollutant: Pollutant
    operator: Operator = "gte"
    threshold: float = Field(gt=0, le=1_000_000)
    unit: str
    name: str | None = Field(None, max_length=80)

    @field_validator("threshold")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v):
            raise ValueError("threshold must be a finite number")
        return v

    @field_validator("unit")
    @classmethod
    def _unit(cls, v: str) -> str:
        c = canonical_unit(v)
        if c is None:
            raise ValueError(f"unit must be one of: {', '.join(UNITS)}")
        return c

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str | None) -> str | None:
        v = re.sub(r"\s+", " ", re.sub(r"[\x00-\x1f\x7f]+", " ", v or "")).strip()
        return v or None


class AlertRulePatch(BaseModel):
    enabled: bool


class AlertRule(BaseModel):
    id: int
    name: str
    location_id: LocationId
    location_name: str
    pollutant: Pollutant
    measurement: str  # display label, e.g. "PM2.5"
    operator: Operator
    threshold: float
    unit: str
    enabled: bool
    created_at: datetime


class Observation(BaseModel):
    value: float
    unit: str
    observed_at: datetime
    age_s: int
    station_id: int
    station: str
    provider: str | None
    distance_km: float


class AlertSource(BaseModel):
    provider: str
    url: str


AlertState = Literal["triggered", "not_triggered", "no_data", "stale", "unit_mismatch", "unavailable", "disabled"]


class AlertStatus(BaseModel):
    rule: AlertRule
    status: AlertState
    observation: Observation | None
    source: AlertSource
    message: str
    evaluated_at: datetime
    threshold_note: str = THRESHOLD_NOTE


class AlertsResponse(BaseModel):
    statuses: list[AlertStatus]
    source_available: bool
    source_message: str | None
    evaluated_at: datetime
    max_rules: int = MAX_RULES
    units: list[str] = UNITS
    note: str = (
        "Alerts compare the latest observed station readings with thresholds you define. No alert is a prediction, and "
        "no source used by AEROCAST provides its own alert conditions."
    )
