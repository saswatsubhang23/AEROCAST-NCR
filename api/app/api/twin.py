import asyncio
from datetime import datetime, timedelta, timezone
from typing import Literal
from pathlib import Path

from functools import lru_cache

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.forecast.contract import ForecastLocation, ForecastRequest, Pollutant
from app.forecast.provider import ForecastUnavailable
from app.history.ingest_air import iso
from app.history.store import HistoryStore
from app.twin.risk import PRESETS, custom_threshold, evaluate
from app.twin.service import MAX_WINDOW_HOURS, TwinDataUnavailable, TwinService, utc_floor
from app.twin.coupled_run import FORECAST_POLLUTANTS, CoupledService, process_catalogue
from app.twin.simulation import MAX_HOURS, MODES, Scenario, SimulationError, SimulationService

router = APIRouter(prefix="/twin", tags=["digital twin (historical replay)"])

TwinVariable = Literal["pm25", "pm10", "no2", "so2", "co", "o3", "aqi"]


def history_path() -> Path:
    s = get_settings()
    return Path(s.ml_history_db or Path(s.data_dir) / "history.sqlite")


def get_twin_service():
    path = history_path()
    if not path.exists():
        raise HTTPException(503, {"code": "twin_data_unavailable", "message": "No historical store exists yet. Build it with: python -m app.history all"})
    store = HistoryStore(path, read_only=True)
    try:
        yield TwinService(store)
    finally:
        store.close()


def _wrap(fn):
    try:
        return fn()
    except TwinDataUnavailable as exc:
        raise HTTPException(503, {"code": "twin_data_unavailable", "message": exc.message}) from exc
    except ValueError as exc:
        raise HTTPException(422, {"code": "invalid_request", "message": str(exc)}) from exc


@router.get("/status", summary="What the historical store contains (period, stations, pollutants, weather coverage)")
def status(svc: TwinService = Depends(get_twin_service)):
    return _wrap(svc.status)


@router.get("/stations", summary="Stations that have usable observations of a pollutant")
def stations(pollutant: Pollutant = "pm25", svc: TwinService = Depends(get_twin_service)):
    return {"pollutant": pollutant, "stations": _wrap(lambda: svc.stations(pollutant))}


@router.get("/window", summary=f"Hourly observed values for every station over up to {MAX_WINDOW_HOURS} hours, with gaps as null")
def window(
    pollutant: TwinVariable = "pm25", start: datetime = Query(..., alias="from"), end: datetime = Query(..., alias="to"), weather: bool = True,
    svc: TwinService = Depends(get_twin_service),
):
    for d in (start, end):
        if d.tzinfo is None:
            raise HTTPException(422, {"code": "invalid_request", "message": "from and to must include a UTC offset (for example 2026-03-01T00:00:00Z)."})
    return _wrap(lambda: svc.window(pollutant, utc_floor(start), utc_floor(end), weather))


@router.get("/estimate", summary="Inverse-distance spatial estimate between stations for one hour, with its leave-one-out error")
def estimate(pollutant: Pollutant = "pm25", time: datetime = Query(...), svc: TwinService = Depends(get_twin_service)):
    if time.tzinfo is None:
        raise HTTPException(422, {"code": "invalid_request", "message": "time must include a UTC offset."})
    return _wrap(lambda: svc.estimate(pollutant, utc_floor(time)))


