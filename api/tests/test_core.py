import logging
from datetime import datetime, timezone

import pytest
from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.core.time import IST, to_ist
from app.main import create_app


def test_settings_load_from_environment(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "qwen-test")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    get_settings.cache_clear()
    s = get_settings()
    assert s.ollama_model == "qwen-test"
    assert s.cors_origin_list == ["http://a.test", "http://b.test"]


def test_secrets_are_masked_in_repr():
    s = get_settings()
    assert "super-secret-aq-key" not in repr(s)
    assert "s3cretpw" not in repr(s)


def test_to_ist_converts_and_rejects_naive():
    utc = datetime(2026, 1, 1, 18, 30, tzinfo=timezone.utc)
    ist = to_ist(utc)
    assert (ist.hour, ist.minute, ist.day) == (0, 0, 2)
    assert ist.utcoffset() == IST.utcoffset(None)
    with pytest.raises(ValueError):
        to_ist(datetime(2026, 1, 1))


def make_client_with_test_routes():
    from fastapi.testclient import TestClient

    app = create_app()
    extra = APIRouter()

    class Body(BaseModel):
        count: int

    @extra.post("/validate")
    def validate(body: Body):
        return body

    @extra.get("/boom")
    def boom():
        raise RuntimeError("secret internal detail")

    app.include_router(extra)
    return TestClient(app, raise_server_exceptions=False)


def test_unknown_route_uses_error_envelope(client):
    r = client.get("/api/nope")
    assert r.status_code == 404
    err = r.json()["error"]
    assert err["code"] == "not_found"
    assert err["request_id"] == r.headers["X-Request-ID"]


def test_validation_errors_use_error_envelope():
    r = make_client_with_test_routes().post("/validate", json={"count": "abc"})
    assert r.status_code == 422
    err = r.json()["error"]
    assert err["code"] == "validation_error"
    assert err["details"][0]["field"] == "body.count"


def test_unhandled_errors_are_hidden_from_clients(caplog):
    client = make_client_with_test_routes()
    # create_app() reconfigures logging, which detaches pytest's capture handler; reattach it.
    logging.getLogger().addHandler(caplog.handler)
    r = client.get("/boom")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal_error"
    assert "secret internal detail" not in r.text
    assert "secret internal detail" in caplog.text  # but it is logged for operators


def test_request_id_is_echoed(client):
    r = client.get("/api/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_unsafe_or_oversized_request_ids_are_replaced_not_echoed(client):
    for bad in ["x" * 65, "has space", "semi;colon", "<script>"]:
        r = client.get("/api/health", headers={"X-Request-ID": bad})
        assert r.headers["X-Request-ID"] != bad and len(r.headers["X-Request-ID"]) == 12
