"""Simulation runs of the digital twin: build inputs from real data, run the transport engine, validate, and describe the run.

Modes (each result says which it is, and none is dressed up as another):
  transport   observed air at the initialisation hour, carried by the weather-model wind (baseline physics, no sources, no chemistry)
  scenario    the same engine with explicitly modified parameters (wind scale/rotation, diffusivity, first-order loss, column dilution);
              hypothetical by construction and returned with the unmodified baseline and the difference
  live        a transport run initialised at the newest hour with enough observations; it is re-created only when the observations or
              the wind data change (the run id is a hash of the inputs), and it says when its initial conditions are stale

Every run carries: initialisation time, valid times, extent and grid resolution, input timestamps and freshness, model and
configuration version, execution status, limitations, and (where later observations exist) a hindcast validation against them
with a persistence baseline and a withheld-station evaluation.
"""

import asyncio
import hashlib
import json
import math
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.history.ingest_air import iso
from app.history.units import POLLUTANTS
from app.services.weather_fields import FIELDS, WeatherFieldsService
from app.twin.service import HOUR, IDW_MIN_STATIONS, IDW_POWER, IDW_RADIUS_KM, TwinDataUnavailable, TwinService, idw_grid, idw_point, utc_floor
from app.twin.transport import KNOWN_THRESHOLD, Grid, MemberParams, regrid_bilinear, rotate_wind, run_transport

MODEL_NAME = "aerocast-passive-transport"
MODEL_VERSION = "1.0.0"
DOMAIN = Grid(south=28.1, north=29.05, west=76.7, east=77.8, rows=40, cols=40)
MIN_HOURS, MAX_HOURS = 6, 48
STALE_OBS_HOURS = 6.0
WITHHOLD_MOD = 5  # stations whose id % 5 == 0 are withheld in the out-of-sample evaluation (deterministic)
MODES = ("transport", "scenario", "live")
DEFAULT_K = 50.0


class SimulationError(Exception):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 422):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


@dataclass(frozen=True)
class Scenario:
    wind_scale: float = 1.0
    wind_rotation_deg: float = 0.0
    diffusivity_m2s: float = DEFAULT_K
    loss_per_hour: float = 0.0
    mixing_mode: str = "none"
    aloft_ratio: float = 0.0

    def check(self) -> None:
        if not 0.25 <= self.wind_scale <= 2.0:
            raise SimulationError("wind_scale must be between 0.25 and 2")
        if not -90.0 <= self.wind_rotation_deg <= 90.0:
            raise SimulationError("wind_rotation_deg must be between -90 and 90")
        if not 1.0 <= self.diffusivity_m2s <= 500.0:
            raise SimulationError("diffusivity_m2s must be between 1 and 500")
        if not 0.0 <= self.loss_per_hour <= 1.0:
            raise SimulationError("loss_per_hour must be between 0 and 1")
        if self.mixing_mode not in ("none", "column_dilution"):
            raise SimulationError("mixing_mode must be 'none' or 'column_dilution'")
        if not 0.0 <= self.aloft_ratio <= 1.0:
            raise SimulationError("aloft_ratio must be between 0 and 1")

    @property
    def is_baseline(self) -> bool:
        return self == Scenario()

    def member(self) -> MemberParams:
        return MemberParams(self.diffusivity_m2s, self.wind_scale, self.wind_rotation_deg, self.loss_per_hour, self.mixing_mode, self.aloft_ratio)


def _round(a: np.ndarray, nd: int = 1) -> list:
    return np.where(np.isnan(a), None, np.round(a, nd)).tolist()


def _digest(*arrays: np.ndarray) -> str:
    h = hashlib.sha256()
    for a in arrays:
        h.update(np.ascontiguousarray(np.nan_to_num(np.asarray(a, dtype=float), nan=-9999.0)).tobytes())
    return h.hexdigest()[:16]


