from functools import lru_cache

from fastapi import APIRouter, Depends

from app.core.config import get_settings
from app.jev.shadow import ShadowService

router = APIRouter(prefix="/jev", tags=["Jev decision support (optional, shadow only)"])


@lru_cache
def get_shadow_service() -> ShadowService:
    return ShadowService(get_settings())


@router.get("/status", summary="Mode of the optional Jev service and what it has recorded in shadow mode")
def status(svc: ShadowService = Depends(get_shadow_service)):
    s = get_settings()
    mode = s.jev_mode.strip().lower()
    local = s.jev_backend.strip().lower() != "typesafe"
    key = local or bool(s.typesafe_api_key.get_secret_value())
    return {
        "mode": mode, "backend": "laya (local)" if local else "typesafe (remote)", "enabled": svc.active, "api_key_configured": key,
        "base_url": None if local else s.jev_base_url, "model": s.laya_model if local else (s.jev_model or "discovered from GET /v1/models"),
        "load_state": getattr(svc.client, "state", None),
        "requests": svc.client.stats,
        "sent_to_service": "Nothing: the model runs on this machine." if local else "Only the user's question text, as the state of one choice question. No measurements, retrieved text, identities or history."
        + (" Passage excerpts are sent only if JEV_SEND_EXCERPTS=true." if s.jev_send_excerpts else ""),
        "influences_answers": False,
        "message": ("Switched off." if mode == "off" else "Shadow mode needs TYPESAFE_API_KEY." if not key else "Shadow mode: decisions are recorded, never used."),
    }


@router.get("/shadow", summary="Agreement, latency and failure statistics of the recorded shadow decisions")
def shadow(svc: ShadowService = Depends(get_shadow_service)):
    return svc.recorder.summary()
