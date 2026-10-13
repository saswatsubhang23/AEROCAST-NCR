from fastapi import APIRouter

from app.core.config import get_settings

router = APIRouter(prefix="/models", tags=["trained models"])


def summarize_run(run) -> dict:
    """Recorded training metadata and held-out scores of one loaded run (nothing recomputed). Used for the active model and for candidates."""
    targets = []
    res = run.results
    for (pollutant, h), members in sorted(run.estimators.items()):
        e = (res.get("pollutants", {}).get(pollutant, {}).get("test", {}) or {}).get(str(h), {})
        names = [m["name"] for m in run.manifest["models"] if m["pollutant"] == pollutant and m["horizon"] == h]
        chosen = e.get("final_model", {}).get("members") or names
        scores = (e.get("ensemble", {}).get("test_scores") if e.get("final_model", {}).get("ensemble") else (e.get("models", {}).get(chosen[0], {}) or {}).get("scores")) if chosen else None
        base = e.get("baselines", {}).get("persistence")
        targets.append({"pollutant": pollutant, "horizon_hours": h, "model": "+".join(chosen), "unit": "µg/m³",
                        "test": None if not scores else {k: scores.get(k) for k in ("n", "mae", "rmse", "r2", "bias")},
                        "persistence_test": None if not base else {k: base.get(k) for k in ("n", "mae", "rmse", "r2")},
                        "beats_persistence_on_test": None if not (scores and base) else bool(scores["mae"] < base["mae"]),
                        "interval": run.intervals.get(pollutant, {}).get(str(h)), "calibration": e.get("calibration"),
                        "per_station": e.get("per_station_summary"), "stratified": e.get("stratified")})
    data = res.get("data", {})
    prov = res.get("dataset_provenance", {})
    return {
        "available": True, "run_id": run.run_id, "created_at": run.manifest.get("created_at"), "data_digest": run.manifest.get("data_digest"),
        "dataset_provenance": prov.get("provenance"), "targets": targets,
        "training": {p: {"rows": d.get("rows"), "stations": d.get("stations"), "split": d.get("split")} for p, d in data.items()},
        "importance": {p: v.get("importance") for p, v in res.get("pollutants", {}).items() if v.get("importance")},
        "location_experiment": {p: v.get("location_experiment") for p, v in res.get("pollutants", {}).items() if v.get("location_experiment")},
        "environment": run.environment, "feature_count": len(run.schema.get("feature_names", [])), "latency_hours": run.schema.get("latency_hours"),
        "report": "docs/ml-model-comparison.md",
        "caveat": "Scores are on a held-out later period of the same stations and are the only evidence of accuracy. Live use also requires fresh input data.",
    }


@router.get("/status", summary="Is a trained forecasting model loaded, and what was it trained and scored on?")
def model_status() -> dict:
    """Reads the saved run (verifying its checksums) and reports its recorded training metadata and held-out scores.
    Nothing here is computed from live data and nothing is filled in: an absent or damaged model is reported as unavailable."""
    from app.ml.artifacts import ModelUnavailable, load_run  # lazy: the API does not import ML libraries at start-up

    s = get_settings()
    if not s.ml_local_model_dir.strip():
        return {"available": False, "reason": "No local model directory is configured (ML_LOCAL_MODEL_DIR). Pollution forecasts are unavailable.", "targets": []}
    try:
        run = load_run(s.ml_local_model_dir)
    except ModelUnavailable as exc:
        return {"available": False, "reason": exc.message, "targets": []}
    return summarize_run(run)
