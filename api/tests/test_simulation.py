"""Simulation runs: inputs, timestamps, freshness, reproducibility, scenarios, validation and the API. Fake wind provider, synthetic store."""

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from mlfakes import make_history

from app.core.config import get_settings
from app.twin.service import TwinService
from app.twin.simulation import DOMAIN, Scenario, SimulationError, SimulationService
from app.twin.transport import KNOWN_THRESHOLD

HOUR = timedelta(hours=1)
HOURS = 120


class FakeFields:
    """Stands in for the Open-Meteo lattice service: wind is a function of the frame index so alignment can be checked exactly."""

    def __init__(self, start: datetime, hours: int, u=lambda k: 2.0 + 0.01 * k, v=lambda k: 0.5, mode="forecast", blh=lambda k: 300.0 + 10 * k):
        self.start, self.hours, self.u, self.v, self.mode, self.blh = start, hours, u, v, mode, blh
        self.calls = 0
        self.nan_at: int | None = None

    async def fields(self, mode, past_days=2, forecast_days=3, start=None, end=None):
        self.calls += 1
        lats = np.linspace(28.1, 29.05, 8).round(4).tolist()
        lons = np.linspace(76.7, 77.8, 9).round(4).tolist()

        def cube(f):
            return [[[f(k)] * 9 for _ in range(8)] for k in range(self.hours)]

        u = cube(self.u)
        if self.nan_at is not None:
            u[self.nan_at][3][3] = None
        zero = cube(lambda k: 0.0)
        var = lambda vals: {"label": "x", "unit": "x", "values": vals, "available": True, "valid_fraction": 1.0}  # noqa: E731
        return {
            "mode": self.mode, "grid": {"lats": lats, "lons": lons, "rows": 8, "cols": 9}, "times": [(self.start + k * HOUR).strftime("%Y-%m-%dT%H:%M:%SZ") for k in range(self.hours)],
            "now_index": None,
            "variables": {"wind_u": var(u), "wind_v": var(cube(self.v)), "boundary_layer_height": var(cube(self.blh)), "pressure_msl": var(zero)},
            "source": {"provider": "fake lattice", "model_resolution": "test", "max_distance_from_requested_point_km": 1.0, "retrieved_at": "2026-01-01T00:00:00Z", "licence_note": ""},
            "notes": [],
        }


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    path = tmp_path_factory.mktemp("sim") / "history.sqlite"
    store, end = make_history(str(path), hours=HOURS, stations=12)
    start = end - (HOURS - 1) * HOUR
    return {"store": store, "start": start, "end": end}


@pytest.fixture
def twin(hist):
    return TwinService(hist["store"])


def make_service(hist, tmp_path=None, now=None, **kw):
    fields = FakeFields(hist["start"] - 24 * HOUR, HOURS + 24 * 3, **kw)
    return SimulationService(fields, store_dir=tmp_path, now=now or (lambda: hist["end"] + HOUR)), fields


@pytest.mark.asyncio
async def test_baseline_run_describes_itself_completely(twin, hist):
    svc, _ = make_service(hist)
    t0 = hist["start"] + 30 * HOUR
    run = await svc.run(twin, "transport", "pm25", hours=12, init_time=t0)
    assert run["execution"]["status"] == "completed" and run["execution"]["simulated_hours"] == 12 and run["execution"]["deterministic"] is True
    assert run["initialisation"] == t0.strftime("%Y-%m-%dT%H:%M:%SZ") and len(run["valid_times"]) == 13 and run["valid_times"][-1].startswith((t0 + 12 * HOUR).strftime("%Y-%m-%dT%H"))
    assert run["grid"]["rows"] == DOMAIN.rows and run["extent"]["south"] == DOMAIN.south and run["grid"]["dx_m"] > 1000
    assert run["model"]["name"] == "aerocast-passive-transport" and run["model"]["version"] and run["model"]["configuration"]["diffusivity_m2s"] == 50.0
    assert run["inputs"]["observations"]["n_stations"] == 12 and run["inputs"]["wind"]["frames"] == 13 and run["inputs"]["wind"]["provider"] == "fake lattice"
    assert run["freshness"]["status"] in ("fresh", "stale") and any("emission" in x for x in run["limitations"])
    assert len(run["concentration"]) == 13 and len(run["concentration"][0]) == DOMAIN.rows
    assert run["uncertainty"]["calibrated"] is False and "not a probability" in run["uncertainty"]["note"]
    assert run["mode"] == "transport" and "scenario" not in run


