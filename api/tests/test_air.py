import re
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api.air import get_air_service
from app.core.config import Settings, get_settings
from app.integrations.http import UpstreamAuthError
from app.integrations.openaq import AqNotConfigured, OpenAQClient
from app.services.air_quality import AirQualityService

NOW = datetime(2026, 10, 9, 6, 20, tzinfo=timezone.utc)
UG = "µg/m³"


def iso(dt: datetime) -> dict:
    return {"utc": dt.strftime("%Y-%m-%dT%H:%M:%SZ"), "local": dt.strftime("%Y-%m-%dT%H:%M:%S+05:30")}


def sensor(sid, name, unit=UG):
    return {"id": sid, "name": f"{name} sensor", "parameter": {"id": sid, "name": name, "units": unit, "displayName": name}}


def location(id_, name, sensors, lat=28.65, lon=77.3, last=NOW - timedelta(hours=1), **kw):
    return {
        "id": id_, "name": name, "locality": "Delhi", "timezone": "Asia/Kolkata", "isMobile": False, "isMonitor": True,
        "provider": {"id": 1, "name": "Test Provider"}, "owner": {"id": 2, "name": "Test Owner"},
        "licenses": [{"id": 1, "name": "CC BY 4.0"}],
        "coordinates": {"latitude": lat, "longitude": lon}, "sensors": sensors,
        "datetimeFirst": iso(NOW - timedelta(days=900)), "datetimeLast": iso(last), **kw,
    }


FULL = [sensor(101, "pm25"), sensor(102, "pm10"), sensor(103, "no2"), sensor(104, "so2"),
        sensor(105, "co", "mg/m³"), sensor(106, "o3"), sensor(107, "temperature", "c")]
LOCATIONS = [
    location(10, "Anand Vihar", FULL),
    location(60, "Partial Station", [sensor(601, "pm25"), sensor(602, "co", "ppm")], lat=28.5, lon=77.1),
    location(20, "Weather Only", [sensor(201, "temperature", "c")]),
    location(30, "Bad Coords", [sensor(301, "pm25")], lat=None),
    location(40, "Null Island", [sensor(401, "pm25")], lat=0, lon=0),
    location(50, "Dormant", [sensor(501, "pm25")], last=NOW - timedelta(days=30)),
    location(70, "Mobile", [sensor(701, "pm25")], isMobile=True),
]
BASE = {101: 45.0, 102: 120.0, 103: 50.0, 104: 10.0, 105: 1.5, 106: 60.0, 601: 80.0, 602: 0.4}


