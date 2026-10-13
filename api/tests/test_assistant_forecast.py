"""The assistant and pollution forecasts: refused in code when no model exists; routed to a forecast tool (with honest failures) when one does."""

import json

import httpx
from test_assistant import FakeOllama, MODEL, ask, call, kinds, of_type, say, text_of
from test_air import FakeOpenAQ
from test_air import make_service as make_air
from test_forecast import good_response
from test_forecast import settings as forecast_settings
from test_weather import NOW, FakeMeteo
from test_weather import make_service as make_weather

from app.assistant.kb import NullKnowledgeBase
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.tools import ToolExecutor
from app.core.config import Settings, get_settings
from app.forecast.provider import ForecastService, HttpForecastProvider
from app.integrations.ollama import OllamaClient
from app.services.llm import LlmService


def build(ollama, forecast: ForecastService | None):
    settings = Settings(**{**get_settings().model_dump(), "ollama_model": MODEL})
    client = OllamaClient(settings, transport=httpx.MockTransport(ollama))
    w, a = make_weather(FakeMeteo()), make_air(FakeOpenAQ())
    configured = forecast is not None and forecast.configured
    return AssistantOrchestrator(
        settings, LlmService(settings, client=client),
        lambda: ToolExecutor(w, a, NullKnowledgeBase(), now=lambda: NOW, forecast=forecast), now=lambda: NOW, forecast_available=lambda: configured)


def service(handler) -> ForecastService:
    s = forecast_settings()
    return ForecastService(s, HttpForecastProvider(s, transport=httpx.MockTransport(handler)), now=lambda: NOW)


def ok_handler(req):
    return httpx.Response(200, json=good_response(json.loads(req.content)))


def tool_names(ollama):
    return [t["function"]["name"] for t in ollama.chat_requests[0].get("tools", [])]


async def test_without_a_forecasting_model_the_question_is_refused_in_code_and_the_tool_is_not_offered():
    ollama = FakeOllama([])
    events = await ask(build(ollama, None), "Will PM2.5 rise tomorrow in Delhi?")
    assert "can't predict future air quality" in text_of(events) and ollama.chat_requests == []
    ollama2 = FakeOllama([say("Delhi is fine.")])
    await ask(build(ollama2, None), "What is the PM2.5 in Delhi?")
    assert "get_pollution_forecast" not in tool_names(ollama2)


async def test_with_a_model_forecast_questions_reach_the_model_and_the_forecast_tool_is_offered():
    ollama = FakeOllama([call(("get_pollution_forecast", {"location": "delhi", "pollutant": "pm25", "hours": 6})),
                         say("The model forecasts about 52 µg/m³ around the next hours [P1].")])
    events = await ask(build(ollama, service(ok_handler)), "Will PM2.5 rise tomorrow in Delhi?")
    assert "get_pollution_forecast" in tool_names(ollama) and "can't predict" not in text_of(events)
    tool = of_type(events, "tool")
    assert any(t.get("name") == "get_pollution_forecast" for t in tool)
    src = of_type(events, "sources")[0]["sources"]
    assert [s["id"] for s in src] == ["P1"] and src[0]["kind"] == "pollution_forecast" and "test-model-1.2" in src[0]["title"]
    done = of_type(events, "done")[0]
    assert done["tools"][0]["ok"] is True and done["ungrounded_numbers"] == [] and done["unknown_citations"] == []


async def test_a_number_the_forecast_did_not_return_is_flagged():
    ollama = FakeOllama([call(("get_pollution_forecast", {"location": "delhi", "hours": 6})), say("It will reach 412 µg/m³ [P1].")])
    done = of_type(await ask(build(ollama, service(ok_handler)), "Will PM2.5 rise tomorrow in Delhi?"), "done")[0]
    assert 412.0 in done["ungrounded_numbers"]


async def test_when_the_model_cannot_forecast_the_tool_says_why_and_forbids_estimating():
    def down(req):
        return httpx.Response(503)

    ollama = FakeOllama([call(("get_pollution_forecast", {"location": "delhi"})), say("I could not get a forecast.")])
    events = await ask(build(ollama, service(down)), "Will PM2.5 rise tomorrow in Delhi?")
    done = of_type(events, "done")[0]
    assert done["tools"][0]["ok"] is False
    followup = json.dumps(ollama.chat_requests[1]["messages"])
    assert "No forecast could be made" in followup and "Do not estimate it yourself" in followup


async def test_invalid_forecast_tool_arguments_never_run():
    ollama = FakeOllama([call(("get_pollution_forecast", {"location": "mars", "hours": 500})), say("Sorry.")])
    events = await ask(build(ollama, service(ok_handler)), "Will PM2.5 rise tomorrow in Delhi?")
    assert of_type(events, "done")[0]["tools"][0]["ok"] is False


def test_assistant_status_does_not_crash_when_a_forecaster_is_configured(client, monkeypatch, tmp_path):
    """Regression: the status schema once allowed only "unavailable", so configuring a model turned /assistant/status into a 500."""
    from app.api.forecast import get_forecast_service
    from app.core.config import get_settings

    monkeypatch.setenv("ML_FORECAST_URL", "http://forecaster.test")
    get_settings.cache_clear()
    get_forecast_service.cache_clear()
    body = client.get("/api/assistant/status")
    assert body.status_code == 200 and body.json()["pollution_forecast"] == "available"