@pytest.mark.asyncio
async def test_same_inputs_give_the_same_run_id_and_identical_fields(twin, hist, tmp_path):
    t0 = hist["start"] + 40 * HOUR
    a, _ = make_service(hist, tmp_path / "a")
    b, _ = make_service(hist, tmp_path / "b")
    r1 = await a.run(twin, "transport", "pm25", 10, t0)
    r2 = await b.run(twin, "transport", "pm25", 10, t0)  # a different service instance with no cache
    assert r1["run_id"] == r2["run_id"] and r1["concentration"] == r2["concentration"] and r1["spread"] == r2["spread"]
    r3 = await a.run(twin, "transport", "pm25", 10, t0)
    assert r3["concentration"] == r1["concentration"]
    assert a.get(r1["run_id"])["run_id"] == r1["run_id"]  # stored and retrievable by id
    assert make_service(hist, tmp_path / "a")[0].get(r1["run_id"]) is not None  # and survives a restart (read from disk)
    other = await a.run(twin, "transport", "pm25", 10, t0 + HOUR)
    assert other["run_id"] != r1["run_id"]


@pytest.mark.asyncio
async def test_wind_frames_are_aligned_to_the_initialisation_hour(twin, hist):
    svc, fields = make_service(hist, u=lambda k: float(k), v=lambda k: 0.0)
    t0 = hist["start"] + 20 * HOUR
    run = await svc.run(twin, "transport", "pm25", 8, t0)
    k0 = int((t0 - fields.start) / HOUR)
    assert run["inputs"]["wind"]["first_frame"] == t0.strftime("%Y-%m-%dT%H:%M:%SZ")
    assert run["wind"]["u"][0][0][0] == float(k0) and run["wind"]["u"][8][0][0] == float(k0 + 8)  # frame k of the run is hour t0 + k of the wind


@pytest.mark.asyncio
async def test_initial_condition_without_observations_is_refused(twin, hist):
    svc, _ = make_service(hist)
    with pytest.raises(SimulationError) as e:
        await svc.run(twin, "transport", "pm25", 12, hist["start"] - 10 * HOUR)  # before any observation exists
    assert e.value.code in ("no_initial_observations", "twin_data_unavailable") or "stations" in e.value.message


@pytest.mark.asyncio
async def test_missing_wind_values_stop_the_run_and_short_wind_limits_it(twin, hist):
    svc, fields = make_service(hist)
    t_a = hist["start"] + 20 * HOUR
    fields.nan_at = int((t_a - fields.start) / HOUR) + 5  # a missing value five hours into the simulated window
    with pytest.raises(SimulationError) as e:
        await svc.run(twin, "transport", "pm25", 12, t_a)
    assert e.value.code == "wind_unavailable"
    svc2, f2 = make_service(hist)
    t0 = hist["start"] + 30 * HOUR
    f2.hours = int((t0 - f2.start) / HOUR) + 9  # wind exists for 8 hours after t0 only
    run = await svc2.run(twin, "transport", "pm25", 24, t0)
    assert run["execution"]["status"] == "limited" and run["execution"]["simulated_hours"] == 8 and run["execution"]["requested_hours"] == 24


@pytest.mark.asyncio
async def test_staleness_is_stated_and_uses_the_injected_clock(twin, hist):
    t0 = hist["start"] + 30 * HOUR
    old = SimulationService(FakeFields(hist["start"] - 24 * HOUR, HOURS + 72), now=lambda: t0 + 3 * HOUR)
    fresh = await old.run(twin, "transport", "pm25", 6, t0)
    assert fresh["freshness"]["status"] == "fresh" and fresh["freshness"]["observation_age_hours"] == 3.0
    late = SimulationService(FakeFields(hist["start"] - 24 * HOUR, HOURS + 72), now=lambda: t0 + 50 * HOUR)
    stale = await late.run(twin, "transport", "pm25", 6, t0)
    assert stale["freshness"]["status"] == "stale" and "describes the past" in stale["freshness"]["note"]


@pytest.mark.asyncio
async def test_live_run_uses_the_newest_dense_hour_and_changes_only_with_new_inputs(twin, hist):
    svc, _ = make_service(hist)
    a = await svc.run(twin, "live", "pm25", 12)
    b = await svc.run(twin, "live", "pm25", 12)
    assert a["live"] is True and a["run_id"] == b["run_id"]  # nothing new arrived: same run
    dense = twin.status()["periods"]["pm25"]["dense_to"]
    assert a["initialisation"] == dense
    svc2, _ = make_service(hist, u=lambda k: 5.0)  # a new wind-model output
    c = await svc2.run(twin, "live", "pm25", 12)
    assert c["run_id"] != a["run_id"]


