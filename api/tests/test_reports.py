import io
import json

import httpx
import pytest
from pypdf import PdfReader
from test_air import BASE as AIR_BASE
from test_air import FakeOpenAQ
from test_air import make_service as make_air
from test_forecast import good_response
from test_forecast import settings as forecast_settings
from test_weather import NOW, FakeMeteo
from test_weather import make_service as make_weather

from app.api.air import get_air_service
from app.api.forecast import get_forecast_service
from app.api.weather import get_weather_service
from app.assistant.kb import NullKnowledgeBase
from app.core.config import Settings, get_settings
from app.forecast.provider import ForecastService, HttpForecastProvider
from app.integrations.ollama import OllamaClient
from app.reports.builder import ReportService
from app.reports.markdown import render_markdown
from app.reports.pdf import render_pdf
from app.reports.store import ReportStore
from app.reports.summary import ReportSummarizer, check_summary
from app.services.llm import LlmService

MODEL = "qwen3:8b-q4_K_M"


def rising():
    return FakeOpenAQ(hours_value=lambda sid, k: (40 + (10 - k) * 5 if k <= 10 else 40) if sid in AIR_BASE else None)


def no_forecast():
    return ForecastService(Settings(**{**get_settings().model_dump(), "ml_forecast_url": ""}))


def mock_forecast(handler=None):
    s = forecast_settings()
    handler = handler or (lambda req: httpx.Response(200, json=good_response(json.loads(req.content))))
    return ForecastService(s, HttpForecastProvider(s, transport=httpx.MockTransport(handler)))


def service(air=None, meteo=None, forecast=None, kb=None, **air_over):
    return ReportService(make_weather(meteo or FakeMeteo()), make_air(air or rising(), **air_over), kb or NullKnowledgeBase(),
                         forecast or no_forecast(), now=lambda: NOW)


# ---------------------------------------------------------------------------------------------- builder
async def test_report_is_built_from_real_service_data_with_sources_and_freshness():
    r = await service().build("delhi", 24, "pm25")
    assert r.location.name == "Delhi" and r.pollutant == "pm25"
    assert r.air.status == "ok" and r.air.station.name == "Anand Vihar" and r.air.largest_rise.rise == pytest.approx(30.0)
    assert r.weather.status == "ok" and r.weather.variables
    assert {s.id for s in r.sources} == {"W1", "A1"} and r.air.source_id == "A1" and r.weather.source_id == "W1"
    assert {f.label for f in r.freshness} == {"Weather-model values", "PM2.5 observations"}
    assert r.coinciding.status == "ok" and r.facts_summary


async def test_missing_data_is_recorded_as_limitations_not_filled_in():
    r = await service(air=FakeOpenAQ(), aq_api_key="").build("delhi", 24, "pm25")
    assert r.air.status == "unavailable" and "not configured" in r.air.reason
    assert r.air.values == [] and r.coinciding.status == "unavailable"
    assert any("No PM2.5 observations" in x for x in r.limitations)
    assert next(f for f in r.freshness if "observations" in f.label).status == "unavailable"


async def test_weather_outage_leaves_air_intact_and_is_reported():
    from app.integrations.http import UpstreamError  # noqa: PLC0415

    class DownWeather:
        async def recent(self, *a, **k):
            raise UpstreamError("down")

    svc = ReportService(DownWeather(), make_air(rising()), NullKnowledgeBase(), no_forecast(), now=lambda: NOW)
    r = await svc.build("delhi", 24, "pm25")
    assert r.weather.status == "unavailable" and r.air.status == "ok"
    assert r.atmosphere.status == "unavailable" and any("No weather values" in x for x in r.limitations)


async def test_without_a_provider_the_report_says_no_forecast_and_contains_none():
    r = await service().build("delhi", 24, "pm25")
    assert r.forecast.status == "unavailable" and r.forecast.values == []
    assert any("contains no forecast" in x for x in r.limitations)


async def test_with_a_provider_the_forecast_is_labelled_external_and_cited():
    r = await service(forecast=mock_forecast()).build("delhi", 24, "pm25")
    assert r.forecast.status == "available" and len(r.forecast.values) == 24 and r.forecast.model_version == "test-model-1.2"
    assert "not by AEROCAST" in r.forecast.reason
    assert "F1" in {s.id for s in r.sources}


