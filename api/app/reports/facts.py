"""The deterministic summary: plain sentences assembled from the report's own numbers. Always present, never model-written."""

from app.assistant.fmt import ist


def facts_summary(r) -> list[str]:  # r: Report (typed loosely to avoid an import cycle with the builder)
    out: list[str] = []
    air, w = r.air, r.weather
    if air.status == "ok" and air.stats and air.station:
        s, u = air.stats, air.stats.unit or ""
        out.append(
            f"{air.label} was observed at {air.station.name} ({air.station.distance_km:.1f} km from the {r.location.name} centre) in "
            f"{s.observed_hours} of {s.observed_hours + s.missing_hours} hours. The latest value was {s.latest:.1f} {u} at {ist(s.latest_time)}; "
            f"the range was {s.min:.1f} to {s.max:.1f} {u} with a mean of {s.mean:.1f} {u}."
        )
        if air.largest_rise:
            x = air.largest_rise
            pct = f" ({x.pct:.0f}%)" if x.pct is not None else ""
            out.append(f"The largest rise within {x.span_hours} hours was +{x.rise:.1f} {u}{pct}, from {x.from_value:.1f} at {ist(x.from_time)} to {x.to_value:.1f} at {ist(x.to_time)}.")
        if air.trend:
            t = air.trend
            out.append(f"Comparing the start and end of the period, the mean moved from {t.first_mean:.1f} to {t.last_mean:.1f} {u} ({t.change:+.1f} {u}).")
    else:
        out.append(f"No {air.label} observations are available for this period. {air.reason or ''}".strip())
    if w.status == "ok":
        by = {v.key: v for v in w.variables}
        parts = []
        if "temperature_2m" in by and by["temperature_2m"].min is not None:
            v = by["temperature_2m"]
            parts.append(f"temperature {v.min:.1f} to {v.max:.1f} {v.unit}")
        if "wind_speed_10m" in by and by["wind_speed_10m"].mean is not None:
            v = by["wind_speed_10m"]
            parts.append(f"wind speed averaging {v.mean:.1f} {v.unit}")
        if "boundary_layer_height" in by and by["boundary_layer_height"].mean is not None:
            v = by["boundary_layer_height"]
            parts.append(f"boundary layer height {v.min:.0f} to {v.max:.0f} {v.unit}")
        if w.rain_total_mm is not None:
            parts.append(f"{w.rain_total_mm:.1f} mm of rain in {w.rainy_hours} hours")
        if parts:
            out.append("Weather-model values for the period: " + "; ".join(parts) + ".")
    else:
        out.append(f"No weather values are available for this period. {w.reason or ''}".strip())
    if r.coinciding.status == "ok" and r.coinciding.items:
        out.append("During the largest rise, " + "; ".join(
            f"{i.label.lower()} averaged {i.during:.1f} {i.unit}" + (f" ({i.relation} the period mean of {i.period_mean:.1f})" if i.relation in ("above", "below") and i.period_mean is not None else "")
            for i in r.coinciding.items if i.label != "Precipitation (total)") + ". " + r.coinciding.caution)
    return out
