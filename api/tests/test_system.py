import httpx
import pytest

from app.core.config import get_settings
from app.services import system_status


def ollama_returns(monkeypatch, models=None, error=None, weather_error=None, aq_status=200):
    """Fakes every outbound httpx.get made by the status probes (Ollama and Open-Meteo)."""

    def fake_get(url, timeout, params=None, headers=None):
        if "aq.example" in url:
            return httpx.Response(aq_status, json={"results": []}, request=httpx.Request("GET", url))
        if "open-meteo" in url:
            if weather_error:
                raise weather_error
            return httpx.Response(200, json={"current": {}}, request=httpx.Request("GET", url))
        if error:
            raise error
        return httpx.Response(200, json={"models": [{"name": m} for m in models]}, request=httpx.Request("GET", url))

    monkeypatch.setattr(system_status.httpx, "get", fake_get)


def by_key(body):
    return {d["key"]: d for d in body["dependencies"]}


def test_health_is_liveness_only_and_touches_no_dependency(client, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("health must not probe dependencies")

    monkeypatch.setattr(system_status, "check_database", boom)
    monkeypatch.setattr(system_status.httpx, "get", boom)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_status_reports_database_down_as_degraded_not_error(client, monkeypatch):
    ollama_returns(monkeypatch, models=["qwen2.5:7b-instruct", "nomic-embed-text:latest"])
    r = client.get("/api/system/status")
    assert r.status_code == 200
    body = r.json()
    deps = by_key(body)
    assert body["status"] == "degraded"
    assert deps["database"]["state"] == "unavailable" and deps["database"]["required"] is True
    assert deps["postgis"]["state"] == "unavailable"
    assert deps["ollama"]["state"] == "ok"
    assert deps["llm_model"]["state"] == "ok"
    assert deps["embed_model"]["state"] == "ok"


def test_status_detects_missing_model_and_unreachable_ollama(client, monkeypatch):
    ollama_returns(monkeypatch, models=["nomic-embed-text:latest"])
    deps = by_key(client.get("/api/system/status").json())
    assert deps["llm_model"]["state"] == "degraded"
    assert "not installed" in deps["llm_model"]["detail"]

    ollama_returns(monkeypatch, error=httpx.ConnectError("refused"))
    deps = by_key(client.get("/api/system/status").json())
    assert deps["ollama"]["state"] == "unavailable"
    assert deps["llm_model"]["state"] == "unavailable"


def test_status_is_ok_when_required_dependencies_are_ok(client, monkeypatch):
    ok = [
        system_status.DependencyStatus(key="database", name="PostgreSQL", required=True, state="ok", detail="Connected"),
    ]
    monkeypatch.setattr(system_status, "check_database", lambda: ok)
    ollama_returns(monkeypatch, error=httpx.ConnectError("refused"))
    # Optional dependencies being down must not make the system degraded.
    assert client.get("/api/system/status").json()["status"] == "ok"


def test_provider_states_and_no_secrets_leak(client, monkeypatch):
    ollama_returns(monkeypatch, models=[])
    r = client.get("/api/system/status")
    deps = by_key(r.json())
    assert deps["weather_provider"]["state"] == "ok"
    assert deps["aq_provider"]["state"] == "ok"
    for secret in ("super-secret-aq-key", "s3cretpw", "127.0.0.1"):
        assert secret not in r.text


def test_status_has_utc_and_ist_timestamps(client, monkeypatch):
    ollama_returns(monkeypatch, models=[])
    body = client.get("/api/system/status").json()
    assert body["generated_at"].endswith("Z") or body["generated_at"].endswith("+00:00")
    assert body["generated_at_ist"].endswith("+05:30")


@pytest.mark.parametrize("path", ["/docs", "/openapi.json"])
def test_openapi_docs_are_served(client, path):
    assert client.get(path).status_code == 200


def test_openapi_lists_exactly_the_implemented_endpoints(client):
    assert set(client.get("/openapi.json").json()["paths"]) == {
        "/api/health", "/api/system/status",
        "/api/weather/point", "/api/weather/grid", "/api/weather/profile", "/api/weather/recent",
        "/api/air/stations", "/api/air/history", "/api/air/stations/{station_id}/aqi",
        "/api/air/stations/{station_id}/export.csv", "/api/air/model-forecast", "/api/air/model-fields", "/api/weather/fields",
        "/api/air/batch-csv", "/api/air/batch-export-csv", "/api/air/batch-export-pdf", "/api/air/batch-text",
        "/api/assistant/status", "/api/assistant/chat",
        "/api/kb/status", "/api/kb/documents", "/api/kb/documents/{doc_id}", "/api/kb/documents/{doc_id}/chunks",
        "/api/kb/documents/{doc_id}/reindex", "/api/kb/search",
        "/api/forecast", "/api/forecast/status", "/api/forecast/contract",
        "/api/alerts", "/api/alerts/rules", "/api/alerts/rules/{rule_id}",
        "/api/reports", "/api/reports/{report_id}", "/api/reports/{report_id}/summary",
        "/api/reports/{report_id}/pdf", "/api/reports/{report_id}/markdown", "/api/reports/export/html", "/api/reports/export/pdf",
        "/api/models/status", "/api/health-intel/exposure", "/api/jev/status", "/api/jev/shadow", "/api/twin/status", "/api/twin/stations", "/api/twin/window", "/api/twin/estimate", "/api/twin/backtest", "/api/twin/thresholds", "/api/twin/risk-windows", "/api/twin/early-warning", "/api/twin/regimes",
        "/api/twin/simulations", "/api/twin/simulations/live", "/api/twin/simulations/{run_id}", "/api/twin/validation/estimates",
        "/api/training/status", "/api/training/jobs", "/api/training/jobs/{job_id}", "/api/training/jobs/{job_id}/cancel", "/api/training/jobs/{job_id}/activate", "/api/training/rollback",
        "/api/terrain/meta", "/api/terrain/heightmap", "/api/terrain/imagery",
        "/api/docs/articles", "/api/docs/articles/{slug}", "/api/twin/coupled", "/api/twin/coupled/config", "/api/twin/coupled/{run_id}", "/api/system/data-availability",
        "/api/geo/status", "/api/geo/stations/nearby", "/api/geo/stations.geojson", "/api/geo/stations/{station_id}/series",
        "/api/kb/datasets", "/api/kb/documents/{doc_id}/profile", "/api/kb/documents/{doc_id}/query", "/api/kb/documents/{doc_id}/relationship",
    }


def test_cors_allows_frontend_origin_only(client):
    ok = client.get("/api/health", headers={"Origin": "http://localhost:3000"})
    assert ok.headers["access-control-allow-origin"] == "http://localhost:3000"
    other = client.get("/api/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_latency_is_attached_only_to_the_service_row(client, monkeypatch):
    ollama_returns(monkeypatch, models=["qwen2.5:7b-instruct", "nomic-embed-text:latest"])
    deps = by_key(client.get("/api/system/status").json())
    assert deps["ollama"]["latency_ms"] is not None
    assert deps["llm_model"]["latency_ms"] is None
    assert deps["embed_model"]["latency_ms"] is None


def test_weather_provider_outage_is_reported_but_not_required(client, monkeypatch):
    ollama_returns(monkeypatch, models=[], weather_error=httpx.ConnectError("refused"))
    body = client.get("/api/system/status").json()
    assert by_key(body)["weather_provider"]["state"] == "unavailable"
    assert by_key(body)["weather_provider"]["required"] is False


def test_air_quality_source_states(client, monkeypatch):
    ollama_returns(monkeypatch, models=[], aq_status=401)
    assert by_key(client.get("/api/system/status").json())["aq_provider"]["state"] == "degraded"
    monkeypatch.setenv("AQ_API_KEY", "")
    get_settings.cache_clear()
    from app.main import create_app
    from fastapi.testclient import TestClient

    body = TestClient(create_app()).get("/api/system/status").json()
    assert by_key(body)["aq_provider"]["state"] == "not_configured"


def test_status_is_reused_within_the_ttl_and_refresh_bypasses_it(client, monkeypatch):
    import app.services.system_status as ss

    monkeypatch.setattr(ss, "STATUS_TTL_S", 60.0)
    ss.clear_status_cache()
    first = client.get("/api/system/status").json()["generated_at"]
    assert client.get("/api/system/status").json()["generated_at"] == first  # served from the cache
    assert client.get("/api/system/status?refresh=true").json()["generated_at"] != first  # probed again
