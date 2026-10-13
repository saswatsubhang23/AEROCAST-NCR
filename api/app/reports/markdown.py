"""Markdown rendering of a Report (used for the assistant's reply and for the .md download)."""

from app.assistant.fmt import ist
from app.reports.models import Report


def _u(unit: str | None) -> str:
    return f" {unit}" if unit else ""


def render_markdown(r: Report, *, link: str | None = None) -> str:
    L: list[str] = [
        f"## Air-quality and weather report: {r.location.name}",
        f"**Period:** {ist(r.period.start)} to {ist(r.period.end)} ({r.period.hours} hours). **Generated:** {ist(r.created_at)}.",
        "",
    ]
    if r.llm_summary.status == "ok" and r.llm_summary.text:
        L += ["### Summary", r.llm_summary.text, f"*{r.llm_summary.label}*", ""]
    L += ["### Key facts", *[f"- {s}" for s in r.facts_summary], ""]

    # ---- air quality
    a = r.air
    L.append(f"### {a.label} observations")
    if a.status != "ok" or not a.stats or not a.station:
        L.append(f"Not available. {a.reason or ''}".strip())
    else:
        s, u = a.stats, a.stats.unit
        L += [
            f"Station: {a.station.name} ({a.station.distance_km:.1f} km from the {r.location.name} centre), provider {a.station.provider or 'unknown'} [{a.source_id}].",
            f"- Observed in {s.observed_hours} of {s.observed_hours + s.missing_hours} hours; {s.missing_hours} hours have no data.",
            f"- Latest observed: {s.latest:.1f}{_u(u)} at {ist(s.latest_time)}.",
            f"- Lowest: {s.min:.1f}{_u(u)} at {ist(s.min_time)}. Highest: {s.max:.1f}{_u(u)} at {ist(s.max_time)}. Mean: {s.mean:.1f}{_u(u)}.",
        ]
        if a.largest_rise:
            x = a.largest_rise
            pct = f" ({x.pct:.0f}%)" if x.pct is not None else ""
            L.append(f"- Largest rise within {x.span_hours} hours: +{x.rise:.1f}{_u(u)}{pct}, from {x.from_value:.1f} at {ist(x.from_time)} to {x.to_value:.1f} at {ist(x.to_time)}.")
        else:
            L.append("- No rise between observed hours was found within 6-hour spans.")
        if a.trend:
            L.append(f"- Trend: the mean moved from {a.trend.first_mean:.1f} to {a.trend.last_mean:.1f}{_u(u)} ({a.trend.change:+.1f}); {a.trend.basis}.")
        others = [x for x in a.latest_readings if x.pollutant != a.pollutant]
        if others:
            L += ["", "Latest readings at the same station (concentrations as reported, not AQI):"]
            L += [f"- {x.label}: {x.value:g} {x.unit} at {ist(x.observed_at)}{' (stale)' if x.stale else ''}" for x in others]

    # ---- weather
    L += ["", "### Weather over the period (weather-model values, not station measurements)"]
    w = r.weather
    if w.status != "ok":
        L.append(f"Not available. {w.reason or ''}".strip())
    else:
        for v in w.variables:
            if v.min is None:
                continue
            L.append(f"- {v.label}: {v.min:.1f} to {v.max:.1f} {v.unit}, mean {v.mean:.1f} {v.unit}.")
        if w.rain_total_mm is not None:
            L.append(f"- Precipitation: {w.rain_total_mm:.1f} mm in total, rain (at least 0.1 mm) in {w.rainy_hours} of {len(w.times)} hours [{w.source_id}].")
        for key in w.unavailable_variables:
            L.append(f"- {key}: not provided by the source.")

    # ---- atmosphere
    at = r.atmosphere
    L += ["", "### Atmospheric conditions (descriptive indicators)"]
    if at.status != "ok":
        L.append(f"Not available. {at.reason or ''}".strip())
    else:
        if at.ventilation_index_latest is not None:
            L.append(f"- Ventilation index (boundary layer height × wind speed): latest {at.ventilation_index_latest:.0f} m²/s, mean {at.ventilation_index_mean:.0f} m²/s.")
        L.append(f"- Hours since rain: {at.hours_since_rain if at.hours_since_rain is not None else 'unknown'}." + (f" {at.hours_since_rain_note}" if at.hours_since_rain_note else ""))
        L.append(at.definition)

    # ---- coinciding
    c = r.coinciding
    if c.status == "ok":
        L += ["", f"### Weather during the largest rise ({ist(c.window_start)} to {ist(c.window_end)})"]
        for i in c.items:
            if i.label == "Precipitation (total)":
                L.append(f"- Precipitation during the rise: {i.during:.1f} mm.")
            else:
                rel = f", {i.relation} the period mean of {i.period_mean:.1f}" if i.relation in ("above", "below") and i.period_mean is not None else (", the same as the period mean" if i.relation == "same" else "")
                L.append(f"- {i.label} averaged {i.during:.1f} {i.unit} during the rise{rel}.")
        L.append(c.caution)

    # ---- references
    L += ["", "### Scientific and guidance references"]
    if r.references.status == "ok":
        for i in r.references.items:
            where = f", {i.location}" if i.location else ""
            L.append(f"- [{i.source_id}] {i.title} ({i.category}{where}; relevance {i.relevance:.2f}): “{i.excerpt}”")
        L.append("Retrieved passages from the knowledge base, quoted as found; they are not conclusions of this report.")
    else:
        L.append(r.references.reason or "None cited.")

    # ---- forecast
    f = r.forecast
    L += ["", "### Forecast"]
    if f.status == "available":
        L.append(f"Provided by {f.provider} (model {f.model_version}, issued {ist(f.issued_at)}) [{f.source_id}]. This is not an AEROCAST forecast and is not an observation.")
        L += [f"- {ist(t)}: {v:g} {f.unit}" + (f" (interval {lo:g} to {hi:g})" if f.lower else "") for t, v, lo, hi in zip(f.times, f.values, f.lower or f.values, f.upper or f.values)][:12]
    else:
        L.append(f.reason)

    # ---- freshness, limitations, sources
    L += ["", "### Data freshness"]
    L += [f"- {x.label}: {x.status}" + (f", newest data {ist(x.latest_data_time)}" if x.latest_data_time else "") + f". {x.detail}" for x in r.freshness]
    L += ["", "### What this report cannot say", *[f"- {x}" for x in r.limitations]]
    L += ["", "### Sources", *[f"- [{s.id}] {s.title}. {s.provider}" + (f", {s.url}" if s.url else "") + f". Retrieved {ist(s.retrieved_at)}." for s in r.sources]]
    if link:
        L += ["", f"[Open the full report and PDF export]({link})"]
    return "\n".join(L)
