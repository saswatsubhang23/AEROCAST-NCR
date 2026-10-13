"""Ingestion (mocked providers), cleaning, model-ready table, coverage report and reproducibility."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from histfakes import (
    FETCHED, HOUR, FakeOpenAQ, add_raw, add_series, add_sensor, add_station, add_weather_raw, archive_response, isoz, loc, sensor_rec,
    store, utc,
)

from app.core.config import get_settings
from app.history import clean as clean_mod
from app.history import cli, coverage, features, ingest_air, ingest_weather
from app.integrations.http import UpstreamAuthError
from app.integrations.openmeteo import OpenMeteoClient

WINDOW_FROM = utc("2026-01-01T00:00:00Z")
WINDOW_TO = utc("2026-01-11T00:00:00Z")


def fake_openaq(**kw):
    locations = [loc(1, last="2026-01-12T00:00:00Z"), loc(2, last="2024-05-01T00:00:00Z", first="2023-01-01T00:00:00Z"), loc(3, mobile=True)]
    late = "2026-01-12T00:00:00Z"
    sensors = {1: [sensor_rec(101, "pm25", "µg/m³", last=late), sensor_rec(102, "pm25", "µg/m³", first="2018-12-15T15:00:00Z", last="2022-10-31T00:30:00Z"),
                   sensor_rec(103, "no2", "ppb", last=late), sensor_rec(104, "relativehumidity", "%")],
               2: [sensor_rec(201, "pm25", "µg/m³", first="2023-01-01T00:00:00Z", last="2024-05-01T00:00:00Z")]}
    return FakeOpenAQ(locations, sensors, **kw)


async def discovered(fake=None):
    fake = fake or fake_openaq()
    st = store()
    res = await ingest_air.discover(st, fake.client(), WINDOW_FROM, "run0", now=utc(FETCHED))
    return st, fake, res


# ---------------------------------------------------------------------------------------------- discovery and backfill
async def test_discovery_stores_stations_and_only_the_sensors_of_stations_active_in_the_window():
    st, _, res = await discovered()
    assert res == {"stations": 2, "stations_in_window": 1, "sensors": 3}  # mobile station skipped; humidity sensor not a pollutant
    assert {r["station_id"] for r in st.query("select station_id from stations")} == {1, 2}
    row = st.query("select * from stations where station_id=1")[0]
    assert (row["lat"], row["lon"], row["zone"], row["agency"]) == (28.6, 77.2, "Delhi", "Delhi (DPCC)")
    assert {r["sensor_id"] for r in st.query("select sensor_id from sensors")} == {101, 102, 103}


async def test_backfill_keeps_provider_values_units_and_provenance():
    st, fake, _ = await discovered()
    rid = ingest_air.start_run(st, "ingest-air", {}, utc(FETCHED))
    res = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, rid, chunk_days=5, now=lambda: utc(FETCHED))
    assert res["failed_windows"] == 0 and res["requests"] == 4  # 2 sensors x 2 windows; the legacy sensor (ended 2022) is never requested
    assert not fake.hour_requests(102) and not fake.hour_requests(201)
    rows = st.query("select * from raw_air where sensor_id=101 order by period_to_utc")
    assert len(rows) == 10 * 24
    r = rows[0]
    assert r["parameter"] == "pm25" and r["units"] == "µg/m³" and r["station_id"] == 1
    assert r["period_to_utc"].endswith(":30:00Z") and r["period_to_local"]
    assert r["fetched_at"] == FETCHED and r["run_id"] == rid and r["percent_coverage"] == 100.0
    assert {x["units"] for x in st.query("select distinct units from raw_air where sensor_id=103")} == {"ppb"}  # units are never rewritten in raw


async def test_rerunning_is_idempotent_and_skips_completed_windows():
    st, fake, _ = await discovered()
    await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=5, now=lambda: utc(FETCHED))
    n = st.count("raw_air")
    fake.calls.clear()
    res = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r2", chunk_days=5, now=lambda: utc(FETCHED))
    assert fake.hour_requests() == [] and res["requests"] == 0 and res["skipped_windows"] == 4 and st.count("raw_air") == n


async def test_a_request_budget_stops_cleanly_and_the_next_run_resumes():
    st, fake, _ = await discovered()
    first = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=5, max_requests=2, concurrency=1, now=lambda: utc(FETCHED))
    assert first["requests"] == 2 and "request budget" in first["note"]
    second = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r2", chunk_days=5, concurrency=1, now=lambda: utc(FETCHED))
    assert second["requests"] == 2 and second["skipped_windows"] == 2
    assert st.count("raw_air") == 2 * 10 * 24


async def test_a_failed_window_is_reported_and_retried_on_the_next_run():
    fake = fake_openaq(fail=lambda sid, frm: sid == 103 and frm.day == 6)
    st, _, _ = await discovered(fake)
    res = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=5, now=lambda: utc(FETCHED))
    assert res["failed_windows"] == 1
    assert st.query("select count(*) c from raw_air where sensor_id=103")[0]["c"] == 5 * 24
    fake.fail = lambda sid, frm: False
    res = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r2", chunk_days=5, now=lambda: utc(FETCHED))
    assert res["failed_windows"] == 0 and res["requests"] == 1
    assert st.query("select count(*) c from raw_air where sensor_id=103")[0]["c"] == 10 * 24


async def test_pagination_collects_every_row(monkeypatch):
    monkeypatch.setattr(ingest_air, "PAGE_LIMIT", 50)
    st, fake, _ = await discovered()
    res = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=10, now=lambda: utc(FETCHED))
    assert st.query("select count(*) c from raw_air where sensor_id=101")[0]["c"] == 240
    assert res["requests"] > 2  # 240 rows at 50 per page


async def test_old_windows_are_final_but_recent_ones_are_always_refetched():
    st, fake, _ = await discovered()
    await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=5, now=lambda: utc("2026-01-12T00:00:00Z"))
    assert {r["status"] for r in st.query("select status from raw_air_progress")} == {"partial"}
    fake.calls.clear()
    res = await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r2", chunk_days=5, now=lambda: utc("2026-03-01T00:00:00Z"))
    assert res["requests"] == 4  # refetched once more; identical rows are not duplicated
    assert st.count("raw_air") == 2 * 10 * 24
    assert {r["status"] for r in st.query("select status from raw_air_progress")} == {"done"}


async def test_a_rejected_key_aborts_instead_of_being_retried_forever():
    st, fake, _ = await discovered()
    bad = httpx.MockTransport(lambda req: httpx.Response(401))
    from app.integrations.openaq import OpenAQClient
    with pytest.raises(UpstreamAuthError):
        await ingest_air.backfill(st, OpenAQClient(get_settings(), transport=bad), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=5)


async def test_a_revised_value_is_kept_as_a_second_raw_version_and_flagged_after_cleaning():
    st, fake, _ = await discovered()
    await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r1", chunk_days=5, now=lambda: utc("2026-01-12T00:00:00Z"))
    fake.value = lambda sid, end: 50.0 + end.hour + (7.0 if sid == 101 and end.day == 3 else 0.0)
    await ingest_air.backfill(st, fake.client(), WINDOW_FROM, WINDOW_TO, "r2", chunk_days=5, now=lambda: utc("2026-01-13T00:00:00Z"))
    # the 24 revised hours of 3 January exist twice (both versions kept), everything else once
    assert st.query("select count(*) c from raw_air where sensor_id=101")[0]["c"] == 10 * 24 + 24
    clean_mod.clean_air(st)
    r = st.query("select * from clean_air where station_id=1 and pollutant='pm25' and label_utc='2026-01-03T05:00:00Z'")[0]
    assert "REVISED" in r["flags"].split(",") and r["usable"] == 1
    assert r["orig_value"] == 50.0 + 5 + 7.0  # the later fetch wins
    quiet = st.query("select flags from clean_air where station_id=1 and pollutant='pm25' and label_utc='2026-01-04T05:00:00Z'")[0]["flags"]
    assert "REVISED" not in quiet


# ---------------------------------------------------------------------------------------------- cleaning
def clean_one(rows_spec, parameter="pm25", **raw_kw):
    st = store()
    add_station(st)
    add_sensor(st, 10, 1, parameter)
    add_series(st, 10, 1, parameter, "2026-01-01T00:30:00Z", rows_spec, **raw_kw)
    clean_mod.clean_air(st)
    return st, st.query("select * from clean_air where station_id=1 and pollutant=? order by label_utc", (parameter,))


def test_clean_rows_carry_label_ist_original_and_standard_values():
    st, rows = clean_one([60.0, 61.0])
    r = rows[0]
    assert r["label_utc"] == "2026-01-01T00:00:00Z" and r["period_to_utc"] == "2026-01-01T00:30:00Z" and r["period_to_ist"] == "2026-01-01T06:00:00+05:30"
    assert (r["orig_value"], r["orig_unit"], r["value_std"], r["std_unit"], r["usable"], r["flags"], r["sensor_id"]) == (60.0, "µg/m³", 60.0, "µg/m³", 1, "", 10)


def test_gas_in_ppb_is_converted_beside_the_original_and_flagged():
    _, rows = clean_one([20.0], parameter="no2", units="ppb")
    r = rows[0]
    assert r["orig_value"] == 20.0 and r["orig_unit"] == "ppb" and r["value_std"] == pytest.approx(20 * 46.0055 / 24.45)
    assert r["flags"] == "UNIT_CONVERTED" and r["usable"] == 1


@pytest.mark.parametrize("value,flag", [(-3.0, "NEGATIVE"), (9000.0, "OUT_OF_RANGE"), (None, "NULL_VALUE")])
def test_hard_flags_keep_the_row_visible_but_unusable(value, flag):
    _, rows = clean_one([value])
    assert len(rows) == 1 and flag in rows[0]["flags"].split(",") and rows[0]["usable"] == 0
    if value is not None:
        assert rows[0]["orig_value"] == value  # the number is never altered or dropped


def test_particulates_in_ppb_are_unusable_not_converted():
    _, rows = clean_one([40.0], units="ppb")
    assert rows[0]["usable"] == 0 and rows[0]["value_std"] is None and "UNIT_UNKNOWN" in rows[0]["flags"]


def test_low_coverage_is_a_soft_flag():
    _, rows = clean_one([55.0], coverage=50.0)
    assert rows[0]["flags"] == "LOW_COVERAGE" and rows[0]["usable"] == 1


def test_irregular_periods_are_unusable():
    _, rows = clean_one([55.0], span_hours=2)
    assert "PERIOD_IRREGULAR" in rows[0]["flags"] and rows[0]["usable"] == 0


def test_flat_lines_are_flagged_from_six_identical_hours_but_not_five():
    _, rows = clean_one([10.0] * 5 + [11.0] + [20.0] * 6 + [21.0])
    flags = [r["flags"] for r in rows]
    assert all("FLATLINE" not in f for f in flags[:6]) and all("FLATLINE" in f for f in flags[6:12]) and "FLATLINE" not in flags[12]
    assert all(r["usable"] == 1 for r in rows)  # soft: visible, not removed


def test_a_flat_run_broken_by_a_missing_hour_is_not_one_run():
    _, rows = clean_one([10.0] * 3 + ["skip"] + [10.0] * 3)
    assert all("FLATLINE" not in r["flags"] for r in rows)


def test_missing_hours_have_no_row_and_are_never_filled():
    _, rows = clean_one([10.0, "skip", "skip", 13.0])
    assert [r["label_utc"] for r in rows] == ["2026-01-01T00:00:00Z", "2026-01-01T03:00:00Z"]


def test_two_sensors_in_one_hour_pick_the_better_covered_and_flag_the_choice():
    st = store()
    add_station(st)
    add_sensor(st, 10, 1, "pm25")
    add_sensor(st, 11, 1, "pm25")
    add_raw(st, 10, 1, "pm25", "2026-01-01T00:30:00Z", 100.0, coverage=60.0)
    add_raw(st, 11, 1, "pm25", "2026-01-01T00:30:00Z", 102.0, coverage=100.0)
    add_raw(st, 10, 1, "pm25", "2026-01-01T01:30:00Z", 100.0)
    add_raw(st, 11, 1, "pm25", "2026-01-01T01:30:00Z", 300.0)
    clean_mod.clean_air(st)
    a, b = st.query("select * from clean_air order by label_utc")
    assert a["sensor_id"] == 11 and a["n_candidates"] == 2 and "MULTI_SENSOR" in a["flags"]
    assert "SENSOR_CONFLICT" in b["flags"] and b["usable"] == 1


def test_cleaning_never_touches_raw_and_is_deterministic():
    st = store()
    add_station(st)
    add_sensor(st, 10, 1, "pm25")
    add_series(st, 10, 1, "pm25", "2026-01-01T00:30:00Z", [10.0 + i % 7 for i in range(100)])
    raw_before = st.digest("raw_air", "row_key")
    clean_mod.clean_air(st)
    d1 = st.digest("clean_air", "station_id, pollutant, label_utc")
    clean_mod.clean_air(st)
    assert st.digest("raw_air", "row_key") == raw_before
    assert st.digest("clean_air", "station_id, pollutant, label_utc") == d1


def unit_store(co_ppb_value=1.0, native=4):
    st = store()
    for i in range(1, native + 1):  # stations that report CO natively in µg/m³, ~1000
        add_station(st, i)
        add_sensor(st, 100 + i, i, "co")
        add_series(st, 100 + i, i, "co", "2026-01-01T00:30:00Z", [900.0 + 40 * i + k % 5 for k in range(60)])
    add_station(st, 9)
    add_sensor(st, 109, 9, "co", units="ppb")
    add_series(st, 109, 9, "co", "2026-01-01T00:30:00Z", [co_ppb_value + (k % 4) / 10 for k in range(60)], units="ppb")
    add_sensor(st, 110, 9, "no2", units="ppb")
    add_series(st, 110, 9, "no2", "2026-01-01T00:30:00Z", [25.0 + k % 3 for k in range(60)], units="ppb")
    for i in range(1, native + 1):
        add_sensor(st, 200 + i, i, "no2")
        add_series(st, 200 + i, i, "no2", "2026-01-01T00:30:00Z", [45.0 + k % 4 for k in range(60)])
    return st


def test_a_sensor_whose_unit_contradicts_its_magnitude_is_flagged_and_excluded_never_rescaled():
    st = unit_store()
    res = clean_mod.clean_air(st)
    assert res["unit_suspect_sensors"] == 1
    check = st.query("select * from sensor_unit_checks where suspect=1")[0]
    assert check["sensor_id"] == 109 and check["units"] == "ppb" and check["ratio"] < 0.01 and check["reference_std"] > 900
    rows = st.query("select * from clean_air where station_id=9 and pollutant='co'")
    assert len(rows) == 60 and all(r["usable"] == 0 and "UNIT_SUSPECT" in r["flags"] for r in rows)
    assert rows[0]["orig_value"] == 1.0 and rows[0]["orig_unit"] == "ppb"  # the provider's number is untouched
    assert all(r["usable"] == 1 for r in st.query("select usable from clean_air where pollutant='co' and station_id=1"))


def test_suspect_sensors_are_listed_in_the_coverage_report():
    st = unit_store()
    clean_mod.clean_air(st)
    rep = coverage.build_report(st, utc("2026-01-01T00:00:00Z"), utc("2026-01-04T00:00:00Z"), now=utc(FETCHED))
    assert [x["sensor_id"] for x in rep["unit_suspect_sensors"]] == [109]
    assert "excluded, not rescaled" in coverage.render_markdown(rep)


def test_co_with_an_implausible_median_is_suspect_even_without_reference_sensors():
    st = store()
    for i in range(1, 4):  # only "ppb" CO sensors reading ~1: no native-unit reference exists, as in the real window
        add_station(st, i)
        add_sensor(st, 100 + i, i, "co", units="ppb")
        add_series(st, 100 + i, i, "co", "2026-01-01T00:30:00Z", [1.0 + 0.1 * (k % 5) for k in range(40)], units="ppb")
    res = clean_mod.clean_air(st)
    assert res["unit_suspect_sensors"] == 3
    assert all(r["usable"] == 0 and "UNIT_SUSPECT" in r["flags"] for r in st.query("select * from clean_air where pollutant='co'"))
    assert st.query("select orig_value from clean_air where station_id=1 limit 1")[0][0] == 1.0  # the provider's number is untouched
    # a plausible CO series (about 700 ug/m3) is not flagged
    ok = store()
    add_station(ok, 1)
    add_sensor(ok, 1, 1, "co")
    add_series(ok, 1, 1, "co", "2026-01-01T00:30:00Z", [700.0 + k for k in range(40)])
    assert clean_mod.clean_air(ok)["unit_suspect_sensors"] == 0


def test_floor_based_suspects_render_in_the_report_without_a_reference_value():
    st = store()
    add_station(st, 1)
    add_sensor(st, 101, 1, "co", units="ppb")
    add_series(st, 101, 1, "co", "2026-01-01T00:30:00Z", [1.0] * 40, units="ppb")
    clean_mod.clean_air(st)
    rep = coverage.build_report(st, utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    assert rep["unit_suspect_sensors"][0]["reference_std"] is None
    assert "physical-plausibility floor" in coverage.render_markdown(rep)


def test_a_plausible_ppb_sensor_is_not_flagged():
    st = unit_store()
    clean_mod.clean_air(st)
    no2 = st.query("select suspect, ratio from sensor_unit_checks where sensor_id=110")[0]
    assert no2["suspect"] == 0 and 0.5 < no2["ratio"] < 2.0


def test_without_enough_native_reference_sensors_the_reference_rule_does_not_fire():
    def build(native):
        st = store()
        for i in range(1, native + 1):  # SO2 reported natively in ug/m3, ~60
            add_station(st, i)
            add_sensor(st, 100 + i, i, "so2")
            add_series(st, 100 + i, i, "so2", "2026-01-01T00:30:00Z", [60.0 + k % 5 for k in range(40)])
        add_station(st, 9)
        add_sensor(st, 109, 9, "so2", units="ppb")
        add_series(st, 109, 9, "so2", "2026-01-01T00:30:00Z", [0.5 + (k % 3) / 10 for k in range(40)], units="ppb")  # ~1.4 ug/m3: 40x too small
        return st
    assert clean_mod.clean_air(build(2))["unit_suspect_sensors"] == 0  # two references are not enough evidence
    assert clean_mod.clean_air(build(3))["unit_suspect_sensors"] == 1  # three are


def test_a_good_sensor_wins_the_hour_over_a_suspect_one_at_the_same_station():
    st = unit_store()
    add_sensor(st, 111, 9, "co")  # a second, native-unit CO sensor at the station with the suspect one
    add_series(st, 111, 9, "co", "2026-01-01T00:30:00Z", [1000.0] * 10, coverage=50.0)
    clean_mod.clean_air(st)
    r = st.query("select * from clean_air where station_id=9 and pollutant='co' and label_utc='2026-01-01T03:00:00Z'")[0]
    assert r["sensor_id"] == 111 and r["usable"] == 1 and r["n_candidates"] == 2


# ---------------------------------------------------------------------------------------------- weather ingestion and cleaning
NOW = utc("2026-01-20T12:00:00Z")


def weather_store():
    st = store()
    add_station(st, 1)
    add_station(st, 2, lat=28.5, lon=77.4, zone="Noida")
    add_sensor(st, 10, 1, "pm25")
    add_sensor(st, 20, 2, "pm25")
    return st


def archive_client(times, **kw):
    seen = []

    def handler(req: httpx.Request):
        seen.append(dict(req.url.params))
        return httpx.Response(200, json=archive_response(len(req.url.params["latitude"].split(",")), times, **kw))

    return OpenMeteoClient(get_settings(), transport=httpx.MockTransport(handler)), seen


async def test_weather_backfill_keeps_hours_up_to_now_only_and_records_the_grid_and_units():
    st = weather_store()
    times = [isoz(NOW + (i - 30) * HOUR).replace("Z", "").rsplit(":", 0)[0] for i in range(40)]  # 30 h before now .. 9 h after
    times = [t[:16] for t in times]
    client, seen = archive_client(times)
    res = await ingest_weather.backfill_weather(st, client, utc("2026-01-15T00:00:00Z"), utc("2026-01-21T00:00:00Z"), "w1", now=lambda: NOW)
    assert res["failed_windows"] == 0 and res["requests"] == 1 and seen[0]["timezone"] == "GMT" and seen[0]["start_date"] == "2026-01-15"
    latest = st.query("select max(time_utc) t from raw_weather")[0]["t"]
    assert latest == isoz(NOW)  # nothing stamped after the fetch time is stored
    assert st.query("select count(*) c from raw_weather where point_id='st1'")[0]["c"] == 31
    meta = st.query("select * from raw_weather_meta where point_id='st2'")[0]
    assert meta["grid_lat"] == pytest.approx(28.6) and meta["elevation_m"] == 215.0 and json.loads(meta["units"])["wind_speed_10m"] == "km/h"


async def test_a_unit_change_in_the_archive_is_reported_as_a_problem():
    st = weather_store()
    client, _ = archive_client(["2026-01-15T00:00"], fail_unit=True)
    res = await ingest_weather.backfill_weather(st, client, utc("2026-01-15T00:00:00Z"), utc("2026-01-16T00:00:00Z"), "w1", now=lambda: NOW)
    assert any("wind_speed_10m" in p and "m/s" in p for p in res["problems"])


async def test_recent_windows_are_refetched_but_old_ones_are_final():
    st = weather_store()
    client, seen = archive_client(["2026-01-18T00:00"])
    await ingest_weather.backfill_weather(st, client, utc("2026-01-18T00:00:00Z"), utc("2026-01-19T00:00:00Z"), "w1", now=lambda: NOW)
    await ingest_weather.backfill_weather(st, client, utc("2026-01-18T00:00:00Z"), utc("2026-01-19T00:00:00Z"), "w2", now=lambda: NOW)
    assert len(seen) == 2  # within 10 days of the fetch: fetched again
    assert st.count("raw_weather") == 2  # identical values are not duplicated

    st2 = weather_store()
    client2, seen2 = archive_client(["2025-12-01T00:00"])
    far = lambda: utc("2026-03-01T00:00:00Z")  # noqa: E731
    for rid in ("a", "b"):
        await ingest_weather.backfill_weather(st2, client2, utc("2025-12-01T00:00:00Z"), utc("2025-12-02T00:00:00Z"), rid, now=far)
    assert len(seen2) == 1


def test_clean_weather_flags_provisional_and_out_of_range_but_keeps_values():
    st = weather_store()
    add_weather_raw(st, 1, ["2026-01-19T00:00:00Z"], fetched="2026-01-20T12:00:00Z")  # 1 day old at fetch: provisional
    add_weather_raw(st, 1, ["2025-12-01T00:00:00Z"], fetched="2026-01-20T12:00:00Z", wind_speed_10m=900.0)
    clean_mod.clean_weather(st)
    recent = st.query("select * from clean_weather where time_utc='2026-01-19T00:00:00Z'")[0]
    old = st.query("select * from clean_weather where time_utc='2025-12-01T00:00:00Z'")[0]
    assert recent["provisional"] == 1 and "PROVISIONAL" in recent["flags"]
    assert old["provisional"] == 0 and "OUT_OF_RANGE:wind_speed_10m" in old["flags"] and old["wind_speed_10m"] == 900.0


# ---------------------------------------------------------------------------------------------- model-ready table
def feature_store(n=300, hours_weather=True):
    st = store()
    add_station(st)
    add_sensor(st, 10, 1, "pm25")
    add_sensor(st, 11, 1, "no2", units="ppb")
    add_series(st, 10, 1, "pm25", "2026-01-01T00:30:00Z", [40.0 + (i * 7) % 53 for i in range(n)])
    add_series(st, 11, 1, "no2", "2026-01-01T00:30:00Z", [10.0 + i % 5 for i in range(n)], units="ppb")
    if hours_weather:
        start = utc("2026-01-01T00:00:00Z")
        add_weather_raw(st, 1, [isoz(start + i * HOUR) for i in range(n)], fetched="2026-06-01T00:00:00Z")
    clean_mod.clean_air(st)
    clean_mod.clean_weather(st)
    return st


def test_model_ready_rows_match_the_clean_layer_and_register_their_provenance():
    st = feature_store()
    res = features.build_model_ready(st, ["pm25"], now=utc(FETCHED))
    assert res["rows"] == 300 and res["columns"] == len(features.feature_columns(features.HORIZONS))
    row = st.query("select * from model_ready where origin_utc='2026-01-05T12:00:00Z'")[0]
    clean = {r["label_utc"]: r["value_std"] for r in st.query("select label_utc, value_std from clean_air where pollutant='pm25'")}
    assert row["target_lag0"] == clean["2026-01-05T12:00:00Z"] and row["target_lag24"] == clean["2026-01-04T12:00:00Z"]
    assert row["y_h6"] == clean["2026-01-05T18:00:00Z"] and row["y_h72"] == clean["2026-01-08T12:00:00Z"]
    assert row["obs_no2"] == pytest.approx((10.0 + (4 * 24 + 12) % 5) * 46.0055 / 24.45)  # the standardised µg/m³ value, not the raw ppb
    assert row["wx_wind_u"] == pytest.approx(-10 / 3.6) and row["origin_ist"] == "2026-01-05T17:30:00+05:30"
    fs = st.query("select * from feature_sets where name='model_ready'")[0]
    assert fs["digest"] == res["digest"] and json.loads(fs["params"])["latency_hours"] == 0 and fs["rows"] == 300


def test_features_are_reproducible_bit_for_bit():
    a, b = feature_store(), feature_store()
    ra = features.build_model_ready(a, ["pm25"], now=utc(FETCHED))
    rb = features.build_model_ready(b, ["pm25"], now=utc(FETCHED))
    assert ra["digest"] == rb["digest"]
    assert features.build_model_ready(a, ["pm25"], now=utc(FETCHED))["digest"] == ra["digest"]  # rebuilding in place changes nothing


def test_unusable_and_out_of_range_inputs_never_reach_the_features():
    st = feature_store(n=60)
    st.execute("update clean_air set usable=0, flags='NEGATIVE' where pollutant='pm25' and label_utc='2026-01-01T20:00:00Z'")
    st.execute("update clean_weather set wind_speed_10m=900, flags='OUT_OF_RANGE:wind_speed_10m' where time_utc='2026-01-01T22:00:00Z'")
    st.commit()
    features.build_model_ready(st, ["pm25"], horizons=[1, 3])
    assert not st.query("select 1 from model_ready where origin_utc='2026-01-01T20:00:00Z'")  # no row anchored on a bad value
    nxt = st.query("select target_lag1, target_n_3h from model_ready where origin_utc='2026-01-01T21:00:00Z'")[0]
    assert nxt["target_lag1"] is None and nxt["target_n_3h"] == 2
    assert st.query("select wx_wind_ms, wx_wind_u from model_ready where origin_utc='2026-01-01T22:00:00Z'")[0]["wx_wind_ms"] is None


def test_features_in_the_store_ignore_flags_and_values_that_only_exist_in_the_future():
    base = feature_store(n=300)
    other = feature_store(n=300)
    # from hour 220 on: a long flat run (flagged FLATLINE) and a revised-looking duplicate; all of it lies after origin 200
    other.execute("delete from raw_air where sensor_id=10 and period_to_utc >= '2026-01-10T04:30:00Z'")
    other.commit()
    add_series(other, 10, 1, "pm25", "2026-01-10T04:30:00Z", [77.0] * 80)
    clean_mod.clean_air(other)
    assert any("FLATLINE" in r["flags"] for r in other.query("select flags from clean_air where pollutant='pm25'"))
    features.build_model_ready(base, ["pm25"])
    features.build_model_ready(other, ["pm25"])
    cols = [c for c in features.feature_columns(features.HORIZONS) if not c.startswith("y_h")]
    q = "select " + ",".join(cols) + " from model_ready where origin_utc < '2026-01-09T08:00:00Z' order by origin_utc"
    a, b = base.query(q), other.query(q)
    assert len(a) == len(b) > 150
    assert [tuple(r) for r in a] == [tuple(r) for r in b]
    assert "target_low_coverage" in cols and "target_soft_flagged" not in cols


def test_missing_weather_leaves_weather_features_null_not_zero():
    st = feature_store(n=60, hours_weather=False)
    features.build_model_ready(st, ["pm25"], horizons=[1])
    r = st.query("select wx_temp, wx_wind_u, wx_precip_sum_24h, wx_hours_since_rain from model_ready limit 1")[0]
    assert tuple(r) == (None, None, None, None)


def test_latency_hours_is_recorded_and_applied():
    st = feature_store(n=100)
    features.build_model_ready(st, ["pm25"], horizons=[1], latency_hours=24)
    assert json.loads(st.query("select params from feature_sets")[0]["params"])["latency_hours"] == 24
    r = st.query("select target_lag0, origin_utc from model_ready where origin_utc='2026-01-03T12:00:00Z'")[0]
    clean = {x["label_utc"]: x["value_std"] for x in st.query("select label_utc, value_std from clean_air where pollutant='pm25'")}
    assert r["target_lag0"] == clean["2026-01-02T12:00:00Z"]


# ---------------------------------------------------------------------------------------------- coverage report
def coverage_store():
    """One station, 48-hour window, 40 usable hours with one 8-hour gap; weather present for the whole window."""
    st = store()
    add_station(st, 1)
    add_sensor(st, 10, 1, "pm25", first="2025-01-01T00:00:00Z", last="2026-06-01T00:00:00Z")
    vals = [50.0 + i for i in range(20)] + ["skip"] * 8 + [70.0 + i for i in range(20)]
    add_series(st, 10, 1, "pm25", "2026-01-01T00:30:00Z", vals)
    start = utc("2026-01-01T00:00:00Z")
    add_weather_raw(st, 1, [isoz(start + i * HOUR) for i in range(48)], fetched="2026-06-01T00:00:00Z")
    clean_mod.clean_air(st)
    clean_mod.clean_weather(st)
    return st


def test_coverage_numbers_are_exactly_what_the_data_contains():
    st = coverage_store()
    rep = coverage.build_report(st, utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    s = next(x for x in rep["by_station"] if x["pollutant"] == "pm25")
    assert (s["usable_hours"], s["active_hours"], s["coverage_active_pct"], s["gap_count"], s["longest_gap_hours"]) == (40, 48, 83.3, 1, 8)
    assert s["zone"] == "Delhi" and s["agency"] == "Delhi (DPCC)" and (s["lat"], s["lon"]) == (28.61, 77.21)
    assert rep["by_pollutant"]["pm25"] == {"stations": 1, "usable_hours": 40, "active_hours": 48, "coverage_active_pct": 83.3}
    assert rep["by_pollutant"]["pm10"]["usable_hours"] == 0
    assert rep["by_month"]["2026-01"]["pm25"]["usable_hours"] == 40
    assert rep["by_region"]["Delhi"]["pm25"]["usable_hours"] == 40
    assert rep["by_region_month"]["Delhi"]["2026-01"]["pm25"]["coverage_active_pct"] == 83.3
    assert rep["duplicates"] == {"raw_rows": 40, "clean_rows": 40, "hours_with_multiple_candidates": 0}
    assert rep["weather"]["rows"] == 48 and rep["weather"]["null_rate_pct"]["temperature_2m"] == 0.0 and rep["weather"]["distinct_grid_cells"] == 0


def test_a_sensor_that_did_not_exist_yet_is_not_counted_as_a_gap():
    st = coverage_store()
    add_sensor(st, 10, 1, "pm25", first="2026-01-02T00:00:00Z", last="2026-06-01T00:00:00Z")
    rep = coverage.build_report(st, utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    s = next(x for x in rep["by_station"] if x["pollutant"] == "pm25")
    assert s["active_hours"] == 24
    assert s["coverage_window_pct"] == 83.3  # against the whole window it is still shown honestly


def test_support_verdicts_follow_the_documented_thresholds(monkeypatch):
    st = coverage_store()
    monkeypatch.setattr(coverage, "MIN_PAIRS", 10)
    monkeypatch.setattr(coverage, "MIN_SPAN_DAYS", 0)
    monkeypatch.setattr(coverage, "SUPPORTED_STATIONS", 1)
    rep = coverage.build_report(st, utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    h1 = rep["support"]["pm25"]["1"]
    assert h1["pairs_with_weather"] == 38 and h1["verdict"] == "supported"  # 40 usable hours, 2 of them are the last hour of a run
    assert rep["support"]["pm25"]["72"]["verdict"] == "insufficient" and rep["support"]["pm25"]["72"]["pairs_with_weather"] == 0
    assert rep["support"]["pm10"]["1"]["verdict"] == "insufficient"


def test_default_thresholds_say_a_two_day_dataset_supports_nothing():
    rep = coverage.build_report(coverage_store(), utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    assert all(v["verdict"] == "insufficient" for p in rep["support"].values() for v in p.values())


def test_markdown_report_states_definitions_limits_and_every_section():
    rep = coverage.build_report(coverage_store(), utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    md = coverage.render_markdown(rep)
    for heading in ("## By pollutant", "## By region", "## By month", "## By station", "## Quality flags", "## Units as received", "## Duplicates",
                    "## Weather", "## Publication latency", "## Which forecasting targets and horizons", "## Ingest runs"):
        assert heading in md
    assert "83.3%" in md and "insufficient" in md and "not a statistical guarantee" in md


def test_a_station_with_no_data_still_appears_with_zero_coverage():
    st = coverage_store()
    add_station(st, 2, lat=28.5, lon=77.4, zone="Noida")
    add_sensor(st, 20, 2, "pm25", first="2025-01-01T00:00:00Z", last="2026-06-01T00:00:00Z")
    rep = coverage.build_report(st, utc("2026-01-01T00:00:00Z"), utc("2026-01-03T00:00:00Z"), now=utc(FETCHED))
    s2 = next(x for x in rep["by_station"] if x["station_id"] == 2 and x["pollutant"] == "pm25")
    assert s2["usable_hours"] == 0 and s2["coverage_active_pct"] == 0.0 and s2["first_usable_utc"] is None


# ---------------------------------------------------------------------------------------------- command line and PostgreSQL check
def test_check_db_reports_unreachable_postgres_and_falls_back_to_sqlite():
    res = cli.check_db(get_settings())
    assert res["postgres"] == "unreachable" and res["pipeline_store"] == "sqlite" and "s3cretpw" not in json.dumps(res)


def test_steps_reuse_the_window_of_the_last_ingest_unless_dates_are_given(tmp_path, capsys):
    db = tmp_path / "h.sqlite"
    st = cli.HistoryStore(str(db))
    ingest_air.start_run(st, "ingest-air", {"from": "2026-01-01T00:00:00+00:00", "to": "2026-01-10T00:00:00+00:00"}, utc(FETCHED))
    add_station(st)
    add_sensor(st, 10, 1, "pm25", first="2025-01-01T00:00:00Z", last="2026-06-01T00:00:00Z")
    add_series(st, 10, 1, "pm25", "2026-01-01T00:30:00Z", [30.0] * 24)
    st.close()
    out = tmp_path / "o"
    assert cli.main(["clean", "--db", str(db)]) == 0 and cli.main(["report", "--db", str(db), "--out", str(out)]) == 0
    rep = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
    assert rep["window"]["from"] == "2026-01-01T00:00:00Z" and rep["window"]["to"] == "2026-01-09T23:00:00Z"


def test_cli_end_to_end_on_local_data(tmp_path):
    db = tmp_path / "h.sqlite"
    st = cli.HistoryStore(str(db))
    add_station(st)
    add_sensor(st, 10, 1, "pm25", first="2025-01-01T00:00:00Z", last="2026-06-01T00:00:00Z")
    add_series(st, 10, 1, "pm25", "2026-01-01T00:30:00Z", [30.0 + i % 9 for i in range(200)])
    add_weather_raw(st, 1, [isoz(utc("2026-01-01T00:00:00Z") + i * HOUR) for i in range(200)], fetched="2026-06-01T00:00:00Z")
    st.close()
    out = tmp_path / "out"
    base = ["--db", str(db), "--from", "2026-01-01", "--to", "2026-01-10"]
    for cmd in ("clean", "features", "report"):
        extra = ["--out", str(out)] if cmd == "report" else []
        assert cli.main([cmd, *base, *extra]) == 0
    assert (out / "coverage-report.json").exists() and (out / "coverage-report.md").exists()
    rep = json.loads((out / "coverage-report.json").read_text(encoding="utf-8"))
    assert rep["by_pollutant"]["pm25"]["usable_hours"] == 200


def test_cleaning_can_be_restricted_to_some_stations_and_leaves_the_others_alone():
    st = store()
    for sid, sensor in ((1, 10), (2, 20)):
        add_station(st, sid=sid, name=f"S{sid}")
        add_sensor(st, sensor, sid, "pm25")
        add_series(st, sensor, sid, "pm25", "2026-01-01T00:30:00Z", [60.0, 61.0, 62.0])
    clean_mod.clean_air(st)
    before_2 = st.query("select * from clean_air where station_id=2 order by label_utc")
    # change station 1's raw data, then clean only station 1
    st.execute("update raw_air set value = value + 100 where station_id = 1")
    st.commit()
    res = clean_mod.clean_air(st, station_ids=[1])
    assert res
    after_1 = [r["orig_value"] for r in st.query("select orig_value from clean_air where station_id=1 order by label_utc")]
    assert after_1 == [160.0, 161.0, 162.0]
    assert [dict(r) for r in st.query("select * from clean_air where station_id=2 order by label_utc")] == [dict(r) for r in before_2]
