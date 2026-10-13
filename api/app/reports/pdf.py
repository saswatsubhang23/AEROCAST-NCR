"""PDF rendering of a Report with fpdf2 (pure Python). Every figure comes from the Report, never from anywhere else.

fpdf2's built-in fonts only cover Latin-1, so text is transliterated first (PM₂.₅ -> PM2.5, >= for ≥) instead of risking
missing glyphs. The charts are drawn from the hourly series, and a missing hour is a visible gap, never an interpolated line.
"""

from datetime import datetime

from fpdf import FPDF

from app.assistant.fmt import ist
from app.reports.models import Report

_MAP = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "≥": ">=", "≤": "<=", "—": "-", "–": "-", "−": "-", "‘": "'", "’": "'", "“": '"',
    "”": '"', "…": "...", "•": "-", "×": "x", "→": "->", "→": "->", " ": " ", "\n": " ",
})
ACCENT = (14, 116, 144)
INK = (20, 28, 44)
MUTED = (96, 108, 130)
LINE = (200, 208, 220)


def latin(text: object) -> str:
    s = str(text).translate(_MAP)
    return s.encode("latin-1", "replace").decode("latin-1")


class _Pdf(FPDF):
    def footer(self) -> None:  # noqa: D401
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, latin(f"AEROCAST NCR - report {self.report_id} - values as retrieved; see Sources"), align="L")
        self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")


def _h(pdf: FPDF, text: str) -> None:
    if pdf.get_y() > 255:
        pdf.add_page()
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 12)
    pdf.set_text_color(*ACCENT)
    pdf.cell(0, 7, latin(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*LINE)
    pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
    pdf.ln(2)
    pdf.set_text_color(*INK)


def _p(pdf: FPDF, text: str, *, size: float = 9.5, italic: bool = False, color=INK) -> None:
    pdf.set_font("Helvetica", "I" if italic else "", size)
    pdf.set_text_color(*color)
    pdf.multi_cell(0, 4.6, latin(text), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _bullets(pdf: FPDF, items: list[str]) -> None:
    for t in items:
        pdf.set_font("Helvetica", "", 9.5)
        pdf.set_text_color(*INK)
        pdf.set_x(pdf.l_margin + 3)
        pdf.multi_cell(pdf.w - pdf.l_margin - pdf.r_margin - 3, 4.6, latin("- " + t), new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1)


def _table(pdf: FPDF, header: list[str], rows: list[list[str]], widths: tuple[float, ...]) -> None:
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*INK)
    with pdf.table(col_widths=widths, line_height=4.6, first_row_as_headings=True, text_align="LEFT", borders_layout="HORIZONTAL_LINES") as t:
        r = t.row()
        for c in header:
            r.cell(latin(c), style=None)
        for row in rows:
            r = t.row()
            for c in row:
                r.cell(latin(c))
    pdf.ln(2)


def _chart(pdf: FPDF, title: str, times: list[datetime], values: list[float | None], unit: str, *, h: float = 42) -> None:
    """A line chart drawn from the hourly series. Runs of consecutive observations are joined; gaps stay gaps."""
    known = [v for v in values if v is not None]
    if not known:
        return
    if pdf.get_y() + h + 14 > 280:
        pdf.add_page()
    x0, w = pdf.l_margin + 12, pdf.w - pdf.l_margin - pdf.r_margin - 14
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_text_color(*INK)
    pdf.cell(0, 5, latin(f"{title} ({unit})" if unit else title), new_x="LMARGIN", new_y="NEXT")
    y0 = pdf.get_y() + 1
    lo, hi = min(known), max(known)
    if hi == lo:
        hi, lo = hi + 1, lo - 1
    pad = (hi - lo) * 0.08
    lo, hi = max(0.0, lo - pad) if min(known) >= 0 else lo - pad, hi + pad

    def X(i: int) -> float:
        return x0 + (w * i / max(1, len(values) - 1))

    def Y(v: float) -> float:
        return y0 + h - (v - lo) / (hi - lo) * h

    pdf.set_draw_color(*LINE)
    pdf.set_line_width(0.2)
    for frac in (0, 0.5, 1):
        yy = y0 + h * frac
        pdf.line(x0, yy, x0 + w, yy)
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*MUTED)
        pdf.set_xy(pdf.l_margin, yy - 1.8)
        pdf.cell(11, 3.6, f"{hi - (hi - lo) * frac:.4g}", align="R")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.5)
    prev: int | None = None
    for i, v in enumerate(values):
        if v is None:
            prev = None
            continue
        if prev is not None:
            pdf.line(X(prev), Y(values[prev]), X(i), Y(v))  # type: ignore[arg-type]
        else:  # a point after a gap: mark it so an isolated reading is still visible
            pdf.set_fill_color(*ACCENT)
            pdf.ellipse(X(i) - 0.6, Y(v) - 0.6, 1.2, 1.2, style="F")
        prev = i
    pdf.set_line_width(0.2)
    pdf.set_font("Helvetica", "", 7)
    pdf.set_text_color(*MUTED)
    pdf.set_xy(x0, y0 + h + 1)
    pdf.cell(w / 2, 3.6, latin(ist(times[0])), align="L")
    pdf.cell(w / 2, 3.6, latin(ist(times[-1])), align="R")
    pdf.set_y(y0 + h + 6)
    pdf.set_text_color(*INK)


