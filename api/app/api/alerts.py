from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Response

from app.alerts.models import MAX_RULES, AlertRule, AlertRuleCreate, AlertRulePatch, AlertsResponse
from app.alerts.service import AlertService, to_rule
from app.alerts.store import AlertRuleStore, TooManyRules
from app.api.air import get_air_service
from app.core.config import get_settings
from app.services.air_quality import AirQualityService

router = APIRouter(prefix="/alerts", tags=["alerts"])


@lru_cache
def get_alert_store() -> AlertRuleStore:
    return AlertRuleStore(Path(get_settings().data_dir) / "alerts.sqlite")


def get_alert_service(store: AlertRuleStore = Depends(get_alert_store), air: AirQualityService = Depends(get_air_service)) -> AlertService:
    return AlertService(store, air)


@router.get("", response_model=AlertsResponse, summary="Every rule with its current status against the latest observations")
async def status(svc: AlertService = Depends(get_alert_service)):
    return await svc.evaluate()


@router.post("/rules", response_model=AlertRule, status_code=201, summary="Create a threshold rule (a user-defined threshold)")
async def create_rule(body: AlertRuleCreate, svc: AlertService = Depends(get_alert_service)):
    try:
        return svc.create(body)
    except TooManyRules:
        raise HTTPException(409, {"code": "too_many_rules", "message": f"At most {MAX_RULES} rules are allowed. Delete one first."}) from None


@router.patch("/rules/{rule_id}", response_model=AlertRule, summary="Switch a rule on or off")
async def patch_rule(rule_id: int, body: AlertRulePatch, store: AlertRuleStore = Depends(get_alert_store)):
    row = store.set_enabled(rule_id, body.enabled)
    if row is None:
        raise HTTPException(404, {"code": "not_found", "message": "Alert rule not found."})
    return to_rule(row)


@router.delete("/rules/{rule_id}", status_code=204, summary="Delete a rule")
async def delete_rule(rule_id: int, store: AlertRuleStore = Depends(get_alert_store)):
    if not store.delete(rule_id):
        raise HTTPException(404, {"code": "not_found", "message": "Alert rule not found."})
    return Response(status_code=204)
