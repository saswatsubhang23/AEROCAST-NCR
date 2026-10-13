"""Evaluates alert rules against the latest station observations.

Rules of evaluation (each is a deliberate guard against a misleading alert):
  * only observed station readings are compared, never weather-model values or anything predicted;
  * a reading older than the staleness limit never triggers: it is reported as stale instead;
  * units are never converted: a reading in another unit is reported as a unit mismatch;
  * no data is reported as no data, never as "not triggered".
"""

import logging
from datetime import datetime

from app.alerts.models import (
    LABELS, OPERATOR_TEXT, AlertRule, AlertRuleCreate, AlertSource, AlertsResponse, AlertStatus, Observation, unit_key,
)
from app.alerts.store import AlertRuleStore
from app.core.places import PLACES, STATION_RADIUS_KM, distance_km
from app.core.time import utc_now
from app.integrations.http import UpstreamAuthError, UpstreamError
from app.integrations.openaq import AqNotConfigured
from app.schemas.air import Reading, Station
from app.services.air_quality import AirQualityService

logger = logging.getLogger("app.alerts")
SOURCE = AlertSource(provider="OpenAQ", url="https://openaq.org")


def default_name(c: AlertRuleCreate) -> str:
    return f"{LABELS[c.pollutant]} {OPERATOR_TEXT[c.operator]} {c.threshold:g} {c.unit} in {PLACES[c.location_id][0]}"


def to_rule(row: dict) -> AlertRule:
    return AlertRule(
        id=row["id"], name=row["name"], location_id=row["location_id"], location_name=PLACES[row["location_id"]][0],
        pollutant=row["pollutant"], measurement=LABELS[row["pollutant"]], operator=row["operator"], threshold=row["threshold"],
        unit=row["unit"], enabled=bool(row["enabled"]), created_at=row["created_at"],
    )


def breached(operator: str, value: float, threshold: float) -> bool:
    return value > threshold if operator == "gt" else value >= threshold


class AlertService:
    def __init__(self, store: AlertRuleStore, air: AirQualityService, now=utc_now):
        self.store, self._air, self._now = store, air, now

    def create(self, c: AlertRuleCreate) -> AlertRule:
        row = self.store.add(c.name or default_name(c), c.location_id, c.pollutant, c.operator, c.threshold, c.unit)
        return to_rule(row)

    def rules(self) -> list[AlertRule]:
        return [to_rule(r) for r in self.store.list()]

    async def evaluate(self) -> AlertsResponse:
        rules = self.rules()
        now = self._now()
        stations: list[Station] = []
        available, why = True, None
        if any(r.enabled for r in rules):
            try:
                stations = (await self._air.stations()).stations
            except AqNotConfigured:
                available, why = False, "The air-quality source is not configured (no API key), so no observations are available."
            except UpstreamAuthError:
                available, why = False, "The air-quality provider rejected the configured API key."
            except UpstreamError:
                available, why = False, "The air-quality source could not be reached."
        stale_after = self._air._s.aq_stale_after_s  # the same limit the rest of the application uses
        statuses = [self._status(r, stations, available, why, now, stale_after) for r in rules]
        return AlertsResponse(statuses=statuses, source_available=available, source_message=why, evaluated_at=now)

    def _status(self, rule: AlertRule, stations: list[Station], available: bool, why: str | None,
                now: datetime, stale_after: int) -> AlertStatus:
        def result(state, message, obs: Observation | None = None) -> AlertStatus:
            return AlertStatus(rule=rule, status=state, observation=obs, source=SOURCE, message=message, evaluated_at=now)

        if not rule.enabled:
            return result("disabled", "This rule is switched off.")
        if not available:
            return result("unavailable", why or "Observations are unavailable.")

        _, lat, lon = PLACES[rule.location_id]
        near: list[tuple[float, Station, Reading]] = sorted(
            ((distance_km(lat, lon, s.lat, s.lon), s, s.latest[rule.pollutant]) for s in stations if rule.pollutant in s.latest),
            key=lambda x: x[0],
        )
        near = [x for x in near if x[0] <= STATION_RADIUS_KM]
        if not near:
            return result("no_data", f"No station within {STATION_RADIUS_KM:.0f} km of {rule.location_name} has a recent {rule.measurement} reading.")

        def obs(x) -> Observation:
            d, s, r = x
            return Observation(value=r.value, unit=r.unit, observed_at=r.observed_at, age_s=r.age_s, station_id=s.id, station=s.name,
                               provider=s.provider, distance_km=round(d, 1))

        same_unit = [x for x in near if unit_key(x[2].unit) == unit_key(rule.unit)]
        if not same_unit:
            o = obs(near[0])
            return result("unit_mismatch", f"The nearest reading is in {o.unit}, not {rule.unit}. AEROCAST does not convert units, so it was not compared.", o)
        fresh = [x for x in same_unit if (now - x[2].observed_at).total_seconds() <= stale_after]
        if not fresh:
            o = obs(same_unit[0])
            return result("stale", f"The newest reading is {o.age_s // 3600} h old, too old to judge against a threshold.", o)
        o = obs(fresh[0])
        text = f"{o.value:g} {o.unit} {'≥' if rule.operator == 'gte' else '>'} {rule.threshold:g} {rule.unit}"
        if breached(rule.operator, o.value, rule.threshold):
            return result("triggered", f"Observed {text} at {o.station}.", o)
        return result("not_triggered", f"Observed {o.value:g} {o.unit} at {o.station}, below the threshold of {rule.threshold:g} {rule.unit}.", o)
