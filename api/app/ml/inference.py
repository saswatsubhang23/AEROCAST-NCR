"""Request-time inference with saved models, behind the existing forecast contract (`app.forecast.contract`).

This module never trains anything and never imports the training code. It builds the model input with exactly the same function
that built the training rows (`app.history.features.compute_rows`), from the history store, then applies saved artifacts.

It says "unavailable" (ForecastUnavailable) instead of answering whenever it cannot do so honestly:
  * no model directory configured, no run saved, files missing/damaged/changed, library versions differ from training;
  * no station near the requested location, or its newest observation is older than `ml_max_input_age_hours`;
  * no weather inputs at that hour, or no requested pollutant has a trained model.
Because the live OpenAQ/CPCB feed is typically about two days behind (see docs/historical-data-pipeline.md), requests made "now"
will usually be unavailable. Requests whose `issued_at` lies inside the stored history (back-testing) are answered.
"""

import asyncio
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.core.config import Settings
from app.core.places import distance_km
from app.core.time import utc_now
from app.forecast.contract import (
    CONTRACT_VERSION, DataFreshness, ForecastRequest, ForecastResponse, PollutantForecast, PredictionInterval, Provenance, SpatialResolution,
)
from app.forecast.provider import ForecastUnavailable
from app.history import features as F
from app.history.ingest_air import iso, parse_iso
from app.history.store import HistoryStore
from app.ml.artifacts import LoadedRun, ModelUnavailable, load_run

HOUR = timedelta(hours=1)
WINDOW_HOURS = 200  # covers the longest lag (168 h) and the longest rolling window (72 h)


