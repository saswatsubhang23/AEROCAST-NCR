import httpx
import pytest

from app.core.config import get_settings
from app.integrations.http import UpstreamError
from app.integrations.openmeteo import OpenMeteoClient
from app.services.model_air_quality import ModelAirQualityService

BODY = {"latitude": 28.6, "longitude": 77.2, "elevation": 214.0,
        "hourly_units": {"pm2_5": "μg/m³", "pm10": "μg/m³"},
        "hourly": {"time": ["2026-10-10T07:00", "2026-10-10T08:00"], "pm2_5": [71.0, None], "pm10": [270.5, 296.2], "ozone": [1.0]}}


def svc(handler):
    return ModelAirQualityService(get_settings(), OpenMeteoClient(get_settings(), httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_values_are_passed_through_labelled_and_cached():
    calls = []

    def h(req):
        calls.append(req)
        return httpx.Response(200, json=BODY)

    s = svc(h)
    out = await s.forecast(28.6139, 77.209)
    assert out["kind"] == "atmospheric_model_forecast" and "not measurements" in out["notes"]
    assert out["pollutants"]["pm25"]["values"] == [71.0, None] and out["pollutants"]["pm10"]["unit"] == "µg/m³"
    assert "ozone" not in out["pollutants"]  # a series whose length does not match the time axis is dropped, not padded
    assert out["times_utc"][0] == "2026-10-10T07:00:00Z"
    await s.forecast(28.6139, 77.209)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_a_response_without_hourly_data_is_an_error_not_an_empty_forecast():
    with pytest.raises(UpstreamError):
        await svc(lambda r: httpx.Response(200, json={"latitude": 1})).forecast(28.6, 77.2)


def test_endpoint_rejects_points_outside_ncr(client):
    assert client.get("/api/air/model-forecast?lat=19.0&lon=72.8").status_code == 422
