"""Air-quality domain logic over OpenAQ: station inventory, latest readings, hourly history, comparison, AQI, CSV.

Nothing here invents data: a missing hour stays None, a missing sensor is reported as missing, units are carried
through exactly as the source reports them, and every response names its source and retrieval time.
"""

import asyncio
import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from app.core.config import Settings
from app.core.time import to_ist, utc_now
from app.integrations.http import UpstreamAuthError, UpstreamError
from app.integrations.openaq import AqNotConfigured, OpenAQClient
from app.schemas.air import (
    POLLUTANTS,
    AqiResult,
    AqSource,
    HistoryResponse,
    Reading,
    SeriesInfo,
    Station,
    StationsResponse,
)
from app.services.aqi import ASSUMPTIONS, Hourly, compute_aqi

logger = logging.getLogger("app.air")

AQ_BBOX = (76.7, 28.1, 77.8, 29.05)  # padded Delhi-NCR box (west, south, east, north)
INVENTORY_TTL = timedelta(hours=6)
AQI_LOOKBACK_HOURS = 30
SUPPORTED = set(POLLUTANTS)

LIMITATIONS = [
    "Data comes from OpenAQ, which redistributes what each provider publishes; which Delhi-NCR stations and "
    "pollutants exist depends on what providers share.",
    "Near-real-time data may be unvalidated and may later be revised by the provider.",
    "Concentrations are shown in each sensor's own reported unit; no conversion is applied except inside the AQI calculation.",
    "Hourly history uses OpenAQ's hourly aggregates, stamped with the hour-ending UTC time of each period. "
    "Latest values carry the timestamp the source assigned.",
    "OpenAQ's free tier allows 60 requests/minute and 2,000/hour, so the first load of all stations can take about a minute.",
]


class AqUnknownStation(Exception):
    pass


@dataclass
class Record:
    id: int
    name: str
    locality: str | None
    lat: float
    lon: float
    provider: str | None
    owner: str | None
    license: str | None
    is_monitor: bool
    sensors: dict[str, tuple[int, str]]  # pollutant -> (sensor id, unit)
    other_parameters: int
    last_observation: datetime | None


@dataclass
class LatestEntry:
    fetched_at: datetime
    status: str
    readings: dict[str, tuple[float, str, datetime]] = field(default_factory=dict)


def _dt(obj) -> datetime | None:
    try:
        raw = obj["utc"]
        d = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None


def _num(v) -> float | None:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    f = float(v)
    # Concentrations cannot be negative; the source occasionally reports calibration artefacts.
    return f if f >= 0 and f < 1e6 else None


def _floor_hour(d: datetime) -> datetime:
    return d.replace(minute=0, second=0, microsecond=0)


