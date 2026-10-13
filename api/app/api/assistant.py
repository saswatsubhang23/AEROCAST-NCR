import json
from collections.abc import AsyncIterator
from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.api.air import get_air_service
from app.api.forecast import get_forecast_service
from app.api.jev import get_shadow_service
from app.api.knowledge import get_kb_service
from app.api.report_deps import get_report_service, get_report_store
from app.api.weather import get_weather_service
from app.assistant.orchestrator import AssistantOrchestrator
from app.assistant.tools import ToolExecutor
from app.core.config import Settings, get_settings
from app.kb.service import KnowledgeBaseService
from app.schemas.assistant import AssistantStatus, ChatRequest
from app.services.llm import LlmService

router = APIRouter(prefix="/assistant", tags=["assistant"])


@lru_cache
def get_llm_service() -> LlmService:
    return LlmService(get_settings())


def get_orchestrator(llm: LlmService = Depends(get_llm_service), kb: KnowledgeBaseService = Depends(get_kb_service),
                     reports=Depends(get_report_service), store=Depends(get_report_store), forecast=Depends(get_forecast_service)) -> AssistantOrchestrator:
    # A fresh ToolExecutor per answer keeps source ids (W1, A1, ...) per-turn; the services below keep the caches.
    return AssistantOrchestrator(
        get_settings(), llm, lambda: ToolExecutor(get_weather_service(), get_air_service(), kb, reports=reports, report_store=store, forecast=forecast),
        shadow=get_shadow_service(), forecast_available=lambda: forecast.configured,
    )


@router.get("/status", response_model=AssistantStatus, summary="Is the assistant usable right now?")
async def status(
    llm: LlmService = Depends(get_llm_service),
    settings: Settings = Depends(get_settings),
    kb: KnowledgeBaseService = Depends(get_kb_service),
    forecast=Depends(get_forecast_service),
):
    s = await llm.status()
    return AssistantStatus(
        available=s.available, model=s.model, code=s.code, message=s.message, tools_supported=s.tools_supported,
        thinking_enabled=settings.llm_think, context_length=s.context_length,
        knowledge_base="ready" if kb.ready else "unavailable", knowledge_base_note=kb.note,
        pollution_forecast="available" if forecast.configured else "unavailable",
        pollution_forecast_note=("A forecasting model is configured; the assistant can request a forecast, which may still be unavailable when the newest observations are too old."
                                 if forecast.configured else "No pollution-forecasting service is connected, so future air quality cannot be predicted."),
    )


@router.post("/chat", summary="Ask the assistant (server-sent events)")
async def chat(
    req: ChatRequest,
    orchestrator: AssistantOrchestrator = Depends(get_orchestrator),
    settings: Settings = Depends(get_settings),
):
    if req.messages[-1].role != "user":
        raise HTTPException(422, "The last message must be from the user.")
    if len(req.messages[-1].content) > settings.llm_max_message_chars:
        raise HTTPException(
            422, {"code": "message_too_long", "message": f"Messages are limited to {settings.llm_max_message_chars} characters."}
        )

    async def events() -> AsyncIterator[str]:
        async for event in orchestrator.run(req):
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )
