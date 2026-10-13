import json
from datetime import date, datetime, timezone

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError
from app.services import weather_fields as wf

NOW = datetime(2026, 10, 10, 12, 30, tzinfo=timezone.utc)
TIMES = ["2026-10-10T10:00", "2026-10-10T11:00", "2026-10-10T12:00", "2026-10-10T13:00"]


def point(i: int, overrides: dict | None = None, times=None):
    h = {
        "time": times or TIMES,
        "temperature_2m": [20.0 + i] * 4, "relative_humidity_2m": [50] * 4, "pressure_msl": [1010.0 + i * 0.1] * 4,
        "precipitation": [0.0, 1.5, 0.0, 0.0], "cloud_cover": [10] * 4, "boundary_layer_height": [300.0] * 4,
        "wind_speed_10m": [2.0] * 4, "wind_direction_10m": [90, 90, 180, 270],
    }
    h.update(overrides or {})
    return {"latitude": 28.2, "longitude": 76.9, "hourly": h, "hourly_units": {"pressure_msl": "hPa"}}


def service(handler):
    return wf.WeatherFieldsService(get_settings(), OpenMeteoClient(get_settings(), httpx.MockTransport(handler)), now=lambda: NOW)


def echo(overrides=None, times=None):
    def h(req: httpx.Request):
        n = len(req.url.params["latitude"].split(","))
        body = [point(i, overrides, times) for i in range(n)]
        return httpx.Response(200, json=body if n > 1 else body[0])
    return h


@pytest.mark.asyncio
async def test_lattice_is_complete_and_values_pass_through_with_units():
    out = await service(echo()).fields("forecast", 1, 1)
    assert out["grid"]["rows"] == wf.ROWS and out["grid"]["cols"] == wf.COLS
    v = out["variables"]["pressure_msl"]
    assert v["unit"] == "hPa" and len(v["values"]) == 4 and len(v["values"][0]) == wf.ROWS and len(v["values"][0][0]) == wf.COLS
    assert out["variables"]["precipitation"]["values"][1][0][0] == 1.5
    assert out["times"][0] == "2026-10-10T10:00:00Z"
    assert out["now_index"] == 2  # 12:00 is the last hour not after 12:30
    assert "not measurements" in " ".join(out["notes"])


@pytest.mark.asyncio
async def test_wind_components_follow_the_from_direction_convention():
    out = await service(echo()).fields("forecast", 1, 1)
    u, v = out["variables"]["wind_u"]["values"], out["variables"]["wind_v"]["values"]
    assert u[0][0][0] == pytest.approx(-2.0) and v[0][0][0] == pytest.approx(0.0, abs=1e-3)  # from the east: blows toward the west
    assert v[2][0][0] == pytest.approx(2.0, abs=1e-3)  # direction 180 is wind from the south: blows toward the north


def test_uv_convention_directly():
    assert wf.uv_from(2.0, 90) == (-2.0, pytest.approx(0.0, abs=1e-3))   # wind from the east moves toward the west
    u, v = wf.uv_from(3.0, 180)
    assert u == pytest.approx(0.0, abs=1e-3) and v == pytest.approx(3.0)  # wind from the south moves toward the north
    assert wf.uv_from(None, 90) == (None, None) and wf.uv_from(2.0, None) == (None, None)


@pytest.mark.asyncio
async def test_missing_and_implausible_values_become_null_never_filled():
    out = await service(echo({"pressure_msl": [None, 5000.0, 1010.0, 1010.0], "temperature_2m": [None] * 4})).fields("forecast", 1, 1)
    p = out["variables"]["pressure_msl"]["values"]
    assert p[0][0][0] is None and p[1][0][0] is None and p[2][0][0] == 1010.0  # None and 5000 hPa are not drawn
    assert out["variables"]["temperature_2m"]["available"] is False


