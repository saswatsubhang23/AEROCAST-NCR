from datetime import datetime, timezone

from app.core.config import get_settings
from app.services.data_availability import build_availability

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=timezone.utc)
STATUS = {"stations": 68, "periods": {"pm25": {"from": "2025-10-09T00:00:00Z", "to": "2026-10-09T20:00:00Z", "dense_to": "2026-10-07T14:00:00Z"},
                                      "no2": {"from": "2025-10-09T00:00:00Z", "to": "2026-10-07T14:00:00Z", "dense_to": "2026-10-07T14:00:00Z"}}}
DEPS = {"aq_provider": {"state": "ok", "detail": "Reachable, key accepted"}, "weather_provider": {"state": "ok", "detail": "Reachable"},
        "llm_model": {"state": "degraded", "detail": "hermes3:8b is not installed on the Ollama host"}}
MODEL = {"available": True, "run_id": "abc", "created_at": "2026-10-10T01:38:28Z"}


def items(out):
    return {i["id"]: i for g in out["groups"] for i in g["items"]}


def test_live_facts_come_from_the_system_and_stale_data_is_called_stale():
    out = build_availability(get_settings(), STATUS, DEPS, MODEL, True, 0, now=NOW)
    it = items(out)
    assert it["obs_pm25"]["status"] == "stale" and "2026-10-07T14:00" in it["obs_pm25"]["detail"] and "68 stations" in it["obs_pm25"]["detail"]
    assert it["live_openaq"]["status"] == "available" and it["wx_surface"]["status"] == "available"
    assert it["obs_pm10"]["status"] == "missing"  # not in the periods: reported missing, not invented
    assert it["llm"]["status"] == "partial" and it["kb"]["status"] == "missing" and it["ml_model"]["status"] == "available"


def test_the_known_gaps_are_listed_with_what_they_prevent_and_where_to_get_them():
    it = items(build_availability(get_settings(), STATUS, DEPS, MODEL, False, 3, now=NOW))
    for key in ("speciation", "vertical_pollutants", "wx_nowcast", "wx_hires", "health_data", "obs_co", "obs_nh3_voc"):
        assert it[key]["status"] == "missing" and it[key]["consequence"] and it[key]["detail"], key
    # a free public source exists for these (some from a provider already in use), so they are "obtainable", not "missing"
    for key in ("emissions", "fires", "obs_nox", "satellite_air", "wx_observed", "landuse"):
        assert it[key]["status"] == "obtainable" and it[key]["how_to_get"], key
    assert "OpenAQ" in it["obs_nox"]["source"]
    assert it["emissions"]["how_to_get"] and "source term" in it["emissions"]["detail"]
    assert it["terrain_imagery"]["status"] == "partial"  # not cached yet
    assert it["kb"]["status"] == "partial" and "3 document" in it["kb"]["detail"]


def test_missing_store_and_missing_model_are_reported_not_hidden():
    out = build_availability(get_settings(), None, {}, {"available": False, "reason": "No model"}, False, None, now=NOW)
    it = items(out)
    assert it["obs_store"]["status"] == "missing" and it["ml_model"]["status"] == "missing" and it["live_openaq"]["status"] == "partial"
    assert out["counts"]["missing"] >= 10 and out["principle"]
    assert sum(out["counts"].values()) == sum(len(g["items"]) for g in out["groups"])
