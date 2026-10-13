import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from app.api.forecast import get_forecast_service
from app.core.config import Settings, get_settings
from app.forecast.contract import (
    ForecastContractError, ForecastLocation, ForecastRequest, ForecastResponse, check_against_request, contract_schemas,
)
from app.forecast.provider import (
    ForecastNotConfigured, ForecastService, ForecastUnavailable, HttpForecastProvider,
)

NOW = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
DELHI = {"id": "delhi", "name": "Delhi", "lat": 28.6139, "lon": 77.209}


def request(**over):
    base = {"location": DELHI, "issued_at": NOW.isoformat(), "horizon_hours": 6, "pollutants": ["pm25"]}
    return ForecastRequest.model_validate({**base, **over})


def good_response(req: dict | None = None, **over) -> dict:
    """What a provider implementing the contract would send. A test fixture, not forecasting code."""
    req = req or request().model_dump(mode="json")
    issued = datetime.fromisoformat(req["issued_at"].replace("Z", "+00:00"))
    n = req["horizon_hours"]
    times = [(issued + timedelta(hours=i + 1)).isoformat() for i in range(n)]
    out = {
        "model_version": "test-model-1.2", "issued_at": issued.isoformat(), "location": req["location"], "horizon_hours": n,
        "forecasts": [{"pollutant": p, "unit": "µg/m³", "times": times, "values": [50.0 + i for i in range(n)],
                       "intervals": [{"level": 0.8, "lower": [40.0 + i for i in range(n)], "upper": [60.0 + i for i in range(n)]}]}
                      for p in req["pollutants"]],
        "provenance": {"provider": "Test provider", "model_name": "unit-test fixture", "generated_at": issued.isoformat(),
                       "input_data": ["OpenAQ PM2.5 hourly, to 2026-10-09T05:00Z"], "training_data": None, "notes": None},
    }
    out.update(over)
    return out


def settings(**over):
    return Settings(**{**get_settings().model_dump(), "ml_forecast_url": "http://forecast.test", "ml_forecast_api_key": "provider-secret", **over})