@pytest.mark.asyncio
async def test_mismatched_time_axes_are_an_error():
    calls = {"n": 0}

    def h(req):
        calls["n"] += 1
        n = len(req.url.params["latitude"].split(","))
        return httpx.Response(200, json=[point(i, times=TIMES if calls["n"] == 1 else TIMES[:3]) for i in range(n)])

    with pytest.raises(UpstreamError):
        await service(h).fields("forecast", 1, 1)


@pytest.mark.asyncio
async def test_historical_window_rules_and_archive_endpoint():
    s = service(echo())
    with pytest.raises(ValueError):
        await s.fields("historical", start=date(2026, 10, 9), end=date(2026, 10, 10))  # today is not in the archive
    with pytest.raises(ValueError):
        await s.fields("historical", start=date(2026, 9, 1), end=date(2026, 9, 20))  # more than 10 days
    with pytest.raises(ValueError):
        await s.fields("historical", start=None, end=None)
    seen = []

    def h(req):
        seen.append(str(req.url))
        return echo()(req)

    out = await service(h).fields("historical", start=date(2026, 10, 1), end=date(2026, 10, 2))
    assert out["now_index"] is None and "archive" in seen[0] and "start_date=2026-10-01" in seen[0]
    assert "reanalysis" in out["source"]["provider"]


@pytest.mark.asyncio
async def test_results_are_cached():
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        return echo()(req)

    s = service(h)
    await s.fields("forecast", 1, 1)
    first = n["c"]
    await s.fields("forecast", 1, 1)
    assert n["c"] == first


def test_endpoint_validates_parameters(client):
    assert client.get("/api/weather/fields?mode=bogus").status_code == 422
    assert client.get("/api/weather/fields?mode=historical").status_code == 422


@pytest.mark.asyncio
async def test_levels_are_only_requested_and_returned_on_demand():
    seen = []

    def h(req):
        seen.append(req.url.params["hourly"])
        return echo({"wind_speed_80m": [10.0] * 4, "wind_direction_80m": [90, 180, 270, 0], "wind_speed_925hPa": [20.0] * 4, "wind_direction_925hPa": [180] * 4,
                     "geopotential_height_925hPa": [780.0] * 4})(req)

    plain = await service(h).fields("forecast", 1, 1)
    assert "wind_speed_80m" not in seen[0] and "wind_u_80m" not in plain["variables"] and plain["levels"] == []
    deep = await service(h).fields("forecast", 1, 1, levels=True)
    assert "wind_speed_925hPa" in seen[-1] and "geopotential_height_925hPa" in seen[-1]
    v = deep["variables"]
    # same from-direction convention at every height: from the east (90) moves toward the west, from the south (180) toward the north
    assert v["wind_u_80m"]["values"][0][0][0] == pytest.approx(-10.0)
    assert v["wind_v_80m"]["values"][1][0][0] == pytest.approx(10.0, abs=1e-2)
    assert v["wind_v_925hPa"]["values"][0][0][0] == pytest.approx(20.0, abs=1e-2)
    assert v["gph_925hPa"]["values"][0][0][0] == 780.0
    meta = {m["key"]: m for m in deep["levels"]}
    assert meta["80m"]["height_agl_m"] == 80.0 and meta["925hPa"]["kind"] == "pressure" and meta["925hPa"]["available"] is True
    assert meta["120m"]["available"] is False  # nothing came back for it: reported, not filled
    # the plain and the level request are cached separately
    assert "wind_u_80m" not in (await service(h).fields("forecast", 1, 1))["variables"]


@pytest.mark.asyncio
async def test_radiation_and_visibility_are_ordinary_bounded_fields():
    out = await service(echo({"shortwave_radiation": [0.0, 250.0, 9999.0, 700.0], "visibility": [4000.0] * 4})).fields("forecast", 1, 1)
    r = out["variables"]["shortwave_radiation"]
    assert r["unit"] == "W/m²" and r["values"][1][0][0] == 250.0 and r["values"][2][0][0] is None  # 9999 W/m2 is not physical: dropped
    assert out["variables"]["visibility"]["values"][0][0][0] == 4000.0