async def test_a_failing_or_invalid_provider_never_breaks_the_report():
    r = await service(forecast=mock_forecast(lambda req: httpx.Response(500))).build("delhi", 24, "pm25")
    assert r.forecast.status == "error" and r.forecast.values == [] and r.air.status == "ok"
    r = await service(forecast=mock_forecast(lambda req: httpx.Response(200, json={"nope": 1}))).build("delhi", 24, "pm25")
    assert r.forecast.status == "error" and r.forecast.values == []


async def test_station_beyond_the_radius_is_not_used():
    r = await service().build("gurugram", 24, "pm25")
    if r.air.status == "ok":
        assert r.air.station.distance_km <= 20
    else:
        assert "within 20 km" in r.air.reason or "reported" in r.air.reason


# ---------------------------------------------------------------------------------------------- markdown and pdf
async def test_markdown_is_deterministic_cites_sources_and_has_the_limitations():
    r = await service().build("delhi", 24, "pm25")
    md = render_markdown(r)
    assert md.startswith("## Air-quality and weather report: Delhi")
    assert "Anand Vihar" in md and "+30.0" in md and "[A1]" in md and "[W1]" in md
    assert "cannot confirm a temperature inversion" in md and "do not show what caused it" in md
    assert render_markdown(r) == md
    assert "(/reports?id=" in render_markdown(r, link=f"/reports?id={r.id}")


async def test_pdf_is_a_valid_document_with_the_report_values():
    r = await service().build("delhi", 24, "pm25")
    data = render_pdf(r)
    assert data.startswith(b"%PDF")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
    assert "Delhi" in text and "Anand Vihar" in text and "30.0" in text
    assert "What this report cannot say" in text and "OpenAQ" in text and "Open-Meteo" in text


async def test_pdf_renders_when_everything_is_unavailable():
    from app.integrations.http import UpstreamError  # noqa: PLC0415

    class DownWeather:
        async def recent(self, *a, **k):
            raise UpstreamError("down")

    svc = ReportService(DownWeather(), make_air(FakeOpenAQ(), aq_api_key=""), NullKnowledgeBase(), no_forecast(), now=lambda: NOW)
    r = await svc.build("delhi", 24, "pm25")
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(render_pdf(r))).pages)
    assert "What this report cannot say" in text and r.air.status == "unavailable"


async def test_pdf_handles_non_latin_text_in_provider_names():
    r = await service().build("delhi", 24, "pm25")
    r.air.station.name = "आनंद विहार – Test’s “station” µg/m³"
    assert render_pdf(r).startswith(b"%PDF")


# ---------------------------------------------------------------------------------------------- summary guard
async def test_summary_check_accepts_report_numbers_and_rejects_invented_ones():
    r = await service().build("delhi", 24, "pm25")
    ok = f"PM2.5 at Anand Vihar rose by 30 in Delhi."
    assert check_summary(ok, r) is None
    assert "not in the report" in check_summary("PM2.5 reached 777 at Anand Vihar.", r)


@pytest.mark.parametrize("text", [
    "The rise was caused by traffic.", "Levels will fall tomorrow.", "A forecast says it improves.",
    "A temperature inversion trapped it.", "The air is safe.", "",
])
async def test_summary_check_refuses_causes_forecasts_and_advice(text):
    r = await service().build("delhi", 24, "pm25")
    assert check_summary(text, r)


def summarizer(rounds, models=(MODEL,)):
    def handler(request: httpx.Request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": m} for m in models]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion", "tools"], "model_info": {}})
        chunks = rounds.pop(0)
        return httpx.Response(200, content="\n".join(json.dumps(c) for c in chunks) + "\n")

    s = Settings(**{**get_settings().model_dump(), "ollama_model": MODEL})
    return ReportSummarizer(LlmService(s, client=OllamaClient(s, transport=httpx.MockTransport(handler))), s, now=lambda: NOW)


def say(text):
    return [{"message": {"role": "assistant", "content": text}, "done": False}, {"message": {"content": ""}, "done": True}]


async def test_a_grounded_summary_is_accepted():
    r = await service().build("delhi", 24, "pm25")
    s = await summarizer([say("PM2.5 near Delhi rose by 30 at Anand Vihar.")]).summarize(r)
    assert s.status == "ok" and "30" in s.text


