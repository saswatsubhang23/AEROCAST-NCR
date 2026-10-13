"""Assembles the full exported report: every figure, table and text of the application for one place, period and pollutant.

Each section is built from a service response and nothing else. A section whose data cannot be had says so in place and the rest
of the report is still produced; no value is estimated to fill a gap. Observation, model and forecast figures carry a label of
what they are, in the caption.
"""

from __future__ import annotations

import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from app.assistant.fmt import ist
from app.core.places import PLACES, POLLUTANT_LABELS
from app.reports import charts
from app.reports.builder import ReportService
from app.reports.doc import Bullets, Callout, Document, Figure, Heading, Paragraph, Table, parse_markdown
from app.reports.models import Report

logger = logging.getLogger("app.reports.export")

DOCS = Path(__file__).resolve().parents[3] / "docs"
CACHE_SECONDS = 600
KINDS = ("Every figure is labelled with what kind of number it is. An **observation** is a station measurement; a **weather model** or "
         "**atmospheric model** value is model output for a grid cell; a **forecast** is a prediction; a **simulation** is computed from assumptions. "
         "Gaps are shown as gaps and are never filled in.")


def _na(reason: str) -> list:
    return [Callout("Not available", reason)]


def _num(v: float | None, nd: int = 1) -> str:
    return "-" if v is None or not math.isfinite(v) else f"{v:.{nd}f}"


def _nearest(times: list[str], target: str) -> int | None:
    try:
        t0 = datetime.fromisoformat(target.replace("Z", "+00:00"))
        diffs = [abs((datetime.fromisoformat(t.replace("Z", "+00:00")) - t0).total_seconds()) for t in times]
    except ValueError:
        return None
    if not diffs:
        return None
    k = min(range(len(diffs)), key=diffs.__getitem__)
    return k if diffs[k] <= 3600 else None


def _articles() -> list[tuple[str, str]]:
    from app.api.articles import _files

    out = []
    for p in _files():
        text = p.read_text(encoding="utf-8")
        title = next((ln[2:].strip() for ln in text.splitlines() if ln.startswith("# ")), p.stem.replace("-", " ").title())
        out.append((title, text))
    return out


