"""The AQI variable of the twin: derived from stored concentrations by the application's one CPCB implementation, never interpolated."""

from datetime import datetime, timedelta, timezone

import pytest
from histfakes import add_sensor, add_series, add_station, isoz
from fastapi import HTTPException

from app.core.config import get_settings
from app.history import clean
from app.history.store import HistoryStore
from app.services.aqi import sub_index
from app.twin.service import TwinService

HOUR = timedelta(hours=1)
START = datetime(2026, 3, 1, 0, 30, tzinfo=timezone.utc)  # first period end; the hour label is the midpoint (00:00)
N = 40


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    path = tmp_path_factory.mktemp("aqi") / "history.sqlite"
    st = HistoryStore(str(path))
    for sid, lat in ((1, 28.60), (2, 28.65), (3, 28.70)):
        add_station(st, sid, lat=lat, lon=77.2, name=f"S{sid}")
    sensor = 100
    for sid in (1, 2, 3):
        for pol, val in (("pm25", 100.0), ("pm10", 150.0), ("no2", 60.0)):
            sensor += 1
            add_sensor(st, sensor, sid, pol)
            if sid == 3 and pol == "no2":
                continue  # station 3 has only two pollutants: CPCB needs three, so it never gets an AQI
            values = [val] * N
            if sid == 2 and pol == "pm25":
                values[20] = "skip"  # a single missing hour does not break the 16-of-24 rule
            add_series(st, sensor, sid, pol, isoz(START), values)
    st.commit()
    clean.clean_air(st)
    return st


def label(i: int) -> str:
    return isoz(START - timedelta(minutes=30) + i * HOUR)


def test_aqi_follows_the_cpch_rules_hour_by_hour(store):
    t = TwinService(store)
    start = START - timedelta(minutes=30)
    out = t.window("aqi", start, start + (N - 1) * HOUR, weather=False)
    assert out["unit"] == "AQI" and out["pollutant"] == "aqi" and out["provenance"]["status"] == "derived"
    names = [s["name"] for s in out["stations"]]
    assert names == ["S1", "S2"]  # station 3 never has three pollutants, so it is absent, not zero
    row = out["values"][0]
    assert all(v is None for v in row[:15])  # fewer than 16 valid hours in the window: no AQI, not a low AQI
    expected = max(sub_index("pm25", 100.0)[0], sub_index("pm10", 150.0)[0], sub_index("no2", 60.0)[0])
    assert row[15] == expected and row[-1] == expected
    assert out["aqi"]["dominant"][0][-1] == "pm25"


def test_one_missing_hour_keeps_the_index_but_too_many_remove_it(store):
    t = TwinService(store)
    start = START - timedelta(minutes=30)
    out = t.window("aqi", start, start + (N - 1) * HOUR, weather=False)
    s2 = out["values"][1]
    assert s2[25] is not None  # hour 20 is missing for PM2.5 but 16 of 24 hours remain


def test_aqi_is_not_interpolated_or_validated_as_a_concentration(store):
    t = TwinService(store)
    with pytest.raises(ValueError):
        t.estimate("aqi", START)
    with pytest.raises(ValueError):
        t.validate_estimates("aqi", START, START + 10 * HOUR)


def test_status_offers_aqi_only_when_it_can_be_computed(store):
    s = TwinService(store).status()
    assert "aqi" in s["pollutants"] and s["periods"]["aqi"]["from"] <= s["periods"]["aqi"]["to"]


def test_api_serves_aqi_and_rejects_it_for_estimates(client, store, monkeypatch):
    monkeypatch.setenv("ML_HISTORY_DB", store.path)
    get_settings.cache_clear()
    a, b = label(16), label(30)
    r = client.get("/api/twin/window", params={"pollutant": "aqi", "from": a, "to": b, "weather": "false"})
    assert r.status_code == 200 and r.json()["unit"] == "AQI" and r.json()["values"][0][0] is not None
    e = client.get("/api/twin/estimate", params={"pollutant": "pm25", "time": a})
    assert e.status_code in (200, 503)  # concentrations are still estimable
    bad = client.get("/api/twin/estimate", params={"pollutant": "aqi", "time": a})
    assert bad.status_code == 422
