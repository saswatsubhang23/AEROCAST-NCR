"""Contract version 2: spatial / freshness / quality blocks are optional, checked when present, and filled honestly by the local provider."""

from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.forecast.contract import (
    CONTRACT_VERSION, DataFreshness, ForecastRequest, ForecastResponse, PollutantForecast, SpatialResolution, check_against_request, ForecastContractError,
)

T0 = datetime(2026, 10, 10, 6, tzinfo=timezone.utc)


def response(**block) -> ForecastResponse:
    f = {"pollutant": "pm25", "unit": "µg/m³", "times": [T0 + timedelta(hours=1)], "values": [40.0], **block}
    return ForecastResponse.model_validate({
        "model_version": "m1", "issued_at": T0, "location": {"lat": 28.6, "lon": 77.2}, "horizon_hours": 6, "forecasts": [f],
        "provenance": {"provider": "p", "generated_at": T0, "input_data": ["x"]},
    })


def request() -> ForecastRequest:
    return ForecastRequest(location={"lat": 28.6, "lon": 77.2}, issued_at=T0, horizon_hours=6, pollutants=["pm25"])


def test_version_1_responses_without_the_new_blocks_are_still_valid():
    r = response()
    f = r.forecasts[0]
    assert f.spatial is None and f.freshness is None and f.quality_flags == [] and r.contract_version is None
    assert CONTRACT_VERSION == "2"


def test_spatial_block_states_what_the_forecast_is_about():
    ok = response(spatial={"kind": "station", "station_id": "8118", "station_name": "Mandir Marg", "distance_km": 3.2}).forecasts[0].spatial
    assert ok.kind == "station" and ok.resolution_km is None
    grid = SpatialResolution(kind="grid", resolution_km=9.0)
    assert grid.resolution_km == 9.0
    with pytest.raises(ValidationError):
        SpatialResolution(kind="grid")  # a field must state its resolution
    with pytest.raises(ValidationError):
        SpatialResolution(kind="station", station_id="1", resolution_km=9.0)  # a station has no grid spacing
    with pytest.raises(ValidationError):
        SpatialResolution(kind="station", distance_km=-1)


def test_freshness_cannot_claim_fresh_beyond_its_own_limit():
    assert DataFreshness(input_age_hours=2.0, max_age_hours=6.0, status="fresh").status == "fresh"
    with pytest.raises(ValidationError):
        DataFreshness(input_age_hours=9.0, max_age_hours=6.0, status="fresh")
    with pytest.raises(ValidationError):
        DataFreshness(status="fresh")  # fresh with no age
    with pytest.raises(ValidationError):
        DataFreshness(input_age_hours=-1, status="unknown")
    assert DataFreshness(status="unknown").input_age_hours is None


def test_cross_checks_reject_inputs_from_the_future_and_unnamed_stations():
    ok = response(spatial={"kind": "station", "station_id": "1"}, freshness={"newest_input_at": T0 - timedelta(hours=2), "input_age_hours": 2.0, "max_age_hours": 6.0, "status": "fresh"})
    check_against_request(request(), ok, T0 + timedelta(minutes=1))
    future = response(freshness={"newest_input_at": T0 + timedelta(hours=3), "input_age_hours": 0.0, "status": "fresh"})
    with pytest.raises(ForecastContractError, match="newest input"):
        check_against_request(request(), future, T0 + timedelta(minutes=1))
    unnamed = response(spatial={"kind": "station"})
    with pytest.raises(ForecastContractError, match="name its station"):
        check_against_request(request(), unnamed, T0 + timedelta(minutes=1))


def test_json_schema_documents_the_new_blocks():
    from app.forecast.contract import contract_schemas

    props = contract_schemas()["response"]["$defs"]["PollutantForecast"]["properties"]
    assert {"spatial", "freshness", "quality_flags"} <= set(props)
