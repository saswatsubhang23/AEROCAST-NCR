from datetime import datetime, timezone

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError
from app.services import cams_fields as cf

NOW = datetime(2026, 10, 11, 1, 30, tzinfo=timezone.utc)
TIMES = ["2026-10-11T00:00", "2026-10-11T01:00", "2026-10-11T02:00"]


def item(i, over=None, times=None):
    h = {"time": times or TIMES, "pm2_5": [50.0 + i] * 3, "pm10": [120.0] * 3, "nitrogen_dioxide": [20.0] * 3, "ozone": [60.0] * 3,
         "sulphur_dioxide": [10.0] * 3, "carbon_monoxide": [400.0] * 3, "nitrogen_monoxide": [1.0] * 3, "dust": [30.0] * 3}
    h.update(over or {})
    return {"latitude": 28.1, "longitude": 76.7, "hourly": h, "hourly_units": {"pm2_5": "μg/m³", "carbon_monoxide": "μg/m³"}}


def svc(handler):
    return cf.CamsFieldsService(get_settings(), OpenMeteoClient(get_settings(), httpx.MockTransport(handler)), now=lambda: NOW)


def echo(over=None, times=None):
    def h(req: httpx.Request):
        n = len(req.url.params["latitude"].split(","))
        return httpx.Response(200, json=[item(i, over, times) for i in range(n)])
    return h


@pytest.mark.asyncio
async def test_lattice_values_pass_through_with_units_and_a_now_index():
    out = await svc(echo()).fields(1, 2)
    assert out["grid"]["rows"] == cf.ROWS and out["grid"]["cols"] == cf.COLS
    v = out["variables"]["pm25"]
    assert len(v["values"]) == 3 and len(v["values"][0]) == cf.ROWS and len(v["values"][0][0]) == cf.COLS
    assert v["unit"] == "µg/m³" and v["values"][0][0][0] == 50.0 and v["available"] is True
    assert out["now_index"] == 1 and out["times"][0] == "2026-10-11T00:00:00Z"
    assert out["source"]["kind"] == "atmospheric_model" and "not measurements" in " ".join(out["notes"])


@pytest.mark.asyncio
async def test_implausible_and_missing_values_become_null():
    out = await svc(echo({"pm2_5": [None, 99999.0, 40.0], "ozone": [None] * 3})).fields(1, 2)
    assert out["variables"]["pm25"]["values"][0][0][0] is None and out["variables"]["pm25"]["values"][1][0][0] is None
    assert out["variables"]["pm25"]["values"][2][0][0] == 40.0
    assert out["variables"]["o3"]["available"] is False


@pytest.mark.asyncio
async def test_results_are_cached_and_inconsistent_time_axes_are_an_error():
    n = {"c": 0}

    def h(req):
        n["c"] += 1
        return echo()(req)

    s = svc(h)
    await s.fields(1, 2)
    first = n["c"]
    await s.fields(1, 2)
    assert n["c"] == first
    calls = {"n": 0}

    def bad(req):
        calls["n"] += 1
        k = len(req.url.params["latitude"].split(","))
        return httpx.Response(200, json=[item(i, times=TIMES if calls["n"] == 1 else TIMES[:2]) for i in range(k)])

    with pytest.raises(UpstreamError):
        await svc(bad).fields(1, 2)


@pytest.mark.asyncio
async def test_out_of_range_requests_are_refused():
    with pytest.raises(ValueError):
        await svc(echo()).fields(500, 2)


def test_endpoint_validates(client):
    assert client.get("/api/air/model-fields?past_hours=999").status_code == 422
