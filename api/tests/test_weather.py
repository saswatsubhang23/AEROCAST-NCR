from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.api.weather import get_weather_service
from app.core.config import get_settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamBadRequest, UpstreamError
from app.services.profile import find_inversions
from app.schemas.weather import ProfilePoint
from app.services.weather import MAX_HOURS, WeatherService

NOW = datetime(2026, 10, 9, 6, 20, tzinfo=timezone.utc)
BASE = {
    "temperature_2m": 30.0, "relative_humidity_2m": 50, "dew_point_2m": 18.0, "wind_speed_10m": 8.0,
    "wind_direction_10m": 120, "precipitation": 0.0, "surface_pressure": 990.0, "cloud_cover": 20,
    "boundary_layer_height": 900.0,
    "temperature_1000hPa": 27.0, "temperature_925hPa": 24.0, "temperature_850hPa": 19.0, "temperature_700hPa": 9.0,
    "geopotential_height_1000hPa": 118.0, "geopotential_height_925hPa": 800.0,
    "geopotential_height_850hPa": 1540.0, "geopotential_height_700hPa": 3180.0,
}
UNITS = {"relative_humidity_2m": "%", "wind_direction_10m": "°", "wind_speed_10m": "km/h", "precipitation": "mm",
         "surface_pressure": "hPa", "cloud_cover": "%", "boundary_layer_height": "m"}


def unit_of(key):
    if key in UNITS:
        return UNITS[key]
    return "m" if key.startswith("geopotential") else "°C"


class FakeMeteo:
    """Stands in for the Open-Meteo HTTP API. `script` entries are consumed one per request before normal answers."""

    def __init__(self, hours=96, script=(), mutate=None, current="2026-10-09T06:15"):
        self.hours, self.script, self.mutate, self.current = hours, list(script), mutate, current
        self.calls: list[dict] = []

    def _one(self, keys):
        start = datetime(2026, 10, 9)
        hourly = {"time": [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(self.hours)]}
        for k in keys:
            hourly[k] = [BASE[k] + i * 0.1 for i in range(self.hours)] if isinstance(BASE[k], float) else [BASE[k]] * self.hours
        raw = {
            "latitude": 28.576448, "longitude": 77.18678, "elevation": 214.0, "utc_offset_seconds": 0,
            "hourly_units": {"time": "iso8601", **{k: unit_of(k) for k in keys}},
            "hourly": hourly, "current": {"time": self.current, "temperature_2m": 31.0},
        }
        if self.mutate:
            self.mutate(raw)
        return raw

    def __call__(self, request: httpx.Request) -> httpx.Response:
        params = dict(request.url.params)
        self.calls.append(params)
        if self.script:
            step = self.script.pop(0)
            if step == "timeout":
                raise httpx.ReadTimeout("slow")
            if isinstance(step, int):
                return httpx.Response(step, json={"error": True, "reason": "Latitude must be in range"})
        keys = params["hourly"].split(",")
        n = len(params["latitude"].split(","))
        items = [self._one(keys) for _ in range(n)]
        for i, item in enumerate(items):
            item["latitude"] += i * 0.01
        return httpx.Response(200, json=items if n > 1 else items[0])


def make_service(fake, clock=lambda: NOW):
    settings = get_settings()
    client = OpenMeteoClient(settings, transport=httpx.MockTransport(fake))
    return WeatherService(settings, client=client, now=lambda: clock())


# ---------------------------------------------------------------- normalization -------------------------
async def test_point_is_sliced_from_current_hour_and_capped_at_72h():
    fake = FakeMeteo()
    r = await make_service(fake).point(28.61, 77.21)
    assert r.times[0] == datetime(2026, 10, 9, 6, tzinfo=timezone.utc)  # floor of 06:20
    assert len(r.times) == MAX_HOURS == r.coverage.hours
    assert r.coverage.start == r.times[0] and r.coverage.end == r.times[-1]
    # Series stay aligned with the times they belong to (value = base + 0.1 * hour-index-in-source).
    assert r.series["temperature_2m"][0] == pytest.approx(30.0 + 6 * 0.1)
    assert {v.key: v.unit for v in r.variables}["wind_speed_10m"] == "km/h"
    assert r.unavailable == []


async def test_request_pins_utc_and_explicit_units():
    fake = FakeMeteo()
    await make_service(fake).point(28.61, 77.21)
    p = fake.calls[0]
    assert (p["timezone"], p["wind_speed_unit"], p["temperature_unit"], p["precipitation_unit"]) == (
        "GMT", "kmh", "celsius", "mm")
    assert p["forecast_days"] == "4"


async def test_source_attribution_and_retrieval_time():
    r = await make_service(FakeMeteo()).point(28.61, 77.21)
    assert r.source.attribution.provider == "Open-Meteo"
    assert r.source.retrieved_at == NOW
    assert r.source.latest_source_time == datetime(2026, 10, 9, 6, 15, tzinfo=timezone.utc)
    assert r.source.freshness == "fresh"
    assert r.location.grid_lat == pytest.approx(28.576448)  # the model cell, not the requested point
    assert r.location.requested_lat == 28.61


