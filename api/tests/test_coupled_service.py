"""Coupled runs: real-shaped inputs in, multi-species fields, validation and honest failure out. Synthetic store, fake weather lattice."""

from datetime import datetime, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient
from histfakes import add_raw, add_sensor, isoz
from mlfakes import make_history

from app.history import clean
from app.twin.coupled_run import CoupledService, process_catalogue
from app.twin.service import TwinService
from app.twin.simulation import DOMAIN, SimulationError

HOUR = timedelta(hours=1)
HOURS = 120
EXTRA = {"pm10": (2000, lambda x, i, s: 1.6 * x + 12), "no2": (3000, lambda x, i, s: 30 + 0.2 * x + 3 * np.sin(i / 5 + s)),
         "o3": (4000, lambda x, i, s: 55 + 10 * np.sin(i / 7 + s)), "so2": (5000, lambda x, i, s: 12 + 2 * np.cos(i / 6 + s))}


class FakeFields:
    def __init__(self, start: datetime, hours: int, rain=lambda k: 0.0, sw=lambda k: 400.0, with_extra=True):
        self.start, self.hours, self.rain, self.sw, self.with_extra = start, hours, rain, sw, with_extra
        self.nan_rain_at: int | None = None

    async def fields(self, mode, past_days=2, forecast_days=3, start=None, end=None, levels=False):
        lats = np.linspace(28.1, 29.05, 14).round(4).tolist()
        lons = np.linspace(76.7, 77.8, 11).round(4).tolist()

        def cube(f):
            return [[[f(k)] * 11 for _ in range(14)] for k in range(self.hours)]

        rain = cube(self.rain)
        if self.nan_rain_at is not None:
            rain[self.nan_rain_at][2][2] = None
        var = lambda vals: {"label": "x", "unit": "x", "values": vals, "available": True, "valid_fraction": 1.0}  # noqa: E731
        variables = {"wind_u": var(cube(lambda k: 0.8)), "wind_v": var(cube(lambda k: 0.2)), "boundary_layer_height": var(cube(lambda k: 400.0)),
                     "pressure_msl": var(cube(lambda k: 0.0))}
        if self.with_extra:
            variables["precipitation"] = var(rain)
            variables["shortwave_radiation"] = var(cube(self.sw))
        return {
            "mode": "forecast", "grid": {"lats": lats, "lons": lons, "rows": 14, "cols": 11}, "times": [(self.start + k * HOUR).strftime("%Y-%m-%dT%H:%M:%SZ") for k in range(self.hours)],
            "now_index": None, "variables": variables,
            "source": {"provider": "fake lattice", "model_resolution": "test", "max_distance_from_requested_point_km": 1.0, "retrieved_at": "2026-01-01T00:00:00Z", "licence_note": ""},
            "notes": [],
        }


@pytest.fixture(scope="module")
def hist(tmp_path_factory):
    path = tmp_path_factory.mktemp("cpl") / "history.sqlite"
    store, end = make_history(str(path), hours=HOURS, stations=12)
    start = end - (HOURS - 1) * HOUR
    rng = np.random.default_rng(5)
    base = {r["station_id"]: 60.0 for r in store.query("select distinct station_id from stations")}
    for sid in base:
        for pol, (sensor0, f) in EXTRA.items():
            add_sensor(store, sensor0 + sid, sid, pol, first="2020-01-01T00:00:00Z", last="2099-01-01T00:00:00Z")
            for i in range(HOURS):
                t = start + i * HOUR
                v = float(max(1.0, f(60.0 + rng.normal(0, 8), i, sid % 5)))
                add_raw(store, sensor0 + sid, sid, pol, isoz(t + timedelta(minutes=30)), round(v, 1))
    store.commit()
    clean.clean_air(store)
    return {"store": store, "start": start, "end": end}


@pytest.fixture
def twin(hist):
    return TwinService(hist["store"])


def service(hist, tmp_path=None, **kw):
    fields = FakeFields(hist["start"] - 24 * HOUR, HOURS + 24 * 3, **kw)
    return CoupledService(fields, store_dir=tmp_path, now=lambda: hist["end"] + HOUR), fields