def provider(handler, **over):
    return HttpForecastProvider(settings(**over), transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------------------------------------- contract
def test_a_complete_response_is_accepted_and_round_trips():
    res = ForecastResponse.model_validate(good_response())
    assert res.model_version == "test-model-1.2" and res.forecasts[0].intervals[0].level == 0.8
    check_against_request(request(), res, NOW + timedelta(minutes=1))


def test_intervals_are_optional():
    data = good_response()
    data["forecasts"][0]["intervals"] = []
    assert ForecastResponse.model_validate(data).forecasts[0].intervals == []


def mutate(fn):
    data = good_response()
    fn(data)
    return data


@pytest.mark.parametrize("name,change,fragment", [
    ("naive issue time", lambda d: d.update(issued_at="2026-10-09T06:00:00"), "timezone"),
    ("naive forecast time", lambda d: d["forecasts"][0]["times"].__setitem__(0, "2026-10-09T07:00:00"), "timezone"),
    ("values shorter than times", lambda d: d["forecasts"][0]["values"].pop(), "same length"),
    ("times not increasing", lambda d: d["forecasts"][0]["times"].__setitem__(2, d["forecasts"][0]["times"][1]), "strictly increasing"),
    ("negative concentration", lambda d: d["forecasts"][0]["values"].__setitem__(0, -1.0), "non-negative"),
    ("interval below the value's lower bound", lambda d: d["forecasts"][0]["intervals"][0]["lower"].__setitem__(0, 99.0), "lower <= value"),
    ("interval above", lambda d: d["forecasts"][0]["intervals"][0]["upper"].__setitem__(0, 1.0), "lower <= value"),
    ("interval length", lambda d: d["forecasts"][0]["intervals"][0]["upper"].pop(), "interval bounds"),
    ("interval level 1.0", lambda d: d["forecasts"][0]["intervals"][0].update(level=1.0), "less than 1"),
    ("negative lower bound", lambda d: d["forecasts"][0]["intervals"][0]["lower"].__setitem__(0, -5.0), "lower <= value"),
    ("forecast starts at issue time", lambda d: d["forecasts"][0]["times"].__setitem__(0, d["issued_at"]), "after its issue time"),
    ("beyond the horizon", lambda d: d.update(horizon_hours=2), "beyond the stated horizon"),
    ("duplicate pollutant", lambda d: d["forecasts"].append(json.loads(json.dumps(d["forecasts"][0]))), "only once"),
    ("unknown pollutant", lambda d: d["forecasts"][0].update(pollutant="nh3"), "pollutant"),
    ("no unit", lambda d: d["forecasts"][0].update(unit=""), "unit"),
    ("no model version", lambda d: d.update(model_version=""), "model_version"),
    ("no provenance inputs", lambda d: d["provenance"].update(input_data=[]), "input_data"),
    ("horizon over 72", lambda d: d.update(horizon_hours=100), "horizon_hours"),
    ("no forecasts", lambda d: d.update(forecasts=[]), "forecasts"),
    ("bad latitude", lambda d: d["location"].update(lat=95), "lat"),
])
def test_responses_that_break_the_contract_are_rejected(name, change, fragment):
    with pytest.raises(ValidationError) as e:
        ForecastResponse.model_validate(mutate(change))
    assert fragment in str(e.value), name


def test_nan_values_are_rejected_even_when_sent_as_raw_json():
    raw = json.dumps(good_response()).replace('"values": [50.0', '"values": [NaN')
    with pytest.raises(ValidationError):
        ForecastResponse.model_validate_json(raw)


@pytest.mark.parametrize("req,change,fragment", [
    ({}, lambda d: d["provenance"].update(generated_at=(NOW + timedelta(hours=2)).isoformat()), "future"),
    ({"horizon_hours": 3}, lambda d: None, "longer than requested"),
    ({}, lambda d: d["location"].update(lat=28.0, lon=77.5), "different location"),
    ({}, lambda d: d["forecasts"].append({**d["forecasts"][0], "pollutant": "pm10"}), "not requested"),
])
def test_a_response_must_answer_the_request_that_was_made(req, change, fragment):
    asked = request(**{k: v for k, v in req.items()})
    data = good_response(request(horizon_hours=6).model_dump(mode="json"))
    change(data)
    with pytest.raises(ForecastContractError) as e:
        check_against_request(asked, ForecastResponse.model_validate(data), NOW + timedelta(minutes=1))
    assert fragment in e.value.message


def test_a_forecast_issued_in_the_future_is_rejected():
    later = request(issued_at=(NOW + timedelta(hours=2)).isoformat())
    res = ForecastResponse.model_validate(good_response(later.model_dump(mode="json")))  # internally consistent, but dated 2 h ahead
    with pytest.raises(ForecastContractError) as e:
        check_against_request(request(), res, NOW + timedelta(minutes=1))
    assert "future" in e.value.message


def test_request_validation():
    for bad in ({"horizon_hours": 0}, {"horizon_hours": 73}, {"pollutants": []}, {"pollutants": ["pm25", "pm25"]},
                {"pollutants": ["lead"]}, {"issued_at": "2026-10-09T06:00:00"}):
        with pytest.raises(ValidationError):
            request(**bad)


# ---------------------------------------------------------------------------------------------- HTTP adapter
async def test_the_provider_receives_the_contract_request_and_credentials():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"], seen["key"], seen["body"] = str(req.url), req.headers.get("X-API-Key"), json.loads(req.content)
        return httpx.Response(200, json=good_response(seen["body"]))

    out = await provider(handler).forecast(request())
    assert seen["url"] == "http://forecast.test/forecast" and seen["key"] == "provider-secret"
    assert seen["body"]["pollutants"] == ["pm25"] and seen["body"]["horizon_hours"] == 6 and seen["body"]["location"]["lat"] == 28.6139
    assert out.model_version == "test-model-1.2"


async def test_no_key_header_is_sent_when_none_is_configured():
    seen = {}

    def handler(req):
        seen["key"] = req.headers.get("X-API-Key")
        return httpx.Response(200, json=good_response())

    await provider(handler, ml_forecast_api_key="").forecast(request())
    assert seen["key"] is None


@pytest.mark.parametrize("resp,fragment", [
    (httpx.Response(401), "credentials"),
    (httpx.Response(403), "credentials"),
    (httpx.Response(500), "HTTP 500"),
    (httpx.Response(404), "HTTP 404"),
])
async def test_provider_http_failures_are_reported_as_unavailable(resp, fragment):
    with pytest.raises(ForecastUnavailable) as e:
        await provider(lambda req: resp).forecast(request())
    assert fragment in e.value.message


async def test_timeouts_and_connection_failures_are_reported_as_unavailable():
    def slow(req):
        raise httpx.ReadTimeout("slow")

    def down(req):
        raise httpx.ConnectError("refused")

    with pytest.raises(ForecastUnavailable) as e:
        await provider(slow).forecast(request())
    assert "too long" in e.value.message
    with pytest.raises(ForecastUnavailable) as e:
        await provider(down).forecast(request())
    assert "not reachable" in e.value.message and "forecast.test" not in e.value.message


async def test_a_malformed_response_is_a_contract_error_that_does_not_echo_the_payload():
    secret_payload = {"model_version": "x", "api_token": "leak-me-not"}
    with pytest.raises(ForecastContractError) as e:
        await provider(lambda req: httpx.Response(200, json=secret_payload)).forecast(request())
    assert "breaks the contract" in e.value.message and "leak-me-not" not in e.value.message
    with pytest.raises(ForecastContractError):
        await provider(lambda req: httpx.Response(200, content=b"<html>not json</html>")).forecast(request())


# ---------------------------------------------------------------------------------------------- service and API
async def test_with_no_provider_the_service_says_so_and_never_invents_a_forecast():
    svc = ForecastService(Settings(**{**get_settings().model_dump(), "ml_forecast_url": ""}), now=lambda: NOW)
    assert not svc.configured and svc.provider_name is None
    with pytest.raises(ForecastNotConfigured):
        await svc.forecast(request())
    with pytest.raises(ForecastNotConfigured):
        await svc.health()


async def test_the_service_validates_before_returning():
    def handler(req):
        return httpx.Response(200, json=good_response(json.loads(req.content), issued_at=(NOW + timedelta(days=1)).isoformat()))

    svc = ForecastService(settings(), provider(handler), now=lambda: NOW + timedelta(minutes=1))
    with pytest.raises(ForecastContractError):
        await svc.forecast(request())


@pytest.fixture
def api(client):
    def install(handler=None, **over):
        s = settings(**over) if handler else Settings(**{**get_settings().model_dump(), "ml_forecast_url": ""})
        prov = HttpForecastProvider(s, transport=httpx.MockTransport(handler)) if handler else None
        client.app.dependency_overrides[get_forecast_service] = lambda: ForecastService(s, prov)
        return client

    return install


def test_with_no_provider_the_api_reports_unavailable_everywhere(api):
    c = api()
    st = c.get("/api/forecast/status").json()
    assert st == {"configured": False, "available": None, "provider": None, "message": "No forecasting service is configured, so pollution forecasts are unavailable."}
    r = c.post("/api/forecast", json={"location_id": "delhi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "forecast_not_configured"
    assert "forecast" not in r.json()  # no synthetic data of any kind


def test_with_a_provider_the_api_returns_the_validated_forecast_unchanged(api):
    def handler(req):
        if req.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        return httpx.Response(200, json=good_response(json.loads(req.content)))

    c = api(handler)
    assert c.get("/api/forecast/status").json()["available"] is True
    r = c.post("/api/forecast", json={"location_id": "noida", "horizon_hours": 4, "pollutants": ["pm25", "pm10"]})
    body = r.json()
    assert r.status_code == 200 and body["provider"] == "forecast.test" and "not by AEROCAST" in body["notice"]
    assert [f["pollutant"] for f in body["forecast"]["forecasts"]] == ["pm25", "pm10"]
    assert body["forecast"]["model_version"] == "test-model-1.2" and len(body["forecast"]["forecasts"][0]["values"]) == 4
    assert body["forecast"]["forecasts"][0]["intervals"][0]["level"] == 0.8


def test_provider_problems_map_to_clear_errors(api):
    assert api(lambda req: httpx.Response(200, json={"bad": 1})).post("/api/forecast", json={"location_id": "delhi"}).json()["error"]["code"] == "forecast_invalid_response"
    r = api(lambda req: httpx.Response(500)).post("/api/forecast", json={"location_id": "delhi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "forecast_unavailable"
    st = api(lambda req: httpx.Response(500)).get("/api/forecast/status").json()
    assert st["configured"] is True and st["available"] is False
    assert "provider-secret" not in json.dumps(st)


@pytest.mark.parametrize("body", [{"location_id": "mumbai"}, {"location_id": "delhi", "horizon_hours": 100},
                                  {"location_id": "delhi", "pollutants": ["lead"]}, {"location_id": "delhi", "pollutants": []}, {}])
def test_forecast_requests_are_validated_before_anything_is_sent(api, body):
    called = []
    c = api(lambda req: called.append(req) or httpx.Response(200, json=good_response()))
    r = c.post("/api/forecast", json=body)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error" and called == []


def test_the_contract_endpoint_publishes_the_schemas(client):
    body = client.get("/api/forecast/contract").json()
    assert set(body) == {"request", "response"} and "model_version" in body["response"]["properties"]
    assert {"location", "issued_at", "horizon_hours", "pollutants"} <= set(body["request"]["properties"])
    assert {"forecasts", "provenance", "model_version", "issued_at"} <= set(body["response"]["properties"])


def test_the_documented_schema_file_matches_the_code():
    path = Path(__file__).resolve().parents[2] / "docs" / "ml-forecast-contract.schema.json"
    assert path.exists(), "run: python -m app.forecast.export_schema"
    assert json.loads(path.read_text(encoding="utf-8")) == json.loads(json.dumps(contract_schemas()))


# ---------------------------------------------------------------------------------------------- system status
def test_system_status_reports_the_optional_provider_without_treating_absence_as_a_problem(client, monkeypatch):
    from test_system import by_key, ollama_returns

    ollama_returns(monkeypatch, models=[])
    row = by_key(client.get("/api/system/status").json())["forecast_provider"]
    assert row["state"] == "not_configured" and row["required"] is False and "unavailable" in row["detail"]


def test_system_status_probes_a_configured_provider(client, monkeypatch):
    from test_system import by_key, ollama_returns
    from app.services import system_status

    ollama_returns(monkeypatch, models=[])
    monkeypatch.setenv("ML_FORECAST_URL", "http://forecast.test")
    get_settings.cache_clear()
    original = system_status.httpx.get

    def fake_get(url, **kw):
        if "forecast.test" in url:
            return httpx.Response(200, request=httpx.Request("GET", url))
        return original(url, **kw)

    monkeypatch.setattr(system_status.httpx, "get", fake_get)
    from app.main import create_app
    from fastapi.testclient import TestClient

    assert by_key(TestClient(create_app()).get("/api/system/status").json())["forecast_provider"]["state"] == "ok"
