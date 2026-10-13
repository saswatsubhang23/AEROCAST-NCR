import sqlite3
from datetime import timedelta

import pytest
from test_air import NOW, FakeOpenAQ, iso, make_service as make_air

from app.alerts.models import MAX_RULES, THRESHOLD_NOTE, AlertRuleCreate
from app.alerts.service import AlertService, breached
from app.alerts.store import AlertRuleStore, TooManyRules
from app.api.alerts import get_alert_service, get_alert_store


def rule(**over):
    base = {"location_id": "delhi", "pollutant": "pm25", "operator": "gte", "threshold": 40, "unit": "µg/m³"}
    return AlertRuleCreate.model_validate({**base, **over})


def service(tmp_path, fake=None, **air_over):
    store = AlertRuleStore(tmp_path / "alerts.sqlite")
    return AlertService(store, make_air(fake or FakeOpenAQ(), **air_over), now=lambda: NOW)


# ---------------------------------------------------------------------------------------------- evaluation
async def test_a_reading_at_or_above_the_threshold_triggers_with_full_traceability(tmp_path):
    svc = service(tmp_path)
    svc.create(rule(threshold=40))  # Anand Vihar reports PM2.5 44 µg/m³ 30 minutes ago
    out = await svc.evaluate()
    st = out.statuses[0]
    assert st.status == "triggered" and out.source_available
    assert st.rule.location_name == "Delhi" and st.rule.measurement == "PM2.5" and st.rule.threshold == 40 and st.rule.unit == "µg/m³"
    o = st.observation
    assert (o.value, o.unit, o.station, o.provider, o.age_s) == (44.0, "µg/m³", "Anand Vihar", "Test Provider", 1800)
    assert o.observed_at == NOW - timedelta(minutes=30) and 0 < o.distance_km < 20
    assert st.source.provider == "OpenAQ" and st.evaluated_at == NOW
    assert "Anand Vihar" in st.message and st.threshold_note == THRESHOLD_NOTE and "not an official health standard" in st.threshold_note


async def test_a_reading_below_the_threshold_does_not_trigger(tmp_path):
    svc = service(tmp_path)
    svc.create(rule(threshold=100))
    st = (await svc.evaluate()).statuses[0]
    assert st.status == "not_triggered" and st.observation.value == 44.0 and "below the threshold" in st.message


@pytest.mark.parametrize("operator,threshold,expected", [("gte", 44, "triggered"), ("gt", 44, "not_triggered"), ("gt", 43.9, "triggered"), ("gte", 44.1, "not_triggered")])
async def test_operators_treat_the_boundary_correctly(tmp_path, operator, threshold, expected):
    svc = service(tmp_path)
    svc.create(rule(operator=operator, threshold=threshold))
    assert (await svc.evaluate()).statuses[0].status == expected


def test_breached_helper():
    assert breached("gte", 5, 5) and not breached("gt", 5, 5) and breached("gt", 5.1, 5)


async def test_a_stale_reading_is_reported_as_stale_and_never_triggers(tmp_path):
    svc = service(tmp_path)
    svc.create(rule(pollutant="co", threshold=0.1, unit="mg/m³"))  # CO reading is 5 h old, far above 0.1
    st = (await svc.evaluate()).statuses[0]
    assert st.status == "stale" and st.observation.value == 1.2 and "too old" in st.message


async def test_units_are_never_converted(tmp_path):
    svc = service(tmp_path)
    svc.create(rule(unit="ppb", threshold=1))  # the PM2.5 sensor reports µg/m³
    st = (await svc.evaluate()).statuses[0]
    assert st.status == "unit_mismatch" and st.observation.unit == "µg/m³" and "does not convert units" in st.message


async def test_missing_data_is_not_a_quiet_all_clear(tmp_path):
    svc = service(tmp_path)
    svc.create(rule(location_id="faridabad"))  # no station within 20 km
    svc.create(rule(pollutant="o3", unit="µg/m³"))  # nearby stations have no recent O3 reading
    s1, s2 = (await svc.evaluate()).statuses
    assert s1.status == "no_data" and s2.status == "no_data" and s1.observation is None
    assert "No station within 20 km" in s1.message


async def test_a_fresh_station_is_preferred_over_a_nearer_stale_one(tmp_path):
    def latest(location_id):
        if location_id == 10:  # the nearest station's PM2.5 is 6 hours old
            return [{"datetime": iso(NOW - timedelta(hours=6)), "value": 500.0, "sensorsId": 101, "locationsId": 10, "coordinates": None}]
        if location_id == 60:
            return [{"datetime": iso(NOW - timedelta(minutes=20)), "value": 90.0, "sensorsId": 601, "locationsId": 60, "coordinates": None}]
        return []

    svc = service(tmp_path, FakeOpenAQ(latest=latest))
    svc.create(rule(threshold=80))
    st = (await svc.evaluate()).statuses[0]
    assert st.status == "triggered" and st.observation.station == "Partial Station" and st.observation.value == 90.0


async def test_an_unavailable_source_is_reported_not_hidden(tmp_path):
    svc = service(tmp_path, aq_api_key="")
    svc.create(rule())
    out = await svc.evaluate()
    assert not out.source_available and "not configured" in out.source_message
    assert out.statuses[0].status == "unavailable" and out.statuses[0].observation is None


async def test_rejected_key_and_outages_are_reported(tmp_path):
    svc = service(tmp_path, FakeOpenAQ(script=[401]))
    svc.create(rule())
    assert "rejected" in (await svc.evaluate()).source_message
    svc2 = service(tmp_path / "b", FakeOpenAQ(script=[503, 503, 503])) if (tmp_path / "b").mkdir() is None else None
    svc2.create(rule())
    assert "could not be reached" in (await svc2.evaluate()).source_message


