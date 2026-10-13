"""The report as data. Every renderer (web page, Markdown, PDF, LLM summary check) works from this one structure, so a number
shown anywhere can be traced to a section here and, through `sources`, to where it came from."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

SectionStatus = Literal["ok", "unavailable"]


class ReportLocation(BaseModel):
    id: str
    name: str
    lat: float
    lon: float


class Period(BaseModel):
    start: datetime
    end: datetime
    hours: int


class SourceEntry(BaseModel):
    id: str
    kind: Literal["weather", "air_quality", "knowledge_base", "forecast", "report"]
    title: str
    provider: str
    url: str | None = None
    retrieved_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None
    note: str | None = None


class FreshnessItem(BaseModel):
    source_id: str | None
    label: str
    latest_data_time: datetime | None
    age_s: int | None
    status: Literal["fresh", "stale", "unavailable"]
    detail: str


class SeriesStats(BaseModel):
    unit: str | None
    latest: float | None
    latest_time: datetime | None
    min: float | None
    min_time: datetime | None
    max: float | None
    max_time: datetime | None
    mean: float | None
    observed_hours: int
    missing_hours: int


class Rise(BaseModel):
    rise: float
    pct: float | None
    from_value: float
    from_time: datetime
    to_value: float
    to_time: datetime
    span_hours: int


class Trend(BaseModel):
    first_mean: float
    last_mean: float
    change: float
    change_pct: float | None
    basis: str


class StationInfo(BaseModel):
    id: int
    name: str
    provider: str | None
    owner: str | None
    licence: str | None
    distance_km: float
    lat: float
    lon: float


class PollutantReading(BaseModel):
    pollutant: str
    label: str
    value: float
    unit: str
    observed_at: datetime
    age_s: int
    stale: bool


class AirSection(BaseModel):
    status: SectionStatus
    reason: str | None = None
    source_id: str | None = None
    pollutant: str
    label: str
    station: StationInfo | None = None
    stats: SeriesStats | None = None
    times: list[datetime] = Field(default_factory=list)
    values: list[float | None] = Field(default_factory=list)  # hourly; null = no observation that hour
    largest_rise: Rise | None = None
    trend: Trend | None = None
    latest_readings: list[PollutantReading] = Field(default_factory=list)


class WeatherVariable(BaseModel):
    key: str
    label: str
    unit: str
    latest: float | None
    min: float | None
    max: float | None
    mean: float | None


class WeatherSection(BaseModel):
    status: SectionStatus
    reason: str | None = None
    source_id: str | None = None
    grid_lat: float | None = None
    grid_lon: float | None = None
    elevation_m: float | None = None
    variables: list[WeatherVariable] = Field(default_factory=list)
    rain_total_mm: float | None = None
    rainy_hours: int | None = None
    times: list[datetime] = Field(default_factory=list)
    series: dict[str, list[float | None]] = Field(default_factory=dict)  # for charts
    unavailable_variables: list[str] = Field(default_factory=list)


class AtmosphereSection(BaseModel):
    status: SectionStatus
    reason: str | None = None
    ventilation_index_latest: float | None = None
    ventilation_index_mean: float | None = None
    hours_since_rain: int | None = None
    hours_since_rain_note: str | None = None
    definition: str = (
        "Descriptive indicators computed by simple arithmetic from weather-model values. They are not measurements, "
        "carry no thresholds or risk labels, and do not show whether a temperature inversion exists."
    )


class Coincident(BaseModel):
    label: str
    unit: str
    during: float
    period_mean: float | None
    relation: Literal["above", "below", "same", "unknown"]


class CoincidingSection(BaseModel):
    status: SectionStatus
    reason: str | None = None
    window_start: datetime | None = None
    window_end: datetime | None = None
    items: list[Coincident] = Field(default_factory=list)
    caution: str = "These are conditions that coincided in time with the rise. They do not show what caused it."


class Reference(BaseModel):
    source_id: str
    document_id: str | None
    title: str
    category: str
    publisher: str | None
    licence: str | None
    location: str
    excerpt: str
    relevance: float
    url: str | None


class ReferencesSection(BaseModel):
    status: Literal["ok", "none_found", "unavailable"]
    reason: str | None = None
    items: list[Reference] = Field(default_factory=list)


class ForecastSection(BaseModel):
    """Observations and forecasts are never mixed: this section is the external provider's output, or an explicit absence."""

    status: Literal["unavailable", "available", "error"]
    reason: str
    source_id: str | None = None
    provider: str | None = None
    model_version: str | None = None
    issued_at: datetime | None = None
    unit: str | None = None
    times: list[datetime] = Field(default_factory=list)
    values: list[float] = Field(default_factory=list)
    interval_level: float | None = None
    lower: list[float] = Field(default_factory=list)
    upper: list[float] = Field(default_factory=list)
    input_data: list[str] = Field(default_factory=list)


class LlmSummary(BaseModel):
    status: Literal["not_requested", "ok", "rejected", "unavailable"] = "not_requested"
    text: str | None = None
    model: str | None = None
    generated_at: datetime | None = None
    duration_ms: int | None = None
    reason: str | None = None
    label: str = (
        "Written by a local language model from the key facts above. Each number was checked to appear in the report, but the model "
        "can still attach a number to the wrong quantity or misdescribe a comparison. The key facts are authoritative."
    )


class Report(BaseModel):
    id: str
    created_at: datetime
    location: ReportLocation
    period: Period
    pollutant: str
    pollutant_label: str
    facts_summary: list[str]  # built by code; always present
    llm_summary: LlmSummary = Field(default_factory=LlmSummary)
    air: AirSection
    weather: WeatherSection
    atmosphere: AtmosphereSection
    coinciding: CoincidingSection
    references: ReferencesSection
    forecast: ForecastSection
    freshness: list[FreshnessItem]
    limitations: list[str]
    sources: list[SourceEntry]
    build_ms: int
