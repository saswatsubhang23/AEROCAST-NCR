import re
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, Field

from app.api.assistant import get_llm_service
from app.api.report_deps import get_export_builder, get_report_service, get_report_store
from app.core.config import get_settings
from app.reports.builder import ReportService
from app.reports.exporters import render_html, render_pdf as render_doc_pdf
from app.reports.export import ExportBuilder
from app.reports.markdown import render_markdown
from app.reports.models import LlmSummary, Report
from app.reports.pdf import render_pdf
from app.reports.store import ReportStore
from app.reports.summary import ReportSummarizer
from app.schemas.assistant import LocationId
from app.schemas.air import Pollutant
from app.services.llm import LlmService

router = APIRouter(prefix="/reports", tags=["reports"])


class ReportRequest(BaseModel):
    location_id: LocationId
    hours: int = Field(24, ge=6, le=168)
    pollutant: Pollutant = "pm25"


def get_summarizer(llm: LlmService = Depends(get_llm_service)) -> ReportSummarizer:
    return ReportSummarizer(llm, get_settings())


def _find(store: ReportStore, report_id: str) -> Report:
    if not re.fullmatch(r"[0-9a-f]{8,32}", report_id):
        raise HTTPException(404, {"code": "not_found", "message": "Report not found."})
    r = store.get(report_id)
    if r is None:
        raise HTTPException(404, {"code": "report_expired", "message": "This report is no longer available (reports are kept for 2 hours). Generate it again."})
    return r


def _filename(r: Report, ext: str) -> str:
    return f"aerocast-report-{r.location.id}-{r.pollutant}-{r.id}.{ext}"


async def _export_doc(location_id: str, hours: int, pollutant: str, articles: bool, builder: ExportBuilder):
    from app.core.places import PLACES

    if location_id not in PLACES:
        raise HTTPException(422, {"code": "unknown_location", "message": "Unknown location."})
    if pollutant not in ("pm25", "pm10", "no2", "o3", "so2", "co"):
        raise HTTPException(422, {"code": "unknown_pollutant", "message": "Unknown pollutant."})
    return await builder.document(location_id, hours, pollutant, articles)


@router.get("/export/html", summary="The full report (all figures, tables and text) as one self-contained HTML file")
async def export_html(location_id: str = Query("delhi"), hours: int = Query(48, ge=6, le=168), pollutant: str = Query("pm25"),
                      articles: bool = Query(True), download: bool = Query(True), builder: ExportBuilder = Depends(get_export_builder)):
    doc = await _export_doc(location_id, hours, pollutant, articles, builder)
    name = f"aerocast-full-report-{location_id}-{pollutant}.html"
    headers = {"Content-Disposition": f'attachment; filename="{name}"'} if download else {}
    return Response(render_html(doc).encode("utf-8"), media_type="text/html; charset=utf-8", headers=headers)


@router.get("/export/pdf", summary="The full report (all figures, tables and text) as a PDF")
async def export_pdf(location_id: str = Query("delhi"), hours: int = Query(48, ge=6, le=168), pollutant: str = Query("pm25"),
                     articles: bool = Query(True), builder: ExportBuilder = Depends(get_export_builder)):
    doc = await _export_doc(location_id, hours, pollutant, articles, builder)
    import asyncio

    data = await asyncio.to_thread(render_doc_pdf, doc)
    name = f"aerocast-full-report-{location_id}-{pollutant}.pdf"
    return Response(data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("", response_model=Report, status_code=201, summary="Generate a report from the live data services (synchronous)")
async def create_report(body: ReportRequest, svc: ReportService = Depends(get_report_service), store: ReportStore = Depends(get_report_store)):
    report = await svc.build(body.location_id, body.hours, body.pollutant)
    store.put(report)
    return report


@router.get("/{report_id}", response_model=Report)
async def get_report(report_id: str, store: ReportStore = Depends(get_report_store)):
    return _find(store, report_id)


@router.post("/{report_id}/summary", response_model=LlmSummary, summary="Add an LLM-written summary, checked against the report's numbers")
async def add_summary(report_id: str, store: ReportStore = Depends(get_report_store), summarizer: ReportSummarizer = Depends(get_summarizer)):
    report = _find(store, report_id)
    summary = await summarizer.summarize(report)
    store.set_summary(report_id, summary)
    return summary


@router.get("/{report_id}/pdf", summary="Download the report as a PDF")
async def pdf(report_id: str, store: ReportStore = Depends(get_report_store)):
    r = _find(store, report_id)
    return Response(render_pdf(r), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{_filename(r, "pdf")}"'})


@router.get("/{report_id}/markdown", summary="Download the report as Markdown")
async def markdown(report_id: str, store: ReportStore = Depends(get_report_store)):
    r = _find(store, report_id)
    return Response(render_markdown(r), media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{_filename(r, "md")}"'})
