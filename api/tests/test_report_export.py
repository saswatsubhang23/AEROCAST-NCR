import io

import pytest
from pypdf import PdfReader
from test_reports import service

from app.reports import charts
from app.reports.doc import Bullets, Heading, Paragraph, Table, parse_markdown, plain
from app.reports.exporters import render_html, render_pdf
from app.reports.export import ExportBuilder

LATS = [28.1 + 0.1 * i for i in range(10)]
LONS = [76.7 + 0.1 * j for j in range(12)]


def cams_payload(avail=True):
    grid = [[(40.0 + 3 * r + c) for c in range(12)] for r in range(10)]
    n = 6
    return {
        "grid": {"lats": LATS, "lons": LONS, "rows": 10, "cols": 12}, "times": [f"2026-10-10T{h:02d}:00:00Z" for h in range(n)], "now_index": 3,
        "variables": {"pm25": {"label": "PM2.5", "unit": "µg/m³", "available": avail, "values": [grid for _ in range(n)]}},
    }


def wind_payload():
    wl, wo = [28.1 + 0.1 * i for i in range(5)], [76.7 + 0.2 * j for j in range(4)]
    u = [[2.0] * 4 for _ in range(5)]
    v = [[-1.0] * 4 for _ in range(5)]
    blh = [[300.0 + 20 * r for _ in range(4)] for r in range(5)]
    times = [f"2026-10-10T{h:02d}:00:00Z" for h in range(6)]
    return {"grid": {"lats": wl, "lons": wo}, "times": times,
            "variables": {"wind_u": {"available": True, "values": [u] * 6}, "wind_v": {"available": True, "values": [v] * 6},
                          "boundary_layer_height": {"available": True, "unit": "m", "values": [blh] * 6}}}


class FakeCams:
    def __init__(self, fail=False, avail=True):
        self.fail, self.avail = fail, avail

    async def fields(self, past, fwd):
        if self.fail:
            raise RuntimeError("boom")
        return cams_payload(self.avail)


class FakeWeatherFields:
    async def fields(self, mode, past, fwd, *a):
        return wind_payload()


def builder(cams=None, articles=None, model=None):
    rs = service()
    async def avail():
        return {"counts": {"available": 1, "missing": 1}, "principle": "A gap is shown as a gap.", "groups": [
            {"key": "g", "label": "Group", "items": [{"name": "Thing", "status": "missing", "detail": "none", "consequence": "nothing"}]}]}
    return ExportBuilder(rs, cams or FakeCams(), FakeWeatherFields(), rs._air, avail, lambda: model or {"available": False, "reason": "No model."},
                         articles=lambda: articles if articles is not None else [("An article", "# An article\n\n> Summary.\n\n## Part\n\nBody **bold** text.\n")],
                         coupled_eval=None)


# --------------------------------------------------------------------------------------------- markdown and charts
def test_markdown_blocks():
    blocks = parse_markdown("# T\n\n> q\n\n## H\n\nPara one\ncontinues.\n\n- a\n- b\n\n| x | y |\n|---|---|\n| 1 | 2 |\n\n```\ncode\n```\n")
    kinds = [type(b).__name__ for b in blocks]
    assert kinds == ["Quote", "Heading", "Paragraph", "Bullets", "Table", "Code"]
    assert blocks[2].text == "Para one continues." and blocks[4].rows == [["1", "2"]]


def test_plain_keeps_link_address():
    assert plain("see [OpenAQ](https://openaq.org) and **this**") == "see OpenAQ (https://openaq.org) and this"


def test_line_chart_leaves_gaps_unjoined():
    from datetime import datetime, timedelta, timezone
    t0 = datetime(2026, 10, 1, tzinfo=timezone.utc)
    times = [t0 + timedelta(hours=i) for i in range(6)]
    svg = charts.line_chart(times, [("x", [1, 2, None, None, 3, 4], None)], "u")
    assert svg.count("<polyline") == 2  # two runs; nothing drawn across the gap