class AirQualityService:
    def __init__(self, settings: Settings, client: OpenAQClient | None = None, now: Callable[[], datetime] = utc_now):
        self._s = settings
        self._client = client or OpenAQClient(settings)
        self._now = now
        self._inventory: tuple[datetime, list[Record], list[str]] | None = None
        self._latest: dict[int, LatestEntry] = {}
        self._hours: dict[tuple[int, int], tuple[datetime, list[tuple[datetime, float | None, float | None]]]] = {}

    @property
    def configured(self) -> bool:
        return self._client.configured

    # ------------------------------------------------------------------ inventory ----------------------
    async def _records(self) -> tuple[list[Record], list[str], datetime]:
        now = self._now()
        if self._inventory and now - self._inventory[0] < INVENTORY_TTL:
            return self._inventory[1], self._inventory[2], self._inventory[0]
        try:
            raw = await self._client.locations(AQ_BBOX)
        except (AqNotConfigured, UpstreamAuthError):
            raise
        except UpstreamError:
            if self._inventory:
                at, records, warnings = self._inventory
                return records, [*warnings, "OpenAQ could not be reached; showing the last known station list."], at
            raise
        records, warnings = self._parse_locations(raw, now)
        self._inventory = (now, records, warnings)
        return records, warnings, now

    def _parse_locations(self, raw: list[dict], now: datetime) -> tuple[list[Record], list[str]]:
        records: list[Record] = []
        skipped = {"invalid_coordinates": 0, "mobile": 0, "inactive": 0, "no_supported_sensor": 0}
        for loc in raw:
            try:
                lat, lon = float(loc["coordinates"]["latitude"]), float(loc["coordinates"]["longitude"])
                station_id = int(loc["id"])
            except (KeyError, TypeError, ValueError):
                skipped["invalid_coordinates"] += 1
                continue
            if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (lat == 0 and lon == 0):
                skipped["invalid_coordinates"] += 1
                continue
            if loc.get("isMobile"):
                skipped["mobile"] += 1
                continue
            last = _dt(loc.get("datetimeLast"))
            if last is None or now - last > timedelta(days=self._s.aq_active_days):
                skipped["inactive"] += 1
                continue
            sensors: dict[str, tuple[int, str]] = {}
            others = 0
            for sensor in loc.get("sensors") or []:
                param = sensor.get("parameter") or {}
                name = param.get("name")
                if name in SUPPORTED:
                    sensors.setdefault(name, (int(sensor["id"]), param.get("units") or ""))
                else:
                    others += 1
            if not sensors:
                skipped["no_supported_sensor"] += 1
                continue
            records.append(Record(
                id=station_id, name=loc.get("name") or f"Station {station_id}", locality=loc.get("locality"),
                lat=lat, lon=lon, provider=(loc.get("provider") or {}).get("name"),
                owner=(loc.get("owner") or {}).get("name"), license=_license(loc.get("licenses")),
                is_monitor=bool(loc.get("isMonitor")), sensors=sensors, other_parameters=others,
                last_observation=last,
            ))
        records.sort(key=lambda r: r.name.lower())
        warnings = []
        if len(records) > self._s.aq_max_stations:
            warnings.append(f"Showing the first {self._s.aq_max_stations} of {len(records)} stations.")
            records = records[: self._s.aq_max_stations]
        labels = {
            "invalid_coordinates": "had missing or invalid coordinates",
            "mobile": "are mobile",
            "inactive": f"reported nothing in the last {self._s.aq_active_days} days",
            "no_supported_sensor": "have none of PM2.5, PM10, NO₂, SO₂, CO, O₃",
        }
        warnings += [f"{n} station(s) left out: they {labels[k]}." for k, n in skipped.items() if n]
        return records, warnings

    # ------------------------------------------------------------------ latest -------------------------
    async def _ensure_latest(self, r: Record, now: datetime) -> LatestEntry:
        cached = self._latest.get(r.id)
        ttl = timedelta(seconds=self._s.aq_cache_ttl_s if (cached and cached.status != "unavailable") else 60)
        if cached and now - cached.fetched_at < ttl:
            return cached
        try:
            rows = await self._client.latest(r.id)
        except (AqNotConfigured, UpstreamAuthError):
            raise
        except UpstreamError as exc:
            logger.warning("Latest readings for station %s unavailable: %s", r.id, exc)
            entry = LatestEntry(now, "unavailable")
            self._latest[r.id] = entry
            return entry
        by_sensor = {sid: (p, unit) for p, (sid, unit) in r.sensors.items()}
        readings: dict[str, tuple[float, str, datetime]] = {}
        for row in rows:
            sid = row.get("sensorsId")
            if sid not in by_sensor:
                continue
            value, when = _num(row.get("value")), _dt(row.get("datetime"))
            pollutant, unit = by_sensor[sid]
            if value is None or when is None:
                continue
            # OpenAQ reports each sensor's last value however old it is (some are years old); those are not "latest".
            if now - when > timedelta(days=self._s.aq_active_days):
                continue
            if pollutant not in readings or when > readings[pollutant][2]:
                readings[pollutant] = (value, unit, when)
        entry = LatestEntry(now, "ok" if readings else "none_reported", readings)
        self._latest[r.id] = entry
        return entry

    def _source(self, retrieved_at: datetime, now: datetime, records: list[Record] | None = None) -> AqSource:
        licences = sorted({r.license for r in (records or []) if r.license})
        return AqSource(
            provider="OpenAQ", url="https://openaq.org",
            attribution=("Data via OpenAQ. " + ("Licences: " + "; ".join(licences) + "." if licences else "See each provider's licence.")),
            retrieved_at=retrieved_at, cache_age_s=max(0, int((now - retrieved_at).total_seconds())),
            reference_only=self._s.aq_reference_only, limitations=LIMITATIONS,
        )

    async def stations(self) -> StationsResponse:
        records, warnings, inv_at = await self._records()
        now = self._now()
        entries = await asyncio.gather(*[self._ensure_latest(r, now) for r in records])
        out: list[Station] = []
        failed = 0
        stale_after = self._s.aq_stale_after_s
        for r, e in zip(records, entries):
            failed += e.status == "unavailable"
            latest = {
                p: Reading(
                    pollutant=p, value=v, unit=u, observed_at=t, age_s=max(0, int((now - t).total_seconds())),
                    stale=(now - t).total_seconds() > stale_after,
                )
                for p, (v, u, t) in e.readings.items()
            }
            out.append(Station(
                id=r.id, name=r.name, locality=r.locality, lat=r.lat, lon=r.lon, provider=r.provider, owner=r.owner,
                license=r.license, is_reference_monitor=r.is_monitor, pollutants={p: u for p, (_, u) in r.sensors.items()},
                other_parameters=r.other_parameters, last_observation=r.last_observation, latest=latest,
                latest_status=e.status,  # type: ignore[arg-type]
            ))
        if failed:
            warnings = [*warnings, f"Latest readings could not be loaded for {failed} station(s)."]
        return StationsResponse(stations=out, source=self._source(inv_at, now, records), warnings=warnings)

    # ------------------------------------------------------------------ hourly history -----------------
    async def _hourly(self, sensor_id: int, n_hours: int, now: datetime):
        key = (sensor_id, n_hours)
        cached = self._hours.get(key)
        if cached and now - cached[0] < timedelta(seconds=self._s.aq_cache_ttl_s):
            return cached[1]
        end = _floor_hour(now)
        rows = await self._client.hours(sensor_id, end - timedelta(hours=n_hours + 1), end + timedelta(hours=1))
        parsed: list[tuple[datetime, float | None, float | None]] = []
        for row in rows:
            stamp = _dt((row.get("period") or {}).get("datetimeTo"))
            if stamp is None:
                continue
            cov = row.get("coverage") or {}
            pct = cov.get("percentCoverage", cov.get("percentComplete"))
            parsed.append((_floor_hour(stamp), _num(row.get("value")), float(pct) if isinstance(pct, (int, float)) else None))
        self._hours[key] = (now, parsed)
        return parsed

    def _find(self, records: list[Record], station_id: int) -> Record:
        for r in records:
            if r.id == station_id:
                return r
        raise AqUnknownStation(station_id)

    async def history(self, station_ids: list[int], pollutant: str, hours: int) -> HistoryResponse:
        records, warnings, inv_at = await self._records()
        now = self._now()
        end = _floor_hour(now)
        grid = [end - timedelta(hours=hours - 1 - i) for i in range(hours)]
        index = {t: i for i, t in enumerate(grid)}
        targets = [self._find(records, sid) for sid in station_ids]

        async def one(r: Record) -> SeriesInfo:
            values: list[float | None] = [None] * hours
            coverage: list[float | None] = [None] * hours
            sensor = r.sensors.get(pollutant)
            if sensor:
                for stamp, value, pct in await self._hourly(sensor[0], hours, now):
                    if stamp in index and value is not None:
                        values[index[stamp]] = value
                        coverage[index[stamp]] = pct
            observed = sum(v is not None for v in values)
            return SeriesInfo(
                station_id=r.id, station_name=r.name, unit=sensor[1] if sensor else None, values=values,
                coverage_percent=coverage, observed_hours=observed, missing_hours=hours - observed,
            )

        series = await asyncio.gather(*[one(r) for r in targets])
        warns = list(warnings)
        warns += [f"{r.name} has no {pollutant} sensor." for r in targets if pollutant not in r.sensors]
        return HistoryResponse(pollutant=pollutant, times=grid, series=list(series), source=self._source(inv_at, now, targets), warnings=warns)  # type: ignore[arg-type]

    # ------------------------------------------------------------------ AQI ----------------------------
    async def aqi(self, station_id: int) -> AqiResult:
        records, _, inv_at = await self._records()
        r = self._find(records, station_id)
        now = self._now()

        async def one(p: str, sensor: tuple[int, str]):
            rows = await self._hourly(sensor[0], AQI_LOOKBACK_HOURS, now)
            return p, [Hourly(end, v) for end, v, _ in rows], sensor[1]

        fetched = await asyncio.gather(*[one(p, s) for p, s in r.sensors.items()])
        ends = [h.end for _, rows, _ in fetched for h in rows if h.value is not None and h.end <= now]
        label = "Computed by AEROCAST from hourly observations using the CPCB National AQI method. Not a value reported by CPCB."
        source = self._source(inv_at, now, [r])
        if not ends:
            return AqiResult(
                station_id=r.id, station_name=r.name, status="insufficient_data", aqi=None, category=None,
                lower_bound_only=False, dominant=None, as_of=None, stale=False, pollutants=[],
                reason=f"No hourly observations in the last {AQI_LOOKBACK_HOURS} hours.", label=label,
                assumptions=ASSUMPTIONS, source=source,
            )
        anchor = max(ends)
        result = compute_aqi({p: (rows, unit) for p, rows, unit in fetched}, anchor)
        return AqiResult(
            station_id=r.id, station_name=r.name, status=result.status,  # type: ignore[arg-type]
            aqi=result.aqi, category=result.category, lower_bound_only=result.lower_bound_only,
            dominant=result.dominant, as_of=anchor,  # type: ignore[arg-type]
            stale=(now - anchor).total_seconds() > self._s.aq_stale_after_s, reason=result.reason,
            pollutants=result.pollutants, label=label, assumptions=ASSUMPTIONS, source=source,
        )

    # ------------------------------------------------------------------ export -------------------------
    async def history_csv(self, station_id: int, pollutant: str, hours: int) -> str:
        data = await self.history([station_id], pollutant, hours)
        s = data.series[0]
        records, _, _ = await self._records()
        r = self._find(records, station_id)
        out = io.StringIO()
        w = csv.writer(out)
        w.writerow([
            "station_id", "station_name", "provider", "pollutant", "unit", "period_end_utc", "period_end_ist",
            "value", "coverage_percent", "source", "retrieved_at_utc",
        ])
        for t, v, c in zip(data.times, s.values, s.coverage_percent):
            if v is None:  # only actual observations are exported
                continue
            w.writerow([
                r.id, r.name, r.provider or "", pollutant, s.unit or "", t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                to_ist(t).strftime("%Y-%m-%dT%H:%M:%S+05:30"), v, "" if c is None else c,
                "OpenAQ", data.source.retrieved_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
            ])
        return out.getvalue()


def _license(value) -> str | None:
    items = value if isinstance(value, list) else [value] if value else []
    names = [i.get("name") for i in items if isinstance(i, dict) and i.get("name")]
    return "; ".join(names) or None