async def test_an_ungrounded_summary_is_discarded_not_edited():
    r = await service().build("delhi", 24, "pm25")
    s = await summarizer([say("PM2.5 reached 999 at Anand Vihar.")]).summarize(r)
    assert s.status == "rejected" and s.text is None and "999" in s.reason


async def test_summary_is_unavailable_when_the_model_is_missing():
    r = await service().build("delhi", 24, "pm25")
    s = await summarizer([], models=()).summarize(r)
    assert s.status == "unavailable"


# ---------------------------------------------------------------------------------------------- store
async def test_store_expires_and_evicts_oldest():
    r = await service().build("delhi", 24, "pm25")
    t = [0.0]
    st = ReportStore(max_items=2, ttl_s=10, clock=lambda: t[0])
    st.put(r)
    assert st.get(r.id) is r
    t[0] = 11
    assert st.get(r.id) is None
    a, b, c = (r.model_copy(update={"id": i}) for i in ("aaaaaaaa", "bbbbbbbb", "cccccccc"))
    for x in (a, b, c):
        st.put(x)
    assert st.get("aaaaaaaa") is None and st.get("cccccccc") is c


# ---------------------------------------------------------------------------------------------- HTTP
@pytest.fixture
def api(client):
    def install(air=None, forecast=None, rounds=None):
        app = client.app
        app.dependency_overrides[get_weather_service] = lambda: make_weather(FakeMeteo())
        app.dependency_overrides[get_air_service] = lambda: make_air(air or rising())
        app.dependency_overrides[get_forecast_service] = lambda: forecast or no_forecast()
        if rounds is not None:
            from app.api.reports import get_summarizer  # noqa: PLC0415

            app.dependency_overrides[get_summarizer] = lambda: summarizer(rounds)
        return client

    return install


def test_report_lifecycle_over_http(api):
    c = api(rounds=[say("PM2.5 near Delhi rose by 30 at Anand Vihar.")])
    r = c.post("/api/reports", json={"location_id": "delhi", "hours": 24, "pollutant": "pm25"})
    assert r.status_code == 201
    rid = r.json()["id"]
    assert c.get(f"/api/reports/{rid}").json()["air"]["station"]["name"] == "Anand Vihar"
    pdf = c.get(f"/api/reports/{rid}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF") and pdf.headers["content-type"] == "application/pdf"
    assert f"{rid}.pdf" in pdf.headers["content-disposition"]
    md = c.get(f"/api/reports/{rid}/markdown")
    assert md.status_code == 200 and md.text.startswith("## Air-quality") and "text/markdown" in md.headers["content-type"]
    s = c.post(f"/api/reports/{rid}/summary").json()
    assert s["status"] == "ok"
    assert c.get(f"/api/reports/{rid}").json()["llm_summary"]["status"] == "ok"
    assert "Summary" in c.get(f"/api/reports/{rid}/markdown").text


def test_unknown_malformed_and_expired_ids(api):
    c = api()
    assert c.get("/api/reports/deadbeefdead").json()["error"]["code"] == "report_expired"
    assert c.get("/api/reports/..%2f..%2fetc").status_code == 404
    assert c.get("/api/reports/NOT-HEX!!/pdf").json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("body", [
    {"location_id": "atlantis"}, {"location_id": "delhi", "hours": 2}, {"location_id": "delhi", "hours": 500},
    {"location_id": "delhi", "pollutant": "xx"}, {},
])
def test_report_requests_are_validated(api, body):
    assert api().post("/api/reports", json=body).status_code == 422


def test_report_endpoint_survives_air_outage_and_provider_absence(api):
    c = api(air=FakeOpenAQ())
    from app.api.air import get_air_service as g  # noqa: PLC0415

    c.app.dependency_overrides[g] = lambda: make_air(FakeOpenAQ(), aq_api_key="")
    r = c.post("/api/reports", json={"location_id": "delhi"})
    assert r.status_code == 201 and r.json()["air"]["status"] == "unavailable" and r.json()["forecast"]["status"] == "unavailable"


def test_report_with_a_provider_includes_the_forecast_section(api):
    c = api(forecast=mock_forecast())
    body = c.post("/api/reports", json={"location_id": "delhi"}).json()
    assert body["forecast"]["status"] == "available" and len(body["forecast"]["values"]) == 24
