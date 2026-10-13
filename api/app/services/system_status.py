"""Dependency probes. Every probe catches its own failures and reports them; none may raise."""

import asyncio
import logging
import time
from collections.abc import Callable

import httpx
from sqlalchemy import text

from app.core.config import Settings
from app.core.time import to_ist, utc_now
from app.db.session import get_engine
from app.schemas.system import AppInfo, DependencyStatus, SystemStatusResponse

logger = logging.getLogger("app.status")


def _timed(fn: Callable[[], list[DependencyStatus]]) -> list[DependencyStatus]:
    start = time.perf_counter()
    result = fn()
    ms = round((time.perf_counter() - start) * 1000)
    # One probe produces several rows; its latency belongs to the first (the service itself), not the derived rows.
    return [result[0].model_copy(update={"latency_ms": ms}), *result[1:]]


def check_database() -> list[DependencyStatus]:
    def probe() -> list[DependencyStatus]:
        try:
            with get_engine().connect() as conn:
                conn.execute(text("select 1"))
                postgis = conn.execute(
                    text("select extversion from pg_extension where extname = 'postgis'")
                ).scalar()
        except Exception as exc:
            # Log the error class only: driver messages can include host and user details.
            logger.warning("Database probe failed: %s", type(exc).__name__)
            return [
                DependencyStatus(
                    key="database", name="PostgreSQL", required=True, state="unavailable",
                    detail=f"Connection failed ({type(exc).__name__})",
                ),
                DependencyStatus(
                    key="postgis", name="PostGIS extension", required=False, state="unavailable",
                    detail="Requires a database connection",
                ),
            ]
        return [
            DependencyStatus(key="database", name="PostgreSQL", required=True, state="ok", detail="Connected"),
            DependencyStatus(
                key="postgis", name="PostGIS extension", required=False,
                state="ok" if postgis else "degraded",
                detail=f"Version {postgis}" if postgis else "Extension not installed in this database",
            ),
        ]

    return _timed(probe)


def check_ollama(settings: Settings) -> list[DependencyStatus]:
    def probe() -> list[DependencyStatus]:
        try:
            r = httpx.get(f"{settings.ollama_base_url.rstrip('/')}/api/tags", timeout=settings.ollama_timeout_s)
            r.raise_for_status()
            installed = [m["name"] for m in r.json().get("models", [])]
        except Exception as exc:
            logger.warning("Ollama probe failed: %s", type(exc).__name__)
            detail = f"Unreachable ({type(exc).__name__})"
            return [
                DependencyStatus(key=k, name=n, required=False, state="unavailable", detail=detail)
                for k, n in (("ollama", "Ollama"), ("llm_model", "Language model"), ("embed_model", "Embedding model"))
            ]

        def has(model: str) -> bool:
            # "name" matches "name:latest"; "name:tag" must match exactly.
            return any(i == model or (":" not in model and i.split(":")[0] == model) for i in installed)

        def model_row(key: str, name: str, model: str) -> DependencyStatus:
            ok = has(model)
            return DependencyStatus(
                key=key, name=name, required=False, state="ok" if ok else "degraded",
                detail=f"{model} installed" if ok else f"{model} is not installed on the Ollama host",
            )

        return [
            DependencyStatus(key="ollama", name="Ollama", required=False, state="ok", detail="Reachable"),
            model_row("llm_model", "Language model", settings.ollama_model),
            model_row("embed_model", "Embedding model", settings.ollama_embed_model),
        ]

    return _timed(probe)


def check_weather(settings: Settings) -> list[DependencyStatus]:
    def probe() -> list[DependencyStatus]:
        try:
            r = httpx.get(
                settings.open_meteo_base_url,
                params={"latitude": 28.61, "longitude": 77.21, "current": "temperature_2m", "timezone": "GMT"},
                timeout=settings.ollama_timeout_s,
            )
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Weather provider probe failed: %s", type(exc).__name__)
            return [DependencyStatus(
                key="weather_provider", name="Weather provider (Open-Meteo)", required=False,
                state="unavailable", detail=f"Unreachable ({type(exc).__name__})",
            )]
        return [DependencyStatus(
            key="weather_provider", name="Weather provider (Open-Meteo)", required=False, state="ok", detail="Reachable",
        )]

    return _timed(probe)


_run_cache: dict[str, tuple[float, object]] = {}


def _local_run(directory: str, loader):
    """Loading verifies every artifact checksum (seconds); do it once per change of the run pointer, not per status request."""
    from pathlib import Path

    pointer = Path(directory) / "latest.json"
    mtime = pointer.stat().st_mtime if pointer.exists() else -1.0
    hit = _run_cache.get(directory)
    if hit and hit[0] == mtime:
        return hit[1]
    run = loader(directory)
    _run_cache[directory] = (mtime, run)
    return run