@pytest.mark.asyncio
async def test_run_returns_every_species_the_couplings_and_a_passive_comparison(twin, hist):
    svc, _ = service(hist, rain=lambda k: 2.0)
    t0 = hist["start"] + 30 * HOUR
    run = await svc.run(twin, hours=12, init_time=t0, focus="pm25")
    assert run["model"]["name"] == "aerocast-coupled-transport" and run["model"]["validated"] is False
    assert {p["key"] for p in run["model"]["processes"] if p["enabled"]} == {"deposition", "washout", "oxidation"}
    assert {p["key"] for p in run["model"]["processes"] if not p["enabled"]} == {"ventilation", "dilution"}
    assert set(run["species"]) >= {"pm25", "pm_coarse", "no2", "o3", "so2", "pm10", "ox_ppb"}
    pm10, pm25 = np.array([[np.nan if x is None else x for x in r] for r in run["species"]["pm10"]["frames"][0]]), np.array([[np.nan if x is None else x for x in r] for r in run["species"]["pm25"]["frames"][0]])
    ok = np.isfinite(pm10) & np.isfinite(pm25)
    assert ok.any() and (pm10[ok] >= pm25[ok] - 0.11).all()  # PM10 never below PM2.5 (0.1 is the rounding)
    assert len(run["valid_times"]) == 13 and len(run["species"]["pm25"]["frames"]) == 13 and run["grid"]["rows"] == DOMAIN.rows
    assert run["passive_focus"] is not None and run["difference_focus"] is not None and run["focus"] == "pm25"
    assert run["budget"]["pm25"]["washout"] > 0 and run["budget"]["pm25"]["deposition"] > 0
    assert run["budget"]["so2"]["oxidation"] > 0 > run["budget"]["pm25"]["oxidation"]
    assert run["effect_of_couplings"]["pm25"]["coupled_mean_end"] != run["effect_of_couplings"]["pm25"]["passive_mean_end"]
    assert run["inputs"]["stations"]["per_species"]["pm25"] == 12 and "so2" in run["inputs"]["stations"]["species_initialised"]
    assert any("emission" in x.lower() for x in run["limitations"]) and run["model"]["not_modelled"]
    assert run["freshness"]["status"] in ("fresh", "stale") and run["source"] == "observations"


@pytest.mark.asyncio
async def test_with_no_couplings_the_coupled_field_is_the_passive_field(twin, hist):
    svc, _ = service(hist, rain=lambda k: 3.0)
    run = await svc.run(twin, hours=8, init_time=hist["start"] + 40 * HOUR, processes=[], validate=False)
    diff = np.array([[[np.nan if x is None else x for x in r] for r in f] for f in run["difference_focus"]])
    assert np.nanmax(np.abs(diff)) < 1e-6


@pytest.mark.asyncio
async def test_rain_lowers_particles_and_leaves_ozone_alone(twin, hist):
    dry, _ = service(hist, rain=lambda k: 0.0)
    wet, _ = service(hist, rain=lambda k: 6.0)
    t0 = hist["start"] + 50 * HOUR
    d = await dry.run(twin, hours=12, init_time=t0, processes=["washout"], validate=False)
    w = await wet.run(twin, hours=12, init_time=t0, processes=["washout"], validate=False)
    assert w["effect_of_couplings"]["pm25"]["coupled_mean_end"] < d["effect_of_couplings"]["pm25"]["coupled_mean_end"]
    assert w["effect_of_couplings"]["o3"]["coupled_mean_end"] == pytest.approx(d["effect_of_couplings"]["o3"]["coupled_mean_end"])
    assert d["budget"]["pm25"]["washout"] == 0 and w["budget"]["pm25"]["washout"] > 0


@pytest.mark.asyncio
async def test_validation_is_out_of_sample_and_compares_with_persistence_and_passive(twin, hist):
    svc, _ = service(hist)
    run = await svc.run(twin, hours=12, init_time=hist["start"] + 30 * HOUR)
    v = run["validation"]
    assert v["available"] is True and "withheld" in v["against"] and v["verdict"]
    d = v["per_species"]["pm25"]
    assert d["available"] and d["stations_withheld"] >= 3
    assert {"mae_coupled", "mae_passive", "mae_persistence", "skill_vs_persistence", "skill_vs_passive", "beats_persistence", "beats_passive"} <= set(d)
    assert "persistence" in v["baselines"] and "passive" in v["baselines"]


