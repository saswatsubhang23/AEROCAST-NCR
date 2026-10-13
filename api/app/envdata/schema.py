"""One typed record for every environmental number the application handles, whatever its source.

The point of the type is to make the things that went wrong in this project impossible to omit: every value says what KIND of number it is
(a measurement, a forecast, an analysis, an interpolation, a simulation), exactly which period it describes, when it was issued and
retrieved, where it is (a station point or a model cell, and how big the cell is), what unit it was in originally, which quality
flags apply, and where it came from and under what licence. An interpolated or simulated value can never be mistaken for a measurement,
because `kind` is part of the record and of its identity.

Time: `valid_from` / `valid_to` are timezone-aware UTC and bound the period the value describes (an hourly mean is [t, t + 1 h]).
`issued_at` is set for forecasts (when the model run was made) and is None for measurements. `retrieved_at` is when we fetched it.
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.history.units import MOLAR_MASS, MOLAR_VOLUME_L, RANGE_STD, to_standard, unit_key

RecordKind = Literal["observation", "forecast", "analysis", "interpolation", "simulation"]
SourceName = Literal[
    "openaq", "xkdr", "open_meteo_forecast", "open_meteo_archive", "open_meteo_air_quality", "aerocast_ml", "aerocast_idw", "aerocast_transport", "aerocast_coupled"
]
IST = timedelta(hours=5, minutes=30)

# canonical variable -> (unit, plausible range)
VARIABLES: dict[str, tuple[str, tuple[float, float]]] = {
    "pm25": ("µg/m³", RANGE_STD["pm25"]), "pm10": ("µg/m³", RANGE_STD["pm10"]), "no2": ("µg/m³", RANGE_STD["no2"]), "so2": ("µg/m³", RANGE_STD["so2"]),
    "co": ("µg/m³", RANGE_STD["co"]), "o3": ("µg/m³", RANGE_STD["o3"]), "no": ("µg/m³", (0.0, 3000.0)), "nox": ("µg/m³", (0.0, 5000.0)),
    "t2m": ("°C", (-60.0, 65.0)), "rh2m": ("%", (0.0, 100.0)), "pressure_msl": ("hPa", (850.0, 1100.0)), "wind_speed_10m": ("m/s", (0.0, 120.0)),
    "wind_dir_10m": ("°", (0.0, 360.0)), "precip": ("mm", (0.0, 500.0)), "cloud_cover": ("%", (0.0, 100.0)), "blh": ("m", (0.0, 10_000.0)),
    "shortwave": ("W/m²", (0.0, 1500.0)), "aod": ("1", (0.0, 10.0)), "dust": ("µg/m³", (0.0, 20_000.0)),
}
MOLAR_EXTRA = {"no": 30.006, "nox": 46.0055}  # NOx is reported "as NO2" by convention
OPENAQ_NAMES = {"pm25": "pm25", "pm10": "pm10", "no2": "no2", "so2": "so2", "co": "co", "o3": "o3", "no": "no", "nox": "nox", "temperature": "t2m",
                "relativehumidity": "rh2m", "wind_speed": "wind_speed_10m", "wind_direction": "wind_dir_10m"}
OPEN_METEO_VARS = {
    "pm2_5": "pm25", "pm10": "pm10", "nitrogen_dioxide": "no2", "sulphur_dioxide": "so2", "carbon_monoxide": "co", "ozone": "o3", "nitrogen_monoxide": "no",
    "aerosol_optical_depth": "aod", "dust": "dust", "temperature_2m": "t2m", "relative_humidity_2m": "rh2m", "pressure_msl": "pressure_msl",
    "wind_speed_10m": "wind_speed_10m", "wind_direction_10m": "wind_dir_10m", "precipitation": "precip", "cloud_cover": "cloud_cover",
    "boundary_layer_height": "blh", "shortwave_radiation": "shortwave",
}
LICENCES = {
    "openaq": ("Per data provider (see the location's licences); API terms require attribution", "OpenAQ"),
    "xkdr": ("Not stated by the provider; confirm before redistribution", "xKDR India air quality archive (CPCB CAAQM and US Embassy data)"),
    "open_meteo_forecast": ("CC BY 4.0 data; free API non-commercial", "Weather data by Open-Meteo.com"),
    "open_meteo_archive": ("CC BY 4.0 data; free API non-commercial", "Weather data by Open-Meteo.com (ERA5 / IFS reanalysis)"),
    "open_meteo_air_quality": ("CC BY 4.0 data; Copernicus CAMS, free with attribution; free API non-commercial", "Generated using Copernicus Atmosphere Monitoring Service information; Open-Meteo.com"),
    "aerocast_ml": ("Derived by this application", "AEROCAST NCR trained model"),
    "aerocast_idw": ("Derived by this application", "AEROCAST NCR inverse-distance interpolation"),
    "aerocast_transport": ("Derived by this application", "AEROCAST NCR passive transport simulation"),
    "aerocast_coupled": ("Derived by this application", "AEROCAST NCR coupled multi-species simulation"),
}


def _aware(t: datetime) -> datetime:
    if t.tzinfo is None or t.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware")
    return t.astimezone(timezone.utc)


class EnvRecord(BaseModel):
    kind: RecordKind
    source: SourceName
    variable: str
    value: float | None
    unit: str
    original_value: float | None = None
    original_unit: str | None = None
    valid_from: datetime
    valid_to: datetime
    issued_at: datetime | None = None
    retrieved_at: datetime
    location_id: str = Field(min_length=3, max_length=80)
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    support: Literal["point", "cell"] = "point"
    resolution_km: float | None = Field(None, gt=0)
    quality_flags: list[str] = Field(default_factory=list)
    usable: bool = True
    licence: str = ""
    attribution: str = ""

    @field_validator("valid_from", "valid_to", "issued_at", "retrieved_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else _aware(v)

    @model_validator(mode="after")
    def _consistent(self) -> "EnvRecord":
        if self.variable not in VARIABLES:
            raise ValueError(f"unknown variable {self.variable!r}")
        if self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be after valid_from")
        if self.kind == "forecast" and self.issued_at is None:
            raise ValueError("a forecast needs issued_at")
        if self.kind == "forecast" and self.issued_at and self.issued_at > self.valid_to:
            raise ValueError("a forecast cannot be issued after the period it describes")
        if self.kind == "observation" and self.issued_at is not None:
            raise ValueError("an observation has no issue time")
        if self.support == "cell" and self.resolution_km is None:
            raise ValueError("a cell value must state the cell size (resolution_km)")
        if self.value is not None:
            if not math.isfinite(self.value):
                raise ValueError("value must be finite or None")
            lo, hi = VARIABLES[self.variable][1]
            if not (lo <= self.value <= hi) and "OUT_OF_RANGE" not in self.quality_flags:
                raise ValueError(f"{self.variable}={self.value} is outside its plausible range but is not flagged OUT_OF_RANGE")
        if self.value is None and self.usable:
            raise ValueError("a record without a value cannot be usable")
        if self.unit != VARIABLES[self.variable][0]:
            raise ValueError(f"{self.variable} must be stored in {VARIABLES[self.variable][0]}, not {self.unit}")
        return self

    @property
    def record_id(self) -> str:
        """Identity: the same measurement or forecast fetched twice is one record. The kind is part of it, so an interpolated value never collides with a measured one."""
        key = "|".join([self.kind, self.source, self.variable, self.location_id, self.valid_from.isoformat(), self.valid_to.isoformat(),
                        self.issued_at.isoformat() if self.issued_at else "-"])
        return hashlib.sha1(key.encode()).hexdigest()


def _clean(variable: str, value: float | None, flags: list[str]) -> tuple[float | None, list[str], bool]:
    """Apply the plausibility range: out-of-range values are kept, flagged and marked unusable, never silently dropped or clipped."""
    if value is None or not math.isfinite(value):
        return None, sorted({*flags, "NULL_VALUE"}), False
    lo, hi = VARIABLES[variable][1]
    if not (lo <= value <= hi):
        return value, sorted({*flags, "OUT_OF_RANGE"}), False
    return value, sorted(set(flags)), True


def _to_ugm3(variable: str, value: float | None, unit: str | None) -> tuple[float | None, list[str]]:
    if variable in MOLAR_EXTRA and unit_key(unit) in ("ppb", "ppm"):
        ppb = None if value is None else value * (1000.0 if unit_key(unit) == "ppm" else 1.0)
        return (None if ppb is None else ppb * MOLAR_EXTRA[variable] / MOLAR_VOLUME_L), ["UNIT_CONVERTED"]
    if variable in MOLAR_MASS or variable in ("pm25", "pm10"):
        return to_standard(variable, value, unit)
    if unit_key(unit) == "ug/m3":
        return value, []
    return None, ["UNIT_UNKNOWN"]


def _convert(variable: str, value: float | None, unit: str | None) -> tuple[float | None, list[str]]:
    target = VARIABLES[variable][0]
    if target == "µg/m³":
        return _to_ugm3(variable, value, unit)
    u = (unit or "").lower().replace(" ", "")
    if variable == "t2m":
        if u in ("c", "°c", "celsius", "degc"):
            return value, []
        if u in ("f", "°f"):
            return (None if value is None else (value - 32) * 5 / 9), ["UNIT_CONVERTED"]
    if variable == "wind_speed_10m":
        if u in ("m/s", "ms"):
            return value, []
        if u in ("km/h", "kmh", "kph"):
            return (None if value is None else value / 3.6), ["UNIT_CONVERTED"]
    return (value, []) if u in (target.lower(), "") or target == "1" else (None, ["UNIT_UNKNOWN"])


def _make(kind: RecordKind, source: SourceName, variable: str, value: float | None, unit: str | None, t0: datetime, t1: datetime, retrieved: datetime, *,
          issued: datetime | None, loc: str, lat: float, lon: float, support: Literal["point", "cell"], res: float | None, flags: list[str]) -> EnvRecord:
    std, f2 = _convert(variable, value, unit)
    val, fl, ok = _clean(variable, std, [*flags, *f2])
    if "UNIT_UNKNOWN" in fl:
        ok = False
    lic, attr = LICENCES[source]
    return EnvRecord(kind=kind, source=source, variable=variable, value=val, unit=VARIABLES[variable][0], original_value=value, original_unit=unit,
                     valid_from=t0, valid_to=t1, issued_at=issued, retrieved_at=retrieved, location_id=loc, lat=lat, lon=lon, support=support, resolution_km=res,
                     quality_flags=fl, usable=ok, licence=lic, attribution=attr)


# ---------------------------------------------------------------------------------------------- normalisers
def from_openaq_hour(row: dict, *, station_id: int, lat: float, lon: float, retrieved_at: datetime, low_coverage_pct: float = 75.0) -> EnvRecord | None:
    """One row of GET /v3/sensors/{id}/hours. The period is OpenAQ's own (`datetimeFrom.utc`, `datetimeTo.utc`); nothing is re-labelled."""
    p = row.get("parameter") or {}
    var = OPENAQ_NAMES.get(str(p.get("name")))
    per = row.get("period") or {}
    t0, t1 = (per.get("datetimeFrom") or {}).get("utc"), (per.get("datetimeTo") or {}).get("utc")
    if var is None or not t0 or not t1:
        return None
    flags = []
    cov = (row.get("coverage") or {}).get("percentCoverage")
    if isinstance(cov, (int, float)) and cov < low_coverage_pct:
        flags.append("LOW_COVERAGE")
    if (row.get("flagInfo") or {}).get("hasFlags"):
        flags.append("PROVIDER_FLAGGED")
    v = row.get("value")
    return _make("observation", "openaq", var, float(v) if isinstance(v, (int, float)) else None, p.get("units"),
                 datetime.fromisoformat(t0.replace("Z", "+00:00")), datetime.fromisoformat(t1.replace("Z", "+00:00")), retrieved_at,
                 issued=None, loc=f"station:{station_id}", lat=lat, lon=lon, support="point", res=None, flags=flags)


