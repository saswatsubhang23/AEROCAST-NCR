import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.integrations.openmeteo import OpenMeteoClient
from app.main import create_app
from app.services.batch_air_quality import BatchAirQualityService, pm25_category

SAMPLE_CSV = """State Name,Place,Latitude,Longitude
Andhra Pradesh,Ananthapuramu,14.68,77.60
Andhra Pradesh,Chittoor,13.22,79.10
Bihar,Patna,25.60,85.10
Delhi,Central,28.61,77.21
"""

SAMPLE_BAD_CSV = """State Name,Place,Latitude,Longitude
Delhi,Central,invalid,77.21
Delhi,North,28.70,out_of_bounds_lon
"""


def test_pm25_category_thresholds():
    assert pm25_category(15.0)[0] == "Good"
    assert pm25_category(45.0)[0] == "Satisfactory"
    assert pm25_category(75.0)[0] == "Moderately polluted"
    assert pm25_category(105.0)[0] == "Poor"
    assert pm25_category(180.0)[0] == "Very poor"
    assert pm25_category(350.0)[0] == "Severe"
    assert pm25_category(None)[0] == "Unknown"


def test_parse_csv_header_variations():
    svc = BatchAirQualityService(get_settings())
    rows, fields = svc.parse_csv_content(SAMPLE_CSV)
    assert len(rows) == 4
    assert fields == ["State Name", "Place", "Latitude", "Longitude"]
    assert rows[0]["place"] == "Ananthapuramu"
    assert rows[0]["latitude"] == 14.68
    assert rows[0]["longitude"] == 77.60
    assert rows[0]["valid"] is True


def test_parse_csv_handles_invalid_rows():
    svc = BatchAirQualityService(get_settings())
    rows, _ = svc.parse_csv_content(SAMPLE_BAD_CSV)
    assert len(rows) == 2
    assert rows[0]["valid"] is False
    assert "Invalid coordinate numbers" in rows[0]["error"]


@pytest.mark.asyncio
async def test_batch_service_fetches_and_enriches():
    def handler(req: httpx.Request):
        # Open-Meteo mock response for 2 coordinates
        return httpx.Response(200, json=[
            {
                "latitude": 14.68, "longitude": 77.60, "elevation": 335.0,
                "current": {"time": "2026-10-13T10:00", "pm2_5": 24.2},
                "hourly": {"time": ["2026-10-13T10:00", "2026-10-13T11:00"], "pm2_5": [24.2, 28.0]},
            },
            {
                "latitude": 28.61, "longitude": 77.21, "elevation": 215.0,
                "current": {"time": "2026-10-13T10:00", "pm2_5": 142.5},
                "hourly": {"time": ["2026-10-13T10:00", "2026-10-13T11:00"], "pm2_5": [142.5, 150.0]},
            },
        ])

    client = OpenMeteoClient(get_settings(), transport=httpx.MockTransport(handler))
    svc = BatchAirQualityService(get_settings(), client=client)

    rows, fields = svc.parse_csv_content(
        "State,Place,lat,lon\nAP,Ananthapur,14.68,77.6\nDelhi,Central,28.61,77.21\n"
    )
    enriched = await svc.fetch_pm25_for_batch(rows)
    assert enriched[0]["current_pm25"] == 24.2
    assert enriched[0]["aqi_category"] == "Good"
    assert enriched[1]["current_pm25"] == 142.5
    assert enriched[1]["aqi_category"] == "Very poor"

    summary = svc.calculate_summary(enriched)
    assert summary["total_rows"] == 2
    assert summary["valid_count"] == 2
    assert summary["avg_pm25"] == round((24.2 + 142.5) / 2, 1)
    assert summary["max_location"]["place"] == "Central"
    assert summary["min_location"]["place"] == "Ananthapur"

    csv_text = svc.generate_enriched_csv(enriched, fields)
    assert "Current_PM25_ug_m3" in csv_text
    assert "24.2" in csv_text
    assert "142.5" in csv_text


