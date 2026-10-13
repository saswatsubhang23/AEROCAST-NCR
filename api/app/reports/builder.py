"""Builds a Report from the real backend services. Nothing here is generated or estimated: every value is read from a
service response, every missing piece is recorded as a limitation, and every source is listed with where and when it was
retrieved."""

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta

from app.assistant.kb import KnowledgeBase
from app.core.places import PLACES, POLLUTANT_LABELS, STATION_RADIUS_KM, distance_km
from app.core.time import utc_now
from app.forecast.contract import ForecastContractError, ForecastLocation, ForecastRequest
from app.forecast.provider import ForecastNotConfigured, ForecastService, ForecastUnavailable
from app.integrations.http import UpstreamAuthError, UpstreamError
from app.integrations.openaq import AqNotConfigured
from app.reports import analysis
from app.reports.facts import facts_summary
from app.reports.models import (
    AirSection, AtmosphereSection, Coincident, CoincidingSection, ForecastSection, FreshnessItem, Period, PollutantReading,
    Reference, ReferencesSection, Report, ReportLocation, SourceEntry, StationInfo, WeatherSection, WeatherVariable,
)
from app.schemas.air import Station
from app.schemas.weather import RecentWeatherResponse
from app.services.air_quality import AirQualityService
from app.services.weather import WeatherService

logger = logging.getLogger("app.reports")

WEATHER_VARS = [
    ("temperature_2m", "Temperature"), ("relative_humidity_2m", "Relative humidity"), ("dew_point_2m", "Dew point"),
    ("wind_speed_10m", "Wind speed"), ("surface_pressure", "Surface pressure"), ("cloud_cover", "Cloud cover"),
    ("boundary_layer_height", "Boundary layer height"),
]
COINCIDING = [("wind_speed_10m", "Wind speed"), ("boundary_layer_height", "Boundary layer height"),
              ("temperature_2m", "Temperature"), ("relative_humidity_2m", "Relative humidity")]
CHART_SERIES = ["temperature_2m", "relative_humidity_2m", "wind_speed_10m", "boundary_layer_height", "precipitation"]