def test_field_map_draws_cells_arrows_and_scale_note():
    grid = [[float(r + c) for c in range(12)] for r in range(10)]
    wl, wo = [28.1, 28.5], [76.8, 77.2]
    svg = charts.field_map(LATS, LONS, grid, "µg/m³", arrows=(wl, wo, [[1.0, 1.0]] * 2, [[0.0, 0.0]] * 2), points=[(28.5, 77.0, 12.0, "s")], marker=(28.6, 77.2, "Delhi"))
    assert svg.count("<rect") > 120 and "<polygon" in svg and "own range" in svg and "Delhi" in svg


# --------------------------------------------------------------------------------------------- the document
async def test_document_has_every_section_and_labels_kinds():
    doc = await builder().document("delhi", 24, "pm25", True)
    heads = [b.text for b in doc.blocks if isinstance(b, Heading) and b.level == 2]
    assert heads[0] == "Summary" and any("observations at Delhi" in h for h in heads)
    for want in ("Weather over the period", "The regional picture", "station network", "Forecast", "How well the models perform", "What data the application has", "Background"):
        assert any(want in h for h in heads), want
    figs = [b for b in doc.blocks if type(b).__name__ == "Figure"]
    assert len(figs) >= 4 and all("<svg" in f.svg and f.caption for f in figs)
    assert any("atmospheric model" in f.caption and "observations" in f.caption for f in figs)


async def test_failed_section_is_reported_in_place_and_the_rest_survives():
    doc = await builder(cams=FakeCams(fail=True)).document("delhi", 24, "pm25", False)
    html = render_html(doc)
    assert "could not be built" in html and "Weather over the period" in html and "Background" not in html


async def test_unavailable_field_is_stated_not_drawn():
    doc = await builder(cams=FakeCams(avail=False)).document("delhi", 24, "pm25", False)
    html = render_html(doc)
    assert "no PM2.5 field right now" in html


async def test_html_is_self_contained_and_escapes():
    doc = await builder(articles=[("T <script>", "# T\n\nbody <img src=x onerror=alert(1)>\n")]).document("delhi", 24, "pm25", True)
    html = render_html(doc)
    assert "<script>" not in html.replace("<script>", "", 0) or "&lt;script&gt;" in html
    assert "<img src=x" not in html and "&lt;img" in html
    assert "http://" not in html.split("</style>")[1].replace("http://www.w3.org/2000/svg", "")  # no external assets
    assert html.startswith("<!doctype html>") and "<nav class=\"toc\"" in html


async def test_pdf_renders_with_text_and_pages():
    doc = await builder().document("delhi", 24, "pm25", True)
    data = render_pdf(doc)
    r = PdfReader(io.BytesIO(data))
    text = " ".join(p.extract_text() or "" for p in r.pages)
    assert data[:4] == b"%PDF" and len(r.pages) >= 3
    assert "Air quality and weather report: Delhi" in text and "What this report cannot say" in text


async def test_export_endpoints(monkeypatch):
    from fastapi.testclient import TestClient

    from app.api.report_deps import get_export_builder
    from app.main import app

    b = builder()
    app.dependency_overrides[get_export_builder] = lambda: b
    try:
        c = TestClient(app)
        h = c.get("/api/reports/export/html?location_id=delhi&hours=24&pollutant=pm25&articles=false")
        assert h.status_code == 200 and h.headers["content-type"].startswith("text/html") and "attachment" in h.headers["content-disposition"]
        p = c.get("/api/reports/export/pdf?location_id=delhi&hours=24&pollutant=pm25&articles=false")
        assert p.status_code == 200 and p.content[:4] == b"%PDF"
        assert c.get("/api/reports/export/html?location_id=nowhere").status_code == 422
        assert c.get("/api/reports/export/html?pollutant=zzz").status_code == 422
    finally:
        app.dependency_overrides.pop(get_export_builder, None)
