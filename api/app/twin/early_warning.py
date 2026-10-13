"""Early-warning overview: one forecast origin, one threshold, every station that reported at that hour.

Honest scope
  * Every station's forecast is the saved local model applied to data available at the origin (a back-test when the origin is in the past).
    It is not a live warning unless the origin is recent; `data_age_hours` and `stale` say how old the origin is.
  * A station is listed only if it has a usable observation at the origin, so each forecast really is that station's own series.
  * Ranking uses the same risk-window rules as `app.twin.risk` (consecutive lead times at or above the threshold; "likely" only when the
    interval's lower bound also reaches it). Nothing here is interpolated between stations.
  * Horizons where the served model did not beat the persistence baseline on its held-out period are reported as weak, never hidden.
"""

from datetime import datetime

from app.twin.risk import Threshold, evaluate

STALE_AFTER_HOURS = 6.0
SEVERITY = {"likely": 2, "possible": 1}


def classify(evaluation: dict) -> dict:
    """Reduce one station's risk evaluation to a level. `likely` if any point is above with its lower bound also above, `possible` if only
    the central forecast reaches the threshold, `none` otherwise."""
    pts = [p for p in evaluation["points"] if p["at_or_above_threshold"]]
    if not pts:
        return {"level": "none", "first_lead_hours": None, "peak_predicted": None, "peak_lead_hours": None, "hours_above": 0}
    level = "likely" if any(p["confidence"] == "likely" for p in pts) else "possible"
    peak = max(pts, key=lambda p: p["predicted"])
    return {"level": level, "first_lead_hours": min(p["lead_hours"] for p in pts), "peak_predicted": peak["predicted"],
            "peak_lead_hours": peak["lead_hours"], "hours_above": len(pts)}


def rank(entries: list[dict]) -> list[dict]:
    """Most severe first, then earliest crossing, then highest peak. Stations without a warning sort last by their peak forecast."""
    def key(e):
        lvl = SEVERITY.get(e["level"], 0)
        first = e["first_lead_hours"] if e["first_lead_hours"] is not None else 10**6
        return (-lvl, first, -(e["peak_predicted"] if e["peak_predicted"] is not None else -1))
    return sorted(entries, key=key)


def build_overview(*, pollutant: str, origin: datetime, now: datetime, threshold: Threshold, stations: list[dict], skipped: list[dict],
                   weak_horizons: list[int], model_version: str | None, interval_level: float | None, importance: list[dict] | None,
                   min_consecutive: int = 1) -> dict:
    """`stations`: [{station_id, name, lat, lon, rows: [forecast rows for risk.evaluate]}]; `skipped`: [{station_id, name, reason}]."""
    entries = []
    for s in stations:
        ev = evaluate(s["rows"], threshold, min_consecutive)
        c = classify(ev)
        entries.append({"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], **c, "windows": ev["windows"],
                        "series": [{"lead_hours": p["lead_hours"], "time": p["time"], "predicted": p["predicted"], "lower": p["lower"], "upper": p["upper"]}
                                   for p in ev["points"]]})
    ranked = rank(entries)
    age = (now - origin).total_seconds() / 3600.0
    counts = {k: sum(e["level"] == k for e in ranked) for k in ("likely", "possible", "none")}
    return {
        "pollutant": pollutant, "origin": origin.isoformat().replace("+00:00", "Z"), "data_age_hours": round(age, 1), "stale": age > STALE_AFTER_HOURS,
        "threshold": {"key": threshold.key, "name": threshold.name, "value": threshold.value, "unit": threshold.unit, "kind": threshold.kind,
                      "averaging": threshold.averaging, "source": threshold.source},
        "counts": counts, "stations": ranked, "skipped": skipped, "weak_horizons": sorted(weak_horizons),
        "model_version": model_version, "interval_level": interval_level,
        "uncertainty": ("A station is 'likely' only when the lower end of the model's empirical prediction interval also reaches the threshold; "
                        "'possible' means only the central forecast does. The interval is a validation-residual band, not a guarantee."
                        + (f" Nominal coverage {interval_level:.0%}." if interval_level else "")),
        "importance": importance, "importance_note": "Tree-model feature importance at the tuning horizon. It describes what the model used, not what causes pollution.",
        "caveats": [
            "Forecasts are from the trained model at its discrete lead times; hours between them are not assessed.",
            "Published standards are 24-hour averages; a single forecast value is not one, so a crossing is an indicator, not an exceedance finding.",
            ("This origin is " + (f"{age:.0f} h" if age < 48 else f"{age / 24:.0f} days") + " old, so this is a replay of the model on stored data, not a current warning."
             if age > STALE_AFTER_HOURS else "This origin is recent."),
        ],
    }