class ReportService:
    def __init__(self, weather: WeatherService, air: AirQualityService, kb: KnowledgeBase, forecast: ForecastService, now=utc_now):
        self._weather, self._air, self._kb, self._forecast, self._now = weather, air, kb, forecast, now

    async def build(self, location_id: str, hours: int, pollutant: str) -> Report:
        started = time.perf_counter()
        name, lat, lon = PLACES[location_id]
        label = POLLUTANT_LABELS[pollutant]
        now = self._now()

        (weather, w_raw, w_src), (air, a_src, a_unit), (forecast, f_src) = await asyncio.gather(
            self._build_weather(lat, lon, hours), self._build_air(name, lat, lon, hours, pollutant, label),
            self._build_forecast(location_id, name, lat, lon, pollutant),
        )
        references, k_srcs = await self._build_references(label)

        sources: list[SourceEntry] = []

        def register(prefix: str, src: SourceEntry | None, n: int = 1) -> str | None:
            if src is None:
                return None
            src.id = f"{prefix}{n}"
            sources.append(src)
            return src.id

        weather.source_id = register("W", w_src)
        air.source_id = register("A", a_src)
        for i, (ref, src) in enumerate(zip(references.items, k_srcs), start=1):
            ref.source_id = register("K", src, i) or ""
        forecast.source_id = register("F", f_src)

        atmosphere = self._atmosphere(w_raw)
        coinciding = self._coinciding(air, w_raw)
        period = self._period(w_raw, air, now, hours)
        freshness = self._freshness(weather, air, w_raw, now)
        limitations = self._limitations(weather, air, references, forecast, freshness, label)

        report = Report(
            id=uuid.uuid4().hex[:12], created_at=now, location=ReportLocation(id=location_id, name=name, lat=lat, lon=lon),
            period=period, pollutant=pollutant, pollutant_label=label, facts_summary=[], air=air, weather=weather,
            atmosphere=atmosphere, coinciding=coinciding, references=references, forecast=forecast, freshness=freshness,
            limitations=limitations, sources=sources, build_ms=0,
        )
        report.facts_summary = facts_summary(report)
        report.build_ms = round((time.perf_counter() - started) * 1000)
        return report

    # ---- weather -------------------------------------------------------------------------------------
    async def _build_weather(self, lat: float, lon: float, hours: int):
        try:
            r = await self._weather.recent(lat, lon, hours)
        except UpstreamError:
            return WeatherSection(status="unavailable", reason="The weather provider could not be reached."), None, None
        variables = []
        for key, label in WEATHER_VARS:
            vals = r.series.get(key)
            unit = next((v.unit for v in r.variables if v.key == key), "")
            if vals is None:
                continue
            st = analysis.stats(r.times, vals, unit)
            variables.append(WeatherVariable(key=key, label=label, unit=unit, latest=st.latest, min=st.min, max=st.max, mean=st.mean))
        rain = [v for v in (r.series.get("precipitation") or []) if v is not None]
        section = WeatherSection(
            status="ok", grid_lat=r.location.grid_lat, grid_lon=r.location.grid_lon, elevation_m=r.location.elevation_m,
            variables=variables, rain_total_mm=sum(rain) if rain else None, rainy_hours=sum(x >= 0.1 for x in rain) if rain else None,
            times=r.times, series={k: r.series[k] for k in CHART_SERIES if k in r.series}, unavailable_variables=r.unavailable,
        )
        src = SourceEntry(id="", kind="weather", title=f"Weather-model values, past {len(r.times)} h", provider="Open-Meteo",
                          url=r.source.attribution.url, retrieved_at=r.source.retrieved_at, period_start=r.times[0], period_end=r.times[-1],
                          note="Model analysis for the grid cell containing the location; not a station measurement.")
        return section, r, src

    # ---- air quality ---------------------------------------------------------------------------------
    async def _build_air(self, name: str, lat: float, lon: float, hours: int, pollutant: str, label: str):
        def unavailable(reason: str):
            return AirSection(status="unavailable", reason=reason, pollutant=pollutant, label=label), None, None

        try:
            listing = await self._air.stations()
            near = sorted(((distance_km(lat, lon, s.lat, s.lon), s) for s in listing.stations if pollutant in s.pollutants), key=lambda x: x[0])
            near = [x for x in near if x[0] <= STATION_RADIUS_KM][:3]
            if not near:
                return unavailable(f"No station within {STATION_RADIUS_KM:.0f} km of {name} reports {label}.")
            histories = await asyncio.gather(*[self._air.history([s.id], pollutant, hours) for _, s in near])
        except AqNotConfigured:
            return unavailable("The air-quality source is not configured (no API key), so there are no observations.")
        except UpstreamAuthError:
            return unavailable("The air-quality provider rejected the configured API key.")
        except UpstreamError:
            return unavailable("The air-quality source could not be reached.")

        best = max(zip(near, histories), key=lambda x: x[1].series[0].observed_hours)
        (dist, station), hist = best
        series = hist.series[0]
        if series.observed_hours == 0:
            return unavailable(f"No station within {STATION_RADIUS_KM:.0f} km of {name} reported {label} during this period.")
        st = analysis.stats(hist.times, series.values, series.unit)
        readings = [
            PollutantReading(pollutant=p, label=POLLUTANT_LABELS[p], value=r.value, unit=r.unit, observed_at=r.observed_at,
                             age_s=r.age_s, stale=r.stale)
            for p, r in sorted(station.latest.items())
        ]
        section = AirSection(
            status="ok", pollutant=pollutant, label=label, station=self._station(dist, station), stats=st, times=hist.times,
            values=series.values, largest_rise=analysis.largest_rise(hist.times, series.values), trend=analysis.trend(series.values),
            latest_readings=readings,
        )
        src = SourceEntry(id="", kind="air_quality", title=f"{label} at {station.name}", provider="OpenAQ", url=listing.source.url,
                          retrieved_at=listing.source.retrieved_at, period_start=hist.times[0], period_end=hist.times[-1],
                          note="Hourly station observations in the sensor's own unit; unvalidated near-real-time data.")
        return section, src, series.unit

    @staticmethod
    def _station(dist: float, s: Station) -> StationInfo:
        return StationInfo(id=s.id, name=s.name, provider=s.provider, owner=s.owner, licence=s.license, distance_km=round(dist, 1),
                           lat=s.lat, lon=s.lon)

    # ---- references from the knowledge base ----------------------------------------------------------
    async def _build_references(self, label: str):
        if not getattr(self._kb, "ready", False):
            return ReferencesSection(status="none_found", reason="The knowledge base has no searchable documents, so no references are cited."), []
        res = await self._kb.search(f"{label} health effects and air quality guidance", 3)
        if res.status == "unavailable":
            return ReferencesSection(status="unavailable", reason=res.reason), []
        if res.status != "ok" or not res.passages:
            return ReferencesSection(status="none_found", reason=res.reason or "No relevant passages were found."), []
        items, srcs = [], []
        now = self._now()
        for p in res.passages:
            items.append(Reference(source_id="", document_id=p.document_id, title=p.document, category=p.category_label, publisher=p.publisher or None,
                                   licence=p.licence or None, location=p.location, excerpt=" ".join(p.text.split())[:400], relevance=round(p.score, 2), url=p.url))
            srcs.append(SourceEntry(id="", kind="knowledge_base", title=p.document, provider=p.publisher or "Uploaded document", url=p.url,
                                    retrieved_at=now, note=f"{p.category_label}, {p.location}".strip(", ")))
        return ReferencesSection(status="ok", items=items), srcs

    # ---- optional external forecast -----------------------------------------------------------------
    async def _build_forecast(self, location_id: str, name: str, lat: float, lon: float, pollutant: str):
        if not self._forecast.configured:
            return ForecastSection(status="unavailable", reason=ForecastNotConfigured.message), None
        request = ForecastRequest(location=ForecastLocation(id=location_id, name=name, lat=lat, lon=lon), issued_at=self._now(),
                                  horizon_hours=24, pollutants=[pollutant])  # type: ignore[list-item]
        try:
            res = await self._forecast.forecast(request)
        except (ForecastUnavailable, ForecastContractError) as exc:
            return ForecastSection(status="error", reason=exc.message, provider=self._forecast.provider_name), None
        f = next((x for x in res.forecasts if x.pollutant == pollutant), None)
        if f is None:
            return ForecastSection(status="error", reason="The forecasting service returned nothing for this pollutant."), None
        iv = f.intervals[0] if f.intervals else None
        src = SourceEntry(id="", kind="forecast", title=f"{POLLUTANT_LABELS[pollutant]} forecast, model {res.model_version}",
                          provider=res.provenance.provider, retrieved_at=self._now(), period_start=f.times[0], period_end=f.times[-1],
                          note="Produced by an external forecasting service, not by AEROCAST.")
        return ForecastSection(
            status="available", reason="Produced by an external forecasting service, not by AEROCAST.", provider=res.provenance.provider,
            model_version=res.model_version, issued_at=res.issued_at, unit=f.unit, times=f.times, values=f.values,
            interval_level=iv.level if iv else None, lower=iv.lower if iv else [], upper=iv.upper if iv else [],
            input_data=res.provenance.input_data,
        ), src

    # ---- derived sections ----------------------------------------------------------------------------
    @staticmethod
    def _atmosphere(w: RecentWeatherResponse | None) -> AtmosphereSection:
        if w is None:
            return AtmosphereSection(status="unavailable", reason="Weather data is unavailable.")
        vi = w.derived.get("ventilation_index")
        hsr = w.derived.get("hours_since_rain")
        vi_vals = [v for v in (vi.values if vi else []) if v is not None]
        hsr_latest = next((v for v in reversed(hsr.values) if v is not None), None) if hsr else None
        return AtmosphereSection(
            status="ok", ventilation_index_latest=vi_vals[-1] if vi_vals else None,
            ventilation_index_mean=sum(vi_vals) / len(vi_vals) if vi_vals else None,
            hours_since_rain=int(hsr_latest) if hsr_latest is not None else None,
            hours_since_rain_note=None if hsr_latest is not None else "Unknown: no rain appeared in this period, or a data gap hides it. This does not mean it has not rained earlier.",
        )

    @staticmethod
    def _coinciding(air: AirSection, w: RecentWeatherResponse | None) -> CoincidingSection:
        rise = air.largest_rise
        if w is None or rise is None:
            return CoincidingSection(status="unavailable", reason="Needs both a rise in the observations and weather data.")
        items: list[Coincident] = []
        for key, label in COINCIDING:
            vals = w.series.get(key)
            if not vals:
                continue
            during = analysis.mean_between(w.times, vals, rise.from_time, rise.to_time)
            if during is None:
                continue
            whole = analysis.mean_between(w.times, vals)
            rel = "unknown" if whole is None else "same" if abs(during - whole) < 1e-9 else "above" if during > whole else "below"
            unit = next((v.unit for v in w.variables if v.key == key), "")
            items.append(Coincident(label=label, unit=unit, during=during, period_mean=whole, relation=rel))
        rain = [v for t, v in zip(w.times, w.series.get("precipitation") or []) if v is not None and rise.from_time <= t <= rise.to_time]
        if rain:
            items.append(Coincident(label="Precipitation (total)", unit="mm", during=sum(rain), period_mean=None, relation="unknown"))
        if not items:
            return CoincidingSection(status="unavailable", reason="No weather values are available for that time.")
        return CoincidingSection(status="ok", window_start=rise.from_time, window_end=rise.to_time, items=items)

    @staticmethod
    def _period(w: RecentWeatherResponse | None, air: AirSection, now: datetime, hours: int) -> Period:
        if w is not None:
            return Period(start=w.times[0], end=w.times[-1], hours=len(w.times))
        if air.times:
            return Period(start=air.times[0], end=air.times[-1], hours=len(air.times))
        end = now.replace(minute=0, second=0, microsecond=0)
        return Period(start=end - timedelta(hours=hours - 1), end=end, hours=hours)

    def _freshness(self, weather: WeatherSection, air: AirSection, w: RecentWeatherResponse | None, now: datetime) -> list[FreshnessItem]:
        out = []
        if w is not None and weather.status == "ok":
            t = w.source.latest_source_time
            out.append(FreshnessItem(
                source_id=weather.source_id, label="Weather-model values", latest_data_time=t,
                age_s=None if t is None else max(0, int((now - t).total_seconds())), status=w.source.freshness,
                detail="The provider's own data time" + ("; the provider's last response is being reused after a failure." if w.source.served_from_cache_after_failure else "."),
            ))
        else:
            out.append(FreshnessItem(source_id=None, label="Weather-model values", latest_data_time=None, age_s=None, status="unavailable", detail=weather.reason or "Unavailable."))
        if air.status == "ok" and air.stats and air.stats.latest_time:
            age = max(0, int((now - air.stats.latest_time).total_seconds()))
            limit = self._air._s.aq_stale_after_s
            out.append(FreshnessItem(source_id=air.source_id, label=f"{air.label} observations", latest_data_time=air.stats.latest_time, age_s=age,
                                     status="stale" if age > limit else "fresh", detail=f"Newest observed hour; readings older than {limit // 3600} h are flagged stale."))
        else:
            out.append(FreshnessItem(source_id=None, label=f"{air.label} observations", latest_data_time=None, age_s=None, status="unavailable", detail=air.reason or "Unavailable."))
        return out

    @staticmethod
    def _limitations(weather, air, references, forecast, freshness, label) -> list[str]:
        out: list[str] = []
        if air.status != "ok":
            out.append(f"No {label} observations: {air.reason}")
        elif air.stats and air.stats.missing_hours:
            out.append(f"{label} was observed in {air.stats.observed_hours} of {air.stats.observed_hours + air.stats.missing_hours} hours; the other {air.stats.missing_hours} hours have no data and are not filled in.")
        if weather.status != "ok":
            out.append(f"No weather values: {weather.reason}")
        else:
            out.append("Weather values are weather-model output for a grid cell, not measurements at the station.")
            if weather.unavailable_variables:
                out.append(f"The weather provider did not supply: {', '.join(weather.unavailable_variables)}.")
        out += [f"{f.label} may be out of date: {f.detail}" for f in freshness if f.status == "stale"]
        if references.status != "ok":
            out.append(f"No scientific references are cited. {references.reason}")
        if forecast.status != "available":
            out.append(f"This report contains no forecast. {forecast.reason}")
        out += [
            "It does not identify pollution sources: no emissions or source data were used.",
            "It cannot confirm a temperature inversion: vertical temperature data for this past period were not used.",
            "Concentrations are shown in the sensor's own unit and are not converted.",
        ]
        return out
