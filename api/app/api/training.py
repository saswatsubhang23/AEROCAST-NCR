"""One-click training: start, watch, cancel and activate local training jobs. See app/training/jobs.py for what a job does and why it is safe."""

from dataclasses import asdict
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.training.jobs import ALLOWED_HORIZONS, ALLOWED_POLLUTANTS, PRESETS, TrainingError, TrainingManager

router = APIRouter(prefix="/training", tags=["model training (local)"])

ACTION_HEADER = "X-AEROCAST-Action"
ACTION_VALUE = "training"


def require_action_header(x_aerocast_action: str | None = Header(None, alias=ACTION_HEADER)) -> None:
    """State-changing training calls must carry `X-AEROCAST-Action: training`.

    A custom header cannot be added by a cross-site form or an <img> tag, and a cross-origin script can only send it after a CORS
    pre-flight that the API answers only for the configured origins. So a page the user happens to have open cannot start, cancel or
    activate a training job in the background. (There is no login yet; this is a guard against drive-by requests, not authentication.)
    """
    if x_aerocast_action != ACTION_VALUE:
        raise HTTPException(403, {"code": "missing_action_header", "message": f"State-changing training calls require the header {ACTION_HEADER}: {ACTION_VALUE}."})



@lru_cache
def get_training_manager() -> TrainingManager:
    s = get_settings()
    data_dir = Path(s.data_dir)
    return TrainingManager(data_dir=data_dir, model_dir=Path(s.ml_local_model_dir or data_dir / "models"), history_db=s.ml_history_db or data_dir / "history.sqlite")


class StartBody(BaseModel):
    preset: str = Field("standard", description="standard (all four pollutants, full model set) or quick (PM2.5 only, two model types, minutes)")
    refresh_data: bool = Field(True, description="download the newest air-quality and weather hours, clean and rebuild features before training")
    pollutants: list[str] | None = None
    horizons: list[int] | None = None


def _wrap(fn):
    try:
        return fn()
    except TrainingError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc


def _job_json(mgr: TrainingManager, job, log_lines: int = 0) -> dict:
    out = asdict(job)
    if log_lines:
        out["log_tail"] = mgr.log_tail(job.job_id, log_lines)
    if job.status == "completed" and job.run_id:
        from app.api.models import summarize_run
        from app.ml.artifacts import ModelUnavailable, load_run

        try:
            run = summarize_run(load_run(job.candidate_root))
            cells = run["targets"]
            out["result"] = {
                "run_id": job.run_id, "created_at": run.get("created_at"), "cells": cells, "training": run.get("training"),
                "cells_total": len(cells), "beat_persistence": sum(1 for c in cells if c.get("beats_persistence_on_test") is True),
                "did_not_beat_persistence": sum(1 for c in cells if c.get("beats_persistence_on_test") is False),
            }
        except ModelUnavailable as exc:
            out["result_error"] = exc.message
    return out


@router.get("/status", summary="What training would use, the active model, and the running job if any")
def status(mgr: TrainingManager = Depends(get_training_manager)):
    from app.ml.artifacts import ModelUnavailable, load_run

    active = mgr.active()
    try:
        run = load_run(mgr.model_dir)
        model = {"available": True, "run_id": run.run_id, "created_at": run.manifest.get("created_at"), "data_digest": run.manifest.get("data_digest"),
                 "cells": len(run.estimators)}
    except ModelUnavailable as exc:
        model = {"available": False, "reason": exc.message}
    previous = None
    pp = mgr.model_dir / "previous.json"
    if pp.exists():
        try:
            import json

            previous = json.loads(pp.read_text(encoding="utf-8")).get("run_id")
        except (OSError, ValueError):
            previous = None
    return {
        "active_job": _job_json(mgr, active, 30) if active else None,
        "data": mgr.readiness(),
        "model": model,
        "previous_model": previous,
        "options": {"presets": list(PRESETS), "pollutants": ALLOWED_POLLUTANTS, "horizons": ALLOWED_HORIZONS},
        "notes": [
            "Training runs on this computer with the project's own scripts; it uses no language model and no Claude tokens.",
            "The newest data come from OpenAQ (a provider feed that lags by days for many stations) and the Open-Meteo archive (about two days behind). "
            "The CPCB history archive ends in September 2025 and is not refreshed.",
            "A finished job leaves the active model unchanged until you activate it.",
        ],
    }


@router.post("/jobs", status_code=202, summary="Start a training job", dependencies=[Depends(require_action_header)])
def start(body: StartBody, mgr: TrainingManager = Depends(get_training_manager)):
    return _wrap(lambda: _job_json(mgr, mgr.start(body.preset, body.refresh_data, body.pollutants, body.horizons)))


@router.get("/jobs", summary="Recent training jobs")
def jobs(limit: int = Query(15, ge=1, le=50), mgr: TrainingManager = Depends(get_training_manager)):
    return {"jobs": [_job_json(mgr, j) for j in mgr.list_jobs(limit)]}


@router.get("/jobs/{job_id}", summary="One job with its steps, log tail and (when finished) its held-out scores")
def job(job_id: str, log_lines: int = Query(120, ge=0, le=1000), mgr: TrainingManager = Depends(get_training_manager)):
    def go():
        j = mgr.load(job_id)
        if j is None:
            raise TrainingError("No such job.", "not_found", 404)
        return _job_json(mgr, j, log_lines)

    return _wrap(go)


@router.post("/jobs/{job_id}/cancel", summary="Stop a running job", dependencies=[Depends(require_action_header)])
def cancel(job_id: str, mgr: TrainingManager = Depends(get_training_manager)):
    return _wrap(lambda: _job_json(mgr, mgr.cancel(job_id)))


@router.post("/jobs/{job_id}/activate", summary="Make a finished job's model the active forecasting model", dependencies=[Depends(require_action_header)])
def activate(job_id: str, mgr: TrainingManager = Depends(get_training_manager)):
    return _wrap(lambda: mgr.activate(job_id))


@router.post("/rollback", summary="Return to the model that was active before the last activation", dependencies=[Depends(require_action_header)])
def rollback(mgr: TrainingManager = Depends(get_training_manager)):
    return _wrap(mgr.rollback)
