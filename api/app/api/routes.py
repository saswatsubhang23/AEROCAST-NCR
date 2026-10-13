from fastapi import APIRouter, Depends

from app.api.air import router as air_router
from app.api.alerts import router as alerts_router
from app.api.articles import router as articles_router
from app.api.assistant import router as assistant_router
from app.api.forecast import router as forecast_router
from app.api.knowledge import router as kb_router
from app.api.health_intel import router as health_intel_router
from app.api.jev import router as jev_router
from app.api.training import router as training_router
from app.api.models import router as models_router
from app.api.reports import router as reports_router
from app.api.terrain import router as terrain_router
from app.api.twin import router as twin_router
from app.api.geo import router as geo_router
from app.api.weather import router as weather_router
from app.core.config import Settings, get_settings
from app.core.time import utc_now
from app.schemas.system import HealthResponse, SystemStatusResponse
from app.services.system_status import build_system_status

router = APIRouter(prefix="/api")
router.include_router(weather_router)
router.include_router(air_router)
router.include_router(alerts_router)
router.include_router(assistant_router)
router.include_router(kb_router)
router.include_router(forecast_router)
router.include_router(reports_router)
router.include_router(models_router)
router.include_router(jev_router)
router.include_router(training_router)
router.include_router(health_intel_router)
router.include_router(twin_router)
router.include_router(geo_router)
router.include_router(terrain_router)
router.include_router(articles_router)


@router.get("/health", response_model=HealthResponse, tags=["system"], summary="Liveness check")
def health(settings: Settings = Depends(get_settings)) -> HealthResponse:
    """Always 200 while the process is serving. Does not touch any dependency."""
    return HealthResponse(status="ok", version=settings.app_version, time=utc_now())


@router.get(
    "/system/status",
    response_model=SystemStatusResponse,
    tags=["system"],
    summary="Dependency status",
)
async def system_status(refresh: bool = False, settings: Settings = Depends(get_settings)) -> SystemStatusResponse:
    """Reports each dependency separately. Always 200: an unavailable dependency is data, not a server error.
    A result is reused for 15 s; `?refresh=true` probes again."""
    return await build_system_status(settings, refresh=refresh)


@router.get("/system/data-availability", tags=["system"], summary="What data the application has, has partly, or does not have, with the consequence of each gap")
async def data_availability(settings: Settings = Depends(get_settings)) -> dict:
    """Live facts (the store's newest hours, provider reachability, the trained model, keys) plus the written catalogue of data the
    application does not have and what each gap prevents. Gaps are reported, never filled."""
    import asyncio

    from app.api.knowledge import get_kb_service
    from app.api.models import model_status
    from app.api.twin import history_path
    from app.history.store import HistoryStore
    from app.services.data_availability import build_availability, terrain_cached
    from app.twin.service import TwinDataUnavailable, TwinService

    status = await build_system_status(settings)
    deps = {d.key: {"state": d.state, "detail": d.detail} for d in status.dependencies}

    def twin_status() -> dict | None:
        path = history_path()
        if not path.exists():
            return None
        store = HistoryStore(path, read_only=True)
        try:
            return TwinService(store).status()
        except TwinDataUnavailable:
            return None
        finally:
            store.close()

    ts, model = await asyncio.gather(asyncio.to_thread(twin_status), asyncio.to_thread(model_status))
    try:
        kb_docs = len(get_kb_service().list_documents())
    except Exception:  # noqa: BLE001 - an unreadable index is reported as zero documents, not as an error page
        kb_docs = None
    return build_availability(settings, ts, deps, model, terrain_cached(settings), kb_docs)
