"""Environmental exposure summaries for a place and a period, with retrieved evidence. Population-level, descriptive, no clinical content.

What this is: summaries of *observed* concentrations at monitoring stations from the historical store (averages, peaks, days above
documented thresholds, data coverage), next to passages from authoritative documents the user has indexed in the knowledge base.
What it is not: it never estimates anyone's personal exposure, risk or illness, never links a concentration to an individual's
health, and never invents evidence. With no documents indexed the evidence section says so.

Method notes
  * A "valid day" is an IST calendar day with at least 18 of 24 hourly observations at a station (the 75% completeness convention
    commonly used for 24-hour means). Days with fewer hours are counted as `incomplete_days`, never averaged in.
  * "Days above" compares a station's valid 24-hour mean with a 24-hour standard or guideline value (see risk.PRESETS). These are
    the correct averaging period for those references. Hourly peaks are reported separately and are not compared with them.
  * For a zone, the figure per day is the median across the stations that have a valid mean that day; station counts are reported.
"""

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from statistics import median

from app.history.ingest_air import iso
from app.history.store import HistoryStore
from app.twin.risk import PRESETS, Threshold

IST = timedelta(hours=5, minutes=30)
MIN_HOURS_PER_DAY = 18


class ExposureUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _day(label: str) -> str:
    return (datetime.fromisoformat(label.replace("Z", "+00:00")) + IST).strftime("%Y-%m-%d")


def exposure_summary(store: HistoryStore, pollutant: str, start: datetime, end: datetime, station_id: int | None = None, zone: str | None = None) -> dict:
    if (station_id is None) == (zone is None):
        raise ValueError("give exactly one of station_id or zone")
    if end < start or end - start > timedelta(days=370):
        raise ValueError("the period must be between one hour and 370 days")
    if station_id is not None:
        stations = store.query("select station_id, name, zone, lat, lon from stations where station_id=?", (station_id,))
    else:
        stations = store.query("select station_id, name, zone, lat, lon from stations where zone=?", (zone,))
    if not stations:
        raise ExposureUnavailable("No such station or zone in the historical store.")
    ids = [s["station_id"] for s in stations]
    q = ",".join("?" * len(ids))
    rows = store.query(f"select station_id, label_utc, value_std from clean_air where pollutant=? and usable=1 and label_utc between ? and ? and station_id in ({q})",
                       (pollutant, iso(start), iso(end), *ids))
    if not rows:
        raise ExposureUnavailable("No usable observations of this pollutant in that place and period.")

    values = [r["value_std"] for r in rows]
    by_station_day: dict[tuple[int, str], list[float]] = defaultdict(list)
    for r in rows:
        by_station_day[(r["station_id"], _day(r["label_utc"]))].append(r["value_std"])
    daily: dict[str, list[float]] = defaultdict(list)  # day -> valid station 24 h means
    incomplete = 0
    for (sid, day), vs in by_station_day.items():
        if len(vs) >= MIN_HOURS_PER_DAY:
            daily[day].append(sum(vs) / len(vs))
        else:
            incomplete += 1
    zone_daily = {d: median(v) for d, v in daily.items()}
    peak = max(rows, key=lambda r: r["value_std"])
    expected_hours = int((end - start) / timedelta(hours=1)) + 1
    refs = [t for t in PRESETS.values() if t.pollutant == pollutant]

    def above(t: Threshold) -> dict:
        days = [d for d, m in zip(zone_daily, zone_daily.values()) if m >= t.value]
        return {"threshold": {"key": t.key, "name": t.name, "value": t.value, "unit": t.unit, "kind": t.kind, "averaging": t.averaging, "source": t.source},
                "valid_days": len(zone_daily), "days_at_or_above": len(days), "share_of_valid_days": None if not zone_daily else len(days) / len(zone_daily),
                "first_day": min(days) if days else None, "last_day": max(days) if days else None}

    return {
        "scope": {"station_id": station_id, "zone": zone, "stations_requested": [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in stations]},
        "pollutant": pollutant, "unit": "µg/m³", "period": {"from": iso(start), "to": iso(end), "expected_hours_per_station": expected_hours},
        "observations": {"hourly_values": len(values), "stations_with_data": len({r["station_id"] for r in rows}),
                         "coverage_of_expected_station_hours": len(values) / (expected_hours * len(ids)),
                         "mean": sum(values) / len(values), "median": median(values),
                         "observed_hourly_peak": {"value": peak["value_std"], "time": peak["label_utc"], "station_id": peak["station_id"]}},
        "daily_means": {"averaging": f"IST calendar day, at least {MIN_HOURS_PER_DAY} of 24 hourly values per station; zone value = median across stations",
                        "valid_days": len(zone_daily), "incomplete_station_days_excluded": incomplete,
                        "mean_of_daily_means": None if not zone_daily else sum(zone_daily.values()) / len(zone_daily),
                        "highest_daily_mean": None if not zone_daily else {"day": max(zone_daily, key=zone_daily.get), "value": max(zone_daily.values())}},
        "days_above_references": [above(t) for t in refs],
        "provenance": {"observations": "OpenAQ hourly aggregates (CPCB and other providers) from the historical store, standardised to µg/m³; usable hours only",
                       "status": "observed", "spatial_coverage": "monitoring-station locations only; nothing is estimated between stations"},
        "uncertainty": "Instrument and aggregation uncertainty is not reported by the providers and is not estimated here. Hourly OpenAQ values blend neighbouring provider hours (see docs/historical-data-pipeline.md).",
        "limitations": ["Concentrations at monitoring stations are not a person's exposure: indoor air, location, movement and time spent outdoors are unknown.",
                        "Reference values are population-level standards or guidelines, not individual thresholds.",
                        "Nothing here is a diagnosis, a risk estimate for an individual, or medical advice."],
    }


async def retrieve_evidence(kb, pollutant_label: str, top_k: int = 3) -> dict:
    """Passages from the user's indexed documents about health effects. No documents indexed means no evidence, and the answer says so."""
    if not getattr(kb, "ready", False):
        return {"status": "none", "reason": getattr(kb, "note", "The knowledge base is not available."), "passages": []}
    res = await kb.search(f"population health effects of {pollutant_label} exposure, guideline values and evidence", top_k)
    if res.status != "ok" or not res.passages:
        return {"status": "none", "reason": res.reason or "No relevant passage was found in the indexed documents.", "passages": []}
    return {"status": "ok", "reason": None, "passages": [
        {"citation": f"K{i}", "document": p.document, "category": p.category_label, "publisher": p.publisher or None, "licence": p.licence or None,
         "location": p.location, "relevance": round(p.score, 2), "url": p.url, "excerpt": " ".join(p.text.split())[:500]}
        for i, p in enumerate(res.passages, start=1)]}