class SimulationService:
    def __init__(self, fields: WeatherFieldsService, store_dir: str | Path | None = None, now=None):
        self._fields = fields
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._dir = Path(store_dir) if store_dir else None
        self._runs: dict[str, dict] = {}

    # ------------------------------------------------------------------------------------------ public
    def get(self, run_id: str) -> dict | None:
        if run_id in self._runs:
            return self._runs[run_id]
        if self._dir and (self._dir / f"{run_id}.json").exists():
            try:
                run = json.loads((self._dir / f"{run_id}.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            self._runs[run_id] = run
            return run
        return None

    async def run(self, twin: TwinService, mode: str, pollutant: str, hours: int = 24, init_time: datetime | None = None,
                  scenario: Scenario | None = None, validate: bool = True) -> dict:
        if mode not in MODES:
            raise SimulationError(f"mode must be one of {', '.join(MODES)}")
        if pollutant not in POLLUTANTS:
            raise SimulationError("unknown pollutant")
        if not MIN_HOURS <= hours <= MAX_HOURS:
            raise SimulationError(f"hours must be between {MIN_HOURS} and {MAX_HOURS}")
        scenario = scenario or Scenario()
        scenario.check()
        if mode == "scenario" and scenario.is_baseline:
            raise SimulationError("a scenario needs at least one modified parameter; use mode 'transport' for the baseline")
        if mode != "scenario" and not scenario.is_baseline:
            raise SimulationError("scenario parameters are only accepted in mode 'scenario'")

        status = await asyncio.to_thread(twin.status)
        period = status["periods"].get(pollutant)
        if not period:
            raise SimulationError("the store has no usable observations of this pollutant", "twin_data_unavailable", 503)
        if mode == "live" or init_time is None:
            t0 = datetime.fromisoformat(period["dense_to"].replace("Z", "+00:00"))
        else:
            if init_time.tzinfo is None:
                raise SimulationError("init_time must include a UTC offset")
            t0 = utc_floor(init_time)
        obs = await asyncio.to_thread(twin._hour_values, pollutant, t0)
        if len(obs) < IDW_MIN_STATIONS + 1:
            raise SimulationError(f"fewer than three stations observed {pollutant} at {iso(t0)}; choose another initialisation hour", "no_initial_observations")

        wind = await self._wind(t0, hours)
        n_hours = wind["hours"]
        run_key = {
            "model": MODEL_NAME, "version": MODEL_VERSION, "mode": "scenario" if mode == "scenario" else "transport", "pollutant": pollutant, "init": iso(t0),
            "hours": n_hours, "scenario": asdict(scenario), "domain": asdict(DOMAIN),
            "inputs": {"obs": _digest(np.array([[o["station_id"], o["value"]] for o in sorted(obs, key=lambda o: o["station_id"])])), "wind": _digest(wind["u"], wind["v"], wind["blh"])},
            "validate": bool(validate),
        }
        run_id = hashlib.sha256(json.dumps(run_key, sort_keys=True).encode()).hexdigest()[:16]
        cached = self.get(run_id)
        if cached:
            # the same inputs give the same run; only its relationship to "now" (staleness) is recomputed, and the live flag is the caller's
            return {**cached, "live": mode == "live", "freshness": self._freshness(t0, wind, cached["inputs"]["observations"]["n_stations"])}
        started = self._now()
        t_start = time.perf_counter()
        body = await asyncio.to_thread(self._execute, twin, run_key, mode, pollutant, t0, n_hours, obs, wind, scenario, validate)
        run = {
            "run_id": run_id, "mode": "scenario" if mode == "scenario" else "transport", "live": mode == "live", "pollutant": pollutant, "unit": "µg/m³",
            "model": {"name": MODEL_NAME, "version": MODEL_VERSION, "scheme": "2-D advection-diffusion, MUSCL minmod advective form, explicit Euler, open boundaries",
                      "configuration": run_key["scenario"], "baseline_diffusivity_m2s": DEFAULT_K},
            "initialisation": iso(t0), "valid_times": [iso(t0 + k * HOUR) for k in range(n_hours + 1)],
            "extent": {"south": DOMAIN.south, "north": DOMAIN.north, "west": DOMAIN.west, "east": DOMAIN.east},
            "grid": {"rows": DOMAIN.rows, "cols": DOMAIN.cols, "dx_m": round(DOMAIN.dx_m), "dy_m": round(DOMAIN.dy_m), "lats": [round(x, 4) for x in DOMAIN.lats.tolist()],
                     "lons": [round(x, 4) for x in DOMAIN.lons.tolist()]},
            "execution": {"status": "completed" if n_hours == hours else "limited", "requested_hours": hours, "simulated_hours": n_hours, "started_at": iso(started),
                          "duration_ms": round((time.perf_counter() - t_start) * 1000), **body.pop("execution")},
            "inputs": {"observations": body.pop("obs_info"), "wind": wind["info"]},
            **body,
        }
        run["freshness"] = self._freshness(t0, wind, run["inputs"]["observations"]["n_stations"])
        self._runs[run_id] = run
        if len(self._runs) > 40:
            self._runs.pop(next(iter(self._runs)))
        if self._dir:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                (self._dir / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
            except OSError:
                pass
        return run

    # ------------------------------------------------------------------------------------------ inputs
    def _freshness(self, t0: datetime, wind: dict, n_stations: int) -> dict:
        age = (self._now() - t0).total_seconds() / 3600.0
        return {
            "observation_age_hours": round(age, 1), "observations_stale": age > STALE_OBS_HOURS, "stale_after_hours": STALE_OBS_HOURS,
            "wind_source": wind["info"]["mode"], "wind_retrieved_at": wind["info"]["retrieved_at"],
            "status": "stale" if age > STALE_OBS_HOURS else "fresh",
            "note": (f"The initial observations are {age:.0f} h old (limit {STALE_OBS_HOURS:.0f} h), so this run describes the past, not the present." if age > STALE_OBS_HOURS
                     else "Initial observations are recent."),
        }

    async def _wind(self, t0: datetime, hours: int) -> dict:
        now = self._now()
        age_days = (now - t0).total_seconds() / 86400.0
        try:
            if age_days <= 6.5 and t0 <= now + timedelta(days=2):
                f = await self._fields.fields("forecast", past_days=7, forecast_days=3)
            else:
                end = (t0 + timedelta(hours=hours)).date()
                if end >= now.date():
                    end = now.date() - timedelta(days=1)
                if end < t0.date():
                    raise SimulationError("no wind data cover that initialisation time", "wind_unavailable", 503)
                f = await self._fields.fields("historical", start=t0.date(), end=end)
        except SimulationError:
            raise
        except Exception as exc:  # noqa: BLE001 - surfaced as an unavailable input, never a guess
            raise SimulationError(f"wind data are unavailable ({type(exc).__name__})", "wind_unavailable", 503) from exc
        times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in f["times"]]
        if t0 not in times:
            raise SimulationError("the wind data do not contain the initialisation hour", "wind_unavailable", 503)
        i0 = times.index(t0)
        avail = len(times) - 1 - i0
        n = min(hours, avail)
        if n < MIN_HOURS:
            raise SimulationError("fewer than six hours of wind data follow the initialisation hour", "wind_unavailable", 503)
        sl = slice(i0, i0 + n + 1)

        def cube(key: str) -> np.ndarray:
            if key not in f["variables"]:  # an optional input (rain, radiation): absent means unknown, and the models that need it say so
                return np.full((n + 1, len(f["grid"]["lats"]), len(f["grid"]["lons"])), np.nan)
            return np.array([[[np.nan if x is None else x for x in row] for row in frame] for frame in f["variables"][key]["values"][sl]], dtype=float)

        u, v = cube("wind_u"), cube("wind_v")
        blh = cube("boundary_layer_height")
        precip, sw = cube("precipitation"), cube("shortwave_radiation")  # used by the coupled model; the passive engine ignores them
        if not (np.isfinite(u).all() and np.isfinite(v).all()):
            raise SimulationError("the wind field has missing values in the simulated window; the engine does not fill them", "wind_unavailable", 503)
        return {
            "u": u, "v": v, "blh": blh, "precip": precip, "sw": sw, "hours": n, "lats": np.array(f["grid"]["lats"]), "lons": np.array(f["grid"]["lons"]),
            "info": {"provider": f["source"]["provider"], "mode": f["mode"], "resolution": f["source"]["model_resolution"], "retrieved_at": f["source"]["retrieved_at"],
                     "first_frame": iso(t0), "last_frame": iso(t0 + n * HOUR), "frames": n + 1, "time_interpolation": "linear between hourly frames",
                     "space_interpolation": "bilinear from the 0.14 degree lattice to the simulation grid",
                     "blh_available": bool(np.isfinite(blh).all())},
        }

    # ------------------------------------------------------------------------------------------ execution
    def _initial(self, obs: list[dict], exclude: set[int] | None = None) -> tuple[np.ndarray, np.ndarray, int]:
        pts = [(o["lat"], o["lon"], o["value"], o["station_id"]) for o in obs if not exclude or o["station_id"] not in exclude]
        if not pts:
            return np.zeros((DOMAIN.rows, DOMAIN.cols)), np.zeros((DOMAIN.rows, DOMAIN.cols), dtype=bool), 0
        vals, _ = idw_grid(pts, DOMAIN.lats, DOMAIN.lons)
        known = np.isfinite(vals)
        return np.where(known, vals, 0.0), known, len(pts)

    def _members(self, scenario: Scenario, ensemble: bool) -> tuple[list[MemberParams], list[str]]:
        base = scenario.member()
        if not ensemble:
            return [base], ["configured"]
        k = base.diffusivity_m2s
        return (
            [base, MemberParams(k * 0.5, 1.0, 0.0), MemberParams(k * 2.0, 1.0, 0.0), MemberParams(k, 1.0, +20.0), MemberParams(k, 1.0, -20.0)],
            ["baseline", "diffusivity x0.5", "diffusivity x2", "wind turned +20 deg", "wind turned -20 deg"],
        )

    def _regrid_winds(self, wind: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray | None]:
        u = regrid_bilinear(wind["u"], wind["lats"], wind["lons"], DOMAIN.lats, DOMAIN.lons)
        v = regrid_bilinear(wind["v"], wind["lats"], wind["lons"], DOMAIN.lats, DOMAIN.lons)
        blh = regrid_bilinear(wind["blh"], wind["lats"], wind["lons"], DOMAIN.lats, DOMAIN.lons) if np.isfinite(wind["blh"]).all() else None
        return u, v, blh

    def _execute(self, twin: TwinService, key: dict, mode: str, pollutant: str, t0: datetime, hours: int, obs: list[dict], wind: dict,
                 scenario: Scenario, validate: bool) -> dict:
        u, v, blh = self._regrid_winds(wind)
        if scenario.mixing_mode == "column_dilution" and blh is None:
            raise SimulationError("column dilution needs boundary-layer height, which is missing in the wind data", "wind_unavailable", 503)
        c0, known0, n_init = self._initial(obs)
        if not known0.any():
            raise SimulationError("no grid cell has two or more stations within the interpolation radius")
        scen = mode == "scenario"
        members, labels = self._members(scenario, ensemble=not scen)
        if scen:  # the unmodified baseline rides along as member 1 so the difference is computed from the same arrays
            members, labels = [scenario.member(), MemberParams(DEFAULT_K)], ["scenario", "baseline"]
        res = run_transport(DOMAIN, c0, known0, u, v, members, blh_frames=blh)
        C = res.concentration  # (members, T, rows, cols)
        main = C[0]
        out: dict = {
            "execution": {"engine_steps": res.steps, "dt_seconds_min": round(res.dt_min_s, 1), "dt_seconds_max": round(res.dt_max_s, 1),
                          "max_courant_number": round(res.max_courant, 2), "members": labels, "deterministic": True},
            "obs_info": {"time": iso(t0), "n_stations": n_init, "method": f"inverse-distance weighting (power {IDW_POWER:g}, radius {IDW_RADIUS_KM:g} km, at least {IDW_MIN_STATIONS} stations)",
                         "cells_with_initial_estimate": int(known0.sum()), "cells_total": int(known0.size)},
            "concentration": _round(main, 1),
            "known_fraction": [round(float(np.isfinite(main[k]).mean()), 3) for k in range(main.shape[0])],
            "wind": {"lats": [round(x, 4) for x in wind["lats"].tolist()], "lons": [round(x, 4) for x in wind["lons"].tolist()]},
        }
        # the wind actually used by the run (scenario modifications applied), on the lattice, for display and inspection
        lu, lv = wind["u"] * scenario.wind_scale, wind["v"] * scenario.wind_scale
        if scenario.wind_rotation_deg:
            lu, lv = rotate_wind(lu, lv, scenario.wind_rotation_deg)
        out["wind"]["u"], out["wind"]["v"] = _round(lu, 2), _round(lv, 2)
        if wind["info"]["blh_available"]:
            out["wind"]["boundary_layer_height_m"] = _round(wind["blh"], 0)

        if scen:
            base_c, delta = C[1], main - C[1]
            out["baseline_concentration"] = _round(base_c, 1)
            out["difference"] = _round(delta, 1)
            out["uncertainty"] = {"kind": "none for scenarios", "note": "A scenario is a what-if with explicitly changed parameters; no spread is computed for it."}
            out["scenario"] = {"parameters": asdict(scenario), "label": "Hypothetical",
                               "changed": {k: v2 for k, v2 in asdict(scenario).items() if v2 != asdict(Scenario())[k]},
                               "statement": "These are model results under changed parameters, not predictions of what will happen."}
            hind = base_c
        else:
            all_known = np.isfinite(C).all(axis=0)  # a spread is only reported where every member has a value
            hi = np.where(np.isfinite(C), C, -np.inf).max(axis=0)
            lo = np.where(np.isfinite(C), C, np.inf).min(axis=0)
            spread = np.where(all_known, hi - lo, np.nan)
            out["spread"] = _round(spread, 1)
            out["uncertainty"] = {
                "kind": "parameter sensitivity spread (max minus min over members)", "members": labels,
                "calibrated": False,
                "note": "How much the field changes when diffusivity is halved or doubled and when the wind direction is turned by 20 degrees either way. "
                        "It is not a probability and does not include errors of the observations, the interpolation or the wind model.",
            }
            hind = main
        # leave-one-out error of the initial estimate (the existing method, evaluated at the initialisation hour)
        pts = [(o["lat"], o["lon"], o["value"], o["station_id"]) for o in obs]
        errs = []
        for la, lo, val, sid in pts:
            est, _, _ = idw_point(pts, la, lo, exclude=sid)
            if est is not None:
                errs.append(est - val)
        out["initial_estimate_error"] = (None if not errs else {"n": len(errs), "mae": round(float(np.mean(np.abs(errs))), 2), "rmse": round(float(math.sqrt(np.mean(np.square(errs)))), 2),
                                                                 "bias": round(float(np.mean(errs)), 2), "stations_total": len(pts), "kind": "leave-one-out at the initialisation hour"})
        # observations at every valid time, for the map and for the comparison
        win = twin.window(pollutant, t0, t0 + hours * HOUR, weather=False)
        stations = win["stations"]
        vals = np.array([[np.nan if x is None else x for x in row] for row in win["values"]], dtype=float) if stations else np.zeros((0, hours + 1))
        out["stations"] = [{"station_id": s["station_id"], "name": s["name"], "lat": s["lat"], "lon": s["lon"]} for s in stations]
        out["observed"] = [[None if np.isnan(vals[s, k]) else round(float(vals[s, k]), 1) for s in range(len(stations))] for k in range(hours + 1)]
        out["observations_available_until"] = None
        have = [k for k in range(hours + 1) if np.isfinite(vals[:, k]).sum() >= 3] if len(stations) else []
        if have:
            out["observations_available_until"] = iso(t0 + max(have) * HOUR)
        if validate and len(stations) and len(have) > 1:
            out["validation"] = self._validate(pollutant, t0, hours, obs, stations, vals, hind, u, v, blh, scenario if not scen else Scenario())
        else:
            out["validation"] = {"available": False, "reason": "no later observations are stored for this window, so the run cannot be checked against them"}
        out["limitations"] = self._limitations(scenario, wind, scen)
        out["forecast_provider"] = {"role": "A separate trained-model forecast exists for single stations (Model forecast view); it is not an input to or an output of this physical transport run."}
        return out

    def _sample(self, frame: np.ndarray, lat: float, lon: float) -> float:
        """Bilinear value of a (rows, cols) frame at a point; NaN when outside the domain or any corner is unknown."""
        if not (DOMAIN.south <= lat <= DOMAIN.north and DOMAIN.west <= lon <= DOMAIN.east):
            return float("nan")
        fy = (lat - DOMAIN.south) / (DOMAIN.north - DOMAIN.south) * (DOMAIN.rows - 1)
        fx = (lon - DOMAIN.west) / (DOMAIN.east - DOMAIN.west) * (DOMAIN.cols - 1)
        r, c = min(int(fy), DOMAIN.rows - 2), min(int(fx), DOMAIN.cols - 2)
        ty, tx = fy - r, fx - c
        q = frame[r:r + 2, c:c + 2]
        w = np.array([[(1 - ty) * (1 - tx), (1 - ty) * tx], [ty * (1 - tx), ty * tx]])
        return float((q * w).sum()) if np.isfinite(q).all() else float("nan")

    def _score(self, frames: np.ndarray, stations: list[dict], vals: np.ndarray, rows: list[int], hours: int) -> dict:
        per_lead = []
        agg = {"sim": [], "persist": [], "obs": []}
        for k in range(0, hours + 1):
            e_sim, e_per = [], []
            for s in rows:
                o, o0 = vals[s, k], vals[s, 0]
                if np.isnan(o):
                    continue
                sim = self._sample(frames[k], stations[s]["lat"], stations[s]["lon"])
                if np.isnan(sim) or np.isnan(o0):
                    continue
                e_sim.append(sim - o)
                e_per.append(o0 - o)
            if len(e_sim) >= 3:
                per_lead.append({"lead_hours": k, "n": len(e_sim), "mae": round(float(np.mean(np.abs(e_sim))), 2), "rmse": round(float(math.sqrt(np.mean(np.square(e_sim)))), 2),
                                 "bias": round(float(np.mean(e_sim)), 2), "persistence_mae": round(float(np.mean(np.abs(e_per))), 2)})
                if k >= 1:
                    agg["sim"] += [abs(x) for x in e_sim]
                    agg["persist"] += [abs(x) for x in e_per]
        summary = None
        if agg["sim"]:
            ms, mp = float(np.mean(agg["sim"])), float(np.mean(agg["persist"]))
            summary = {"n": len(agg["sim"]), "mae": round(ms, 2), "persistence_mae": round(mp, 2), "skill_vs_persistence": None if mp == 0 else round(1 - ms / mp, 3),
                       "beats_persistence": ms < mp, "leads": "1 to %d h" % hours}
        return {"per_lead": per_lead, "summary": summary}

    def _validate(self, pollutant, t0, hours, obs, stations, vals, frames, u, v, blh, scenario) -> dict:
        all_rows = list(range(len(stations)))
        full = self._score(frames, stations, vals, all_rows, hours)
        withheld_ids = {s["station_id"] for s in stations if s["station_id"] % WITHHOLD_MOD == 0}
        out: dict = {"available": True, "against": "later stored observations at the stations",
                     "all_stations": {**full, "note": "These stations also supplied the initial field, so lead 0 is not independent; later leads are a hindcast."}}
        if len(withheld_ids) >= 3:
            c0, known0, n = self._initial(obs, exclude=withheld_ids)
            if known0.any():
                res = run_transport(DOMAIN, c0, known0, u, v, [scenario.member()], blh_frames=blh)
                rows = [i for i, s in enumerate(stations) if s["station_id"] in withheld_ids]
                out["withheld_stations"] = {**self._score(res.concentration[0], stations, vals, rows, hours),
                                            "stations_withheld": len(rows), "stations_used_for_initial_field": n,
                                            "note": "Stations with id divisible by 5 were left out of the initial field and scored only here: an out-of-sample test of the spatial estimate (lead 0) and of the transport (later leads)."}
        sm = (out.get("withheld_stations") or {}).get("summary") or out["all_stations"].get("summary")
        if sm is None:
            out["verdict"] = "Too few station-hours were available to compare the simulation with later observations."
        elif sm["beats_persistence"]:
            out["verdict"] = (f"On this window the simulation was closer to later observations than simply holding the initial observation "
                              f"(MAE {sm['mae']} against {sm['persistence_mae']} ug/m3, skill {sm['skill_vs_persistence']:+.2f}). One window is not a general result.")
        else:
            out["verdict"] = (f"On this window the simulation did NOT beat simply holding the initial observation (MAE {sm['mae']} against "
                              f"{sm['persistence_mae']} ug/m3, skill {sm['skill_vs_persistence']:+.2f}). Concentrations change through emissions and chemistry that "
                              f"this transport-only model does not contain; treat the field as a picture of where the observed air is carried, not as a forecast.")
        return out

    def _limitations(self, scenario: Scenario, wind: dict, scen: bool) -> list[str]:
        L = [
            "Passive transport only: no emission sources, no chemistry, no deposition, no secondary aerosol formation, no vertical structure.",
            "Concentrations show where the observed air would be carried by the modelled 10 m wind. They do not identify or locate pollution sources.",
            "The initial field is an interpolation between stations (inverse-distance weighting); areas more than 12 km from two stations are unknown and stay unknown.",
            "Air entering the domain from outside is unknown: cells fill with 'no information', never with an assumed background value.",
            "Wind is weather-model output on a 0.14 degree lattice at 10 m, not a measurement; it is not divergence-free, so total mass is not conserved in the advective form.",
            f"Horizontal eddy diffusivity is a fixed parameter ({scenario.diffusivity_m2s:g} m2/s), not a measured quantity.",
        ]
        if scenario.mixing_mode == "column_dilution":
            L.append(f"Column dilution is switched on: when the boundary layer deepens, concentrations are diluted assuming air aloft is {scenario.aloft_ratio:.0%} of the surface value; "
                     "this is an assumption, not an observation.")
        else:
            L.append("Boundary-layer depth is shown but does not change concentrations in the baseline (no entrainment is assumed).")
        if scenario.loss_per_hour:
            L.append(f"A first-order loss of {scenario.loss_per_hour:g} per hour is applied. It is a hypothetical removal rate, not a measured process.")
        if scen:
            L.append("This is a hypothetical scenario with explicitly modified parameters.")
        return L