def render_pdf(r: Report) -> bytes:
    pdf = _Pdf(format="A4")
    pdf.report_id = r.id  # type: ignore[attr-defined]
    pdf.set_margins(16, 14, 16)
    pdf.set_auto_page_break(True, 16)
    pdf.alias_nb_pages()
    pdf.set_title(latin(f"AEROCAST NCR report: {r.location.name}"))
    pdf.set_author("AEROCAST NCR")
    pdf.set_creator("AEROCAST NCR")
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 17)
    pdf.set_text_color(*INK)
    pdf.cell(0, 9, "AEROCAST NCR", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 12)
    pdf.cell(0, 6, latin(f"Air-quality and weather report: {r.location.name}"), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4.6, latin(f"Period: {ist(r.period.start)} to {ist(r.period.end)} ({r.period.hours} hours). Generated {ist(r.created_at)}. Report id {r.id}."), new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(*ACCENT)
    pdf.set_line_width(0.8)
    pdf.line(pdf.l_margin, pdf.get_y() + 1, pdf.w - pdf.r_margin, pdf.get_y() + 1)
    pdf.set_line_width(0.2)
    pdf.ln(3)

    if r.llm_summary.status == "ok" and r.llm_summary.text:
        _h(pdf, "Summary")
        _p(pdf, r.llm_summary.text)
        _p(pdf, r.llm_summary.label, size=8, italic=True, color=MUTED)
    _h(pdf, "Key facts")
    _bullets(pdf, r.facts_summary)

    # ---- air quality
    a = r.air
    _h(pdf, f"{a.label} observations")
    if a.status != "ok" or not a.stats or not a.station:
        _p(pdf, f"Not available. {a.reason or ''}")
    else:
        s, u = a.stats, a.stats.unit or ""
        _p(pdf, f"Station: {a.station.name} ({a.station.distance_km:.1f} km from the {r.location.name} centre). Provider: {a.station.provider or 'unknown'}. Source [{a.source_id}]." + (f" Licence: {a.station.licence}." if a.station.licence else ""), size=9)
        _table(pdf, ["Measure", "Value"], [
            ["Hours observed", f"{s.observed_hours} of {s.observed_hours + s.missing_hours} ({s.missing_hours} missing)"],
            ["Latest", f"{s.latest:.1f} {u} at {ist(s.latest_time)}"],
            ["Lowest", f"{s.min:.1f} {u} at {ist(s.min_time)}"], ["Highest", f"{s.max:.1f} {u} at {ist(s.max_time)}"],
            ["Mean", f"{s.mean:.1f} {u}"],
            *([["Largest 6-hour rise", f"+{a.largest_rise.rise:.1f} {u}: {a.largest_rise.from_value:.1f} at {ist(a.largest_rise.from_time)} to {a.largest_rise.to_value:.1f} at {ist(a.largest_rise.to_time)}"]] if a.largest_rise else []),
            *([["Trend", f"{a.trend.first_mean:.1f} to {a.trend.last_mean:.1f} {u} ({a.trend.change:+.1f}); {a.trend.basis}"]] if a.trend else []),
        ], (38, 142))
        _chart(pdf, f"{a.label} - hourly observations, IST", a.times, a.values, u)
        others = [x for x in a.latest_readings if x.pollutant != a.pollutant]
        if others:
            _p(pdf, "Latest readings at the same station (concentrations as reported, not AQI):", size=9)
            _table(pdf, ["Pollutant", "Reading", "Observed (IST)", "Note"], [[x.label, f"{x.value:g} {x.unit}", ist(x.observed_at), "stale" if x.stale else ""] for x in others], (28, 42, 70, 40))

    # ---- weather
    _h(pdf, "Weather over the period")
    w = r.weather
    if w.status != "ok":
        _p(pdf, f"Not available. {w.reason or ''}")
    else:
        _p(pdf, f"Weather-model values for the grid cell at {w.grid_lat:.2f} N, {w.grid_lon:.2f} E (elevation {w.elevation_m} m). Not station measurements. Source [{w.source_id}].", size=9)
        rows = [[v.label, f"{v.min:.1f}", f"{v.max:.1f}", f"{v.mean:.1f}", v.unit] for v in w.variables if v.min is not None]
        if w.rain_total_mm is not None:
            rows.append(["Precipitation", "-", "-", f"{w.rain_total_mm:.1f} total", f"mm, {w.rainy_hours} rainy hours"])
        _table(pdf, ["Variable", "Min", "Max", "Mean", "Unit"], rows, (50, 24, 24, 34, 48))
        if "temperature_2m" in w.series:
            _chart(pdf, "Temperature - hourly, IST", w.times, w.series["temperature_2m"], "deg C", h=34)
        if "wind_speed_10m" in w.series:
            _chart(pdf, "Wind speed - hourly, IST", w.times, w.series["wind_speed_10m"], "km/h", h=34)

    # ---- atmosphere + coinciding
    at = r.atmosphere
    _h(pdf, "Atmospheric conditions (descriptive indicators)")
    if at.status != "ok":
        _p(pdf, f"Not available. {at.reason or ''}")
    else:
        items = []
        if at.ventilation_index_latest is not None:
            items.append(f"Ventilation index (boundary layer height x wind speed): latest {at.ventilation_index_latest:.0f} m2/s, mean {at.ventilation_index_mean:.0f} m2/s.")
        items.append(f"Hours since rain: {at.hours_since_rain if at.hours_since_rain is not None else 'unknown'}." + (f" {at.hours_since_rain_note}" if at.hours_since_rain_note else ""))
        _bullets(pdf, items)
        _p(pdf, at.definition, size=8, italic=True, color=MUTED)
    c = r.coinciding
    if c.status == "ok":
        _h(pdf, f"Weather during the largest rise ({ist(c.window_start)} to {ist(c.window_end)})")
        _table(pdf, ["Variable", "During the rise", "Period mean", "Relation"], [
            [i.label, f"{i.during:.1f} {i.unit}", "-" if i.period_mean is None else f"{i.period_mean:.1f} {i.unit}", "" if i.relation == "unknown" else i.relation] for i in c.items], (58, 46, 46, 30))
        _p(pdf, c.caution, size=8.5, italic=True, color=MUTED)

    # ---- references + forecast
    _h(pdf, "Scientific and guidance references")
    if r.references.status == "ok":
        for i in r.references.items:
            _p(pdf, f"[{i.source_id}] {i.title} - {i.category}" + (f", {i.location}" if i.location else "") + f" (relevance {i.relevance:.2f})", size=9)
            _p(pdf, f'"{i.excerpt}"', size=8.5, italic=True, color=MUTED)
        _p(pdf, "Retrieved passages from the knowledge base, quoted as found; they are not conclusions of this report.", size=8, color=MUTED)
    else:
        _p(pdf, r.references.reason or "None cited.")
    _h(pdf, "Forecast")
    f = r.forecast
    if f.status == "available":
        _p(pdf, f"Provided by {f.provider} (model {f.model_version}, issued {ist(f.issued_at)}) [{f.source_id}]. This is not an AEROCAST forecast and is not an observation.", size=9)
        _chart(pdf, f"{a.label} - external forecast, IST", f.times, list(f.values), f.unit or "", h=30)
    else:
        _p(pdf, f.reason)

    # ---- freshness, limitations, sources
    _h(pdf, "Data freshness")
    _table(pdf, ["Source", "Status", "Newest data (IST)", "Detail"], [[x.label, x.status, ist(x.latest_data_time) if x.latest_data_time else "-", x.detail] for x in r.freshness], (40, 20, 48, 72))
    _h(pdf, "What this report cannot say")
    _bullets(pdf, r.limitations)
    _h(pdf, "Sources")
    _table(pdf, ["ID", "Source", "Retrieved (IST)"], [[s.id, f"{s.title}. {s.provider}" + (f", {s.url}" if s.url else ""), ist(s.retrieved_at)] for s in r.sources], (12, 120, 48))
    return bytes(pdf.output())
