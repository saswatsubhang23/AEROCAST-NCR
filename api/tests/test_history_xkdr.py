"""XKDR archive ingestion with a mock transport (no network): station matching, time conversion, idempotence, key handling, provenance."""

from datetime import datetime

import httpx
import pytest

from app.history import ingest_xkdr as x
from app.history.store import HistoryStore
from app.ml.dataset import dataset_provenance

KEY = "aqi_test_key_value"

STATIONS = {"data": [
    {"station_id": "site_5024", "station_name": "Alipur, Delhi - DPCC", "state_name": "Delhi", "city_name": "Delhi", "source": "cpcb_caaqm",
     "latitude": 28.8153, "longitude": 77.1530, "first_seen": "2018-11-11T14:00:00", "last_seen": "2025-09-01T17:00:00", "parameters": ["PM2.5", "NO2", "Benzene"]},
    {"station_id": "site_999", "station_name": "New Place, Noida", "state_name": "Uttar Pradesh", "city_name": "Noida", "source": "cpcb_caaqm",
     "latitude": 28.5, "longitude": 77.4, "first_seen": "2020-01-01T00:00:00", "last_seen": "2025-09-01T17:00:00", "parameters": ["PM2.5"]},
    {"station_id": "site_far", "station_name": "Mumbai", "state_name": "Maharashtra", "city_name": "Mumbai", "source": "cpcb_caaqm",
     "latitude": 19.0, "longitude": 72.8, "first_seen": "2020-01-01T00:00:00", "last_seen": "2025-09-01T17:00:00", "parameters": ["PM2.5"]},
]}


def handler(seen):
    def h(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(401, json={"error": "unauthorized"})
        if request.url.path == "/v1/stations":
            return httpx.Response(200, json=STATIONS)
        q = request.url.params
        rows = [{"station_id": q["station"], "parameter_name": q["parameter"], "unit": "µg/m³", "period_start": "2025-01-01T00:00:00", "mean": 40.0, "min": 40.0, "max": 40.0, "n": 1},
                {"station_id": q["station"], "parameter_name": q["parameter"], "unit": "µg/m³", "period_start": "2025-01-01T01:00:00", "mean": None, "n": 0}]
        return httpx.Response(200, json={"meta": {"truncated": False}, "data": rows})
    return h


def store_with_openaq_alipur() -> HistoryStore:
    s = HistoryStore(":memory:")
    s.execute("insert into stations (station_id,name,lat,lon) values (6932,'Alipur, Delhi - DPCC',28.8153,77.153)")
    s.commit()
    return s


def test_parse_row_converts_naive_ist_hour_start_to_a_utc_period():
    r = x.parse_row(6932, 9_000_050_240, "pm25", {"period_start": "2025-01-01T00:00:00", "mean": 40.0, "unit": "µg/m³", "n": 1}, "now", "run")
    assert r[5] == "2024-12-31T18:30:00Z" and r[6] == "2024-12-31T19:30:00Z"  # 00:00 IST = 18:30 UTC the day before
    assert r[8] == 40.0 and r[14] is None  # no coverage percentage is invented
    assert x.parse_row(1, 2, "pm25", {"period_start": "2025-01-01T01:00:00", "mean": None}, "n", "r") is None


@pytest.mark.asyncio
async def test_discovery_matches_existing_stations_adds_new_ones_and_skips_outside_ncr():
    s = store_with_openaq_alipur()
    seen: list = []
    res = await x.run(s, KEY, datetime(2025, 1, 1), datetime(2025, 2, 1), ["pm25"], transport=httpx.MockTransport(handler(seen)))
    assert res["matched_existing"] == 1 and res["created"] == 1 and res["stations"] == 2
    assert s.query("select count(*) from stations where station_id >= ?", (x.ID_OFFSET,))[0][0] == 1  # Mumbai is not NCR
    ids = {r["station_id"] for r in s.query("select distinct station_id from raw_air")}
    assert ids == {6932, x.ID_OFFSET + 999}  # the matched station keeps its OpenAQ id: one station, one series
    assert s.count("raw_air") == 2 and res["failed_windows"] == 0  # the null reading is dropped, not stored


@pytest.mark.asyncio
async def test_rerun_is_idempotent_and_wrong_key_is_an_error_without_echoing_it():
    s = store_with_openaq_alipur()
    t = httpx.MockTransport(handler([]))
    await x.run(s, KEY, datetime(2025, 1, 1), datetime(2025, 2, 1), ["pm25"], transport=t)
    again = await x.run(s, KEY, datetime(2025, 1, 1), datetime(2025, 2, 1), ["pm25"], transport=t)
    assert s.count("raw_air") == 2 and again["windows"] == 0
    with pytest.raises(x.XkdrError) as e:
        await x.run(s, "wrong-key", datetime(2025, 1, 1), datetime(2025, 2, 1), transport=t)
    assert "wrong-key" not in str(e.value) and KEY not in str(e.value)


@pytest.mark.asyncio
async def test_the_provenance_guard_accepts_a_store_built_by_xkdr_runs():
    s = store_with_openaq_alipur()
    await x.run(s, KEY, datetime(2025, 1, 1), datetime(2025, 2, 1), ["pm25"], transport=httpx.MockTransport(handler([])))
    assert dataset_provenance(s)["provenance"] == "real_source_ingest"


def test_us_embassy_timestamps_are_read_as_utc_not_ist():
    """Evidence: docs/phase1/xkdr-alignment.json. The same hourly series agrees with OpenAQ perfectly only when read as UTC."""
    row = {"period_start": "2025-01-01T00:00:00", "mean": 40.0, "unit": "µg/m³", "n": 1}
    ist = x.parse_row(1, 2, "pm25", row, "now", "run")
    utc = x.parse_row(1, 2, "pm25", row, "now", "run", naive_is_utc=True)
    assert ist[5] == "2024-12-31T18:30:00Z" and ist[6] == "2024-12-31T19:30:00Z"  # CPCB stations: naive IST
    assert utc[5] == "2025-01-01T00:00:00Z" and utc[6] == "2025-01-01T01:00:00Z"  # US Embassy: already UTC
    assert "us_embassy" in x.UTC_NAIVE_SOURCES and "cpcb_caaqm" not in x.UTC_NAIVE_SOURCES