async def _run_backtest(svc: TwinService, pollutant: str, station_id: int, origin: datetime) -> dict:
    from app.ml.inference import LocalModelProvider  # lazy: the API process only loads ML code when this is used

    if origin.tzinfo is None:
        raise HTTPException(422, {"code": "invalid_request", "message": "origin must include a UTC offset."})
    origin = utc_floor(origin)
    st = next((s for s in svc.stations(pollutant) if s["station_id"] == station_id), None)
    if st is None:
        raise HTTPException(404, {"code": "not_found", "message": "That station has no usable observations of this pollutant."})
    settings = get_settings()
    if not settings.ml_local_model_dir.strip():
        raise HTTPException(503, {"code": "model_unavailable", "message": "No trained model is configured (ML_LOCAL_MODEL_DIR)."})
    request = ForecastRequest(location=ForecastLocation(id=None, name=st["name"], lat=st["lat"], lon=st["lon"]), issued_at=origin + timedelta(minutes=20),
                              horizon_hours=72, pollutants=[pollutant])
    try:
        res = await LocalModelProvider(settings).forecast(request)
    except ForecastUnavailable as exc:
        raise HTTPException(503, {"code": "model_unavailable", "message": exc.message}) from exc
    f = res.forecasts[0]
    observed = svc.observed(pollutant, station_id, f.times)
    iv = f.intervals[0] if f.intervals else None
    rows = []
    for i, t in enumerate(f.times):
        rows.append({"time": iso(t), "lead_hours": int((t - origin).total_seconds() // 3600), "predicted": f.values[i], "observed": observed[i],
                     "lower": iv.lower[i] if iv else None, "upper": iv.upper[i] if iv else None,
                     "error": None if observed[i] is None else f.values[i] - observed[i]})
    scored = [r for r in rows if r["observed"] is not None]
    return {"pollutant": pollutant, "unit": f.unit, "station": st, "origin": iso(origin), "model_version": res.model_version,
            "interval_level": iv.level if iv else None, "rows": rows,
            "scored": {"n": len(scored), "mae": sum(abs(r["error"]) for r in scored) / len(scored) if scored else None},
            "provenance": res.provenance.model_dump(mode="json"),
            "note": "A back-test: the forecast uses only data available at the origin; observed values are shown afterwards for comparison. One origin is an example, not an accuracy estimate; see the model report."}


@router.get("/backtest", summary="Model forecast issued at a past origin, next to what was actually observed afterwards")
async def backtest(
    pollutant: Pollutant = "pm25", station_id: int = Query(...), origin: datetime = Query(...), svc: TwinService = Depends(get_twin_service),
):
    return await _run_backtest(svc, pollutant, station_id, origin)


@router.get("/thresholds", summary="Documented reference thresholds that risk windows can use")
def thresholds():
    return {"thresholds": [t.__dict__ for t in PRESETS.values()],
            "note": "The India NAAQS and WHO values are 24-hour standards/guidelines. Risk windows compare them with single forecast values, so they are indicators only."}


@router.get("/risk-windows", summary="Forecast lead times at or above a threshold, grouped into windows")
async def risk_windows(
    pollutant: Pollutant = "pm25", station_id: int = Query(...), origin: datetime = Query(...), threshold: str | None = None,
    threshold_value: float | None = Query(None, gt=0, le=100000), min_consecutive: int = Query(1, ge=1, le=10), svc: TwinService = Depends(get_twin_service),
):
    if (threshold is None) == (threshold_value is None):
        raise HTTPException(422, {"code": "invalid_request", "message": "Give exactly one of threshold (a preset key) or threshold_value."})
    if threshold is not None:
        t = PRESETS.get(threshold)
        if t is None or t.pollutant != pollutant:
            raise HTTPException(422, {"code": "invalid_request", "message": f"Unknown threshold for {pollutant}. See /api/twin/thresholds."})
    else:
        t = custom_threshold(pollutant, threshold_value)  # type: ignore[arg-type]
    bt = await _run_backtest(svc, pollutant, station_id, origin)
    out = evaluate(bt["rows"], t, min_consecutive)
    return {**out, "pollutant": pollutant, "station": bt["station"], "origin": bt["origin"], "model_version": bt["model_version"], "interval_level": bt["interval_level"],
            "unit": bt["unit"], "input_data": bt["provenance"]["input_data"], "observed_afterwards": [r["observed"] for r in bt["rows"]]}


# The per-station forecasts of an early-warning overview take about a minute for 40 stations. They depend only on the pollutant, the origin
# hour, the station set and the active model, so they are reused for a few minutes; the threshold, ranking and ages are recomputed each time.
_EW_TTL_S = 300.0
_EW_MAX_ENTRIES = 24
_ew_cache: dict[tuple, tuple[float, dict, list]] = {}


def _model_stamp() -> tuple:
    """Changes when a different model is activated (the registry pointer is rewritten), so a cached overview is never served for the old one."""
    base = Path(get_settings().ml_local_model_dir) if get_settings().ml_local_model_dir.strip() else Path(get_settings().data_dir) / "models"
    try:
        st = (base / "latest.json").stat()
        return (str(base), st.st_mtime_ns, st.st_size)
    except OSError:
        return (str(base), None, None)


async def _forecast_results(svc: TwinService, pollutant: str, origin: datetime, inventory: list[dict]) -> tuple[dict[int, dict], list[dict], bool]:
    """The trained model's forecast for every station in `inventory` at `origin`, reused for a few minutes (see _ew_cache). Returns
    (results by station id, skipped stations with reasons, whether the results came from the cache)."""
    import asyncio
    import time

    cache_key = (pollutant, origin, tuple(s["station_id"] for s in inventory), _model_stamp())
    hit = _ew_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < _EW_TTL_S:
        return hit[1], hit[2], True
    results: dict[int, dict] = {}
    skipped: list[dict] = []
    sem = asyncio.Semaphore(4)

    async def one(st: dict):
        async with sem:
            try:
                results[st["station_id"]] = await _run_backtest(svc, pollutant, st["station_id"], origin)
            except HTTPException as exc:
                skipped.append({"station_id": st["station_id"], "name": st["name"], "reason": (exc.detail or {}).get("message", "unavailable")})

    await asyncio.gather(*(one(st) for st in inventory))
    if results:  # a total failure is never cached: the next request tries again
        if len(_ew_cache) >= _EW_MAX_ENTRIES:
            _ew_cache.pop(min(_ew_cache, key=lambda k: _ew_cache[k][0]))
        _ew_cache[cache_key] = (time.monotonic(), results, skipped)
    return results, skipped, False


@router.get("/early-warning", summary="Every station that reported at an origin, ranked by its forecast against a threshold")
async def early_warning(
    pollutant: Pollutant = "pm25", origin: datetime = Query(...), threshold: str | None = None,
    threshold_value: float | None = Query(None, gt=0, le=100000), min_consecutive: int = Query(1, ge=1, le=10),
    max_stations: int = Query(40, ge=1, le=120), svc: TwinService = Depends(get_twin_service),
):
    from app.core.time import utc_now
    from app.twin.early_warning import build_overview

    if (threshold is None) == (threshold_value is None):
        raise HTTPException(422, {"code": "invalid_request", "message": "Give exactly one of threshold (a preset key) or threshold_value."})
    if threshold is not None:
        t = PRESETS.get(threshold)
        if t is None or t.pollutant != pollutant:
            raise HTTPException(422, {"code": "invalid_request", "message": f"Unknown threshold for {pollutant}. See /api/twin/thresholds."})
    else:
        t = custom_threshold(pollutant, threshold_value)  # type: ignore[arg-type]
    if origin.tzinfo is None:
        raise HTTPException(422, {"code": "invalid_request", "message": "origin must include a UTC offset."})
    origin = utc_floor(origin)
    reporting = {r["station_id"] for r in svc._hour_values(pollutant, origin)}
    inventory = [s for s in svc.stations(pollutant) if s["station_id"] in reporting]
    if not inventory:
        raise HTTPException(404, {"code": "no_observations", "message": "No station has a usable observation of this pollutant at that hour, so there is nothing to forecast from."})
    inventory = inventory[:max_stations]
    results, skipped, cached = await _forecast_results(svc, pollutant, origin, inventory)
    if not results:
        reason = skipped[0]["reason"] if skipped else "no forecast could be produced"
        raise HTTPException(503, {"code": "model_unavailable", "message": f"The model could not forecast any station at this origin: {reason}"})
    any_bt = next(iter(results.values()))
    stations = [{"station_id": st["station_id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"], "rows": results[st["station_id"]]["rows"]}
                for st in inventory if st["station_id"] in results]
    weak: list[int] = []
    importance = None
    try:
        from app.ml.artifacts import load_run
        from app.ml.inference import beats_persistence

        run = load_run(get_settings().ml_local_model_dir)
        weak = [h for h in run.horizons(pollutant) if beats_persistence(run, pollutant, h) is False]
        imp = run.results.get("pollutants", {}).get(pollutant, {}).get("importance") or {}
        if imp:
            importance = next(iter(imp.values()))
    except Exception:  # noqa: BLE001 - diagnostics are optional; the overview itself does not depend on them
        pass
    out = build_overview(pollutant=pollutant, origin=origin, now=utc_now(), threshold=t, stations=stations, skipped=skipped, weak_horizons=weak,
                         model_version=any_bt["model_version"], interval_level=any_bt["interval_level"], importance=importance, min_consecutive=min_consecutive)
    out["forecasts_reused"] = cached  # the per-station forecasts came from a request within the last few minutes (same origin, stations and model)
    return out


def _regimes_path() -> Path:
    s = get_settings()
    base = Path(s.ml_local_model_dir) if s.ml_local_model_dir.strip() else Path(s.data_dir) / "models"
    return base / "regimes.json"


@router.get("/regimes", summary="Learned atmospheric regimes, how PM2.5 differs between them, and each station's regime at an hour")
def regimes(time: datetime | None = None, svc: TwinService = Depends(get_twin_service)):
    import json

    import numpy as np

    from app.ml.regimes import FEATURES, assign, feature_matrix

    path = _regimes_path()
    if not path.exists():
        raise HTTPException(503, {"code": "regimes_unavailable", "message": "No regime analysis has been run. Use: python -m app.ml regimes"})
    res = json.loads(path.read_text(encoding="utf-8"))
    model = res["model"]
    out = {"regimes": [{"index": i, "label": model["labels"][i], "centroid": dict(zip(FEATURES, model["centroids"][i])),
                        "development": res["development"]["pm"].get(str(i)), "test": res["test"]["pm"].get(str(i))} for i in range(model["k"])],
           "selection": res["selection"], "method": res["method"], "pollutant": res["pollutant"], "dev_end": res["dev_end"],
           "kruskal_wallis_test_period": res["test"]["kruskal_wallis"], "small_test_samples": res["test"]["small_samples"], "caveat": res["caveat"], "features": FEATURES}
    if time is not None:
        if time.tzinfo is None:
            raise HTTPException(422, {"code": "invalid_request", "message": "time must include a UTC offset."})
        t = iso(utc_floor(time))
        rows = svc.store.query("select station_id, time_utc, wind_speed_10m, boundary_layer_height, relative_humidity_2m, precipitation, temperature_2m "
                               "from clean_weather where time_utc=?", (t,))
        X, keys = feature_matrix(rows)
        out["time"] = t
        out["stations"] = [] if len(X) == 0 else [{"station_id": sid, "regime": int(g)} for (sid, _), g in zip(keys, assign(np.asarray(X), model))]
    return out


# ---------------------------------------------------------------------------------------------- simulations
@lru_cache
def get_simulation_service() -> SimulationService:
    from app.api.weather import get_fields_service

    s = get_settings()
    return SimulationService(get_fields_service(), store_dir=Path(s.data_dir) / "twin_runs")


class ScenarioBody(BaseModel):
    wind_scale: float = 1.0
    wind_rotation_deg: float = 0.0
    diffusivity_m2s: float = 50.0
    loss_per_hour: float = 0.0
    mixing_mode: str = "none"
    aloft_ratio: float = 0.0


class SimulationBody(BaseModel):
    mode: str = Field("transport", description="one of " + ", ".join(MODES))
    pollutant: Pollutant = "pm25"
    hours: int = Field(24, ge=6, le=MAX_HOURS)
    init_time: datetime | None = Field(None, description="UTC initialisation hour; defaults to the newest hour with enough observations")
    scenario: ScenarioBody | None = None
    validate_against_observations: bool = True


async def _simulate(svc: SimulationService, twin: TwinService, body: SimulationBody):
    try:
        scenario = Scenario(**body.scenario.model_dump()) if body.scenario else None
        return await svc.run(twin, body.mode, body.pollutant, body.hours, body.init_time, scenario, body.validate_against_observations)
    except SimulationError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc
    except TwinDataUnavailable as exc:
        raise HTTPException(503, {"code": "twin_data_unavailable", "message": exc.message}) from exc


@router.post("/simulations", summary="Run a transport simulation (baseline, scenario or live) and return its time-indexed fields")
async def create_simulation(body: SimulationBody, twin: TwinService = Depends(get_twin_service), svc: SimulationService = Depends(get_simulation_service)):
    return await _simulate(svc, twin, body)


@router.get("/simulations/live", summary="The live run: re-created only when the observations or the wind data have changed")
async def live_simulation(pollutant: Pollutant = "pm25", hours: int = Query(24, ge=6, le=MAX_HOURS), twin: TwinService = Depends(get_twin_service),
                          svc: SimulationService = Depends(get_simulation_service)):
    return await _simulate(svc, twin, SimulationBody(mode="live", pollutant=pollutant, hours=hours))


@router.get("/simulations/{run_id}", summary="A stored simulation run by id (runs are reproducible from their inputs)")
def get_simulation(run_id: str, svc: SimulationService = Depends(get_simulation_service)):
    if not run_id.isalnum() or len(run_id) > 32:
        raise HTTPException(422, {"code": "invalid_request", "message": "invalid run id"})
    run = svc.get(run_id)
    if run is None:
        raise HTTPException(404, {"code": "run_not_found", "message": "No stored run has that id."})
    return run


@router.get("/validation/estimates", summary="Out-of-sample check of the spatial estimate over many hours (leave-one-out against a baseline)")
def validate_estimates(
    pollutant: Pollutant = "pm25", start: datetime = Query(..., alias="from"), end: datetime = Query(..., alias="to"), hours: int = Query(24, ge=1, le=72),
    svc: TwinService = Depends(get_twin_service),
):
    for d in (start, end):
        if d.tzinfo is None:
            raise HTTPException(422, {"code": "invalid_request", "message": "from and to must include a UTC offset."})
    return _wrap(lambda: svc.validate_estimates(pollutant, utc_floor(start), utc_floor(end), hours))


# ---------------------------------------------------------------------------------------------- coupled multi-species model
@lru_cache
def get_coupled_service() -> CoupledService:
    from app.api.weather import get_fields_service

    return CoupledService(get_fields_service(), store_dir=Path(get_settings().data_dir) / "twin_coupled")


class CoupledBody(BaseModel):
    source: Literal["observations", "model_forecast", "live", "cams"] = Field(
        "observations", description="start from stored station observations, the trained model's station forecasts, the live OpenAQ readings (with their ages), "
                                    "or the current CAMS model field (hourly, gap-free, model output)")
    hours: int = Field(24, ge=6, le=MAX_HOURS)
    init_time: datetime | None = Field(None, description="observations: the start hour; model_forecast: the forecast ORIGIN (data time). Default: the newest hour with enough PM2.5 stations")
    lead_hours: int = Field(6, ge=1, le=72, description="model_forecast only: which trained lead time starts the run (the run begins at origin + lead)")
    processes: list[str] | None = Field(None, description="couplings to switch on: dilution, deposition, washout, oxidation (default all)")
    params: dict | None = None
    focus: str = "pm25"
    validate_against_observations: bool = True
    max_stations: int = Field(30, ge=5, le=60)


@router.get("/coupled/config", summary="The coupled model's processes, parameters, basis and what it does not model")
def coupled_config():
    return process_catalogue()


@router.post("/coupled", summary="Run the coupled multi-species model, from observations or from the trained model's forecasts")
async def run_coupled_model(body: CoupledBody, twin: TwinService = Depends(get_twin_service), svc: CoupledService = Depends(get_coupled_service)):
    from app.core.time import utc_now

    try:
        station_values = None
        forecast_info = None
        init = body.init_time
        if body.source == "live":
            station_values, init, forecast_info = await _live_state()
        elif body.source == "cams":
            station_values, init, forecast_info = await _cams_state()
        elif body.source == "model_forecast":
            if init is None:
                status = await asyncio.to_thread(twin.status)
                period = status["periods"].get("pm25")
                if not period:
                    raise SimulationError("the store has no usable PM2.5 observations", "twin_data_unavailable", 503)
                init = datetime.fromisoformat(period["dense_to"].replace("Z", "+00:00"))
            if init.tzinfo is None:
                raise SimulationError("init_time must include a UTC offset")
            origin = utc_floor(init)
            station_values, forecast_info = await _model_forecast_state(twin, origin, body.lead_hours, body.max_stations)
            init = origin + timedelta(hours=body.lead_hours)  # the run starts at the VALID time of the forecast values
        return await svc.run(twin, hours=body.hours, init_time=init, processes=body.processes, params=body.params, focus=body.focus,
                             validate=body.validate_against_observations, station_values=station_values, forecast_info=forecast_info)
    except SimulationError as exc:
        raise HTTPException(exc.status, {"code": exc.code, "message": exc.message}) from exc
    except TwinDataUnavailable as exc:
        raise HTTPException(503, {"code": "twin_data_unavailable", "message": exc.message}) from exc


async def _model_forecast_state(twin: TwinService, origin: datetime, lead: int, max_stations: int) -> tuple[dict[str, list[dict]], dict]:
    """Station values the trained model forecasts for origin + lead, per pollutant it was trained for. The model is applied only to data
    available at the origin, exactly as in a back-test."""
    from app.ml.artifacts import ModelUnavailable, load_run
    from app.ml.inference import beats_persistence

    try:
        run = load_run(get_settings().ml_local_model_dir)
    except ModelUnavailable as exc:
        raise SimulationError(f"no trained model is available: {exc.message}", "model_unavailable", 503) from exc
    horizons = sorted({h for p in FORECAST_POLLUTANTS for h in run.horizons(p)})
    if lead not in horizons:
        raise SimulationError(f"the trained model has no +{lead} h forecast; available lead times: {', '.join(str(h) for h in horizons) or 'none'}")
    values: dict[str, list[dict]] = {}
    used: dict[str, int] = {}
    skipped_total = 0
    for pol in FORECAST_POLLUTANTS:
        if lead not in run.horizons(pol):
            continue
        reporting = {r["station_id"] for r in twin._hour_values(pol, origin)}
        inventory = [s for s in twin.stations(pol) if s["station_id"] in reporting][:max_stations]
        if not inventory:
            continue
        results, skipped, _ = await _forecast_results(twin, pol, origin, inventory)
        skipped_total += len(skipped)
        rows = []
        for st in inventory:
            res = results.get(st["station_id"])
            if not res:
                continue
            row = next((r for r in res["rows"] if r["lead_hours"] == lead), None)
            if row is not None and row.get("predicted") is not None:
                rows.append({"station_id": st["station_id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"], "value": float(row["predicted"])})
        if rows:
            values[pol] = rows
            used[pol] = len(rows)
    if "pm25" not in values or len(values["pm25"]) < 3:
        raise SimulationError("the model could not forecast PM2.5 at three or more stations for that origin (inputs missing or too old)", "model_unavailable", 503)
    weak = [p for p in values if beats_persistence(run, p, lead) is False]
    return values, {
        "origin": iso(origin), "lead_hours": lead, "valid_time": iso(origin + timedelta(hours=lead)), "model_version": run.run_id,
        "stations_per_pollutant": used, "skipped_stations": skipped_total, "pollutants_without_model": [p for p in ("so2", "co") ],
        "weak_pollutants": weak,
        "note": "Station values are the trained model's forecasts for the lead time, interpolated between stations to start the simulation. SO2 has no trained model, so it is not initialised.",
    }


@router.get("/coupled/{run_id}", summary="A stored coupled run by id (runs are reproducible from their inputs)")
def get_coupled_run(run_id: str, svc: CoupledService = Depends(get_coupled_service)):
    if not run_id.isalnum() or len(run_id) > 32:
        raise HTTPException(422, {"code": "invalid_request", "message": "invalid run id"})
    run = svc.get(run_id)
    if run is None:
        raise HTTPException(404, {"code": "run_not_found", "message": "No stored run has that id."})
    return run


LIVE_MAX_SPREAD_H = 3.0  # readings more than this much older than the newest one are not part of the "now" field
_UG_PER_PPB = {"no2": 1.88, "o3": 1.96, "so2": 2.62}


async def _live_state() -> tuple[dict[str, list[dict]], datetime, dict]:
    """Station values from the live OpenAQ feed: for each species, the stations whose newest reading is within LIVE_MAX_SPREAD_H of the
    newest reading overall. Gas readings in ppb are converted with the documented 25 C factors; anything else in another unit is skipped."""
    from app.api.air import get_air_service
    from app.integrations.http import UpstreamError
    from app.integrations.openaq import AqNotConfigured

    try:
        resp = await get_air_service().stations()
    except AqNotConfigured as exc:
        raise SimulationError("the live air-quality feed is not configured (AQ_API_KEY)", "not_configured", 503) from exc
    except UpstreamError as exc:
        raise SimulationError("the live air-quality feed is temporarily unavailable", "live_unavailable", 503) from exc
    readings: list[tuple[str, dict, float, datetime]] = []
    for st in resp.stations:
        for pol in ("pm25", "pm10", "no2", "o3", "so2"):
            r = st.latest.get(pol)
            if r is None:
                continue
            unit = (r.unit or "").lower().replace(" ", "")
            if unit in ("µg/m³", "ug/m3", "μg/m³", "µg/m3"):
                v = float(r.value)
            elif unit == "ppb" and pol in _UG_PER_PPB:
                v = float(r.value) * _UG_PER_PPB[pol]
            else:
                continue
            readings.append((pol, {"station_id": st.id, "name": st.name, "lat": st.lat, "lon": st.lon}, v, r.observed_at))
    if not readings:
        raise SimulationError("the live feed has no usable readings right now", "live_unavailable", 503)
    newest = max(t for *_, t in readings)
    cutoff = newest - timedelta(hours=LIVE_MAX_SPREAD_H)
    values: dict[str, list[dict]] = {}
    for pol, meta, v, t in readings:
        if t >= cutoff and v >= 0:
            values.setdefault(pol, []).append({**meta, "value": v})
    start = utc_floor(newest)
    from app.core.time import utc_now

    return values, start, {
        "origin": iso(start), "lead_hours": 0, "valid_time": iso(start), "model_version": None, "live": True,
        "newest_reading_at": iso(newest), "newest_reading_age_hours": round((utc_now() - newest).total_seconds() / 3600.0, 1),
        "stations_per_pollutant": {p: len(v) for p, v in values.items()},
        "note": f"Newest readings from the live OpenAQ feed, within {LIVE_MAX_SPREAD_H:g} h of the most recent one. Many stations publish with a lag, so the age is shown.",
    }


async def _cams_state() -> tuple[dict[str, list[dict]], datetime, dict]:
    """The current CAMS model field as the start: each lattice cell becomes a pseudo-station (negative id) so the same interpolation applies.
    The values are model output, not measurements, and the run says so."""
    from app.api.air import get_cams_service
    from app.core.time import utc_now
    from app.integrations.http import UpstreamError

    try:
        cams = await get_cams_service().fields(past_hours=3, forecast_hours=1)
    except UpstreamError as exc:
        raise SimulationError("the CAMS model feed is temporarily unavailable", "live_unavailable", 503) from exc
    idx = cams.get("now_index")
    if idx is None:
        raise SimulationError("the CAMS feed has no hour at or before now", "live_unavailable", 503)
    lats, lons = cams["grid"]["lats"], cams["grid"]["lons"]
    values: dict[str, list[dict]] = {}
    for code in ("pm25", "pm10", "no2", "o3", "so2"):
        v = cams["variables"].get(code)
        if not v or not v["available"]:
            continue
        frame = v["values"][idx]
        rows = []
        for r, la in enumerate(lats):
            for c, lo in enumerate(lons):
                x = frame[r][c]
                if x is not None:
                    rows.append({"station_id": -(r * len(lons) + c + 1), "name": f"CAMS cell {la:.2f}N {lo:.2f}E", "lat": la, "lon": lo, "value": float(x)})
        if rows:
            values[code] = rows
    start = utc_floor(datetime.fromisoformat(cams["times"][idx].replace("Z", "+00:00")))
    return values, start, {
        "origin": iso(start), "lead_hours": 0, "valid_time": iso(start), "model_version": "ECMWF CAMS (via Open-Meteo)", "cams": True,
        "stations_per_pollutant": {p: len(v) for p, v in values.items()},
        "newest_reading_age_hours": round((utc_now() - start).total_seconds() / 3600.0, 1),
        "note": "The start is the current CAMS atmospheric-chemistry model field (model cells of about 0.4 degrees, 44 km, so only a few cells cover the area), interpolated to the grid. It is model output, not a measurement, "
                "and it already includes emissions and chemistry.",
    }