class FakeOpenAQ:
    def __init__(self, hours_value=None, latest=None, script=()):
        # hours_value(sensor_id, hour_index_from_now) -> float | None
        self.hours_value = hours_value or (lambda sid, k: BASE.get(sid))
        self.latest_rows = latest
        self.script = list(script)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.headers["X-API-Key"] == "super-secret-aq-key"
        if self.script:
            step = self.script.pop(0)
            if isinstance(step, int):
                return httpx.Response(step, json={"message": "nope"})
        path = request.url.path
        q = dict(request.url.params)
        if path.endswith("/locations"):
            page = int(q.get("page", 1))
            return httpx.Response(200, json={"meta": {"found": len(LOCATIONS)}, "results": LOCATIONS if page == 1 else []})
        if m := re.search(r"/locations/(\d+)/latest$", path):
            if self.latest_rows is not None:
                return httpx.Response(200, json={"results": self.latest_rows(int(m.group(1)))})
            return httpx.Response(200, json={"results": default_latest(int(m.group(1)))})
        if m := re.search(r"/sensors/(\d+)/hours$", path):
            sid = int(m.group(1))
            start = datetime.fromisoformat(q["datetime_from"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(q["datetime_to"].replace("Z", "+00:00"))
            rows, t, now_h = [], start + timedelta(hours=1), NOW.replace(minute=0)
            while t <= end:
                k = int((now_h - t).total_seconds() // 3600)
                if k >= 0:
                    rows.append({
                        "value": self.hours_value(sid, k),
                        "period": {"label": "1hour", "datetimeFrom": iso(t - timedelta(hours=1)), "datetimeTo": iso(t)},
                        "coverage": {"percentCoverage": 100.0, "percentComplete": 100.0},
                        "parameter": {"id": sid, "name": "x", "units": UG},
                    })
                t += timedelta(hours=1)
            return httpx.Response(200, json={"results": rows})
        return httpx.Response(404, json={"message": "no route"})


def default_latest(location_id: int) -> list[dict]:
    if location_id == 10:
        return [
            {"datetime": iso(NOW - timedelta(minutes=30)), "value": 44.0, "sensorsId": 101, "locationsId": 10, "coordinates": None},
            {"datetime": iso(NOW - timedelta(minutes=30)), "value": -9.0, "sensorsId": 102, "locationsId": 10, "coordinates": None},  # invalid
            {"datetime": iso(NOW - timedelta(hours=5)), "value": 1.2, "sensorsId": 105, "locationsId": 10, "coordinates": None},  # stale
            {"datetime": iso(NOW - timedelta(days=30)), "value": 77.0, "sensorsId": 106, "locationsId": 10, "coordinates": None},  # a dead sensor's last value
            {"datetime": iso(NOW), "value": 21.0, "sensorsId": 107, "locationsId": 10, "coordinates": None},  # not a supported pollutant
        ]
    return []


def make_service(fake, **overrides):
    settings = Settings(**{**get_settings().model_dump(), **overrides})
    client = OpenAQClient(settings, transport=httpx.MockTransport(fake))
    return AirQualityService(settings, client=client, now=lambda: NOW)


# ------------------------------------------------------------------ stations -----------------------------
async def test_station_inventory_keeps_only_valid_active_fixed_stations_with_supported_sensors():
    r = await make_service(FakeOpenAQ()).stations()
    assert [s.name for s in r.stations] == ["Anand Vihar", "Partial Station"]
    text = " ".join(r.warnings)
    for fragment in ("invalid coordinates", "mobile", "reported nothing in the last 7 days", "have none of PM2.5"):
        assert fragment in text
    s = r.stations[0]
    assert (s.lat, s.lon) == (28.65, 77.3) and s.provider == "Test Provider" and s.license == "CC BY 4.0"
    assert s.is_reference_monitor and s.other_parameters == 1


async def test_units_are_preserved_per_sensor_exactly_as_reported():
    s = (await make_service(FakeOpenAQ()).stations()).stations
    assert s[0].pollutants == {"pm25": UG, "pm10": UG, "no2": UG, "so2": UG, "co": "mg/m³", "o3": UG}
    assert s[1].pollutants["co"] == "ppm"


async def test_latest_readings_have_timestamps_age_staleness_and_drop_invalid_values():
    s = (await make_service(FakeOpenAQ()).stations()).stations[0]
    assert set(s.latest) == {"pm25", "co"}  # not shown: negative PM10, the temperature sensor, a 30-day-old O3 value
    pm = s.latest["pm25"]
    assert pm.value == 44.0 and pm.unit == UG and pm.age_s == 1800 and not pm.stale
    assert pm.observed_at == NOW - timedelta(minutes=30)
    assert s.latest["co"].stale is True  # 5 h old, beyond the 3 h limit
    assert s.latest_status == "ok"


async def test_station_with_no_latest_rows_is_reported_as_none_reported_not_as_zero():
    s = (await make_service(FakeOpenAQ()).stations()).stations[1]
    assert s.latest == {} and s.latest_status == "none_reported"


async def test_a_failing_latest_call_degrades_one_station_not_the_whole_list():
    fake = FakeOpenAQ()
    original = fake.__call__

    def flaky(request):
        if request.url.path.endswith("/locations/60/latest"):
            return httpx.Response(503, json={})
        return original(request)

    r = await make_service(flaky).stations()
    assert [s.latest_status for s in r.stations] == ["ok", "unavailable"]
    assert any("could not be loaded for 1 station" in w for w in r.warnings)


async def test_repeat_calls_within_ttl_do_not_hit_the_provider_again():
    fake = FakeOpenAQ()
    svc = make_service(fake)
    await svc.stations()
    n = len(fake.requests)
    await svc.stations()
    assert len(fake.requests) == n


async def test_source_block_carries_provenance_and_limitations():
    src = (await make_service(FakeOpenAQ()).stations()).source
    assert src.provider == "OpenAQ" and "CC BY 4.0" in src.attribution and src.reference_only is True
    assert any("60 requests/minute" in x for x in src.limitations)
    assert src.retrieved_at == NOW


async def test_reference_only_and_provider_filters_are_sent_to_the_provider():
    fake = FakeOpenAQ()
    await make_service(fake, aq_provider_ids="7,8").stations()
    q = dict(next(r for r in fake.requests if r.url.path.endswith("/locations")).url.params)
    assert q["monitor"] == "true" and q["providers_id"] == "7,8" and q["bbox"] == "76.7,28.1,77.8,29.05"


# ------------------------------------------------------------------ errors -----------------------------
async def test_missing_key_raises_not_configured():
    svc = make_service(FakeOpenAQ(), aq_api_key="")
    with pytest.raises(AqNotConfigured):
        await svc.stations()


async def test_rejected_key_is_an_auth_error_and_not_retried():
    fake = FakeOpenAQ(script=[401])
    with pytest.raises(UpstreamAuthError):
        await make_service(fake).stations()
    assert len(fake.requests) == 1


async def test_rate_limit_responses_are_retried():
    fake = FakeOpenAQ(script=[429, 429])
    r = await make_service(fake).stations()
    assert len(r.stations) == 2


async def test_client_spaces_requests_to_respect_the_rate_limit():
    sleeps, t = [], [100.0]

    async def fake_sleep(s):
        sleeps.append(round(s, 3))
        t[0] += s

    settings = Settings(**{**get_settings().model_dump(), "aq_rate_per_minute": 60})
    client = OpenAQClient(settings, transport=httpx.MockTransport(FakeOpenAQ()), clock=lambda: t[0], sleep=fake_sleep)
    for _ in range(3):
        await client.latest(10)
    assert sleeps == [1.0, 1.0]  # first call immediate, then one request per second


# ------------------------------------------------------------------ history ------------------------------
async def test_history_uses_a_shared_hourly_grid_with_gaps_left_as_null():
    def value(sid, k):  # hours-ago k: the two most recent hours missing, one more hole at k=10
        return None if k in (0, 1, 10) else 40.0 + k

    r = await make_service(FakeOpenAQ(hours_value=value)).history([10], "pm25", 24)
    s = r.series[0]
    assert len(r.times) == 24 and r.times[-1] == datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
    assert s.values[-1] is None and s.values[-2] is None and s.values[-11] is None
    assert s.values[-3] == 42.0  # k=2
    assert s.observed_hours == 21 and s.missing_hours == 3
    assert s.unit == UG and s.coverage_percent[-3] == 100.0 and s.coverage_percent[-1] is None


async def test_history_for_a_station_without_the_sensor_is_all_missing_with_a_warning():
    r = await make_service(FakeOpenAQ()).history([60], "no2", 12)
    assert r.series[0].observed_hours == 0 and r.series[0].unit is None
    assert any("no no2 sensor" in w for w in r.warnings)


async def test_comparison_aligns_stations_on_the_same_times():
    r = await make_service(FakeOpenAQ()).history([10, 60], "pm25", 6)
    assert [s.station_id for s in r.series] == [10, 60]
    assert len(r.series[0].values) == len(r.series[1].values) == len(r.times) == 6
    assert r.series[0].values[0] == 45.0 and r.series[1].values[0] == 80.0


# ------------------------------------------------------------------ AQI ------------------------------------
async def test_aqi_is_computed_with_cpcb_method_and_labelled_as_computed():
    r = await make_service(FakeOpenAQ()).aqi(10)
    assert r.status == "available" and r.aqi == 114 and r.dominant == "pm10"
    assert "Not a value reported by CPCB" in r.label and r.assumptions
    assert r.as_of == datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc) and not r.stale
    assert {p.pollutant for p in r.pollutants} == {"pm25", "pm10", "no2", "so2", "co", "o3"}


async def test_aqi_is_not_derived_when_inputs_are_insufficient():
    r = await make_service(FakeOpenAQ()).aqi(60)  # PM2.5 plus CO reported in ppm (unusable)
    assert r.status == "insufficient_data" and r.aqi is None and r.category is None
    assert "at least 3" in r.reason
    co = next(p for p in r.pollutants if p.pollutant == "co")
    assert not co.used and "ppm" in co.reason
    assert next(p for p in r.pollutants if p.pollutant == "pm25").sub_index == 166  # (200-101)/(90-61)*(80-61)+101; per-pollutant value still given


async def test_aqi_with_no_observations_says_so():
    r = await make_service(FakeOpenAQ(hours_value=lambda sid, k: None)).aqi(10)
    assert r.status == "insufficient_data" and "No hourly observations" in r.reason


async def test_aqi_is_flagged_stale_when_the_latest_hour_is_old():
    r = await make_service(FakeOpenAQ(hours_value=lambda sid, k: BASE[sid] if k >= 6 else None)).aqi(10)
    assert r.stale is True and r.as_of == datetime(2026, 10, 9, 0, 0, tzinfo=timezone.utc)


# ------------------------------------------------------------------ CSV export -----------------------------
async def test_csv_exports_only_actual_observations_with_provenance():
    svc = make_service(FakeOpenAQ(hours_value=lambda sid, k: None if k < 2 else BASE[sid]))
    csv_text = await svc.history_csv(10, "pm25", 4)
    lines = csv_text.strip().splitlines()
    assert lines[0].startswith("station_id,station_name,provider,pollutant,unit,period_end_utc,period_end_ist")
    assert len(lines) == 3  # 4 hours requested, the 2 most recent have no data and are not exported
    assert "2026-10-09T04:00:00Z" in lines[2] and "2026-10-09T09:30:00+05:30" in lines[2]
    assert "OpenAQ" in lines[1] and "µg/m³" in lines[1]


# ------------------------------------------------------------------ HTTP routes ------------------------------
@pytest.fixture
def api(client):
    def install(fake=None, **overrides):
        client.app.dependency_overrides[get_air_service] = lambda: make_service(fake or FakeOpenAQ(), **overrides)
        return client

    return install


def test_stations_route(api):
    r = api().get("/api/air/stations")
    assert r.status_code == 200 and len(r.json()["stations"]) == 2


def test_route_reports_missing_configuration_clearly(api):
    r = api(aq_api_key="").get("/api/air/stations")
    assert r.status_code == 503 and "AQ_API_KEY" in r.json()["error"]["message"]
    assert r.json()["error"]["code"] == "not_configured"


def test_route_reports_rejected_key_without_leaking_it(api):
    r = api(FakeOpenAQ(script=[401])).get("/api/air/stations")
    assert r.status_code == 502 and "rejected the configured API key" in r.json()["error"]["message"]
    assert r.json()["error"]["code"] == "upstream_auth"
    assert "super-secret-aq-key" not in r.text


def test_history_route_validation(api):
    c = api()
    assert c.get("/api/air/history", params={"pollutant": "pm25", "stations": "10", "hours": 24}).status_code == 200
    assert c.get("/api/air/history", params={"pollutant": "nh3", "stations": "10"}).status_code == 422
    assert c.get("/api/air/history", params={"pollutant": "pm25", "stations": "10", "hours": 500}).status_code == 422
    assert c.get("/api/air/history", params={"pollutant": "pm25", "stations": "1,2,3,4,5,6,7"}).status_code == 422
    assert c.get("/api/air/history", params={"pollutant": "pm25", "stations": "abc"}).status_code == 422
    assert c.get("/api/air/history", params={"pollutant": "pm25", "stations": "999"}).status_code == 404


def test_aqi_and_csv_routes(api):
    c = api()
    assert c.get("/api/air/stations/10/aqi").json()["aqi"] == 114
    r = c.get("/api/air/stations/10/export.csv", params={"pollutant": "pm25", "hours": 6})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert c.get("/api/air/stations/999/aqi").status_code == 404
