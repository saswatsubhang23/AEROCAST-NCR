"""Executive PDF report generator for Batch Coordinate PM2.5 Analysis using fpdf2.

Aesthetic Features:
- Executive Navy Hero Header (#0b132b) with brand typography and metadata banner
- Executive Status Alert Callout Box with dynamic risk-level styling
- 6 Key Performance Indicator Cards (Mean, Median, CPCB Non-Compliance, WHO Exceedance, Cleanest, Peak Hotspot)
- Full-Width Multi-Segment AQI Distribution Spectrum Bar
- CPCB Category Breakdown Table with in-cell proportion bars & health notes
- Regulatory Benchmark Reference Matrix (CPCB 24h & Annual, WHO 24h & Annual)
- State-Level Comparative Vector Bar Chart with CPCB 60 ug/m3 Reference Line
- State & Territory Regional Rankings Table with AQI category badges
- Hotspot Spotlight: Top Critical Pollution Hotspots & Cleanest Baseline Coordinates
- Actionable Operational & Public Health Guidance Matrix
- Spatial Coordinate Registry Appendix with clean pagination and repeating headers
- Model Provenance & CPCB Regulatory Compliance Notice Box
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

from fpdf import FPDF

# Translation table to prevent Latin-1 encoding errors with unicode characters
_MAP = str.maketrans({
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4", "₅": "5",
    "≥": ">=", "≤": "<=", "—": "-", "–": "-", "−": "-",
    "‘": "'", "’": "'", "“": '"', "”": '"', "…": "...", "•": "-",
    "×": "x", "→": "->", "←": "<-", "µ": "u", "³": "3", "²": "2",
    " ": " ", "\n": " ", "°": " deg ", "·": "|", "\t": " ",
})

# Refined Color Palette
NAVY_PRIMARY = (11, 19, 43)      # #0b132b deep slate / brand hero
NAVY_HEADER = (15, 23, 42)       # #0f172a slate-900 table header
TEXT_INK = (15, 23, 42)          # #0f172a dark readable text
TEXT_MUTED = (100, 116, 139)     # #64748b secondary text
LINE_BORDER = (226, 232, 240)    # #e2e8f0 border lines
BG_LIGHT = (248, 250, 252)       # #f8fafc subtle card fill
BG_ZEBRA = (241, 245, 249)       # #f1f5f9 alternate table row

TEAL_ACCENT = (14, 116, 144)     # #0e7490 cyan/teal primary accent
EMERALD_GREEN = (16, 185, 129)   # #10b981 positive/clean
LIME_SAT = (132, 204, 22)        # #84cc16 satisfactory
AMBER_WARN = (234, 179, 8)       # #eab308 moderate
ORANGE_POOR = (249, 115, 22)     # #f97316 poor
ROSE_RED = (239, 68, 68)         # #ef4444 very poor
CRIMSON_SEVERE = (185, 28, 28)   # #b91c1c severe

CPCB_COLORS: dict[str, tuple[tuple[int, int, int], tuple[int, int, int]]] = {
    "Good": (EMERALD_GREEN, (209, 250, 229)),
    "Satisfactory": (LIME_SAT, (236, 252, 203)),
    "Moderately polluted": (AMBER_WARN, (254, 240, 138)),
    "Poor": (ORANGE_POOR, (255, 237, 213)),
    "Very poor": (ROSE_RED, (254, 226, 226)),
    "Severe": (CRIMSON_SEVERE, (254, 202, 202)),
    "Unknown": (TEXT_MUTED, (241, 245, 249)),
}


def latin(text: object) -> str:
    """Sanitizes strings to safe Latin-1 text for fpdf2."""
    s = str(text if text is not None else "").translate(_MAP)
    return s.encode("latin-1", "replace").decode("latin-1")


class _BatchPdf(FPDF):
    def __init__(self, doc_title: str) -> None:
        super().__init__(format="A4")
        self.doc_title = doc_title
        self.set_margins(14, 12, 14)
        self.set_auto_page_break(auto=True, margin=15)

    def header(self) -> None:
        if self.page_no() > 1:
            self.set_font("Helvetica", "B", 7)
            self.set_text_color(*TEXT_MUTED)
            self.cell(0, 4, latin(f"AEROCAST INTELLIGENCE  |  {self.doc_title}"), align="L")
            self.set_draw_color(*LINE_BORDER)
            self.set_line_width(0.2)
            self.line(self.l_margin, self.get_y() + 5, self.w - self.r_margin, self.get_y() + 5)
            self.ln(6)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*TEXT_MUTED)
        self.cell(
            0,
            4,
            latin("AEROCAST NCR | Spatial PM2.5 Analysis | Source: Open-Meteo ECMWF CAMS Atmospheric Model"),
            align="L",
        )
        self.cell(0, 4, f"Page {self.page_no()} of {{nb}}", align="R")


def render_batch_pdf(
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
    title: str = "Spatial PM2.5 Coordinate Batch Intelligence Report",
) -> bytes:
    pdf = _BatchPdf(doc_title=title)
    pdf.alias_nb_pages()

    width = pdf.w - pdf.l_margin - pdf.r_margin  # 182 mm
    cur_x = pdf.l_margin

    # Extract numerical series
    valid_pm_vals = [
        float(r["current_pm25"])
        for r in rows
        if r.get("current_pm25") is not None and not math.isnan(float(r["current_pm25"]))
    ]
    total_locs = summary.get("valid_count", len(rows))
    invalid_locs = summary.get("invalid_count", 0)

    avg_pm = summary.get("avg_pm25")
    if avg_pm is None and valid_pm_vals:
        avg_pm = sum(valid_pm_vals) / len(valid_pm_vals)
    avg_pm_val = avg_pm if avg_pm is not None else 0.0

    med_pm_val = statistics.median(valid_pm_vals) if valid_pm_vals else avg_pm_val
    cpcb_exceed_count = sum(1 for v in valid_pm_vals if v > 60.0)
    cpcb_exceed_pct = (cpcb_exceed_count / len(valid_pm_vals) * 100.0) if valid_pm_vals else 0.0

    who_exceed_count = sum(1 for v in valid_pm_vals if v > 15.0)
    who_exceed_pct = (who_exceed_count / len(valid_pm_vals) * 100.0) if valid_pm_vals else 0.0

    min_loc = summary.get("min_location") or {}
    max_loc = summary.get("max_location") or {}

    min_val = min_loc.get("value")
    max_val = max_loc.get("value")

    def section_heading(num: str, heading_title: str) -> None:
        pdf.set_font("Helvetica", "B", 8.8)
        pdf.set_text_color(*TEAL_ACCENT)
        pdf.cell(5.5, 4.8, num)
        pdf.set_text_color(*TEXT_INK)
        pdf.cell(0, 4.8, latin(heading_title.upper()), new_x="LMARGIN", new_y="NEXT")
        pdf.set_draw_color(*TEAL_ACCENT)
        pdf.set_line_width(0.35)
        pdf.line(pdf.l_margin, pdf.get_y() + 0.5, pdf.w - pdf.r_margin, pdf.get_y() + 0.5)
        pdf.ln(2.2)

    # =========================================================================
    # PAGE 1: EXECUTIVE BRIEFING & DASHBOARD
    # =========================================================================
    pdf.add_page()

    # 1. TOP HEADER BANNER
    banner_h = 24.0
    y_start = pdf.get_y()
    pdf.set_fill_color(*NAVY_PRIMARY)
    pdf.rect(cur_x, y_start, width, banner_h, style="F")

    # Left Accent Bar
    pdf.set_fill_color(*TEAL_ACCENT)
    pdf.rect(cur_x, y_start, 2.5, banner_h, style="F")

    # Kicker Pill
    pdf.set_xy(cur_x + 6, y_start + 3.8)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*TEAL_ACCENT)
    pdf.cell(0, 3.8, latin("AEROCAST INTELLIGENCE  |  EXECUTIVE SPATIAL PM2.5 DOSSIER"))

    # Title
    pdf.set_xy(cur_x + 6, y_start + 8.5)
    pdf.set_font("Helvetica", "B", 13.5)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 6, latin(title.upper()))

    # Subtitle
    pdf.set_xy(cur_x + 6, y_start + 15.8)
    pdf.set_font("Helvetica", "", 7.8)
    pdf.set_text_color(203, 213, 225)
    pdf.cell(0, 4, latin("Copernicus ECMWF CAMS Atmospheric Chemistry & Dispersion Model Output across India"))

    pdf.set_y(y_start + banner_h + 3.0)

    # 2. METADATA STRIP (Clean 4-column balanced layout)
    meta_h = 9.0
    m_y = pdf.get_y()
    pdf.set_fill_color(*BG_LIGHT)
    pdf.set_draw_color(*LINE_BORDER)
    pdf.set_line_width(0.2)
    pdf.rect(cur_x, m_y, width, meta_h, style="DF")

    gen_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    meta_items = [
        ("GENERATED:", gen_utc, 44),
        ("LOCATIONS:", f"{total_locs:,} valid ({invalid_locs} skipped)", 48),
        ("SPATIAL MODEL:", "ECMWF CAMS (~44 km)", 50),
        ("GRID TYPE:", "Batch Multi-Point", 40),
    ]

    mx = cur_x + 3
    for m_label, m_val, m_w in meta_items:
        pdf.set_xy(mx, m_y + 2.2)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(*TEXT_MUTED)
        lbl_w = pdf.get_string_width(m_label) + 1.5
        pdf.cell(lbl_w, 4, m_label)

        pdf.set_font("Helvetica", "", 6.8)
        pdf.set_text_color(*TEXT_INK)
        pdf.cell(m_w - lbl_w, 4, latin(m_val))
        mx += m_w

    pdf.set_y(m_y + meta_h + 3.5)

    # 3. EXECUTIVE VERDICT CALLOUT BANNER
    callout_y = pdf.get_y()
    callout_h = 13.0

    if avg_pm_val > 120.0:
        v_title = "CRITICAL AIR POLLUTION ALERT"
        v_color = ROSE_RED
        v_bg = (254, 242, 242)
    elif avg_pm_val > 60.0:
        v_title = "ELEVATED EXPOSURE WARNING"
        v_color = ORANGE_POOR
        v_bg = (255, 247, 237)
    elif avg_pm_val > 30.0:
        v_title = "MODERATE POLLUTION LEVEL"
        v_color = AMBER_WARN
        v_bg = (254, 252, 232)
    else:
        v_title = "FAVORABLE AIR QUALITY"
        v_color = EMERALD_GREEN
        v_bg = (240, 253, 244)

    pdf.set_fill_color(*v_bg)
    pdf.set_draw_color(*v_color)
    pdf.set_line_width(0.3)
    pdf.rect(cur_x, callout_y, width, callout_h, style="DF")

    pdf.set_fill_color(*v_color)
    pdf.rect(cur_x, callout_y, 2.5, callout_h, style="F")

    pdf.set_xy(cur_x + 6, callout_y + 1.8)
    pdf.set_font("Helvetica", "B", 7.5)
    pdf.set_text_color(*v_color)
    pdf.cell(0, 4, latin(f"EXECUTIVE ASSESSMENT: {v_title} (DATASET MEAN: {avg_pm_val:.1f} ug/m3)"))

    pdf.set_xy(cur_x + 6, callout_y + 6.2)
    pdf.set_font("Helvetica", "", 7.2)
    pdf.set_text_color(*TEXT_INK)
    callout_desc = (
        f"{cpcb_exceed_pct:.1f}% of surveyed coordinates exceed the National Ambient Air Quality Standard (24-hr CPCB: 60 ug/m3). "
        f"{who_exceed_pct:.1f}% breach WHO Health Guidelines (15 ug/m3). Peak exposure recorded at "
        f"{latin(max_loc.get('place', 'N/A'))} ({max_val:.1f} ug/m3)."
    )
    pdf.multi_cell(width - 9, 3.2, callout_desc)

    pdf.set_y(callout_y + callout_h + 4.0)

    # 4. KEY PERFORMANCE INDICATORS (6 CARDS IN 2 ROWS OF 3)
    card_w = (width - 6) / 3.0  # 58.6 mm each
    card_h = 22.5
    kpi_y = pdf.get_y()

    kpi_cards = [
        # Row 1
        (
            "DATASET MEAN PM2.5",
            TEAL_ACCENT,
            f"{avg_pm_val:.1f}",
            "ug/m3",
            f"Across {total_locs:,} valid coordinates",
            "Arithmetic Average",
        ),
        (
            "MEDIAN PM2.5 (P50)",
            TEAL_ACCENT,
            f"{med_pm_val:.1f}",
            "ug/m3",
            "Robust 50th percentile",
            "Spatial Centerpoint",
        ),
        (
            "CPCB NON-COMPLIANCE",
            ROSE_RED if cpcb_exceed_pct > 50 else AMBER_WARN,
            f"{cpcb_exceed_pct:.1f}%",
            "",
            f"{cpcb_exceed_count} of {total_locs} points",
            "> 60 ug/m3 Standard",
        ),
        # Row 2
        (
            "WHO EXCEEDANCE RATE",
            ORANGE_POOR,
            f"{who_exceed_pct:.1f}%",
            "",
            f"{who_exceed_count} of {total_locs} points",
            "> 15 ug/m3 Guideline",
        ),
        (
            "CLEANEST LOCATION",
            EMERALD_GREEN,
            f"{min_val:.1f}" if min_val is not None else "N/A",
            "ug/m3",
            f"{latin(min_loc.get('place', 'N/A'))[:22]}",
            latin(min_loc.get("state", "Green Zone") or "Green Zone")[:22],
        ),
        (
            "PEAK HOTSPOT",
            CRIMSON_SEVERE,
            f"{max_val:.1f}" if max_val is not None else "N/A",
            "ug/m3",
            f"{latin(max_loc.get('place', 'N/A'))[:22]}",
            latin(max_loc.get("state", "Peak") or "Peak")[:22],
        ),
    ]

    for idx, (c_label, c_color, c_val, c_unit, c_p1, c_p2) in enumerate(kpi_cards):
        col_idx = idx % 3
        row_idx = idx // 3
        cx = cur_x + col_idx * (card_w + 3)
        cy = kpi_y + row_idx * (card_h + 3)

        pdf.set_fill_color(*BG_LIGHT)
        pdf.set_draw_color(*LINE_BORDER)
        pdf.set_line_width(0.2)
        pdf.rect(cx, cy, card_w, card_h, style="DF")

        # Top Accent Stripe
        pdf.set_fill_color(*c_color)
        pdf.rect(cx, cy, card_w, 1.8, style="F")

        # Card Label
        pdf.set_xy(cx + 3, cy + 2.8)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.cell(card_w - 6, 3.2, latin(c_label))

        # Value
        pdf.set_xy(cx + 3, cy + 6.2)
        pdf.set_font("Helvetica", "B", 13)
        pdf.set_text_color(*TEXT_INK)
        val_w = pdf.get_string_width(c_val)
        pdf.cell(val_w + 1, 6.2, latin(c_val))

        if c_unit:
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*TEXT_MUTED)
            pdf.cell(0, 6.2, latin(f" {c_unit}"))

        # Line 1 Details
        pdf.set_xy(cx + 3, cy + 13.2)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(*TEXT_INK)
        pdf.cell(card_w - 6, 3.2, latin(c_p1))

        # Line 2 Subtitle
        pdf.set_xy(cx + 3, cy + 16.8)
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.cell(card_w - 6, 3.2, latin(c_p2))

    pdf.set_y(kpi_y + 2 * (card_h + 3) + 3.0)

    # 5. CPCB AIR QUALITY CATEGORY DISTRIBUTION TABLE
    section_heading("1", "National Air Quality Index (CPCB) Category Distribution")

    cat_dist = summary.get("category_distribution") or {}
    cat_ranges = [
        ("Good", "0.0 - 30.0", "Minimal health impact; clean pristine ambient air"),
        ("Satisfactory", "30.1 - 60.0", "Minor breathing discomfort to sensitive individuals"),
        ("Moderately polluted", "60.1 - 90.0", "Breathing discomfort to people with asthma / lungs"),
        ("Poor", "90.1 - 120.0", "Breathing discomfort to most people on prolonged exposure"),
        ("Very poor", "120.1 - 250.0", "Respiratory illness to people on prolonged exposure"),
        ("Severe", "> 250.0", "Severe health impacts on healthy population and vulnerable"),
    ]

    # Full-Width Stacked Category Distribution Spectrum Bar
    spec_y = pdf.get_y()
    spec_h = 4.2
    cur_bx = cur_x
    for cat_name, _, _ in cat_ranges:
        cnt = cat_dist.get(cat_name, 0)
        pct = (cnt / total_locs * 100) if total_locs else 0.0
        seg_w = (pct / 100.0) * width
        if seg_w > 0:
            c_color, _ = CPCB_COLORS.get(cat_name, (TEXT_MUTED, BG_LIGHT))
            pdf.set_fill_color(*c_color)
            pdf.rect(cur_bx, spec_y, seg_w, spec_h, style="F")
            cur_bx += seg_w
    pdf.set_draw_color(*LINE_BORDER)
    pdf.rect(cur_x, spec_y, width, spec_h, style="D")
    pdf.set_y(spec_y + spec_h + 2.5)

    col_w = (32, 24, 18, 16, 42, 50)  # Total 182 mm
    cat_headers = ["CATEGORY", "PM2.5 RANGE", "COUNT", "SHARE", "PROPORTION BAR", "HEALTH IMPLICATION"]

    th_y = pdf.get_y()
    pdf.set_fill_color(*NAVY_HEADER)
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 7)

    hx = cur_x
    for idx, w_c in enumerate(col_w):
        pdf.rect(hx, th_y, w_c, 5.0, style="F")
        pdf.set_xy(hx + 1.5, th_y + 0.6)
        pdf.cell(w_c - 3, 3.8, cat_headers[idx], align="R" if idx in (1, 2, 3) else "L")
        hx += w_c

    pdf.set_y(th_y + 5.0)

    for i, (cat_name, cat_range, cat_health) in enumerate(cat_ranges):
        cnt = cat_dist.get(cat_name, 0)
        pct = (cnt / total_locs * 100) if total_locs else 0.0
        row_y = pdf.get_y()
        row_h = 4.8

        pdf.set_fill_color(*(BG_LIGHT if i % 2 == 0 else (255, 255, 255)))
        pdf.rect(cur_x, row_y, width, row_h, style="F")

        cat_color, _ = CPCB_COLORS.get(cat_name, (TEXT_MUTED, BG_LIGHT))

        # Color dot + Category Name
        pdf.set_fill_color(*cat_color)
        pdf.rect(cur_x + 2, row_y + 1.4, 2.2, 2.2, style="F")

        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*TEXT_INK)
        pdf.set_xy(cur_x + 5.5, row_y + 0.5)
        pdf.cell(col_w[0] - 5.5, row_h, latin(cat_name))

        # Range
        pdf.set_font("Helvetica", "", 6.8)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + col_w[0], row_y + 0.5)
        pdf.cell(col_w[1] - 3, row_h, latin(cat_range), align="R")

        # Count
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*TEXT_INK)
        pdf.set_xy(cur_x + col_w[0] + col_w[1], row_y + 0.5)
        pdf.cell(col_w[2] - 3, row_h, f"{cnt:,}", align="R")

        # Share
        pdf.set_font("Helvetica", "", 7)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + col_w[0] + col_w[1] + col_w[2], row_y + 0.5)
        pdf.cell(col_w[3] - 3, row_h, f"{pct:.1f}%", align="R")

        # Visual Bar Track
        bar_x = cur_x + col_w[0] + col_w[1] + col_w[2] + col_w[3] + 3
        bar_track_w = col_w[4] - 6
        bar_fill_w = max(0.5, (pct / 100.0) * bar_track_w) if pct > 0 else 0

        pdf.set_fill_color(*LINE_BORDER)
        pdf.rect(bar_x, row_y + 1.5, bar_track_w, 2.0, style="F")

        if bar_fill_w > 0:
            pdf.set_fill_color(*cat_color)
            pdf.rect(bar_x, row_y + 1.5, bar_fill_w, 2.0, style="F")

        # Health note
        pdf.set_font("Helvetica", "", 6.2)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + sum(col_w[:5]) + 1.5, row_y + 0.5)
        pdf.cell(col_w[5] - 2, row_h, latin(cat_health))

        pdf.set_y(row_y + row_h)

    pdf.set_draw_color(*LINE_BORDER)
    pdf.line(cur_x, pdf.get_y(), cur_x + width, pdf.get_y())
    pdf.ln(3.5)

    # 6. REGULATORY BENCHMARK SUMMARY STRIP
    bench_y = pdf.get_y()
    bench_h = 13.0
    pdf.set_fill_color(*BG_LIGHT)
    pdf.set_draw_color(*LINE_BORDER)
    pdf.set_line_width(0.2)
    pdf.rect(cur_x, bench_y, width, bench_h, style="DF")

    pdf.set_xy(cur_x + 3, bench_y + 1.5)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*TEAL_ACCENT)
    pdf.cell(0, 3.5, latin("REGULATORY & EPIDEMIOLOGICAL BENCHMARKS REFERENCE"))

    benchmarks = [
        ("CPCB 24-Hour Standard:", "60 ug/m3", f"{cpcb_exceed_pct:.1f}% exceedance"),
        ("CPCB Annual Standard:", "40 ug/m3", f"{sum(1 for v in valid_pm_vals if v > 40)/max(1, len(valid_pm_vals))*100:.1f}% exceedance"),
        ("WHO 24-Hour Guideline:", "15 ug/m3", f"{who_exceed_pct:.1f}% exceedance"),
        ("WHO Annual Guideline:", "5 ug/m3", "100.0% exceedance"),
    ]

    bx = cur_x + 3
    b_col_w = (width - 6) / 4.0
    for b_title, b_thresh, b_stat in benchmarks:
        pdf.set_xy(bx, bench_y + 5.0)
        pdf.set_font("Helvetica", "B", 6.5)
        pdf.set_text_color(*TEXT_INK)
        pdf.cell(b_col_w, 3.0, latin(b_title))

        pdf.set_xy(bx, bench_y + 8.2)
        pdf.set_font("Helvetica", "", 6.2)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.cell(b_col_w, 3.0, latin(f"Threshold: {b_thresh}  ({b_stat})"))
        bx += b_col_w

    # =========================================================================
    # PAGE 2: REGIONAL RANKINGS & CRITICAL HOTSPOTS SPOTLIGHT
    # =========================================================================
    pdf.add_page()

    # Section 2: STATE & UT REGIONAL RANKINGS
    state_sums = summary.get("state_summaries") or []
    if state_sums:
        section_heading("2", "State & Union Territory PM2.5 Regional Exposure Rankings")

        st_cols = (9, 45, 18, 28, 38, 24, 20)  # Total 182 mm
        st_headers = ["#", "STATE / TERRITORY", "POINTS", "MEAN PM2.5", "SPREAD (MIN - MAX)", "DOMINANT AQI", "EXCEED %"]

        sth_y = pdf.get_y()
        pdf.set_fill_color(*NAVY_HEADER)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 7)

        hx = cur_x
        for idx, w_c in enumerate(st_cols):
            pdf.rect(hx, sth_y, w_c, 5.0, style="F")
            pdf.set_xy(hx + 1.2, sth_y + 0.6)
            pdf.cell(w_c - 2.4, 3.8, st_headers[idx], align="R" if idx in (2, 3, 4, 6) else "L")
            hx += w_c

        pdf.set_y(sth_y + 5.0)

        # Show up to top 10 states in table
        table_states = state_sums[:10]
        for rank, s in enumerate(table_states, start=1):
            r_y = pdf.get_y()
            r_h = 4.6

            pdf.set_fill_color(*(BG_LIGHT if rank % 2 == 1 else (255, 255, 255)))
            pdf.rect(cur_x, r_y, width, r_h, style="F")

            # Rank
            pdf.set_font("Helvetica", "", 6.8)
            pdf.set_text_color(*TEXT_MUTED)
            pdf.set_xy(cur_x, r_y + 0.4)
            pdf.cell(st_cols[0], r_h, str(rank), align="C")

            # State Name
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*TEXT_INK)
            pdf.set_xy(cur_x + st_cols[0] + 1.2, r_y + 0.4)
            pdf.cell(st_cols[1] - 2, r_h, latin(s.get("state", "Unknown")[:24]))

            # Points Count
            pdf.set_font("Helvetica", "", 6.8)
            pdf.set_text_color(*TEXT_MUTED)
            pdf.set_xy(cur_x + st_cols[0] + st_cols[1], r_y + 0.4)
            pdf.cell(st_cols[2] - 2, r_h, str(s.get("count", 0)), align="R")

            # Mean PM2.5
            pdf.set_font("Helvetica", "B", 7)
            pdf.set_text_color(*TEXT_INK)
            pdf.set_xy(cur_x + sum(st_cols[:3]), r_y + 0.4)
            pdf.cell(st_cols[3] - 2, r_h, f"{s.get('avg_pm25', 0):.1f} ug/m3", align="R")

            # Min-Max Spread
            pdf.set_font("Helvetica", "", 6.8)
            pdf.set_text_color(*TEXT_MUTED)
            pdf.set_xy(cur_x + sum(st_cols[:4]), r_y + 0.4)
            range_str = f"{s.get('min_pm25', 0):.1f} - {s.get('max_pm25', 0):.1f} ug/m3"
            pdf.cell(st_cols[4] - 2, r_h, range_str, align="R")

            # Status pill
            st_cat = s.get("aqi_category", "Unknown")
            cat_c, cat_bg = CPCB_COLORS.get(st_cat, (TEXT_MUTED, BG_LIGHT))
            badge_x = cur_x + sum(st_cols[:5]) + 1.5
            badge_w = st_cols[5] - 3.0
            pdf.set_fill_color(*cat_bg)
            pdf.set_draw_color(*cat_c)
            pdf.rect(badge_x, r_y + 0.8, badge_w, 3.0, style="DF")
            pdf.set_font("Helvetica", "B", 5.8)
            pdf.set_text_color(*cat_c)
            pdf.set_xy(badge_x, r_y + 0.8)
            pdf.cell(badge_w, 3.0, latin(st_cat), align="C")

            # Exceedance note
            st_avg = s.get("avg_pm25", 0)
            exceed_tag = "> 60 ug" if st_avg > 60 else "Compliant"
            ex_color = ROSE_RED if st_avg > 60 else EMERALD_GREEN
            pdf.set_font("Helvetica", "B", 6.5)
            pdf.set_text_color(*ex_color)
            pdf.set_xy(cur_x + sum(st_cols[:6]), r_y + 0.4)
            pdf.cell(st_cols[6] - 2, r_h, exceed_tag, align="R")

            pdf.set_y(r_y + r_h)

        pdf.set_draw_color(*LINE_BORDER)
        pdf.line(cur_x, pdf.get_y(), cur_x + width, pdf.get_y())
        pdf.ln(3.5)

    # Section 3: EXECUTIVE HOTSPOT & CLEAN BASELINE SPOTLIGHT
    section_heading("3", "Executive Spotlight: Critical Exposure Hotspots vs. Cleanest Baselines")

    valid_rows = [r for r in rows if r.get("current_pm25") is not None]
    sorted_hotspots = sorted(valid_rows, key=lambda x: float(x.get("current_pm25", 0)), reverse=True)[:5]
    sorted_clean = sorted(valid_rows, key=lambda x: float(x.get("current_pm25", 0)))[:5]

    spot_w = (width - 4) / 2.0  # 89 mm each
    spot_h = 32.0
    spot_y = pdf.get_y()

    # Left Box: Top 5 Critical Hotspots
    pdf.set_fill_color(*BG_LIGHT)
    pdf.set_draw_color(*ROSE_RED)
    pdf.set_line_width(0.3)
    pdf.rect(cur_x, spot_y, spot_w, spot_h, style="DF")
    pdf.set_fill_color(*ROSE_RED)
    pdf.rect(cur_x, spot_y, spot_w, 4.5, style="F")

    pdf.set_xy(cur_x + 3, spot_y + 0.7)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(spot_w - 6, 3.5, latin("TOP 5 CRITICAL POLLUTION HOTSPOTS"))

    hy = spot_y + 5.5
    for h_i, hr in enumerate(sorted_hotspots, start=1):
        pdf.set_xy(cur_x + 3, hy)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(*TEXT_INK)
        p_name = latin(f"{h_i}. {hr.get('place', 'N/A')}, {hr.get('state', '')}")[:30]
        pdf.cell(spot_w - 28, 4.0, p_name)

        h_val = float(hr.get("current_pm25", 0))
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*ROSE_RED)
        pdf.cell(22, 4.0, f"{h_val:.1f} ug/m3", align="R")
        hy += 4.8

    # Right Box: Top 5 Cleanest Baselines
    rx = cur_x + spot_w + 4
    pdf.set_fill_color(*BG_LIGHT)
    pdf.set_draw_color(*EMERALD_GREEN)
    pdf.set_line_width(0.3)
    pdf.rect(rx, spot_y, spot_w, spot_h, style="DF")
    pdf.set_fill_color(*EMERALD_GREEN)
    pdf.rect(rx, spot_y, spot_w, 4.5, style="F")

    pdf.set_xy(rx + 3, spot_y + 0.7)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(spot_w - 6, 3.5, latin("TOP 5 CLEANEST BASELINE COORDINATES"))

    cy = spot_y + 5.5
    for c_i, cr in enumerate(sorted_clean, start=1):
        pdf.set_xy(rx + 3, cy)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(*TEXT_INK)
        p_name = latin(f"{c_i}. {cr.get('place', 'N/A')}, {cr.get('state', '')}")[:30]
        pdf.cell(spot_w - 28, 4.0, p_name)

        c_val = float(cr.get("current_pm25", 0))
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*EMERALD_GREEN)
        pdf.cell(22, 4.0, f"{c_val:.1f} ug/m3", align="R")
        cy += 4.8

    pdf.set_y(spot_y + spot_h + 3.5)

    # Section 4: ACTIONABLE OPERATIONAL & PUBLIC HEALTH GUIDANCE
    section_heading("4", "Actionable Operational & Public Health Guidance")

    adv_y = pdf.get_y()
    adv_h = 23.0
    pdf.set_fill_color(*BG_LIGHT)
    pdf.set_draw_color(*LINE_BORDER)
    pdf.set_line_width(0.2)
    pdf.rect(cur_x, adv_y, width, adv_h, style="DF")

    pdf.set_fill_color(*TEAL_ACCENT)
    pdf.rect(cur_x, adv_y, 2.5, adv_h, style="F")

    advisories = [
        ("Industrial & Municipalities", "Deploy mechanical road sweepers, enforce GRAP mitigation, and monitor high-emission industrial corridors."),
        ("Vulnerable Demographics", "Elderly, pregnant, and asthma patients should avoid prolonged outdoor exposure during nocturnal boundary layer inversions."),
        ("Schools & Workplaces", "Reschedule sports and strenuous activities to mid-afternoon hours when thermal mixing lowers ground concentrations."),
        ("Sensor Correlation", "Calibrate dense low-cost micro-sensors against these regional ECMWF CAMS reference baselines to eliminate drift."),
    ]

    ay = adv_y + 1.8
    for a_title, a_desc in advisories:
        pdf.set_xy(cur_x + 5, ay)
        pdf.set_font("Helvetica", "B", 6.8)
        pdf.set_text_color(*TEXT_INK)
        t_w = pdf.get_string_width(a_title) + 1.5
        pdf.cell(t_w, 4.2, latin(f"{a_title}:"))

        pdf.set_font("Helvetica", "", 6.6)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.cell(width - 8 - t_w, 4.2, latin(a_desc))
        ay += 5.0

    # =========================================================================
    # PAGE 3+: DETAILED SPATIAL DATA REGISTRY APPENDIX
    # =========================================================================
    pdf.add_page()
    section_heading("5", "Spatial Data Registry Appendix (Surveyed Locations)")

    loc_cols = (9, 36, 40, 31, 24, 23, 19)  # Total 182 mm
    loc_headers = ["#", "STATE", "PLACE / POINT", "COORDINATES", "CURRENT PM2.5", "24H FORECAST", "ELEVATION"]

    def draw_loc_header() -> None:
        lh_y = pdf.get_y()
        pdf.set_fill_color(*NAVY_HEADER)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font("Helvetica", "B", 7)
        hx = cur_x
        for c_i, w_col in enumerate(loc_cols):
            pdf.rect(hx, lh_y, w_col, 5.0, style="F")
            pdf.set_xy(hx + 1.2, lh_y + 0.6)
            pdf.cell(w_col - 2.4, 3.8, loc_headers[c_i], align="R" if c_i in (4, 5, 6) else "L")
            hx += w_col
        pdf.set_y(lh_y + 5.0)

    draw_loc_header()

    display_limit = min(200, len(rows))
    display_rows = rows[:display_limit]

    for idx, r in enumerate(display_rows, start=1):
        if pdf.get_y() > 270:
            pdf.add_page()
            draw_loc_header()

        r_y = pdf.get_y()
        r_h = 4.4

        pdf.set_fill_color(*(BG_LIGHT if idx % 2 == 1 else (255, 255, 255)))
        pdf.rect(cur_x, r_y, width, r_h, style="F")

        # Rank
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x, r_y + 0.3)
        pdf.cell(loc_cols[0], r_h, str(r.get("index", idx)), align="C")

        # State
        pdf.set_font("Helvetica", "", 6.8)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + loc_cols[0] + 1.2, r_y + 0.3)
        pdf.cell(loc_cols[1] - 2, r_h, latin(str(r.get("state", "Unknown"))[:20]))

        # Place
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*TEXT_INK)
        pdf.set_xy(cur_x + loc_cols[0] + loc_cols[1] + 1.2, r_y + 0.3)
        pdf.cell(loc_cols[2] - 2, r_h, latin(str(r.get("place", f"Point {idx}"))[:24]))

        # Coordinates
        lat_v = r.get("latitude")
        lon_v = r.get("longitude")
        lat_str = f"{lat_v:.2f}N" if isinstance(lat_v, (int, float)) else str(lat_v or "")
        lon_str = f"{lon_v:.2f}E" if isinstance(lon_v, (int, float)) else str(lon_v or "")
        coords_str = f"{lat_str}, {lon_str}"
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + sum(loc_cols[:3]), r_y + 0.3)
        pdf.cell(loc_cols[3] - 2, r_h, latin(coords_str))

        # Current PM2.5
        pm_val = r.get("current_pm25")
        pm_str = f"{pm_val:.1f} ug/m3" if pm_val is not None else "-"
        cat_c, _ = CPCB_COLORS.get(r.get("aqi_category", ""), (TEXT_INK, BG_LIGHT))
        pdf.set_font("Helvetica", "B", 7)
        pdf.set_text_color(*cat_c)
        pdf.set_xy(cur_x + sum(loc_cols[:4]), r_y + 0.3)
        pdf.cell(loc_cols[4] - 2, r_h, pm_str, align="R")

        # 24h Average
        avg_val = r.get("forecast_24h_avg")
        avg_str = f"{avg_val:.1f}" if avg_val is not None else "-"
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + sum(loc_cols[:5]), r_y + 0.3)
        pdf.cell(loc_cols[5] - 2, r_h, avg_str, align="R")

        # Elevation
        elev_val = r.get("elevation_m")
        elev_str = f"{int(elev_val)} m" if elev_val is not None and not math.isnan(elev_val) else "-"
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*TEXT_MUTED)
        pdf.set_xy(cur_x + sum(loc_cols[:6]), r_y + 0.3)
        pdf.cell(loc_cols[6] - 2, r_h, elev_str, align="R")

        pdf.set_y(r_y + r_h)

    pdf.set_draw_color(*LINE_BORDER)
    pdf.line(cur_x, pdf.get_y(), cur_x + width, pdf.get_y())
    pdf.ln(5)

    # METHODOLOGY & REGULATORY NOTICE CALLOUT BOX
    if pdf.get_y() > 240:
        pdf.add_page()

    note_y = pdf.get_y()
    note_h = 24.0

    pdf.set_fill_color(*BG_LIGHT)
    pdf.set_draw_color(*LINE_BORDER)
    pdf.set_line_width(0.3)
    pdf.rect(cur_x, note_y, width, note_h, style="DF")

    pdf.set_fill_color(*TEAL_ACCENT)
    pdf.rect(cur_x, note_y, 2.5, note_h, style="F")

    pdf.set_xy(cur_x + 5, note_y + 2.0)
    pdf.set_font("Helvetica", "B", 7)
    pdf.set_text_color(*TEAL_ACCENT)
    pdf.cell(0, 3.5, latin("METHODOLOGY, MODEL RESOLUTION & REGULATORY COMPLIANCE NOTICE"))

    pdf.set_xy(cur_x + 5, note_y + 6.2)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(*TEXT_MUTED)
    notice_text = (
        "1. Atmospheric Chemical Transport Model: Values in this report are retrieved from the Copernicus Atmosphere "
        "Monitoring Service (ECMWF CAMS global atmospheric model) via Open-Meteo Air Quality API. Output represents a ~44 km "
        "spatial grid lattice, reflecting regional chemical composition, dispersion, and emissions rather than micro-local point sensors.\n"
        "2. Ground Truth & Compliance: Modelled concentrations are intended for regional trend assessment and operational planning. "
        "For legal air quality compliance, health alerts, and clinical actions, reference official Continuous Ambient Air Quality "
        "Monitoring Stations (CAAQMS) operated by the Central Pollution Control Board (CPCB) and State Pollution Control Boards."
    )
    pdf.multi_cell(width - 8, 3.4, latin(notice_text))

    return bytes(pdf.output())