@pytest.mark.asyncio
async def test_same_inputs_same_run_and_a_restart_can_read_it_back(twin, hist, tmp_path):
    t0 = hist["start"] + 45 * HOUR
    a, _ = service(hist, tmp_path)
    r1 = await a.run(twin, hours=8, init_time=t0, validate=False)
    b, _ = service(hist, tmp_path / "other")
    r2 = await b.run(twin, hours=8, init_time=t0, validate=False)
    assert r1["run_id"] == r2["run_id"] and r1["species"]["pm25"]["frames"] == r2["species"]["pm25"]["frames"]
    assert service(hist, tmp_path)[0].get(r1["run_id"])["run_id"] == r1["run_id"]
    other = await a.run(twin, hours=8, init_time=t0 + HOUR, validate=False)
    assert other["run_id"] != r1["run_id"]
    changed = await a.run(twin, hours=8, init_time=t0, params={"so2_oxidation_per_hour": 0.1}, validate=False)
    assert changed["run_id"] != r1["run_id"]


@pytest.mark.asyncio
async def test_missing_rain_or_radiation_stops_the_run_instead_of_assuming_dry_and_dark(twin, hist):
    svc, fields = service(hist, with_extra=False)
    with pytest.raises(SimulationError, match="precipitation or radiation"):
        await svc.run(twin, hours=8, init_time=hist["start"] + 30 * HOUR, validate=False)
    svc2, fields2 = service(hist)
    fields2.nan_rain_at = 24 + 30 + 3  # three hours into the run window (the fake lattice starts 24 h before the store)
    # a hole in the rain lattice is a hole in the input: the engine refuses it
    with pytest.raises(SimulationError):
        await svc2.run(twin, hours=8, init_time=hist["start"] + 30 * HOUR, validate=False)


@pytest.mark.asyncio
async def test_a_model_forecast_start_uses_the_given_values_and_says_where_they_came_from(twin, hist):
    svc, _ = service(hist)
    t0 = hist["start"] + 60 * HOUR
    stations = twin.stations("pm25")
    values = {"pm25": [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], "value": 100.0 + i} for i, s in enumerate(stations)],
              "pm10": [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"], "value": 190.0} for s in stations]}
    info = {"origin": "x", "lead_hours": 6, "model_version": "m", "note": "n"}
    run = await svc.run(twin, hours=6, init_time=t0, station_values=values, forecast_info=info, validate=False)
    assert run["source"] == "model_forecast" and run["forecast"]["lead_hours"] == 6
    first = [v for row in run["species"]["pm25"]["frames"][0] for v in row if v is not None]
    assert first and 99.0 <= min(first) and max(first) <= 112.0  # the field starts from the forecast values (100..111), not from observations
    assert {"no2", "o3", "so2"} <= set(run["inputs"]["stations"]["species_without_initial_state"])
    assert "no2" not in run["species"] and "so2" not in run["species"]  # not initialised: not shown, not invented


@pytest.mark.asyncio
async def test_bad_requests_are_refused(twin, hist):
    svc, _ = service(hist)
    t0 = hist["start"] + 30 * HOUR
    for kw, msg in [({"hours": 3}, "hours"), ({"processes": ["magic"]}, "unknown process"), ({"focus": "co"}, "focus"),
                    ({"params": {"diffusivity_m2s": 9999}}, "diffusivity"), ({"params": {"aloft_ratio": 2}}, "aloft"), ({"params": {"so2_oxidation_per_hour": 5}}, "oxidation")]:
        with pytest.raises(SimulationError, match=msg):
            await svc.run(twin, **{"hours": 8, "init_time": t0, "validate": False, **kw})


def test_catalogue_documents_every_process_and_what_is_not_modelled():
    c = process_catalogue()
    assert [p["key"] for p in c["processes"]] == ["ventilation", "dilution", "deposition", "washout", "oxidation"]
    assert c["default_processes"] == ["deposition", "washout", "oxidation"]
    assert "evaluation" in c  # the recorded hindcast travels with the model description (None until it has been run)
    assert all(p["basis"] and p["limits"] and p["what"] for p in c["processes"])
    assert any("emission" in x.lower() for x in c["not_modelled"])
    assert c["defaults"]["v_dep_cm_s"]["pm_coarse"] > c["defaults"]["v_dep_cm_s"]["pm25"]


def test_endpoints_validate_and_serve_the_catalogue(client):
    assert client.get("/api/twin/coupled/config").status_code == 200
    assert client.get("/api/twin/coupled/not-a-run!").status_code == 422
    assert client.get("/api/twin/coupled/aaaaaaaaaaaaaaaa").status_code == 404
    r = client.post("/api/twin/coupled", json={"hours": 2})
    assert r.status_code in (422, 503)  # 422 for the body; 503 first when this test client has no historical store
    r = client.post("/api/twin/coupled", json={"source": "model_forecast", "hours": 12, "init_time": "2026-01-01T00:00:00"})
    assert r.status_code in (422, 503)