class LocalModelProvider:
    """A ForecastProvider backed by artifacts produced by `python -m app.ml train`."""

    name = "local-model"

    def __init__(self, settings: Settings, now=utc_now):
        self._model_dir = settings.ml_local_model_dir
        self._db = settings.ml_history_db or str(Path(settings.data_dir) / "history.sqlite")
        self._max_km = settings.ml_max_station_km
        self._max_age = settings.ml_max_input_age_hours
        self._now = now
        self._run: LoadedRun | None = None
        self._error: str | None = None

    # ---- loading -----------------------------------------------------------------------------------
    def _loaded(self) -> LoadedRun:
        # load_run is cached by the registry pointer's modification time, so this is cheap, and a newly activated model is picked up
        # on the next request without restarting the API.
        if not self._model_dir:
            raise ForecastUnavailable("No local model directory is configured.")
        try:
            self._run = load_run(self._model_dir)
        except ModelUnavailable as exc:
            raise ForecastUnavailable(exc.message) from None
        return self._run

    async def health(self) -> None:
        await asyncio.to_thread(self._loaded)
        if not Path(self._db).exists():
            raise ForecastUnavailable("The historical data store the model reads its inputs from is missing.")

    async def forecast(self, request: ForecastRequest) -> ForecastResponse:
        return await asyncio.to_thread(self._forecast_sync, request)

    # ---- the work ------------------------------------------------------------------------------------
    def _forecast_sync(self, request: ForecastRequest) -> ForecastResponse:
        run = self._loaded()
        if not Path(self._db).exists():
            raise ForecastUnavailable("The historical data store the model reads its inputs from is missing.")
        store = HistoryStore(self._db, read_only=True)
        try:
            return self._predict(run, store, request)
        finally:
            store.close()

    def _predict(self, run: LoadedRun, store: HistoryStore, request: ForecastRequest) -> ForecastResponse:
        issued = request.issued_at.astimezone(timezone.utc)
        origin_cap = issued.replace(minute=0, second=0, microsecond=0)
        usable_pollutants = [p for p in request.pollutants if run.horizons(p)]
        if not usable_pollutants:
            raise ForecastUnavailable("No trained model exists for the requested pollutant(s).")
        schema = run.schema
        series, notes, weak = [], [], []
        for pollutant in usable_pollutants:
            picked = self._pick_station(store, request.location.lat, request.location.lon, pollutant, origin_cap)
            station, origin = picked
            horizons = [h for h in run.horizons(pollutant) if origin + h * HOUR > issued and origin + h * HOUR <= issued + request.horizon_hours * HOUR]
            if not horizons:
                continue
            row = self._feature_row(store, station["station_id"], pollutant, origin, schema)
            x = np.array([[np.nan if row.get(c) is None else row[c] for c in schema["feature_names"] if c not in F_LOCATION] +
                          ([station["lat"], station["lon"]] if schema["location_features"] else [])], dtype=np.float32)
            times, values, lowers, uppers = [], [], [], []
            for h in horizons:
                if beats_persistence(run, pollutant, h) is False:
                    weak.append(f"{pollutant} +{h} h")
                pred = float(np.mean([float(e.predict(x)[0]) for e in run.estimators[(pollutant, h)]]))
                pred = max(0.0, pred) if math.isfinite(pred) else None
                if pred is None:
                    continue
                iv = run.intervals.get(pollutant, {}).get(str(h))
                times.append(origin + h * HOUR)
                values.append(pred)
                if iv:
                    lowers.append(max(0.0, min(pred, pred + iv["q_low"])))
                    uppers.append(max(pred, pred + iv["q_high"]))
            if not times:
                continue
            level = run.intervals.get(pollutant, {}).get(str(horizons[0]), {}).get("level")
            has_interval = bool(level and len(lowers) == len(times))
            age = max(0.0, (issued - origin).total_seconds() / 3600.0)
            flags = [f"weak_horizon:+{h}h" for h in horizons if beats_persistence(run, pollutant, h) is False]
            flags.append("interval:empirical_validation_residuals" if has_interval else "interval:none")
            flags.append("weather_inputs:archive_values_from_store")
            series.append(PollutantForecast(
                pollutant=pollutant, unit="µg/m³", times=times, values=values,
                intervals=[PredictionInterval(level=level, lower=lowers, upper=uppers)] if has_interval else [],
                spatial=SpatialResolution(kind="station", station_id=str(station["station_id"]), station_name=station["name"], lat=station["lat"], lon=station["lon"],
                                          distance_km=round(float(station["dist"]), 2)),
                freshness=DataFreshness(newest_input_at=origin, input_age_hours=round(age, 2), max_age_hours=float(self._max_age),
                                        status="fresh" if age <= self._max_age else "stale"),
                quality_flags=flags))
            notes.append(f"{pollutant}: station {station['name']} ({station['station_id']}, {station['dist']:.1f} km away), last observation {iso(origin)}")
        if not series:
            raise ForecastUnavailable("The trained models cannot produce a forecast for this request (no horizon falls after the issue time within the requested range).")
        last = max(s.times[-1] for s in series)
        horizon = min(request.horizon_hours, max(1, math.ceil((last - issued) / HOUR)))
        data = run.results.get("data", {})
        training = "; ".join(f"{p}: {d['rows']:,} rows, {d['split']['data_from']} to {d['split']['dev_to_exclusive']} (test from {d['split']['test_from']})" for p, d in data.items() if p in usable_pollutants)
        names = sorted({e["name"] for e in run.manifest["models"] if e["pollutant"] in usable_pollutants})
        return ForecastResponse(
            contract_version=CONTRACT_VERSION, model_version=run.run_id, issued_at=request.issued_at, location=request.location, horizon_hours=horizon, forecasts=series,
            provenance=Provenance(
                provider="AEROCAST local model", model_name=", ".join(names)[:80], generated_at=self._now(),
                input_data=notes + ["weather: Open-Meteo archive values at the station, from the historical store"],
                training_data=training[:500] or None,
                notes=("Trained offline on about one year of data and not validated against live conditions. Intervals are empirical "
                       "validation-residual quantiles, not guarantees. See docs/ml-model-comparison.md for held-out scores."
                       + (f" WARNING: on the held-out period the model for {', '.join(weak)} did not beat the persistence baseline." if weak else ""))[:1000]))

    def _pick_station(self, store: HistoryStore, lat: float, lon: float, pollutant: str, origin_cap: datetime):
        stations = store.query("select station_id, name, lat, lon from stations")
        near = sorted(((distance_km(lat, lon, s["lat"], s["lon"]), s) for s in stations), key=lambda x: x[0])
        near = [x for x in near if x[0] <= self._max_km]
        if not near:
            raise ForecastUnavailable(f"No monitoring station within {self._max_km:.0f} km of the requested location.")
        newest_age = None
        for dist, s in near:
            r = store.query("select max(label_utc) m from clean_air where station_id=? and pollutant=? and usable=1 and label_utc<=?",
                            (s["station_id"], pollutant, iso(origin_cap)))
            label = parse_iso(r[0]["m"]) if r and r[0]["m"] else None
            if label is None:
                continue
            age = (origin_cap - label) / HOUR
            newest_age = age if newest_age is None else min(newest_age, age)
            if age <= self._max_age:
                return {**dict(s), "dist": dist}, label
        why = "no station near the location has any observation before the issue time" if newest_age is None else \
            f"the newest observation near the location is {newest_age:.0f} h old (the limit is {self._max_age} h)"
        raise ForecastUnavailable(f"Not enough recent data to forecast: {why}.")

    def _feature_row(self, store: HistoryStore, station_id: int, pollutant: str, origin: datetime, schema: dict) -> dict:
        loaded = F.load_station_inputs(store, station_id, pollutant, origin - WINDOW_HOURS * HOUR, origin)
        if loaded is None:
            raise ForecastUnavailable("No usable recent observations are stored for the nearest station.")
        times, series, weather, prov, soft = loaded
        latency = int(schema.get("latency_hours") or 0)
        rows = F.compute_rows(station_id, pollutant, times, series, weather, prov, soft, horizons=schema["horizons"], latency_hours=latency)
        cols = F.feature_columns(schema["horizons"])
        last = None
        for r in rows:
            if r[cols.index("origin_utc")] == iso(origin):
                last = dict(zip(cols, r))
        if last is None:
            raise ForecastUnavailable("The nearest station has no usable observation at the forecast origin.")
        if last["wx_temp"] is None:
            raise ForecastUnavailable("No weather inputs are stored for the forecast origin, so the model cannot be applied.")
        return last


F_LOCATION = {"station_lat", "station_lon"}


def beats_persistence(run: LoadedRun, pollutant: str, h: int) -> bool | None:
    """Did the served model for this cell beat persistence on the held-out test period? None if the run has no such record."""
    e = run.results.get("pollutants", {}).get(pollutant, {}).get("test", {}).get(str(h), {})
    final = e.get("final_model") or {}
    members = final.get("members") or []
    scores = e.get("ensemble", {}).get("test_scores") if final.get("ensemble") else (e.get("models", {}).get(members[0], {}) or {}).get("scores") if members else None
    base = e.get("baselines", {}).get("persistence")
    if not scores or not base or scores.get("mae") is None or base.get("mae") is None:
        return None
    return bool(scores["mae"] < base["mae"])
