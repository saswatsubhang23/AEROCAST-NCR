"""Exposure summaries: numbers come from the stored observations; evidence comes only from indexed documents; nothing is individual."""

from datetime import datetime, timedelta, timezone
from statistics import median

import pytest
from mlfakes import make_history

from app.api.knowledge import get_kb_service
from app.assistant.kb import KbPassage, KbResult, NullKnowledgeBase
from app.core.config import get_settings

HOURS = 24 * 8


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    path = tmp_path_factory.mktemp("hi") / "history.sqlite"
    end = datetime(2026, 3, 10, 18, 0, tzinfo=timezone.utc)
    store, end = make_history(str(path), hours=HOURS, stations=4, end=end)
    return {"path": str(path), "store": store, "end": end, "start": end - (HOURS - 1) * timedelta(hours=1)}


@pytest.fixture
def api(client, hist, monkeypatch):
    monkeypatch.setenv("ML_HISTORY_DB", hist["path"])
    get_settings.cache_clear()
    client.app.dependency_overrides[get_kb_service] = lambda: NullKnowledgeBase()
    return client


def z(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def params(hist, **kw):
    return {"pollutant": "pm25", "from": z(hist["start"]), "to": z(hist["end"]), **kw}


def test_station_summary_matches_a_hand_computation_from_the_store(api, hist):
    r = api.get("/api/health-intel/exposure", params=params(hist, station_id=100))
    assert r.status_code == 200, r.text
    s = r.json()
    vals = [x["value_std"] for x in hist["store"].query("select value_std from clean_air where station_id=100 and pollutant='pm25' and usable=1")]
    o = s["observations"]
    assert o["hourly_values"] == len(vals) == HOURS and o["mean"] == pytest.approx(sum(vals) / len(vals)) and o["median"] == pytest.approx(median(vals))
    assert o["observed_hourly_peak"]["value"] == max(vals) and o["coverage_of_expected_station_hours"] == pytest.approx(1.0)
    assert s["unit"] == "µg/m³" and s["provenance"]["status"] == "observed" and "nothing is estimated between stations" in s["provenance"]["spatial_coverage"]


def test_daily_means_need_eighteen_hours_and_incomplete_days_are_excluded_not_averaged(api, hist):
    # remove 8 hours from one IST day at station 101 -> that station-day has 16 hours: incomplete
    day_start = hist["start"] + timedelta(hours=24 * 3)
    ist_day = (day_start + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
    labels = [r["label_utc"] for r in hist["store"].query("select label_utc from clean_air where station_id=101 and pollutant='pm25' order by label_utc")
              if (datetime.fromisoformat(r["label_utc"].replace("Z", "+00:00")) + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d") == ist_day][:8]
    hist["store"].executemany("update clean_air set usable=0, flags='NEGATIVE' where station_id=101 and pollutant='pm25' and label_utc=?", [(l,) for l in labels])
    hist["store"].commit()
    s = api.get("/api/health-intel/exposure", params=params(hist, station_id=101)).json()
    d = s["daily_means"]
    assert d["incomplete_station_days_excluded"] >= 1 and "at least 18 of 24" in d["averaging"]
    assert d["valid_days"] <= 8 and d["valid_days"] >= 6


def test_days_above_references_use_24_hour_means_and_cite_the_source(api, hist):
    s = api.get("/api/health-intel/exposure", params=params(hist, station_id=100)).json()
    refs = {x["threshold"]["key"]: x for x in s["days_above_references"]}
    assert set(refs) == {"naaqs_pm25_24h", "who_pm25_24h"}
    assert refs["naaqs_pm25_24h"]["threshold"]["averaging"] == "24 hours" and "CPCB" in refs["naaqs_pm25_24h"]["threshold"]["source"]
    assert refs["who_pm25_24h"]["threshold"]["value"] == 15.0 and refs["who_pm25_24h"]["days_at_or_above"] <= refs["who_pm25_24h"]["valid_days"]
    assert refs["who_pm25_24h"]["days_at_or_above"] >= refs["naaqs_pm25_24h"]["days_at_or_above"]  # the stricter guideline is crossed at least as often


def test_zone_scope_uses_the_median_across_stations_and_counts_them(api, hist):
    s = api.get("/api/health-intel/exposure", params=params(hist, zone="Delhi")).json()
    assert s["observations"]["stations_with_data"] == 4 and len(s["scope"]["stations_requested"]) == 4 and "median across stations" in s["daily_means"]["averaging"]


@pytest.mark.parametrize("extra,status", [({}, 422), ({"station_id": 100, "zone": "Delhi"}, 422), ({"station_id": 99999}, 404), ({"zone": "Atlantis"}, 404)])
def test_scope_is_validated(api, hist, extra, status):
    assert api.get("/api/health-intel/exposure", params=params(hist, **extra)).status_code == status


def test_a_period_without_observations_is_404_not_zeros(api, hist):
    r = api.get("/api/health-intel/exposure", params={"pollutant": "pm25", "from": "2020-01-01T00:00:00Z", "to": "2020-01-05T00:00:00Z", "station_id": 100})
    assert r.status_code == 404 and r.json()["error"]["code"] == "exposure_unavailable"
    assert api.get("/api/health-intel/exposure", params={"pollutant": "pm25", "from": "2026-01-01T00:00:00", "to": "2026-01-02T00:00:00", "station_id": 100}).status_code == 422
    assert api.get("/api/health-intel/exposure", params={"pollutant": "pm25", "from": "2020-01-01T00:00:00Z", "to": "2026-01-02T00:00:00Z", "station_id": 100}).status_code == 422


def test_with_no_indexed_documents_the_evidence_section_says_so(api, hist):
    s = api.get("/api/health-intel/exposure", params=params(hist, station_id=100)).json()
    assert s["evidence"]["status"] == "none" and s["evidence"]["passages"] == [] and "no indexed documents" in s["evidence"]["reason"]


class StubKb:
    ready = True
    note = ""

    async def search(self, query, top_k, document=None):
        assert "health effects" in query and "PM2.5" in query
        return KbResult(status="ok", passages=[KbPassage(document="WHO AQG 2021", publisher="WHO", licence="CC BY-NC-SA 3.0 IGO", text="Long " * 400,
                                                         location="p. 12", category="official_guidance", category_label="Official guidance", score=0.77)])


def test_retrieved_evidence_is_cited_attributed_and_truncated(api, hist):
    api.app.dependency_overrides[get_kb_service] = lambda: StubKb()
    s = api.get("/api/health-intel/exposure", params=params(hist, station_id=100)).json()
    p = s["evidence"]["passages"][0]
    assert s["evidence"]["status"] == "ok" and p["citation"] == "K1" and p["document"] == "WHO AQG 2021" and p["publisher"] == "WHO" and p["location"] == "p. 12"
    assert len(p["excerpt"]) <= 500 and p["relevance"] == 0.77


def test_the_response_is_population_level_and_contains_no_individual_health_claims(api, hist):
    s = api.get("/api/health-intel/exposure", params=params(hist, station_id=100)).json()
    text = str(s).lower()
    assert "not a diagnosis" in s["disclaimer"].lower() and any("not a person's exposure" in x.lower() for x in s["limitations"])
    for forbidden in ("probability of disease", "your risk", "you will", "diagnos" + "ed with"):
        assert forbidden not in text
