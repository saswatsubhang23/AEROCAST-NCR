"""Risk windows: periods in which a *model forecast* reaches a documented threshold.

Honest scope
  * Input is a forecast at the model's discrete lead times (for example +1, +3, +6, +12, +24 h). A window is a run of consecutive
    lead times whose predicted value is at or above the threshold; its start and end are those lead times. Nothing is said about
    the hours between two lead times (no interpolation).
  * Thresholds are labelled by kind. The two reference sets below are published *24-hour* standards/guidelines; a forecast at one
    lead time is not a 24-hour mean, so crossing one is an indicator, not a determination that the standard is exceeded.
  * `user_defined` thresholds are the caller's own numbers and carry no regulatory meaning.
  * Uncertainty: if the forecast carries an interval, each point is classed "likely" when its lower bound also reaches the
    threshold and "possible" when only the central value does. The interval is an empirical validation-residual band, not a guarantee.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Threshold:
    key: str
    name: str
    pollutant: str
    value: float
    unit: str
    kind: str  # official_standard | guideline | user_defined
    averaging: str
    source: str


PRESETS: dict[str, Threshold] = {t.key: t for t in [
    Threshold("naaqs_pm25_24h", "India NAAQS PM2.5, 24-hour", "pm25", 60.0, "µg/m³", "official_standard", "24 hours",
              "National Ambient Air Quality Standards, CPCB (2009 notification)"),
    Threshold("naaqs_pm10_24h", "India NAAQS PM10, 24-hour", "pm10", 100.0, "µg/m³", "official_standard", "24 hours",
              "National Ambient Air Quality Standards, CPCB (2009 notification)"),
    Threshold("who_pm25_24h", "WHO guideline PM2.5, 24-hour", "pm25", 15.0, "µg/m³", "guideline", "24 hours",
              "WHO global air quality guidelines (2021)"),
    Threshold("who_pm10_24h", "WHO guideline PM10, 24-hour", "pm10", 45.0, "µg/m³", "guideline", "24 hours",
              "WHO global air quality guidelines (2021)"),
]}


def custom_threshold(pollutant: str, value: float) -> Threshold:
    return Threshold("custom", "User-defined threshold", pollutant, float(value), "µg/m³", "user_defined", "as forecast (one value per lead time)",
                     "Chosen by the user; not an official standard or health guidance")


def evaluate(rows: list[dict], threshold: Threshold, min_consecutive: int = 1) -> dict:
    """`rows`: forecast points ordered by lead time with `time`, `lead_hours`, `predicted`, optional `lower`/`upper`."""
    points = []
    for r in rows:
        pred = r["predicted"]
        lower = r.get("lower")
        status = "above" if pred >= threshold.value else "below"
        likely = status == "above" and lower is not None and lower >= threshold.value
        points.append({"time": r["time"], "lead_hours": r["lead_hours"], "predicted": pred, "lower": lower, "upper": r.get("upper"),
                       "at_or_above_threshold": status == "above", "confidence": ("likely" if likely else "possible") if status == "above" else None})
    windows, run = [], []
    for p in points + [None]:
        if p is not None and p["at_or_above_threshold"]:
            run.append(p)
            continue
        if len(run) >= min_consecutive:
            peak = max(run, key=lambda q: q["predicted"])
            windows.append({"start": run[0]["time"], "end": run[-1]["time"], "lead_from_hours": run[0]["lead_hours"], "lead_to_hours": run[-1]["lead_hours"],
                            "points": len(run), "peak_predicted": peak["predicted"], "peak_time": peak["time"],
                            "likely_points": sum(q["confidence"] == "likely" for q in run),
                            "predicted_range": [min(q["predicted"] for q in run), peak["predicted"]]})
        run = []
    return {"threshold": {"key": threshold.key, "name": threshold.name, "value": threshold.value, "unit": threshold.unit, "kind": threshold.kind,
                          "averaging": threshold.averaging, "source": threshold.source},
            "duration_rule": f"at least {min_consecutive} consecutive forecast lead time(s) at or above the threshold",
            "points": points, "windows": windows,
            "limitations": ["Evaluated at the model's discrete lead times only; the hours between them are not assessed.",
                            "Published standards are 24-hour averages; a single forecast value is not one, so this is an indicator.",
                            "Intervals are empirical validation-residual bands, not guarantees."]}