class ExportBuilder:
    def __init__(self, reports: ReportService, cams, wfields, air, availability: Callable[[], Awaitable[dict]], model_status: Callable[[], dict],
                 articles: Callable[[], list[tuple[str, str]]] = _articles, coupled_eval: Path | None = None, cache: dict | None = None):
        self._reports, self._cams, self._wf, self._air = reports, cams, wfields, air
        self._availability, self._model_status, self._articles = availability, model_status, articles
        self._coupled_eval = coupled_eval or DOCS / "coupled-evaluation.json"
        self._cache: dict[tuple, tuple[float, Document]] = cache if cache is not None else {}

    async def document(self, location_id: str, hours: int, pollutant: str, include_articles: bool = True) -> Document:
        key = (location_id, hours, pollutant, include_articles)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_SECONDS:
            return hit[1]
        doc = await self._build(location_id, hours, pollutant, include_articles)
        self._cache[key] = (time.monotonic(), doc)
        return doc

    async def _safe(self, name: str, fn) -> list:
        try:
            out = fn()
            return await out if hasattr(out, "__await__") else out
        except Exception as exc:  # noqa: BLE001 - one failed section must not lose the whole report
            logger.warning("report section %s failed: %s: %s", name, type(exc).__name__, exc)
            return _na(f"This section could not be built ({type(exc).__name__}). The rest of the report is unaffected.")

    # ------------------------------------------------------------------------------------------------ assembly
    async def _build(self, location_id: str, hours: int, pollutant: str, include_articles: bool) -> Document:
        name, lat, lon = PLACES[location_id]
        label = POLLUTANT_LABELS[pollutant]
        report = await self._reports.build(location_id, hours, pollutant)
        doc = Document(
            title=f"Air quality and weather report: {name}",
            subtitle=f"{label} over the past {hours} hours, the regional atmosphere, the data behind it and how far to trust it.",
            meta=[("Place", f"{name} ({lat:.2f} N, {lon:.2f} E)"), ("Period", f"{ist(report.period.start)} to {ist(report.period.end)}"),
                  ("Pollutant", label), ("Generated", ist(report.created_at)), ("Report id", report.id)],
        )
        b = doc.blocks
        b.append(Heading(2, "Summary"))
        b.append(Paragraph(KINDS))
        b.append(Bullets(report.facts_summary or ["No findings could be derived from the data available."]))
        b += await self._safe("air", lambda: self._air_section(report))
        b += await self._safe("weather", lambda: self._weather_section(report))
        b += await self._safe("atmosphere", lambda: self._atmosphere_section(report))
        b += await self._safe("regional", lambda: self._regional_section(report, pollutant, label, lat, lon, name))
        b += await self._safe("network", lambda: self._network_section(pollutant, label))
        b += await self._safe("forecast", lambda: self._forecast_section(report, label))
        b += await self._safe("models", self._models_section)
        b += await self._safe("coverage", self._coverage_section)
        b += await self._safe("sources", lambda: self._sources_section(report))
        if include_articles:
            b += await self._safe("articles", self._article_section)
        return doc

    # ------------------------------------------------------------------------------------------------ sections
    def _air_section(self, r: Report) -> list:
        a = r.air
        out: list = [Heading(2, f"{a.label} observations at {r.location.name}")]
        if a.status != "ok" or not a.stats or not a.station:
            return out + _na(a.reason or "No observations were available for this place and period.")
        s, u = a.stats, a.stats.unit or ""
        out.append(Paragraph(f"Station **{a.station.name}**, {a.station.distance_km:.1f} km from the centre of {r.location.name}"
                             f" (provider: {a.station.provider or 'unknown'}). Observation, source [{a.source_id}]."))
        out.append(Figure(charts.line_chart(a.times, [(f"{a.label} ({u})", a.values, charts.ACCENT)], u),
                          f"Hourly {a.label} at {a.station.name}, observation, IST. A missing hour is a gap in the line.", alt=f"{a.label} time series"))
        rows = [["Hours observed", f"{s.observed_hours} of {s.observed_hours + s.missing_hours} ({s.missing_hours} missing)"],
                ["Latest", f"{_num(s.latest)} {u} at {ist(s.latest_time) if s.latest_time else '-'}"],
                ["Lowest", f"{_num(s.min)} {u}" + (f" at {ist(s.min_time)}" if s.min_time else "")],
                ["Highest", f"{_num(s.max)} {u}" + (f" at {ist(s.max_time)}" if s.max_time else "")], ["Mean", f"{_num(s.mean)} {u}"]]
        if a.largest_rise:
            ri = a.largest_rise
            rows.append(["Largest 6-hour rise", f"+{_num(ri.rise)} {u}: {_num(ri.from_value)} at {ist(ri.from_time)} to {_num(ri.to_value)} at {ist(ri.to_time)}"])
        if a.trend:
            rows.append(["Trend", f"{_num(a.trend.first_mean)} to {_num(a.trend.last_mean)} {u} ({a.trend.change:+.1f}); {a.trend.basis}"])
        out.append(Table(["Measure", "Value"], rows, [1, 3]))
        others = [x for x in a.latest_readings if x.pollutant != a.pollutant]
        if others:
            out.append(Heading(3, "Other pollutants at the same station"))
            out.append(Table(["Pollutant", "Reading", "Observed (IST)", "Note"],
                             [[x.label, f"{x.value:g} {x.unit}", ist(x.observed_at), "stale" if x.stale else ""] for x in others], [2, 2, 3, 1],
                             caption="Concentrations as reported by the sensor, in its own unit; they are not AQI values."))
        return out

    def _weather_section(self, r: Report) -> list:
        w = r.weather
        out: list = [Heading(2, "Weather over the period")]
        if w.status != "ok":
            return out + _na(w.reason or "Weather values were not available.")
        out.append(Paragraph(f"Weather-model values for the grid cell at {w.grid_lat:.2f} N, {w.grid_lon:.2f} E (elevation {w.elevation_m} m). "
                             f"Weather model, not station measurements. Source [{w.source_id}]."))
        meta = {v.key: v for v in w.variables}
        spec = [("temperature_2m", "Temperature", "#dc2626"), ("relative_humidity_2m", "Relative humidity", "#2563eb"),
                ("wind_speed_10m", "Wind speed at 10 m", "#0e7490"), ("boundary_layer_height", "Boundary-layer height", "#7c3aed")]
        for key, title, colour in spec:
            if key in w.series and any(v is not None for v in w.series[key]):
                unit = meta[key].unit if key in meta else ""
                out.append(Figure(charts.line_chart(w.times, [(f"{title} ({unit})", w.series[key], colour)], unit, zero_based=key != "temperature_2m"),
                                  f"{title}, weather model, hourly, IST."))
        if "precipitation" in w.series and any(v is not None for v in w.series["precipitation"]):
            out.append(Figure(charts.line_chart(w.times, [("Precipitation (mm)", w.series["precipitation"], "#2563eb")], "mm", zero_based=True),
                              f"Hourly precipitation, weather model. Total {_num(w.rain_total_mm)} mm in {w.rainy_hours} rainy hours."))
        rows = [[v.label, _num(v.min), _num(v.max), _num(v.mean), v.unit] for v in w.variables if v.min is not None]
        if w.rain_total_mm is not None:
            rows.append(["Precipitation", "-", "-", f"{w.rain_total_mm:.1f} total", f"mm, {w.rainy_hours} rainy hours"])
        out.append(Table(["Variable", "Min", "Max", "Mean", "Unit"], rows, [3, 1, 1, 2, 2]))
        if w.unavailable_variables:
            out.append(Paragraph(f"The provider did not supply: {', '.join(w.unavailable_variables)}.", muted=True))
        return out

    def _atmosphere_section(self, r: Report) -> list:
        at, c = r.atmosphere, r.coinciding
        out: list = [Heading(2, "Atmospheric conditions and what coincided with the largest rise")]
        if at.status != "ok":
            out += _na(at.reason or "Not available.")
        else:
            items = []
            if at.ventilation_index_latest is not None:
                items.append(f"Ventilation index (boundary-layer height times wind speed): latest {at.ventilation_index_latest:.0f} m²/s, mean {_num(at.ventilation_index_mean, 0)} m²/s.")
            items.append("Hours since rain: " + (str(at.hours_since_rain) if at.hours_since_rain is not None else "unknown") + "." + (f" {at.hours_since_rain_note}" if at.hours_since_rain_note else ""))
            out.append(Bullets(items))
            out.append(Paragraph(at.definition, muted=True))
        if c.status == "ok":
            out.append(Heading(3, f"Weather during the largest rise ({ist(c.window_start)} to {ist(c.window_end)})"))
            out.append(Table(["Variable", "During the rise", "Period mean", "Relation"],
                             [[i.label, f"{_num(i.during)} {i.unit}", "-" if i.period_mean is None else f"{_num(i.period_mean)} {i.unit}",
                               "" if i.relation == "unknown" else i.relation] for i in c.items], [3, 2, 2, 1], caption=c.caution))
        return out

    async def _regional_section(self, r: Report, pollutant: str, label: str, lat: float, lon: float, name: str) -> list:
        out: list = [Heading(2, "The regional picture: air and wind across Delhi-NCR")]
        cams = await self._cams.fields(12, 48)
        var = cams["variables"].get(pollutant)
        if not var or not var.get("available"):
            return out + _na(f"The atmospheric model has no {label} field right now.")
        k = cams.get("now_index")
        if k is None:
            return out + _na("The atmospheric model's time axis does not include the present.")
        grid = var["values"][k]
        unit = var["unit"]
        lats, lons = cams["grid"]["lats"], cams["grid"]["lons"]
        arrows = None
        wf = None
        try:
            wf = await self._wf.fields("forecast", 1, 1)
            wk = _nearest(wf["times"], cams["times"][k])
            if wk is not None and wf["variables"]["wind_u"]["available"]:
                arrows = (wf["grid"]["lats"], wf["grid"]["lons"], wf["variables"]["wind_u"]["values"][wk], wf["variables"]["wind_v"]["values"][wk])
        except Exception as exc:  # noqa: BLE001 - the map is still useful without arrows
            logger.warning("wind field unavailable for the report map: %s", exc)
        points: list[tuple[float, float, float | None, str]] = []
        n_skipped = 0
        try:
            listing = await self._air.stations()
            for s in listing.stations:
                rd = s.latest.get(pollutant)
                if rd is None or rd.unit.replace("μ", "µ") != unit:
                    n_skipped += rd is not None
                    continue
                points.append((s.lat, s.lon, rd.value, s.name))
        except Exception as exc:  # noqa: BLE001
            logger.warning("station layer unavailable for the report map: %s", exc)
        when = ist(datetime.fromisoformat(cams["times"][k].replace("Z", "+00:00")))
        cap = (f"{label} on the atmospheric-model lattice at {when} (atmospheric model, not a measurement). Cells are about 0.4 degrees (44 km), so the field is a few "
               f"large blocks. Dots are the newest station readings on the same colour scale (observations, of varying age); arrows are the weather model's 10 m wind.")
        out.append(Figure(charts.field_map(lats, lons, grid, unit, arrows=arrows, points=points, marker=(lat, lon, name)), cap, alt=f"Map of modelled {label}"))
        if n_skipped:
            out.append(Paragraph(f"{n_skipped} station reading(s) are in a different unit and are not drawn on this scale.", muted=True))
        # domain mean through time
        vals = var["values"]
        mean_series = []
        for t in range(len(cams["times"])):
            flat = [v for row in vals[t] for v in row if v is not None]
            mean_series.append(sum(flat) / len(flat) if flat else None)
        times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in cams["times"]]
        out.append(Figure(charts.line_chart(times, [(f"Domain mean {label} ({unit})", mean_series, "#7c3aed")], unit, zero_based=True),
                          f"Mean of the atmospheric-model lattice over Delhi-NCR, 12 hours back to 48 hours ahead (atmospheric model, forecast beyond now), IST."))
        if wf is not None:
            wk = _nearest(wf["times"], cams["times"][k])
            blh = wf["variables"].get("boundary_layer_height")
            if wk is not None and blh and blh.get("available"):
                out.append(Figure(charts.field_map(wf["grid"]["lats"], wf["grid"]["lons"], blh["values"][wk], blh["unit"], arrows=arrows, marker=(lat, lon, name)),
                                  "Boundary-layer height, weather model, same hour. A shallow layer holds emissions in a small volume; a deep one dilutes them.",
                                  alt="Map of boundary-layer height"))
        return out

    async def _network_section(self, pollutant: str, label: str) -> list:
        out: list = [Heading(2, f"The station network: latest {label}")]
        listing = await self._air.stations()
        rows = [(s, s.latest[pollutant]) for s in listing.stations if pollutant in s.latest]
        if not rows:
            return out + _na(f"No station currently reports {label}.")
        rows.sort(key=lambda x: -x[1].value)
        top = rows[:15]
        unit = top[0][1].unit
        top = [(s, rd) for s, rd in top if rd.unit == unit]
        vmax = max(rd.value for _, rd in top) or 1.0
        items = [(s.name, rd.value, charts.ramp(rd.value / vmax), f"{rd.age_s / 3600:.0f} h old") for s, rd in top]
        ages = sorted(rd.age_s / 3600 for _, rd in rows)
        med = ages[len(ages) // 2]
        out.append(Figure(charts.hbar_chart(items, unit),
                          f"The {len(top)} highest of {len(rows)} stations reporting {label}: newest observed hour at each, in the sensor's unit (observations). "
                          f"The median reading is {med:.0f} hours old, so these are not 'now'."))
        out.append(Callout("How current is this?", f"The station feed lags: the median newest reading above is {med:.0f} hours old and the oldest is {ages[-1]:.0f} hours old. "
                                                   "Compare with the atmospheric model above, which is current but coarse."))
        return out

    def _forecast_section(self, r: Report, label: str) -> list:
        out: list = [Heading(2, "Forecast")]
        f = r.forecast
        if f.status == "available" and f.times:
            out.append(Paragraph(f"Provided by {f.provider} (model {f.model_version}, issued {ist(f.issued_at)}) [{f.source_id}]. This is not an AEROCAST forecast and is not an observation."))
            series = [(f"{label} forecast ({f.unit})", list(f.values), "#d97706")]
            if f.lower and f.upper:
                series += [(f"lower {int((f.interval_level or 0) * 100) or ''}%", list(f.lower), "#fcd9a8"), ("upper", list(f.upper), "#fcd9a8")]
            out.append(Figure(charts.line_chart(f.times, series, f.unit or ""), f"{label} forecast with its interval, IST (forecast)."))
        else:
            out += _na(f.reason or "No forecast was available.")
        return out

    def _models_section(self) -> list:
        out: list = [Heading(2, "How well the models perform")]
        m = self._model_status()
        if m.get("available"):
            rows = []
            for t in m.get("targets", []):
                te, pe = t.get("test"), t.get("persistence_test")
                rows.append([POLLUTANT_LABELS.get(t["pollutant"], t["pollutant"]), f"+{t['horizon_hours']} h", t.get("model", ""),
                             _num(te["mae"]) if te else "-", _num(pe["mae"]) if pe else "-",
                             "-" if t.get("beats_persistence_on_test") is None else ("yes" if t["beats_persistence_on_test"] else "no")])
            out.append(Paragraph(f"Trained model run **{m.get('run_id')}**, created {str(m.get('created_at'))[:10]}. Errors are mean absolute error in µg/m³ on a held-out later period."))
            out.append(Table(["Pollutant", "Horizon", "Model", "Model error", "Persistence error", "Beats persistence"], rows, [2, 1, 3, 1.5, 1.8, 1.8],
                             caption="Persistence repeats the last observed value. A model is only useful where it beats it."))
        else:
            out += _na(m.get("reason", "No trained model is loaded."))
        try:
            ev = json.loads(self._coupled_eval.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return out + [Paragraph("The coupled-model hindcast results file was not found.", muted=True)]
        cfg_name, cfg = next(iter(ev.get("configs", {}).items()), (None, None))
        if cfg:
            rows_chart = []
            for p, d in cfg.items():
                for base, text in (("vs_persistence", "persistence"), ("vs_passive", "passive transport")):
                    s = d.get(base)
                    if s:
                        rows_chart.append((f"{POLLUTANT_LABELS.get(p, p)} vs {text}", s["median"], s.get("p25"), s.get("p75"), s.get("share_positive")))
            out.append(Heading(3, "The coupled transport model against simple baselines"))
            out.append(Figure(charts.skill_chart(rows_chart),
                              f"Hindcast of the coupled model ({cfg_name}) over {len(ev.get('windows_used', []))} historical {ev.get('hours')}-hour windows, scored at stations "
                              "withheld from the starting field (simulation evaluated against observations)."))
            out.append(Paragraph(f"Skill is {ev.get('scoring', '')}. Negative values mean the model did worse than the baseline. "
                                 "The coupled model has no emissions and did not beat persistence; it is a picture of how air moves, not a forecaster.", muted=True))
        return out

    async def _coverage_section(self) -> list:
        out: list = [Heading(2, "What data the application has, and what it does not")]
        av = await self._availability()
        c = av.get("counts", {})
        out.append(Paragraph("**" + "**, **".join(f"{n} {k}" for k, n in c.items() if n) + "** " + "items are tracked. " + av.get("principle", "")))
        for g in av.get("groups", []):
            out.append(Heading(3, g["label"]))
            out.append(Table(["Data", "Status", "What exists", "What a gap prevents"],
                             [[i["name"], i["status"], i["detail"], i.get("consequence") or "-"] for i in g["items"]], [3, 1.2, 3.5, 3.5]))
        return out

    def _sources_section(self, r: Report) -> list:
        out: list = [Heading(2, "Data freshness, limitations and sources")]
        out.append(Table(["Source", "Status", "Newest data (IST)", "Detail"],
                         [[x.label, x.status, ist(x.latest_data_time) if x.latest_data_time else "-", x.detail] for x in r.freshness], [3, 1.2, 2.6, 4]))
        out.append(Heading(3, "What this report cannot say"))
        out.append(Bullets(r.limitations))
        if r.references.status == "ok" and r.references.items:
            out.append(Heading(3, "Guidance references"))
            out.append(Table(["Reference", "Excerpt"], [[f"[{i.source_id}] {i.title} ({i.category})", f"“{i.excerpt}”"] for i in r.references.items], [2, 4],
                             caption="Passages retrieved from the knowledge base and quoted as found; they are not conclusions of this report."))
        out.append(Heading(3, "Sources"))
        out.append(Table(["ID", "Source", "Retrieved (IST)"], [[s.id, f"{s.title}. {s.provider}" + (f", {s.url}" if s.url else ""), ist(s.retrieved_at)] for s in r.sources], [0.7, 6, 2]))
        return out

    def _article_section(self) -> list:
        arts = self._articles()
        if not arts:
            return []
        out: list = [Heading(2, "Background: the written reports")]
        out.append(Paragraph("The reasoning, evidence and limits behind the figures above, as written in the application's Report page."))
        for title, text in arts:
            out.append(Heading(3, title))
            out += parse_markdown(text, skip_title=True, demote=2)
        return out