async def test_missing_values_stay_null_never_zero():
    def mutate(raw):
        raw["hourly"]["precipitation"][10] = None
        raw["hourly"]["precipitation"][6] = 0.0
        raw["hourly"]["temperature_2m"][8] = None

    r = await make_service(FakeMeteo(mutate=mutate)).point(28.61, 77.21)
    assert r.series["precipitation"][10 - 6] is None
    assert r.series["temperature_2m"][8 - 6] is None
    assert r.series["precipitation"][0] == 0.0  # a real zero is still reported as zero


async def test_variable_returned_entirely_empty_or_omitted_is_unavailable():
    def mutate(raw):
        raw["hourly"]["boundary_layer_height"] = [None] * len(raw["hourly"]["time"])
        del raw["hourly"]["cloud_cover"]

    r = await make_service(FakeMeteo(mutate=mutate)).point(28.61, 77.21)
    assert {"boundary_layer_height", "cloud_cover"} <= set(r.unavailable)
    assert "boundary_layer_height" not in r.series and "cloud_cover" not in r.series
    assert any("cloud_cover" in w for w in r.source.warnings)


async def test_unexpected_unit_makes_variable_unavailable_instead_of_being_trusted():
    def mutate(raw):
        raw["hourly_units"]["wind_speed_10m"] = "m/s"

    r = await make_service(FakeMeteo(mutate=mutate)).point(28.61, 77.21)
    assert "wind_speed_10m" in r.unavailable
    assert any("unit" in w for w in r.source.warnings)


async def test_physically_impossible_values_are_discarded():
    def mutate(raw):
        raw["hourly"]["relative_humidity_2m"][7] = 180

    r = await make_service(FakeMeteo(mutate=mutate)).point(28.61, 77.21)
    assert r.series["relative_humidity_2m"][1] is None
    assert any("plausible" in w for w in r.source.warnings)


async def test_non_utc_response_is_rejected():
    with pytest.raises(UpstreamError):
        await make_service(FakeMeteo(mutate=lambda raw: raw.update(utc_offset_seconds=19800))).point(28.61, 77.21)


async def test_horizon_is_clamped_to_what_the_source_provides():
    r = await make_service(FakeMeteo(hours=40)).point(28.61, 77.21)  # 40 h from 00:00 -> 34 h from 06:00
    assert r.coverage.hours == 34 < MAX_HOURS


async def test_data_older_than_threshold_is_flagged_stale():
    r = await make_service(FakeMeteo(current="2026-10-09T01:00")).point(28.61, 77.21)
    assert r.source.freshness == "stale"


# ---------------------------------------------------------------- caching and failure --------------------
async def test_cache_avoids_repeat_requests_until_ttl_expires():
    fake, t = FakeMeteo(), [NOW]
    svc = make_service(fake, clock=lambda: t[0])
    await svc.point(28.61, 77.21)
    t[0] = NOW + timedelta(minutes=10)
    again = await svc.point(28.61, 77.21)
    assert len(fake.calls) == 1 and again.source.cache_age_s == 600
    t[0] = NOW + timedelta(minutes=20)
    await svc.point(28.61, 77.21)
    assert len(fake.calls) == 2


async def test_serves_last_good_data_marked_stale_when_provider_fails():
    fake, t = FakeMeteo(), [NOW]
    svc = make_service(fake, clock=lambda: t[0])
    await svc.point(28.61, 77.21)
    fake.script = [503, 503, 503]
    t[0] = NOW + timedelta(minutes=30)
    r = await svc.point(28.61, 77.21)
    assert r.source.served_from_cache_after_failure and r.source.freshness == "stale"
    assert r.source.cache_age_s == 1800
    assert any("most recent successful" in w for w in r.source.warnings)


async def test_failure_with_no_cache_raises():
    with pytest.raises(UpstreamError):
        await make_service(FakeMeteo(script=[503, 503, 503])).point(28.61, 77.21)


# ---------------------------------------------------------------- client retry behaviour ----------------
async def test_transient_failures_are_retried():
    fake = FakeMeteo(script=[503, "timeout"])
    r = await make_service(fake).point(28.61, 77.21)
    assert len(fake.calls) == 3 and r.coverage.hours == 72


async def test_bad_request_is_not_retried():
    fake = FakeMeteo(script=[400])
    with pytest.raises(UpstreamBadRequest):
        await make_service(fake).point(28.61, 77.21)
    assert len(fake.calls) == 1


# ---------------------------------------------------------------- grid -----------------------------------
async def test_grid_requests_16_cells_in_one_call_and_reports_each_cell_location():
    fake = FakeMeteo()
    g = await make_service(fake).grid()
    assert len(fake.calls) == 1 and len(fake.calls[0]["latitude"].split(",")) == 16
    assert len(g.points) == 16
    assert len({(p.location.grid_lat) for p in g.points}) == 16
    assert "nothing is interpolated" in g.note
    assert g.coverage.hours == 72