def check_forecast(settings: Settings) -> list[DependencyStatus]:
    """Optional external forecasting service: not configured is normal and is reported as such, never as an error."""
    key, name = "forecast_provider", "Pollution forecasting service (optional)"
    if not settings.ml_forecast_url.strip() and settings.ml_local_model_dir.strip():
        def probe_local() -> list[DependencyStatus]:
            from app.ml.artifacts import ModelUnavailable, load_run
            try:
                run = _local_run(settings.ml_local_model_dir, load_run)
            except ModelUnavailable as exc:
                return [DependencyStatus(key=key, name=name, required=False, state="unavailable", detail=f"Local model configured but unusable: {exc.message}")]
            return [DependencyStatus(key=key, name=name, required=False, state="ok", detail=f"Local model run {run.run_id} loaded")]

        return _timed(probe_local)
    if not settings.ml_forecast_url.strip():
        return [DependencyStatus(key=key, name=name, required=False, state="not_configured",
                                 detail="None connected: pollution forecasts are unavailable")]

    def probe() -> list[DependencyStatus]:
        try:
            headers = {"X-API-Key": settings.ml_forecast_api_key.get_secret_value()} if settings.ml_forecast_api_key.get_secret_value() else {}
            r = httpx.get(f"{settings.ml_forecast_url.rstrip('/')}/health", headers=headers, timeout=settings.ollama_timeout_s)
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Forecast provider probe failed: %s", type(exc).__name__)
            return [DependencyStatus(key=key, name=name, required=False, state="unavailable",
                                     detail=f"Configured but unreachable ({type(exc).__name__})")]
        return [DependencyStatus(key=key, name=name, required=False, state="ok", detail="Reachable")]

    return _timed(probe)


def check_air_quality(settings: Settings) -> list[DependencyStatus]:
    key, name = "aq_provider", "Air-quality source (OpenAQ)"
    secret = settings.aq_api_key.get_secret_value()
    if not secret:
        return [DependencyStatus(key=key, name=name, required=False, state="not_configured",
                                 detail="AQ_API_KEY is not set")]

    def probe() -> list[DependencyStatus]:
        try:
            r = httpx.get(
                f"{settings.aq_api_base_url.rstrip('/')}/locations", params={"limit": 1},
                headers={"X-API-Key": secret}, timeout=settings.ollama_timeout_s,
            )
            if r.status_code in (401, 403):
                return [DependencyStatus(key=key, name=name, required=False, state="degraded",
                                         detail="API key rejected by the provider")]
            r.raise_for_status()
        except Exception as exc:
            logger.warning("Air-quality probe failed: %s", type(exc).__name__)
            return [DependencyStatus(key=key, name=name, required=False, state="unavailable",
                                     detail=f"Unreachable ({type(exc).__name__})")]
        return [DependencyStatus(key=key, name=name, required=False, state="ok", detail="Reachable, key accepted")]

    return _timed(probe)


STATUS_TTL_S = 15.0
_status_cache: tuple[float, SystemStatusResponse] | None = None


def clear_status_cache() -> None:
    global _status_cache
    _status_cache = None


async def build_system_status(settings: Settings, refresh: bool = False) -> SystemStatusResponse:
    """Probes take several seconds in total (a down database alone costs its connect timeout), and every page asks for the
    status on load, so a result is reused for STATUS_TTL_S. `refresh=True` (the Recheck button) always probes again."""
    global _status_cache
    if not refresh and _status_cache and time.monotonic() - _status_cache[0] < STATUS_TTL_S:
        return _status_cache[1]
    result = await _probe_all(settings)
    _status_cache = (time.monotonic(), result)
    return result


async def _probe_all(settings: Settings) -> SystemStatusResponse:
    db, llm, weather, air, forecast = await asyncio.gather(
        asyncio.to_thread(check_database),
        asyncio.to_thread(check_ollama, settings),
        asyncio.to_thread(check_weather, settings),
        asyncio.to_thread(check_air_quality, settings),
        asyncio.to_thread(check_forecast, settings),
    )
    deps = [
        *db,
        *llm,
        *weather,
        *air,
        *forecast,
    ]
    now = utc_now()
    healthy = all(d.state == "ok" for d in deps if d.required)
    return SystemStatusResponse(
        status="ok" if healthy else "degraded",
        app=AppInfo(name=settings.app_name, version=settings.app_version, environment=settings.environment),
        generated_at=now,
        generated_at_ist=to_ist(now),
        dependencies=deps,
    )
