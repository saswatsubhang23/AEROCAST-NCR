from datetime import datetime

from app.db.postgis_sync import SOURCE_OPENAQ, SOURCE_XKDR, record_id, source_for_sensor, transform
from app.envdata.schema import EnvRecord
from app.history.ingest_xkdr import ID_OFFSET

ROW = (17, "no2", "2025-10-08T23:30:00Z", "2025-10-09T00:30:00Z", 123456, 35.2, "ppb", 66.2, "UNIT_CONVERTED", 1, "2026-10-09T21:01:32Z")


def test_sensor_id_decides_source():
    assert source_for_sensor(123456) == SOURCE_OPENAQ
    assert source_for_sensor(ID_OFFSET + 50) == SOURCE_XKDR


def test_record_id_matches_the_envrecord_identity():
    t = transform(ROW, "2026-10-11T00:00:00Z")
    rec = EnvRecord(
        kind="observation", source="openaq", variable="no2", value=66.2, unit="µg/m³",
        valid_from=datetime.fromisoformat(t[7]), valid_to=datetime.fromisoformat(t[8]), retrieved_at=datetime.fromisoformat(t[9]),
        location_id="station:17", lat=28.6, lon=77.2,
    )
    assert t[0] == rec.record_id == record_id("openaq", "no2", 17, ROW[2], ROW[3])


def test_transform_maps_values_flags_and_retrieval_time():
    t = transform(ROW, "2026-10-11T00:00:00Z")
    assert t[1:7] == ("openaq", "no2", 66.2, "µg/m³", 35.2, "ppb")
    assert t[9] == "2026-10-09T21:01:32+00:00"
    assert t[11] == "{UNIT_CONVERTED}" and t[12] is True


def test_missing_raw_match_is_flagged_not_hidden():
    row = (*ROW[:-1], None)
    t = transform(row, "2026-10-11T00:00:00Z")
    assert t[9] == "2026-10-11T00:00:00+00:00"
    assert t[11] == "{RETRIEVED_AT_UNKNOWN,UNIT_CONVERTED}"


def test_unusable_rows_are_kept_with_null_value():
    row = (17, "co", "2025-10-08T23:30:00Z", "2025-10-09T00:30:00Z", ID_OFFSET + 7, None, None, None, "LOW_COVERAGE", 0, None)
    t = transform(row, "2026-10-11T00:00:00Z")
    assert t[1] == "xkdr" and t[3] is None and t[12] is False


def test_geo_endpoints_degrade_to_503_when_postgres_is_down(client):
    for url in ("/api/geo/status", "/api/geo/stations/nearby?lat=28.6&lon=77.2", "/api/geo/stations.geojson", "/api/geo/stations/17/series"):
        r = client.get(url)
        assert r.status_code == 503, url
        assert r.json()["error"]["code"] == "geo_unavailable"


def test_nearby_validates_inputs(client):
    assert client.get("/api/geo/stations/nearby?lat=95&lon=77").status_code == 422
    assert client.get("/api/geo/stations/nearby?lat=28&lon=77&radius_km=5000").status_code == 422
