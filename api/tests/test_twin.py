"""Digital-twin API: reads only the historical store; gaps stay gaps; the spatial estimate states its method and its error."""

import math
from datetime import timedelta

import pytest
from mlfakes import make_history

from app.core.config import Settings, get_settings

HOURS = 300


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    path = tmp_path_factory.mktemp("twin") / "history.sqlite"
    store, end = make_history(str(path), hours=HOURS, stations=6)
    # punch holes: station 101 has no observation for 5 consecutive hours; station 102 has none at all after hour 250
    start = end - (HOURS - 1) * timedelta(hours=1)
    for i in range(100, 105):
        store.execute("update clean_air set usable=0, flags='NEGATIVE' where station_id=101 and label_utc=?", ((start + i * timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    store.execute("delete from clean_air where station_id=102 and label_utc > ?", ((start + 250 * timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    store.commit()
    return {"path": str(path), "end": end, "start": start, "store": store}


@pytest.fixture
def api(client, hist, monkeypatch):
    monkeypatch.setenv("ML_HISTORY_DB", hist["path"])
    get_settings.cache_clear()
    return client


def z(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_status_describes_the_store_and_says_it_is_a_replay(api, hist):
    s = api.get("/api/twin/status").json()
    assert s["available"] and s["pollutants"] == ["pm25"] and s["stations"] == 6 and s["weather"]["rows"] > 0
    assert s["from"] == z(hist["start"]) and "Historical replay" in s["data_note"]
    per = s["periods"]["pm25"]
    assert (per["from"], per["to"]) == (z(hist["start"]), z(hist["end"])) and per["from"] <= per["dense_to"] <= per["to"]  # span of usable observations


def test_stations_carry_real_coordinates_and_the_hours_they_have(api):
    st = api.get("/api/twin/stations", params={"pollutant": "pm25"}).json()["stations"]
    assert len(st) == 6 and st[0]["lat"] and st[0]["zone"] == "Delhi" and all(s["hours"] > 100 for s in st)


def test_window_is_a_station_by_hour_matrix_with_gaps_left_as_null(api, hist):
    a, b = hist["start"] + timedelta(hours=96), hist["start"] + timedelta(hours=110)
    w = api.get("/api/twin/window", params={"pollutant": "pm25", "from": z(a), "to": z(b)}).json()
    assert len(w["times"]) == 15 and len(w["values"]) == 6 and all(len(r) == 15 for r in w["values"])
    k = [s["station_id"] for s in w["stations"]].index(101)
    assert w["values"][k][4:9] == [None] * 5 and all(v is not None for v in w["values"][k][:4])
    assert w["provenance"]["status"] == "observed" and "nothing is filled in" in w["provenance"]["gaps"]
    assert w["unit"] == "µg/m³" and w["times"][0] == z(a)


def test_window_includes_weather_with_the_documented_wind_convention(api, hist):
    a = hist["start"] + timedelta(hours=10)
    w = api.get("/api/twin/window", params={"pollutant": "pm25", "from": z(a), "to": z(a + timedelta(hours=3))}).json()
    u, v = w["weather"]["wind_u_ms"][0], w["weather"]["wind_v_ms"][0]
    assert all(x is not None for x in u) and all(abs(x) < 1e-9 for x in v)  # fixture wind blows from 90 degrees: purely westward (u < 0)
    assert all(x < 0 for x in u) and w["weather"]["provenance"]["status"] == "weather_forecast"
    no_wx = api.get("/api/twin/window", params={"pollutant": "pm25", "from": z(a), "to": z(a), "weather": "false"}).json()
    assert "weather" not in no_wx


@pytest.mark.parametrize("params,code", [
    ({"from": "2026-01-01T00:00:00Z", "to": "2026-03-01T00:00:00Z"}, "invalid_request"),  # too long
    ({"from": "2026-01-02T00:00:00Z", "to": "2026-01-01T00:00:00Z"}, "invalid_request"),
    ({"from": "2026-01-01T00:00:00", "to": "2026-01-01T05:00:00"}, "invalid_request"),  # no UTC offset
])
def test_window_validates_its_input(api, params, code):
    r = api.get("/api/twin/window", params={"pollutant": "pm25", **params})
    assert r.status_code == 422 and r.json()["error"]["code"] == code


def test_unknown_pollutants_are_rejected(api, hist):
    assert api.get("/api/twin/window", params={"pollutant": "xx", "from": z(hist["start"]), "to": z(hist["start"])}).status_code == 422


def test_spatial_estimate_states_its_method_coverage_and_error(api, hist):
    t = hist["start"] + timedelta(hours=50)
    e = api.get("/api/twin/estimate", params={"pollutant": "pm25", "time": z(t)}).json()
    assert e["method"]["name"] == "inverse-distance weighting" and e["method"]["radius_km"] == 12.0 and e["provenance"]["status"] == "estimate"
    assert e["leave_one_out"]["n"] == 6 and e["leave_one_out"]["mae"] >= 0 and "not measured at the cell" in e["provenance"]["caveat"]
    flat = [v for row in e["values"] for v in row if v is not None]
    obs = api.get("/api/twin/window", params={"pollutant": "pm25", "from": z(t), "to": z(t), "weather": "false"}).json()
    vals = [r[0] for r in obs["values"] if r[0] is not None]
    assert flat and min(vals) - 1e-9 <= min(flat) and max(flat) <= max(vals) + 1e-9  # IDW never extrapolates beyond the observed range
    assert len(e["values"]) == e["grid"]
    assert all((e["stations_in_range"][i][j] >= 2) == (e["values"][i][j] is not None) for i in range(e["grid"]) for j in range(e["grid"]))


def test_cells_beyond_the_radius_get_no_estimate(api, hist, monkeypatch):
    from app.twin import service
    monkeypatch.setattr(service, "IDW_RADIUS_KM", 2.0)
    e = api.get("/api/twin/estimate", params={"pollutant": "pm25", "time": z(hist["start"] + timedelta(hours=50))}).json()
    assert e["method"]["radius_km"] == 2.0 and any(v is None for row in e["values"] for v in row)
    assert any(v is not None for row in e["values"] for v in row)


def test_no_spatial_estimate_when_too_few_stations_observed(api, hist):
    t = hist["start"] + timedelta(hours=100)  # at this hour only station 101 is missing; remove four more
    for sid in (100, 102, 103, 104):
        hist["store"].execute("update clean_air set usable=0 where station_id=? and pollutant='pm25' and label_utc=?", (sid, z(t)))
    hist["store"].commit()
    r = api.get("/api/twin/estimate", params={"pollutant": "pm25", "time": z(t)})
    assert r.status_code == 503 and r.json()["error"]["code"] == "twin_data_unavailable"


def test_a_missing_store_is_reported_not_papered_over(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ML_HISTORY_DB", str(tmp_path / "none.sqlite"))
    get_settings.cache_clear()
    r = client.get("/api/twin/status")
    assert r.status_code == 503 and r.json()["error"]["code"] == "twin_data_unavailable"


def test_the_twin_never_writes_to_the_store(api, hist):
    before = hist["store"].digest("clean_air", "station_id, pollutant, label_utc")
    api.get("/api/twin/status")
    api.get("/api/twin/window", params={"pollutant": "pm25", "from": z(hist["start"]), "to": z(hist["start"] + timedelta(hours=5))})
    assert hist["store"].digest("clean_air", "station_id, pollutant, label_utc") == before


def test_models_status_without_a_model_is_unavailable_with_a_reason(client, tmp_path, monkeypatch):
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", "")
    get_settings.cache_clear()
    s = client.get("/api/models/status").json()
    assert s["available"] is False and "ML_LOCAL_MODEL_DIR" in s["reason"] and s["targets"] == []
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", str(tmp_path))
    get_settings.cache_clear()
    s = client.get("/api/models/status").json()
    assert s["available"] is False and "No trained model" in s["reason"]


# ---------------------------------------------------------------------------------------------- risk windows
from app.twin import risk  # noqa: E402


def rows(preds, lowers=None):
    return [{"time": f"2026-03-01T{h:02d}:00:00Z", "lead_hours": h, "predicted": p, "lower": None if lowers is None else lowers[i], "upper": p + 10}
            for i, (h, p) in enumerate(zip([1, 3, 6, 12, 24], preds))]


def test_windows_are_runs_of_consecutive_lead_times_at_or_above_the_threshold():
    t = risk.PRESETS["naaqs_pm25_24h"]
    out = risk.evaluate(rows([50, 61, 70, 55, 80]), t)
    assert [(w["lead_from_hours"], w["lead_to_hours"], w["points"]) for w in out["windows"]] == [(3, 6, 2), (24, 24, 1)]
    assert out["windows"][0]["peak_predicted"] == 70 and out["windows"][0]["predicted_range"] == [61, 70]
    assert [p["at_or_above_threshold"] for p in out["points"]] == [False, True, True, False, True]
    assert out["threshold"]["kind"] == "official_standard" and "24" in out["threshold"]["averaging"] and "2009" in out["threshold"]["source"]


def test_the_duration_rule_drops_short_runs():
    out = risk.evaluate(rows([50, 61, 70, 55, 80]), risk.PRESETS["naaqs_pm25_24h"], min_consecutive=2)
    assert [w["lead_from_hours"] for w in out["windows"]] == [3] and "at least 2 consecutive" in out["duration_rule"]


def test_a_threshold_equal_to_the_forecast_counts_and_nothing_below_does():
    assert risk.evaluate(rows([60, 59.9, 1, 2, 3]), risk.PRESETS["naaqs_pm25_24h"])["windows"][0]["points"] == 1
    assert risk.evaluate(rows([1, 2, 3, 4, 5]), risk.PRESETS["naaqs_pm25_24h"])["windows"] == []


def test_uncertainty_separates_likely_from_possible_exceedances():
    out = risk.evaluate(rows([70, 70, 70, 70, 70], lowers=[65, 40, 61, 59, 10]), risk.PRESETS["naaqs_pm25_24h"])
    assert [p["confidence"] for p in out["points"]] == ["likely", "possible", "likely", "possible", "possible"]
    assert out["windows"][0]["likely_points"] == 2


def test_custom_thresholds_are_labelled_as_not_official():
    t = risk.custom_threshold("pm25", 33)
    out = risk.evaluate(rows([40, 20, 20, 20, 20]), t)
    assert out["threshold"]["kind"] == "user_defined" and "not an official" in out["threshold"]["source"] and out["windows"][0]["points"] == 1
    assert out["limitations"] and any("24-hour" in x for x in out["limitations"])


def test_threshold_catalogue_names_its_sources(client):
    ts = client.get("/api/twin/thresholds").json()
    assert {t["key"] for t in ts["thresholds"]} >= {"naaqs_pm25_24h", "who_pm25_24h"} and all(t["source"] for t in ts["thresholds"])
    assert "indicators only" in ts["note"]


@pytest.mark.parametrize("params", [{}, {"threshold": "naaqs_pm25_24h", "threshold_value": 50}, {"threshold": "who_pm10_24h"}, {"threshold": "nope"}, {"threshold_value": -5}])
def test_risk_window_requests_are_validated(api, hist, params):
    r = api.get("/api/twin/risk-windows", params={"pollutant": "pm25", "station_id": 100, "origin": z(hist["end"]), **params})
    assert r.status_code == 422


# ---------------------------------------------------------------------------------------------- atmospheric regimes
def test_regimes_are_learned_on_the_development_period_only_and_validated_on_the_rest(hist, tmp_path):
    from app.ml import regimes
    dev_end = hist["start"] + timedelta(hours=200)
    res = regimes.fit_regimes(hist["store"], dev_end)
    m = res["model"]
    assert 2 <= m["k"] <= 5 and len(m["labels"]) == m["k"] and all(isinstance(x, str) and x for x in m["labels"])
    assert res["dev_end"] == z(dev_end) and res["development"]["rows"] > 1000 and res["test"]["rows"] > 200
    assert [s["k"] for s in res["selection"]] == [2, 3, 4, 5]
    assert "association" in res["caveat"] and set(res["test"]["pm"]) == set(res["development"]["pm"])
    # changing every value after dev_end must not change the fitted model
    import numpy as np

    def same_model(a, b):  # equal up to floating-point summation order
        return a["k"] == b["k"] and a["labels"] == b["labels"] and np.allclose(a["centroids_z"], b["centroids_z"], atol=1e-9) and np.allclose(a["mean"], b["mean"])

    again = regimes.fit_regimes(hist["store"], dev_end)
    assert same_model(again["model"], res["model"])
    hist["store"].execute("update clean_weather set temperature_2m = temperature_2m + 20 where time_utc >= ?", (z(dev_end),))
    hist["store"].commit()
    assert same_model(regimes.fit_regimes(hist["store"], dev_end)["model"], res["model"])
    out = tmp_path / "regimes.json"
    regimes.save(res, out)
    assert out.exists()


def test_regime_assignment_uses_only_the_saved_centroids():
    import numpy as np
    from app.ml import regimes
    model = {"mean": [0, 0, 0, 0, 0], "std": [1, 1, 1, 1, 1], "centroids_z": [[-1, 0, 0, 0, 0], [1, 0, 0, 0, 0]]}
    X = np.array([[-2.0, 0, 0, 0, 0], [3.0, 0, 0, 0, 0], [0.1, 0, 0, 0, 0]])
    assert regimes.assign(X, model).tolist() == [0, 1, 1]
    assert regimes.name_regime([-1.0, 0.7, 0, 0, 0]) == "lower wind, deeper boundary layer"
    assert regimes.name_regime([0, 0, 0, 0, 0]) == "mid-range conditions"


def test_regimes_endpoint_is_unavailable_until_an_analysis_exists_then_serves_it(api, hist, tmp_path, monkeypatch):
    from app.ml import regimes
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", str(tmp_path))
    get_settings.cache_clear()
    r = api.get("/api/twin/regimes")
    assert r.status_code == 503 and r.json()["error"]["code"] == "regimes_unavailable"
    regimes.save(regimes.fit_regimes(hist["store"], hist["start"] + timedelta(hours=200)), tmp_path / "regimes.json")
    out = api.get("/api/twin/regimes", params={"time": z(hist["start"] + timedelta(hours=250))}).json()
    assert out["regimes"] and out["features"][0] == "wind_ms" and out["dev_end"] and out["caveat"]
    assert len(out["stations"]) == 6 and all(0 <= s["regime"] < len(out["regimes"]) for s in out["stations"])
    assert api.get("/api/twin/regimes", params={"time": "2026-01-01T00:00:00"}).status_code == 422