async def test_grid_with_wrong_location_count_is_rejected():
    class Short(FakeMeteo):
        def __call__(self, request):
            resp = super().__call__(request)
            return httpx.Response(200, json=resp.json()[:5])

    with pytest.raises(UpstreamError):
        await make_service(Short()).grid()


# ---------------------------------------------------------------- vertical profile -----------------------
async def test_profile_excludes_levels_below_ground():
    r = await make_service(FakeMeteo()).profile(28.61, 77.21)
    pressures = [p.pressure_hpa for p in r.hours[0].points]
    # surface pressure is ~990 hPa and ground is 214 m, so the 1000 hPa level (118 m) is underground.
    assert 1000.0 not in pressures
    assert pressures == [None, 925.0, 850.0, 700.0]
    assert r.hours[0].points[0].height_agl_m == 2.0
    assert r.hours[0].points[1].height_agl_m == pytest.approx(800 + 6 * 0.1 - 214)  # gph minus ground elevation
    assert "not balloon soundings" in r.note


def test_inversion_is_detected_where_temperature_rises_with_height():
    pts = [
        ProfilePoint(pressure_hpa=None, height_agl_m=2, temperature_c=18.0),
        ProfilePoint(pressure_hpa=925, height_agl_m=500, temperature_c=22.0),
        ProfilePoint(pressure_hpa=850, height_agl_m=1300, temperature_c=17.0),
    ]
    inv = find_inversions(pts)
    assert len(inv) == 1 and (inv[0].base_agl_m, inv[0].top_agl_m, inv[0].strength_c) == (2, 500, 4.0)
    assert find_inversions(list(reversed(pts[:1])) + [pts[2]]) == []


# ---------------------------------------------------------------- HTTP routes ----------------------------
@pytest.fixture
def api(client):
    def install(fake):
        client.app.dependency_overrides[get_weather_service] = lambda: make_service(fake)
        return client

    return install


def test_point_route_returns_normalized_forecast(api):
    r = api(FakeMeteo()).get("/api/weather/point", params={"lat": 28.6139, "lon": 77.209})
    assert r.status_code == 200
    body = r.json()
    assert body["coverage"]["timezone"] == "UTC" and body["times"][0].endswith("Z")
    assert body["source"]["attribution"]["text"] == "Weather data by Open-Meteo.com"


@pytest.mark.parametrize("params", [{"lat": 10, "lon": 77.2}, {"lat": 28.6, "lon": 100}, {"lat": "x", "lon": 77}, {}])
def test_coordinates_outside_ncr_or_invalid_are_rejected(api, params):
    r = api(FakeMeteo()).get("/api/weather/point", params=params)
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_error"


def test_upstream_outage_becomes_503_envelope_without_internal_detail(api):
    r = api(FakeMeteo(script=[503, 503, 503])).get("/api/weather/point", params={"lat": 28.6, "lon": 77.2})
    assert r.status_code == 503
    err = r.json()["error"]
    assert err["code"] == "service_unavailable" and "Open-Meteo" not in err["message"]


def test_grid_and_profile_routes_and_openapi(api):
    c = api(FakeMeteo())
    assert c.get("/api/weather/grid").status_code == 200
    assert c.get("/api/weather/profile", params={"lat": 28.6, "lon": 77.2}).status_code == 200
    paths = set(c.get("/openapi.json").json()["paths"])
    assert {"/api/weather/point", "/api/weather/grid", "/api/weather/profile"} <= paths


# ---------------------------------------------------------------- recent window + derived indicators -----
async def test_recent_window_ends_at_the_current_hour_and_adds_derived_indicators():
    fake = FakeMeteo()
    r = await make_service(fake).recent(28.61, 77.21, 6)
    assert [t.hour for t in r.times] == [1, 2, 3, 4, 5, 6] and r.coverage.hours == 6
    assert fake.calls[0]["past_days"] == "2" and fake.calls[0]["forecast_days"] == "1"
    vi = r.derived["ventilation_index"]
    # blh and wind both drift +0.1 per source hour: first window hour is source index 1
    assert vi.unit == "m²/s" and vi.values[0] == pytest.approx((900 + 0.1) * ((8 + 0.1) / 3.6), abs=0.1)
    assert "not a measurement" in vi.definition.lower()
    assert "hours_since_rain" in r.derived


async def test_recent_without_inputs_omits_the_derived_indicator_instead_of_guessing():
    def mutate(raw):
        del raw["hourly"]["boundary_layer_height"]

    r = await make_service(FakeMeteo(mutate=mutate)).recent(28.61, 77.21, 6)
    assert "ventilation_index" not in r.derived and "boundary_layer_height" in r.unavailable


def test_recent_route_validates_hours(api):
    c = api(FakeMeteo())
    assert c.get("/api/weather/recent", params={"lat": 28.6, "lon": 77.2, "hours": 6}).status_code == 200
    assert c.get("/api/weather/recent", params={"lat": 28.6, "lon": 77.2, "hours": 999}).status_code == 422
