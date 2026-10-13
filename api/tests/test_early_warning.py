from datetime import datetime, timedelta, timezone

from app.twin.early_warning import build_overview, classify, rank
from app.twin.risk import Threshold, evaluate

T = Threshold("t", "test", "pm25", 60.0, "µg/m³", "user_defined", "as forecast", "test")
ORIGIN = datetime(2025, 1, 10, 0, tzinfo=timezone.utc)


def rows(values, lower_offset=None):
    return [{"time": (ORIGIN + timedelta(hours=h)).isoformat(), "lead_hours": h, "predicted": v,
             "lower": None if lower_offset is None else v - lower_offset, "upper": None if lower_offset is None else v + lower_offset}
            for h, v in zip((1, 3, 6, 12, 24), values)]


def test_classify_levels():
    assert classify(evaluate(rows([10, 20, 30, 30, 30]), T))["level"] == "none"
    assert classify(evaluate(rows([10, 20, 70, 30, 30], 5), T)) | {} == classify(evaluate(rows([10, 20, 70, 30, 30], 5), T))
    likely = classify(evaluate(rows([10, 20, 90, 30, 30], 5), T))
    assert likely["level"] == "likely" and likely["first_lead_hours"] == 6 and likely["peak_predicted"] == 90
    possible = classify(evaluate(rows([10, 20, 62, 30, 30], 20), T))
    assert possible["level"] == "possible"  # lower bound 42 < 60
    no_interval = classify(evaluate(rows([10, 20, 62, 30, 30]), T))
    assert no_interval["level"] == "possible"  # without an interval nothing can be called likely


def test_rank_orders_by_severity_then_time_then_peak():
    e = [dict(station_id=1, level="none", first_lead_hours=None, peak_predicted=None),
         dict(station_id=2, level="possible", first_lead_hours=1, peak_predicted=65),
         dict(station_id=3, level="likely", first_lead_hours=12, peak_predicted=80),
         dict(station_id=4, level="likely", first_lead_hours=6, peak_predicted=70),
         dict(station_id=5, level="likely", first_lead_hours=6, peak_predicted=95)]
    assert [x["station_id"] for x in rank(e)] == [5, 4, 3, 2, 1]


def test_overview_flags_stale_origin_and_keeps_skipped_and_weak_horizons():
    st = [{"station_id": 1, "name": "A", "lat": 28.6, "lon": 77.2, "rows": rows([90, 90, 90, 90, 90], 5)},
          {"station_id": 2, "name": "B", "lat": 28.7, "lon": 77.1, "rows": rows([10, 10, 10, 10, 10], 5)}]
    out = build_overview(pollutant="pm25", origin=ORIGIN, now=ORIGIN + timedelta(days=30), threshold=T, stations=st,
                         skipped=[{"station_id": 3, "name": "C", "reason": "no data"}], weak_horizons=[24, 6], model_version="m", interval_level=0.8, importance=None)
    assert out["stale"] is True and out["counts"] == {"likely": 1, "possible": 0, "none": 1}
    assert out["stations"][0]["station_id"] == 1 and out["skipped"][0]["station_id"] == 3 and out["weak_horizons"] == [6, 24]
    assert any("replay" in c for c in out["caveats"])
    fresh = build_overview(pollutant="pm25", origin=ORIGIN, now=ORIGIN + timedelta(hours=2), threshold=T, stations=st, skipped=[], weak_horizons=[],
                           model_version="m", interval_level=None, importance=None)
    assert fresh["stale"] is False


# ---------------------------------------------------------------------------------------------- endpoint
import pytest
from fastapi import HTTPException

from tests.test_twin import api, hist, z  # noqa: F401 - reuse the synthetic-store fixtures


@pytest.mark.parametrize("params", [{}, {"threshold": "naaqs_pm25_24h", "threshold_value": 50}, {"threshold": "who_pm10_24h"}, {"threshold_value": -1}])
def test_early_warning_requests_are_validated(api, hist, params):  # noqa: F811
    r = api.get("/api/twin/early-warning", params={"pollutant": "pm25", "origin": z(hist["end"]), **params})
    assert r.status_code == 422