@pytest.mark.asyncio
async def test_scenario_is_hypothetical_returns_the_baseline_and_the_difference(twin, hist):
    svc, _ = make_service(hist)
    t0 = hist["start"] + 30 * HOUR
    with pytest.raises(SimulationError):
        await svc.run(twin, "scenario", "pm25", 12, t0)  # nothing modified
    with pytest.raises(SimulationError):
        await svc.run(twin, "transport", "pm25", 12, t0, Scenario(wind_scale=2.0))  # scenario parameters need scenario mode
    with pytest.raises(SimulationError):
        await svc.run(twin, "scenario", "pm25", 12, t0, Scenario(wind_scale=9.0))  # outside the allowed range
    sc = await svc.run(twin, "scenario", "pm25", 12, t0, Scenario(wind_scale=2.0, loss_per_hour=0.2))
    assert sc["mode"] == "scenario" and sc["scenario"]["label"] == "Hypothetical" and set(sc["scenario"]["changed"]) == {"wind_scale", "loss_per_hour"}
    assert "not predictions" in sc["scenario"]["statement"] and "spread" not in sc
    base = np.array([[[np.nan if x is None else x for x in r] for r in f] for f in sc["baseline_concentration"]])
    cur = np.array([[[np.nan if x is None else x for x in r] for r in f] for f in sc["concentration"]])
    diff = np.array([[[np.nan if x is None else x for x in r] for r in f] for f in sc["difference"]])
    ok = np.isfinite(base) & np.isfinite(cur)
    assert np.allclose((cur - base)[ok], diff[ok], atol=0.11)  # rounding to 0.1 only
    baseline_run = await svc.run(twin, "transport", "pm25", 12, t0)
    assert baseline_run["concentration"][0] == sc["concentration"][0]  # same initial field; they differ only afterwards
    assert any("hypothetical" in x.lower() for x in sc["limitations"])


@pytest.mark.asyncio
async def test_validation_reports_persistence_and_a_withheld_station_test(twin, hist):
    svc, _ = make_service(hist, u=lambda k: 0.2, v=lambda k: 0.0)  # a slow wind keeps the small station cluster inside the known region
    t0 = hist["start"] + 40 * HOUR
    run = await svc.run(twin, "transport", "pm25", 12, t0)
    v = run["validation"]
    assert v["available"] and v["all_stations"]["summary"]["persistence_mae"] is not None and "beats_persistence" in v["all_stations"]["summary"]
    assert v["withheld_stations"]["stations_withheld"] >= 3 and v["withheld_stations"]["summary"] is not None
    assert v["verdict"].startswith("On this window the simulation")
    first = v["all_stations"]["per_lead"][0]
    assert first["lead_hours"] == 0 and first["persistence_mae"] == 0.0
    late = await svc.run(twin, "transport", "pm25", 12, hist["end"] - 3 * HOUR, validate=True)
    assert late["validation"]["available"] is False or late["validation"]["all_stations"]["per_lead"]


@pytest.mark.asyncio
async def test_unknown_cells_in_the_result_are_null_and_known_fraction_never_exceeds_the_initial(twin, hist):
    svc, _ = make_service(hist, u=lambda k: 4.0, v=lambda k: 0.0)
    run = await svc.run(twin, "transport", "pm25", 24, hist["start"] + 30 * HOUR)
    kf = run["known_fraction"]
    assert kf[0] > 0 and all(b <= a + 1e-9 for a, b in zip(kf, kf[1:]))  # inflow only removes knowledge
    assert any(x is None for row in run["concentration"][-1] for x in row)
    assert KNOWN_THRESHOLD == 0.5


def test_estimate_validation_beats_or_loses_to_the_mean_and_says_which(twin, hist):
    out = twin.validate_estimates("pm25", hist["start"] + 10 * HOUR, hist["start"] + 60 * HOUR, 12)
    assert out["hours_used"] >= 6 and out["predictions"] > 20 and out["idw"]["mae"] >= 0 and "baseline_mean_of_other_stations" in out
    assert isinstance(out["beats_baseline"], bool) and "Leave-one-out" in out["note"]


def test_api_validates_inputs_and_reports_unknown_runs(client, hist, monkeypatch):
    monkeypatch.setenv("ML_HISTORY_DB", hist["store"].path)
    get_settings.cache_clear()
    assert client.post("/api/twin/simulations", json={"mode": "bogus", "pollutant": "pm25", "hours": 12}).status_code == 422
    assert client.post("/api/twin/simulations", json={"mode": "transport", "pollutant": "pm25", "hours": 2}).status_code == 422
    assert client.get("/api/twin/simulations/doesnotexist").status_code == 404
    assert client.get("/api/twin/simulations/../etc").status_code in (404, 422)
    r = client.get("/api/twin/validation/estimates", params={"pollutant": "pm25", "from": (hist["start"] + 10 * HOUR).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                              "to": (hist["start"] + 50 * HOUR).strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": 10})
    assert r.status_code == 200 and r.json()["hours_used"] >= 3


def test_vectorised_idw_equals_the_shared_scalar_method(twin, hist):
    from app.twin.service import idw_grid, idw_point

    pts = [(r["lat"], r["lon"], r["value"], r["station_id"]) for r in twin._hour_values("pm25", hist["start"] + 30 * HOUR)]
    lats, lons = np.linspace(28.55, 28.75, 7), np.linspace(77.15, 77.35, 6)
    vec, n = idw_grid(pts, lats, lons)
    for i, la in enumerate(lats):
        for j, lo in enumerate(lons):
            v, cnt, _ = idw_point(pts, float(la), float(lo))
            assert cnt == n[i, j]
            if v is None:
                assert np.isnan(vec[i, j])
            else:
                assert vec[i, j] == pytest.approx(v, rel=1e-9)
