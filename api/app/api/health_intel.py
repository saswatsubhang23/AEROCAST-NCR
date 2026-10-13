from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.knowledge import get_kb_service
from app.api.twin import get_twin_service
from app.forecast.contract import Pollutant
from app.core.places import POLLUTANT_LABELS
from app.health_intel.service import ExposureUnavailable, exposure_summary, retrieve_evidence
from app.twin.service import TwinService, utc_floor

router = APIRouter(prefix="/health-intel", tags=["environmental exposure intelligence (population level)"])

DISCLAIMER = ("Environmental exposure summaries for research support. They describe observed concentrations at monitoring stations and the documents "
              "retrieved about them. They are not a diagnosis, not an individual risk estimate and not medical advice.")


@router.get("/exposure", summary="Observed exposure summary for a station or zone and period, with retrieved evidence")
async def exposure(
    pollutant: Pollutant = "pm25", start: datetime = Query(..., alias="from"), end: datetime = Query(..., alias="to"),
    station_id: int | None = None, zone: str | None = Query(None, max_length=40),
    svc: TwinService = Depends(get_twin_service), kb=Depends(get_kb_service),
):
    for d in (start, end):
        if d.tzinfo is None:
            raise HTTPException(422, {"code": "invalid_request", "message": "from and to must include a UTC offset."})
    try:
        summary = exposure_summary(svc.store, pollutant, utc_floor(start), utc_floor(end), station_id, zone)
    except ExposureUnavailable as exc:
        raise HTTPException(404, {"code": "exposure_unavailable", "message": exc.message}) from exc
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_request", "message": str(exc)}) from exc
    evidence = await retrieve_evidence(kb, POLLUTANT_LABELS[pollutant])
    return {**summary, "evidence": evidence, "disclaimer": DISCLAIMER}