def from_xkdr_row(row: dict, *, station_id: int, source: str, lat: float, lon: float, parameter: str, retrieved_at: datetime) -> EnvRecord | None:
    """One row of GET /v1/measurements (hourly). `period_start` is naive: IST for CPCB stations, UTC for the US Embassy (verified, see the ingest)."""
    from app.history.ingest_xkdr import UTC_NAIVE_SOURCES

    names = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "Ozone": "o3", "CO": "co"}
    var = names.get(parameter)
    start, mean = row.get("period_start"), row.get("mean")
    if var is None or not start:
        return None
    naive = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    t0 = naive if source in UTC_NAIVE_SOURCES else naive - IST
    return _make("observation", "xkdr", var, float(mean) if isinstance(mean, (int, float)) else None, row.get("unit"), t0, t0 + timedelta(hours=1), retrieved_at,
                 issued=None, loc=f"station:{station_id}", lat=lat, lon=lon, support="point", res=None, flags=[])


def from_open_meteo(body: dict, *, source: SourceName, kind: RecordKind, retrieved_at: datetime, issued_at: datetime | None, resolution_km: float,
                    cell_prefix: str) -> list[EnvRecord]:
    """An Open-Meteo `hourly` block (one location). Values are model output: `kind` is "forecast" (with its issue time), "analysis" for past
    hours of a reanalysis/analysis, never "observation". Open-Meteo labels an hourly value by the START of its hour for state variables and by
    the END for accumulations (precipitation, radiation); that is recorded in the period."""
    h = body.get("hourly") or {}
    units = body.get("hourly_units") or {}
    times = h.get("time") or []
    lat, lon = float(body["latitude"]), float(body["longitude"])
    loc = f"cell:{cell_prefix}:{lat:.3f},{lon:.3f}"
    out: list[EnvRecord] = []
    for key, var in OPEN_METEO_VARS.items():
        vals = h.get(key)
        if not isinstance(vals, list):
            continue
        accum = key in ("precipitation", "shortwave_radiation")
        for ts, v in zip(times, vals):
            t = datetime.fromisoformat(ts + ("+00:00" if len(ts) == 16 or "+" not in ts else "")).astimezone(timezone.utc)
            t0, t1 = (t - timedelta(hours=1), t) if accum else (t, t + timedelta(hours=1))
            rec_kind = kind
            if kind == "forecast" and issued_at is not None and t1 <= issued_at:
                rec_kind = "analysis"  # a past hour of a forecast response is the model's analysis, not a forecast
            out.append(_make(rec_kind, source, var, float(v) if isinstance(v, (int, float)) else None, str(units.get(key, "")).replace("μ", "µ"), t0, t1, retrieved_at,
                             issued=issued_at if rec_kind == "forecast" else None, loc=loc, lat=lat, lon=lon, support="cell", res=resolution_km, flags=[]))
    return out


