import pytest
from fastapi.testclient import TestClient

from app.api.alerts import get_alert_store
from app.api.jev import get_shadow_service
from app.api.knowledge import get_kb_service
from app.api.report_deps import get_report_store
from app.core.config import get_settings
from app.db.session import get_engine
from app.services.system_status import clear_status_cache

# Port 1 refuses connections immediately, so "database down" tests are fast and need no real server.
UNREACHABLE_DB = "postgresql+psycopg://user:s3cretpw@127.0.0.1:1/none"


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    """Tests never read a developer's api/.env or hit real services."""
    monkeypatch.chdir(tmp_path)
    clear_status_cache()  # the status endpoint reuses results for 15 s; tests must not see each other's
    monkeypatch.setattr("app.services.system_status.STATUS_TTL_S", 0.0)
    for key, value in {
        "ENVIRONMENT": "test",
        "DATABASE_URL": UNREACHABLE_DB,
        "OLLAMA_BASE_URL": "http://ollama.test:11434",
        "OLLAMA_MODEL": "qwen2.5:7b-instruct",
        "OLLAMA_EMBED_MODEL": "nomic-embed-text",
        "WEATHER_RETRY_BACKOFF_S": "0",
        "AQ_RATE_PER_MINUTE": "100000",
        "AQ_RETRY_BACKOFF_S": "0",
        "AQ_API_BASE_URL": "https://aq.example/api",
        "AQ_API_KEY": "super-secret-aq-key",
        "CORS_ORIGINS": "http://localhost:3000",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_kb_service.cache_clear()
    get_alert_store.cache_clear()
    get_report_store.cache_clear()
    get_shadow_service.cache_clear()
    yield
    get_settings.cache_clear()
    get_engine.cache_clear()
    get_kb_service.cache_clear()
    get_alert_store.cache_clear()
    get_report_store.cache_clear()
    get_shadow_service.cache_clear()


@pytest.fixture
def client():
    from app.main import create_app

    # raise_server_exceptions=False so tests see the real 500 response the client would get.
    return TestClient(create_app(), raise_server_exceptions=False)