def test_early_warning_without_observations_at_the_origin_says_so(api, hist):  # noqa: F811
    r = api.get("/api/twin/early-warning", params={"pollutant": "pm25", "origin": z(hist["start"] - timedelta(days=400)), "threshold": "naaqs_pm25_24h"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "no_observations"


def test_early_warning_ranks_stations_and_reports_skipped_ones(api, hist, monkeypatch):  # noqa: F811
    import app.api.twin as twin_api

    async def fake(svc, pollutant, station_id, origin):
        if station_id % 2:
            raise HTTPException(503, {"code": "model_unavailable", "message": "no recent data"})
        vals = [70 + station_id, 80, 90, 50, 40]
        return {"rows": [{"time": z(origin + timedelta(hours=h)), "lead_hours": h, "predicted": v, "lower": v - 5, "upper": v + 5}
                         for h, v in zip((1, 3, 6, 12, 24), vals)],
                "model_version": "fake", "interval_level": 0.8, "station": {}, "provenance": {"input_data": []}}

    monkeypatch.setattr(twin_api, "_run_backtest", fake)
    r = api.get("/api/twin/early-warning", params={"pollutant": "pm25", "origin": z(hist["end"]), "threshold": "naaqs_pm25_24h"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stations"] and all(s["level"] == "likely" for s in body["stations"])
    assert all(s["station_id"] % 2 == 0 for s in body["stations"]) and all(s["reason"] == "no recent data" for s in body["skipped"])
    assert body["threshold"]["kind"] == "official_standard" and body["uncertainty"] and body["importance_note"]


def test_early_warning_reuses_station_forecasts_but_recomputes_the_ranking(api, hist, monkeypatch):  # noqa: F811
    """The expensive part is the per-station forecast; changing only the threshold must not recompute it, and a new model must."""
    import app.api.twin as twin_api

    twin_api._ew_cache.clear()
    calls: list[int] = []

    async def fake(svc, pollutant, station_id, origin):
        calls.append(station_id)
        return {"rows": [{"time": z(origin + timedelta(hours=h)), "lead_hours": h, "predicted": v, "lower": v - 5, "upper": v + 5}
                         for h, v in zip((1, 3, 6, 12, 24), [70, 80, 90, 50, 40])],
                "model_version": "fake", "interval_level": 0.8, "station": {}, "provenance": {"input_data": []}}

    monkeypatch.setattr(twin_api, "_run_backtest", fake)
    params = {"pollutant": "pm25", "origin": z(hist["end"]), "threshold": "naaqs_pm25_24h"}
    first = api.get("/api/twin/early-warning", params=params).json()
    n = len(calls)
    assert n > 0 and first["forecasts_reused"] is False
    second = api.get("/api/twin/early-warning", params={**params, "threshold": "who_pm25_24h"}).json()
    assert len(calls) == n and second["forecasts_reused"] is True  # no new forecasts
    assert second["threshold"]["key"] != first["threshold"]["key"]  # but the ranking was rebuilt for the new threshold
    # a different model (pointer rewritten) is never served from the cache
    monkeypatch.setattr(twin_api, "_model_stamp", lambda: ("other", 1, 1))
    third = api.get("/api/twin/early-warning", params=params).json()
    assert len(calls) == 2 * n and third["forecasts_reused"] is False
    twin_api._ew_cache.clear()


def test_a_total_failure_is_not_cached(api, hist, monkeypatch):  # noqa: F811
    import app.api.twin as twin_api

    twin_api._ew_cache.clear()

    async def down(svc, pollutant, station_id, origin):
        raise HTTPException(503, {"code": "model_unavailable", "message": "down"})

    monkeypatch.setattr(twin_api, "_run_backtest", down)
    r = api.get("/api/twin/early-warning", params={"pollutant": "pm25", "origin": z(hist["end"]), "threshold": "naaqs_pm25_24h"})
    assert r.status_code == 503 and not twin_api._ew_cache