async def test_disabled_rules_are_not_evaluated_and_do_not_query_the_source(tmp_path):
    fake = FakeOpenAQ()
    svc = service(tmp_path, fake)
    r = svc.create(rule())
    svc.store.set_enabled(r.id, False)
    out = await svc.evaluate()
    assert out.statuses[0].status == "disabled" and fake.requests == []


# ---------------------------------------------------------------------------------------------- rules and storage
def test_rules_persist_across_restarts_and_names_are_generated_or_cleaned(tmp_path):
    a = service(tmp_path)
    r1 = a.create(rule(threshold=60.5))
    r2 = a.create(rule(name="  Evening\nsmog\x00 watch  ", location_id="noida", operator="gt"))
    assert r1.name == "PM2.5 ≥ 60.5 µg/m³ in Delhi" and r2.name == "Evening smog watch"
    a.store.close()
    b = AlertRuleStore(tmp_path / "alerts.sqlite")
    assert [x["id"] for x in b.list()] == [r1.id, r2.id] and b.list()[1]["operator"] == "gt"


def test_there_is_a_limit_on_the_number_of_rules(tmp_path):
    store = AlertRuleStore(tmp_path / "a.sqlite")
    for i in range(MAX_RULES):
        store.add(f"r{i}", "delhi", "pm25", "gte", 10, "µg/m³")
    with pytest.raises(TooManyRules):
        store.add("one too many", "delhi", "pm25", "gte", 10, "µg/m³")


def test_hostile_text_is_stored_as_text_and_cannot_touch_the_database(tmp_path):
    store = AlertRuleStore(tmp_path / "a.sqlite")
    evil = "x'); DROP TABLE alert_rules; --"
    row = store.add(evil, "delhi", "pm25", "gte", 10, "µg/m³")
    assert store.get(row["id"])["name"] == evil and len(store.list()) == 1
    assert sqlite3.connect(tmp_path / "a.sqlite").execute("select count(*) from alert_rules").fetchone()[0] == 1


@pytest.mark.parametrize("bad", [
    {"location_id": "mumbai"}, {"pollutant": "nh3"}, {"operator": "lt"}, {"threshold": 0}, {"threshold": -5}, {"threshold": 10**7},
    {"threshold": float("nan")}, {"unit": "kg"}, {"unit": ""}, {"name": "x" * 81}, {"threshold": "abc"},
])
def test_rule_validation(bad):
    with pytest.raises(ValueError):
        rule(**bad)


def test_unit_spellings_are_normalised():
    assert rule(unit="ug/m3").unit == "µg/m³" and rule(unit="μg/m³").unit == "µg/m³" and rule(unit="PPB").unit == "ppb"


# ---------------------------------------------------------------------------------------------- HTTP API
@pytest.fixture
def api(client, tmp_path):
    def install(fake=None, **air_over):
        store = AlertRuleStore(tmp_path / "api.sqlite")
        client.app.dependency_overrides[get_alert_store] = lambda: store
        client.app.dependency_overrides[get_alert_service] = lambda: AlertService(store, make_air(fake or FakeOpenAQ(), **air_over), now=lambda: NOW)
        return client

    return install


def body(**over):
    return {"location_id": "delhi", "pollutant": "pm25", "operator": "gte", "threshold": 40, "unit": "µg/m³", **over}


def test_rule_lifecycle_over_http(api):
    c = api()
    assert c.get("/api/alerts").json()["statuses"] == []
    created = c.post("/api/alerts/rules", json=body())
    assert created.status_code == 201 and created.json()["enabled"] is True and created.json()["location_name"] == "Delhi"
    rid = created.json()["id"]

    listing = c.get("/api/alerts").json()
    assert listing["statuses"][0]["status"] == "triggered" and "no alert is a prediction" in listing["note"].lower()
    assert listing["statuses"][0]["source"]["provider"] == "OpenAQ" and listing["statuses"][0]["observation"]["station"] == "Anand Vihar"

    off = c.patch(f"/api/alerts/rules/{rid}", json={"enabled": False}).json()
    assert off["enabled"] is False and c.get("/api/alerts").json()["statuses"][0]["status"] == "disabled"
    assert c.delete(f"/api/alerts/rules/{rid}").status_code == 204
    assert c.get("/api/alerts").json()["statuses"] == []


def test_http_validation_and_missing_rules(api):
    c = api()
    for bad in ({"unit": "kg"}, {"threshold": -1}, {"location_id": "mumbai"}, {"operator": "lt"}):
        r = c.post("/api/alerts/rules", json=body(**bad))
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"
    assert c.post("/api/alerts/rules", json={}).status_code == 422
    for call in (lambda: c.delete("/api/alerts/rules/999"), lambda: c.patch("/api/alerts/rules/999", json={"enabled": True})):
        r = call()
        assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert c.patch("/api/alerts/rules/1", json={}).status_code == 422


def test_the_rule_limit_returns_409(api):
    c = api()
    for _ in range(MAX_RULES):
        assert c.post("/api/alerts/rules", json=body()).status_code == 201
    r = c.post("/api/alerts/rules", json=body())
    assert r.status_code == 409 and r.json()["error"]["code"] == "too_many_rules"


def test_the_api_reports_an_unconfigured_source_instead_of_failing(api):
    c = api(aq_api_key="")
    c.post("/api/alerts/rules", json=body())
    r = c.get("/api/alerts")
    assert r.status_code == 200 and r.json()["source_available"] is False and r.json()["statuses"][0]["status"] == "unavailable"


def test_cors_allows_patch_from_the_frontend(client):
    r = client.options("/api/alerts/rules/1", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "PATCH"})
    assert r.status_code == 200 and "PATCH" in r.headers["access-control-allow-methods"]
