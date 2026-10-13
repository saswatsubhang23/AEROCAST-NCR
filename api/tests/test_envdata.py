"""The normalised environmental record: kinds, units, time semantics, flags and identity."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.envdata.ddl import POSTGIS_DDL, SOURCES_SEED
from app.envdata.schema import EnvRecord, EnvStore, from_open_meteo, from_openaq_hour, from_xkdr_row

NOW = datetime(2026, 10, 11, 6, 0, tzinfo=timezone.utc)


def openaq_row(value, units, name="pm25", frm="2025-11-03T23:30:00Z", to="2025-11-04T00:30:00Z", cov=100.0, flags=False):
    return {"value": value, "parameter": {"name": name, "units": units}, "period": {"datetimeFrom": {"utc": frm}, "datetimeTo": {"utc": to}},
            "coverage": {"percentCoverage": cov}, "flagInfo": {"hasFlags": flags}}


# ------------------------------------------------------------------------------------------------ OpenAQ
def test_openaq_hour_keeps_the_providers_period_and_is_an_observation():
    r = from_openaq_hour(openaq_row(142.0, "µg/m³"), station_id=8118, lat=28.6, lon=77.2, retrieved_at=NOW)
    assert r.kind == "observation" and r.issued_at is None and r.source == "openaq"
    assert r.valid_from.isoformat() == "2025-11-03T23:30:00+00:00" and r.valid_to.isoformat() == "2025-11-04T00:30:00+00:00"
    assert r.value == 142.0 and r.unit == "µg/m³" and r.usable and r.quality_flags == []
    assert r.location_id == "station:8118" and r.support == "point"


def test_gas_in_ppb_is_converted_keeping_the_original_and_flagging_it():
    r = from_openaq_hour(openaq_row(20.0, "ppb", name="no2"), station_id=1, lat=28.6, lon=77.2, retrieved_at=NOW)
    assert r.original_value == 20.0 and r.original_unit == "ppb" and r.unit == "µg/m³"
    assert r.value == pytest.approx(20.0 * 46.0055 / 24.45, rel=1e-6) and "UNIT_CONVERTED" in r.quality_flags and r.usable


def test_nox_is_reported_as_no2_and_ozone_ppm_is_scaled():
    nox = from_openaq_hour(openaq_row(10.0, "ppb", name="nox"), station_id=1, lat=28.6, lon=77.2, retrieved_at=NOW)
    assert nox.variable == "nox" and nox.value == pytest.approx(10.0 * 46.0055 / 24.45, rel=1e-6)
    o3 = from_openaq_hour(openaq_row(0.04, "ppm", name="o3"), station_id=1, lat=28.6, lon=77.2, retrieved_at=NOW)
    assert o3.value == pytest.approx(40.0 * 47.9982 / 24.45, rel=1e-6)


def test_unknown_unit_and_out_of_range_values_are_kept_but_unusable():
    unk = from_openaq_hour(openaq_row(12.0, "ppb", name="pm25"), station_id=1, lat=28.6, lon=77.2, retrieved_at=NOW)  # PM in ppb has no honest conversion
    assert unk.value is None and not unk.usable and "UNIT_UNKNOWN" in unk.quality_flags
    big = from_openaq_hour(openaq_row(99999.0, "µg/m³"), station_id=1, lat=28.6, lon=77.2, retrieved_at=NOW)
    assert big.value == 99999.0 and not big.usable and "OUT_OF_RANGE" in big.quality_flags  # kept and flagged, not clipped or dropped


def test_low_coverage_and_provider_flags_are_carried():
    r = from_openaq_hour(openaq_row(50.0, "µg/m³", cov=40.0, flags=True), station_id=1, lat=28.6, lon=77.2, retrieved_at=NOW)
    assert set(r.quality_flags) == {"LOW_COVERAGE", "PROVIDER_FLAGGED"} and r.usable


# ------------------------------------------------------------------------------------------------ xKDR
def test_xkdr_cpcb_is_read_as_ist_and_the_us_embassy_as_utc():
    row = {"period_start": "2025-01-01T00:00:00", "mean": 40.0, "unit": "µg/m³"}
    cpcb = from_xkdr_row(row, station_id=1, source="cpcb_caaqm", lat=28.6, lon=77.2, parameter="PM2.5", retrieved_at=NOW)
    us = from_xkdr_row(row, station_id=2, source="us_embassy", lat=28.6, lon=77.2, parameter="PM2.5", retrieved_at=NOW)
    assert cpcb.valid_from.isoformat() == "2024-12-31T18:30:00+00:00"
    assert us.valid_from.isoformat() == "2025-01-01T00:00:00+00:00"
    assert cpcb.valid_to - cpcb.valid_from == timedelta(hours=1)


# ------------------------------------------------------------------------------------------------ Open-Meteo
def om_body(times, **hourly):
    return {"latitude": 28.576, "longitude": 77.187, "hourly": {"time": times, **hourly},
            "hourly_units": {"temperature_2m": "°C", "wind_speed_10m": "km/h", "precipitation": "mm", "pm2_5": "μg/m³"}}


def test_open_meteo_forecast_hours_are_forecasts_and_past_hours_are_analysis():
    issued = datetime(2026, 10, 11, 2, 0, tzinfo=timezone.utc)
    body = om_body(["2026-10-11T00:00", "2026-10-11T05:00"], temperature_2m=[24.0, 30.0], wind_speed_10m=[18.0, 7.2])
    recs = from_open_meteo(body, source="open_meteo_forecast", kind="forecast", retrieved_at=NOW, issued_at=issued, resolution_km=9, cell_prefix="ifs")
    by = {(r.variable, r.valid_from.hour): r for r in recs}
    assert by[("t2m", 0)].kind == "analysis" and by[("t2m", 0)].issued_at is None  # entirely before the issue time
    assert by[("t2m", 5)].kind == "forecast" and by[("t2m", 5)].issued_at == issued
    assert by[("wind_speed_10m", 5)].value == pytest.approx(2.0) and "UNIT_CONVERTED" in by[("wind_speed_10m", 5)].quality_flags  # km/h -> m/s
    assert by[("t2m", 5)].support == "cell" and by[("t2m", 5)].resolution_km == 9


def test_accumulated_variables_describe_the_hour_ending_at_the_label():
    body = om_body(["2026-10-11T05:00"], precipitation=[1.5], temperature_2m=[24.0])
    recs = from_open_meteo(body, source="open_meteo_archive", kind="analysis", retrieved_at=NOW, issued_at=None, resolution_km=9, cell_prefix="era")
    p = next(r for r in recs if r.variable == "precip")
    t = next(r for r in recs if r.variable == "t2m")
    assert p.valid_to.hour == 5 and p.valid_from.hour == 4  # the hour ending at 05:00
    assert t.valid_from.hour == 5 and t.valid_to.hour == 6


def test_cams_cell_records_state_their_cell_size():
    body = om_body(["2026-10-11T05:00"], pm2_5=[91.0])
    r = from_open_meteo(body, source="open_meteo_air_quality", kind="forecast", retrieved_at=NOW, issued_at=NOW - timedelta(hours=6), resolution_km=44, cell_prefix="cams")[0]
    assert r.variable == "pm25" and r.unit == "µg/m³" and r.resolution_km == 44 and "Copernicus" in r.attribution


# ------------------------------------------------------------------------------------------------ the type itself
def base(**kw):
    d = dict(kind="observation", source="openaq", variable="pm25", value=10.0, unit="µg/m³", valid_from=NOW, valid_to=NOW + timedelta(hours=1), retrieved_at=NOW,
             location_id="station:1", lat=28.6, lon=77.2)
    d.update(kw)
    return d


@pytest.mark.parametrize("bad", [
    {"valid_to": NOW},  # empty period
    {"kind": "forecast"},  # forecast without an issue time
    {"issued_at": NOW},  # observation with an issue time
    {"kind": "forecast", "issued_at": NOW + timedelta(hours=5)},  # issued after the period it describes
    {"support": "cell"},  # cell value without its size
    {"unit": "ppb"},  # wrong storage unit
    {"variable": "made_up"},
    {"value": 99999.0},  # out of range but not flagged
    {"value": None, "usable": True},
    {"valid_from": datetime(2026, 10, 11, 6, 0)},  # naive timestamp
])
def test_the_record_refuses_inconsistent_combinations(bad):
    with pytest.raises(ValidationError):
        EnvRecord(**base(**bad))


def test_kind_is_part_of_identity_so_an_interpolation_never_collides_with_a_measurement():
    a = EnvRecord(**base())
    b = EnvRecord(**base(kind="interpolation", source="aerocast_idw"))
    c = EnvRecord(**base())
    assert a.record_id == c.record_id and a.record_id != b.record_id


def test_store_upserts_by_identity_and_keeps_kinds_apart():
    st = EnvStore()
    recs = [EnvRecord(**base()), EnvRecord(**base(kind="interpolation", source="aerocast_idw")), EnvRecord(**base(valid_from=NOW + timedelta(hours=1), valid_to=NOW + timedelta(hours=2)))]
    assert st.upsert(recs) == 3
    st.upsert([EnvRecord(**base(value=11.0, retrieved_at=NOW + timedelta(hours=3)))])  # the same hour fetched again replaces it
    rows = st.query("select kind, value, retrieved_at from env_record order by kind, valid_from")
    assert len(rows) == 3
    assert [r["kind"] for r in rows] == ["interpolation", "observation", "observation"]
    assert rows[1]["value"] == 11.0


def test_postgis_ddl_covers_the_required_objects():
    for needle in ("create extension if not exists postgis", "env_record", "check (kind <> 'forecast' or issued_at is not null)", "using gist", "exposure_cell", "sensitive_site",
                   "geometry(Point, 4326)", "timestamptz"):
        assert needle in POSTGIS_DDL, needle
    assert "open_meteo_air_quality" in SOURCES_SEED
