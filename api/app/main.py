import logging
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging

logger = logging.getLogger("app.request")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)

    app = FastAPI(title=settings.app_name, version=settings.app_version)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        supplied = request.headers.get("X-Request-ID", "")
        # A caller-supplied id is only echoed (and logged) if it is plain and short; anything else is replaced.
        request.state.request_id = supplied if re.fullmatch(r"[A-Za-z0-9._-]{1,64}", supplied) else uuid.uuid4().hex[:12]
        start = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info(
            "%s %s -> %d (%d ms) [%s]",
            request.method, request.url.path, response.status_code,
            (time.perf_counter() - start) * 1000, request.state.request_id,
        )
        return response

    register_error_handlers(app)
    app.include_router(router)
    return app


def _warm_twin() -> None:
    """The twin's first inventory (status, station list) scans millions of stored rows and takes tens of seconds on a cold file cache.
    Doing it once at start-up, in the background on its own read-only connection, means the first person to open the page does not wait."""
    import threading
    from pathlib import Path

    def run() -> None:
        try:
            s = get_settings()
            path = Path(s.ml_history_db or Path(s.data_dir) / "history.sqlite")
            if not path.exists():
                return
            from app.history.store import HistoryStore
            from app.twin.service import TwinService

            TwinService(HistoryStore(path, read_only=True)).status()
        except Exception:  # noqa: BLE001 - a warm-up must never stop the API from starting
            logger.warning("twin warm-up skipped")

    threading.Thread(target=run, name="twin-startup-warm", daemon=True).start()


app = create_app()
_warm_twin()