def test_api_batch_text_endpoint():
    app = create_app()
    client = TestClient(app)

    # We mock OpenMeteo inside the service via dependency override or mock transport
    def mock_handler(req: httpx.Request):
        return httpx.Response(200, json=[
            {
                "latitude": 14.68, "longitude": 77.60, "elevation": 335.0,
                "current": {"time": "2026-10-13T10:00", "pm2_5": 22.0},
                "hourly": {"time": ["2026-10-13T10:00"], "pm2_5": [22.0]},
            }
        ])

    from app.api.air import get_batch_air_service
    mock_svc = BatchAirQualityService(
        get_settings(),
        client=OpenMeteoClient(get_settings(), transport=httpx.MockTransport(mock_handler))
    )
    app.dependency_overrides[get_batch_air_service] = lambda: mock_svc

    resp = client.post("/api/air/batch-text", json={"csv_text": "State,Place,Latitude,Longitude\nAP,Place1,14.68,77.60\n"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["summary"]["total_rows"] == 1
    assert data["rows"][0]["current_pm25"] == 22.0
    assert data["rows"][0]["aqi_category"] == "Good"

    # Test CSV export endpoint
    export_resp = client.post("/api/air/batch-export-csv", json={"csv_text": "State,Place,Latitude,Longitude\nAP,Place1,14.68,77.60\n"})
    assert export_resp.status_code == 200
    assert "text/csv" in export_resp.headers["content-type"]
    assert "Current_PM25_ug_m3" in export_resp.text

    # Test PDF export endpoint
    pdf_resp = client.post("/api/air/batch-export-pdf", json={
        "summary": data["summary"],
        "rows": data["rows"],
        "title": "Test Batch Analysis",
    })
    assert pdf_resp.status_code == 200
    assert "application/pdf" in pdf_resp.headers["content-type"]
    assert pdf_resp.content.startswith(b"%PDF")


def test_batch_service_row_limit_guard():
    svc = BatchAirQualityService(get_settings())
    # Generate CSV with 2,501 rows to test guardrail
    lines = ["State,Place,Latitude,Longitude"] + ["AP,Place,14.68,77.60"] * 2501
    large_csv = "\n".join(lines)
    with pytest.raises(ValueError, match="which exceeds the safe batch limit"):
        svc.parse_csv_content(large_csv, max_rows=2500)


@pytest.mark.asyncio
async def test_hourly_cache_continuation_and_suppression():
    from app.services.batch_hourly_cache import BatchHourlyCache

    calls: list[httpx.Request] = []

    def mock_handler(req: httpx.Request):
        calls.append(req)
        # Mock Open-Meteo response
        return httpx.Response(200, json=[
            {
                "latitude": 28.61, "longitude": 77.21, "elevation": 215.0,
                "current": {"time": "2026-10-13T10:00", "pm2_5": 55.0},
                "hourly": {
                    "time": ["2026-10-13T09:00", "2026-10-13T10:00"],
                    "pm2_5": [50.0, 55.0],
                },
            }
        ])

    cache = BatchHourlyCache(":memory:")
    client = OpenMeteoClient(get_settings(), transport=httpx.MockTransport(mock_handler))
    svc = BatchAirQualityService(get_settings(), client=client, cache=cache)

    rows, _ = svc.parse_csv_content("Place,Latitude,Longitude\nDelhi,28.61,77.21\n")

    # Call 1: Initial fetch for window 2026-10-13T00:00 to 2026-10-13T10:00
    res1 = await svc.fetch_pm25_for_batch(
        rows,
        start_date="2026-10-13T00:00",
        end_date="2026-10-13T10:00",
    )
    assert len(calls) == 1
    assert res1[0]["from_cache"] is False
    assert res1[0]["current_pm25"] == 55.0

    # Call 2: Repeat fetch for the EXACT SAME window
    # Must NOT invoke the upstream API (should_fetch = False, request suppressed!)
    calls.clear()
    res2 = await svc.fetch_pm25_for_batch(
        rows,
        start_date="2026-10-13T00:00",
        end_date="2026-10-13T10:00",
    )
    assert len(calls) == 0, "Expected 0 API calls because data up to 10:00 is already cached!"
    assert res2[0]["from_cache"] is True
    assert res2[0]["fetch_reason"] == "already_cached_complete"
    assert res2[0]["current_pm25"] == 55.0

    # Call 3: Later window up to 2026-10-13T14:00
    # Must continue from 2026-10-13T11:00 (T + 1 hour)
    def continuation_handler(req: httpx.Request):
        calls.append(req)
        return httpx.Response(200, json=[
            {
                "latitude": 28.61, "longitude": 77.21, "elevation": 215.0,
                "current": {"time": "2026-10-13T14:00", "pm2_5": 72.0},
                "hourly": {
                    "time": ["2026-10-13T11:00", "2026-10-13T12:00", "2026-10-13T13:00", "2026-10-13T14:00"],
                    "pm2_5": [58.0, 62.0, 68.0, 72.0],
                },
            }
        ])

    client_cont = OpenMeteoClient(get_settings(), transport=httpx.MockTransport(continuation_handler))
    svc._client = client_cont

    calls.clear()
    res3 = await svc.fetch_pm25_for_batch(
        rows,
        start_date="2026-10-13T00:00",
        end_date="2026-10-13T14:00",
    )
    assert len(calls) == 1
    # Verify that the API was called with continuation start_hour
    sent_url = str(calls[0].url)
    assert "start_hour=2026-10-13T11%3A00" in sent_url or "start_hour=2026-10-13T11:00" in sent_url
    assert res3[0]["from_cache"] is False
    assert res3[0]["continued_from"] == "2026-10-13T10:00:00Z"
    # Merged series should contain both initial and continuation hours!
    assert len(res3[0]["hourly_times"]) == 6
    assert res3[0]["current_pm25"] == 72.0