# ---------------------------------------------------------------------------------------------- store (SQLite for development; PostGIS DDL in ddl.py)
SQLITE_DDL = """
create table if not exists env_record (
  record_id text primary key, kind text not null, source text not null, variable text not null, value real, unit text not null,
  original_value real, original_unit text, valid_from text not null, valid_to text not null, issued_at text, retrieved_at text not null,
  location_id text not null, lat real not null, lon real not null, support text not null, resolution_km real,
  quality_flags text not null, usable integer not null, licence text, attribution text
);
create index if not exists ix_env_var_time on env_record(variable, valid_to);
create index if not exists ix_env_loc on env_record(location_id, variable, valid_to);
create index if not exists ix_env_kind on env_record(kind, source);
"""


class EnvStore:
    def __init__(self, path: str = ":memory:"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SQLITE_DDL)

    def upsert(self, records: list[EnvRecord]) -> int:
        """Insert or replace by identity. A later fetch of the same hour replaces the earlier one (`retrieved_at` shows which)."""
        rows = [(r.record_id, r.kind, r.source, r.variable, r.value, r.unit, r.original_value, r.original_unit, r.valid_from.isoformat(), r.valid_to.isoformat(),
                 r.issued_at.isoformat() if r.issued_at else None, r.retrieved_at.isoformat(), r.location_id, r.lat, r.lon, r.support, r.resolution_km,
                 ",".join(r.quality_flags), int(r.usable), r.licence, r.attribution) for r in records]
        self.db.executemany("insert or replace into env_record values (" + ",".join("?" * 21) + ")", rows)
        self.db.commit()
        return len(rows)

    def query(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        return self.db.execute(sql, args).fetchall()
