"""Coupled-model runs of the digital twin: real inputs in, a multi-species forecast field out, checked against what was observed.

Two ways to start (each result says which):
  observations     the stored/observed station values at the initialisation hour (as the passive simulation does)
  model_forecast   the trained local model's station forecasts at origin + lead (so the picture follows the ML model, and changes by itself
                   when a new model is activated: the caller re-requests and the run id changes with the inputs)

Every run carries: the processes and parameters used, the passive-transport run of the same inputs for comparison, a budget of what each
coupling did, a hindcast against later observations (with persistence and passive baselines, and stations withheld from the initial field),
the freshness of its inputs, and its limitations. Nothing is trained here.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import time
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.history.ingest_air import iso
from app.services.weather_fields import WeatherFieldsService
from app.twin.coupled import DEFAULT_PROCESSES, LABELS, PROCESSES, SPECIES, CouplingParams, SULFATE_PER_SO2, derived_fields, run_coupled
from app.twin.service import HOUR, IDW_MIN_STATIONS, IDW_POWER, IDW_RADIUS_KM, TwinService, idw_grid, utc_floor
from app.twin.simulation import DOMAIN, MAX_HOURS, MIN_HOURS, STALE_OBS_HOURS, WITHHOLD_MOD, SimulationError, SimulationService, _digest, _round
from app.twin.transport import KNOWN_THRESHOLD, regrid_bilinear

MODEL_NAME = "aerocast-coupled-transport"
MODEL_VERSION = "1.0.0"
OBSERVED = {"pm25": "pm25", "pm10": "pm10", "no2": "no2", "o3": "o3", "so2": "so2"}  # transported species <- stored pollutant
FORECAST_POLLUTANTS = ("pm25", "pm10", "no2", "o3")  # the trained local model's targets (SO2 has none)
RUN_HOURS = (6, 12, 24, 36, 48)

# What each process is, where its number comes from, and what it leaves out: shown to the user next to the run.
PROCESS_INFO = {
    "ventilation": {
        "label": "Ventilation (boundary-layer depth x wind), off by default",
        "kind": "weather -> primary species",
        "what": "PM2.5, coarse PM, NO2 and SO2 follow the ventilation coefficient: a shallow, calm boundary layer raises concentrations, a deep windy one lowers them, and the air relaxes toward that level over a few hours.",
        "basis": "The steady-emissions rule C ∝ 1/(H·u) used in operational air-quality forecasting; relaxation time 3 h; ratio limited to 0.25 to 4.",
        "limits": "ASSUMES emissions stay as they were at the start (no morning or evening traffic peak, no burning). O3 is secondary and is not scaled. In the 22-window hindcast it made PM2.5 results worse than plain transport (median skill -0.26), so it is opt-in.",
    },
    "dilution": {
        "label": "Mixed-layer dilution (one-sided, off by default)",
        "kind": "weather -> all species",
        "what": "When the weather model's boundary layer deepens, the surface air mixes with cleaner air aloft and concentrations fall in proportion.",
        "basis": "Mass conservation in a well-mixed column; `aloft_ratio` is the concentration aloft as a fraction of the surface value (default 0).",
        "limits": "Nothing replaces the air that is diluted (there are no emissions) and a shallowing layer does not re-concentrate it, so it biases results low. Use it with an aloft ratio you can justify.",
    },
    "deposition": {
        "label": "Dry deposition and settling",
        "kind": "weather -> species",
        "what": "Species are removed at the ground at a rate v/H, so a shallow boundary layer removes faster; coarse particles settle faster than fine ones.",
        "basis": "Order-of-magnitude deposition velocities (cm/s): PM2.5 0.1, coarse PM 0.6, NO2 0.15, O3 0.4, SO2 0.5 (Seinfeld & Pandis).",
        "limits": "One value per species: no dependence on surface type, wind speed or time of day.",
    },
    "washout": {
        "label": "Wet scavenging by rain",
        "kind": "weather -> species",
        "what": "Rain removes particles (strongly) and SO2 (weakly) at a rate a·P^b, with P the model's hourly rain in mm/h. NO2 and O3 are poorly soluble and are left alone.",
        "basis": "Rate = 1e-4 · P^0.79 per second times a per-species efficiency (coarse PM 2, PM2.5 1, SO2 0.3): the usual order of magnitude for below-cloud scavenging.",
        "limits": "Rain is the model's gridded hourly total, not a radar or gauge measurement; below-cloud scavenging only.",
    },
    "oxidation": {
        "label": "SO2 to sulfate aerosol",
        "kind": "species -> species",
        "what": "A fraction of SO2 is oxidised each hour in sunlight and becomes PM2.5 sulfate (each unit of SO2 lost adds 1.5 units of PM2.5, the 96/64 mass ratio).",
        "basis": "First order, 2 %/h at 800 W/m2 of shortwave radiation, scaled by the model radiation (gas-phase oxidation is typically 1-3 %/h).",
        "limits": "No aqueous-phase oxidation in cloud, no ammonium or nitrate partitioning. Where PM2.5 is unknown no sulfate is added.",
    },
}
NOT_MODELLED = [
    "Emissions: there is no source term, so concentrations can only be carried, diluted or removed. Fresh pollution from traffic, industry or burning cannot appear.",
    "NO titration of O3: NO is not observed in the stored data (the CAMS model has it, but it is not a measurement), so O3 and NO2 are not exchanged. Ox = O3 + NO2 is shown instead because titration leaves it nearly unchanged.",
    "NO2 to nitrate and secondary organic aerosol: they depend on ammonia, VOCs and temperature, none of which is observed here.",
    "Vertical structure: the model is one well-mixed layer. There are no vertical concentration observations.",
    "Terrain and street-scale effects: the grid is about 2.7 km and the wind is a 8 x 10 km weather-model field.",
]


def load_evaluation() -> dict | None:
    """The recorded historical evaluation (docs/coupled-evaluation.json), summarised for the interface. None if it has not been run."""
    path = Path(__file__).resolve().parents[3] / "docs" / "coupled-evaluation.json"
    try:
        r = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    cfg = r.get("configs", {})
    first = next(iter(cfg), None)
    if first is None:
        return None
    return {
        "generated_at": r.get("generated_at"), "windows": len(r.get("windows_used", [])), "hours": r.get("hours"), "scoring": r.get("scoring"),
        "defaults": {sp: d for sp, d in cfg[first].items()},
        "configs": {name: {sp: {"vs_passive": d["vs_passive"], "vs_persistence": d["vs_persistence"]} for sp, d in per.items()} for name, per in cfg.items()},
        "report": "docs/coupled-evaluation.md",
    }


def process_catalogue() -> dict:
    p = CouplingParams()
    return {
        "evaluation": load_evaluation(),
        "model": {"name": MODEL_NAME, "version": MODEL_VERSION},
        "species": [{"key": s, "label": LABELS[s]} for s in SPECIES],
        "derived": [{"key": "pm10", "label": "PM10 (PM2.5 + coarse)"}, {"key": "ox_ppb", "label": "Ox = O3 + NO2 (ppb)"}],
        "processes": [{"key": k, **PROCESS_INFO[k]} for k in PROCESSES],
        "default_processes": [k for k in PROCESSES if k in DEFAULT_PROCESSES],
        "defaults": {"diffusivity_m2s": p.diffusivity_m2s, "aloft_ratio": p.aloft_ratio, "so2_oxidation_per_hour": p.so2_oxidation_per_hour,
                     "ventilation_tau_h": p.ventilation_tau_h,
                     "washout_a": p.washout_a, "washout_b": p.washout_b, "v_dep_cm_s": dict(p.v_dep_cm_s), "washout_efficiency": dict(p.washout_efficiency)},
        "not_modelled": NOT_MODELLED,
        "run_hours": list(RUN_HOURS),
        "sulfate_per_so2": SULFATE_PER_SO2,
    }


def build_params(overrides: dict | None) -> CouplingParams:
    o = overrides or {}
    base = CouplingParams()
    diff = float(o.get("diffusivity_m2s", base.diffusivity_m2s))
    aloft = float(o.get("aloft_ratio", base.aloft_ratio))
    ox = float(o.get("so2_oxidation_per_hour", base.so2_oxidation_per_hour))
    tau = float(o.get("ventilation_tau_h", base.ventilation_tau_h))
    if not 0.5 <= tau <= 24.0:
        raise SimulationError("ventilation_tau_h must be between 0.5 and 24")
    if not 1.0 <= diff <= 500.0:
        raise SimulationError("diffusivity_m2s must be between 1 and 500")
    if not 0.0 <= aloft <= 1.0:
        raise SimulationError("aloft_ratio must be between 0 and 1")
    if not 0.0 <= ox <= 0.2:
        raise SimulationError("so2_oxidation_per_hour must be between 0 and 0.2")
    return CouplingParams(diffusivity_m2s=diff, aloft_ratio=aloft, so2_oxidation_per_hour=ox, ventilation_tau_h=tau)


class CoupledService:
    def __init__(self, fields: WeatherFieldsService, store_dir: str | Path | None = None, now=None):
        self._sim = SimulationService(fields, None, now)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._dir = Path(store_dir) if store_dir else None
        self._runs: dict[str, dict] = {}

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

    # ------------------------------------------------------------------------------------------------ run
    async def run(self, twin: TwinService, *, hours: int = 24, init_time: datetime | None = None, processes: list[str] | None = None,
                  params: dict | None = None, focus: str = "pm25", validate: bool = True,
                  station_values: dict[str, list[dict]] | None = None, forecast_info: dict | None = None) -> dict:
        """`station_values` (species -> [{station_id, name, lat, lon, value}]) replaces the observations as the initial state (model_forecast mode);
        `init_time` is then the VALID time of those values."""
        if not MIN_HOURS <= hours <= MAX_HOURS:
            raise SimulationError(f"hours must be between {MIN_HOURS} and {MAX_HOURS}")
        enabled = set(DEFAULT_PROCESSES if processes is None else processes)
        bad = enabled - set(PROCESSES)
        if bad:
            raise SimulationError(f"unknown process: {', '.join(sorted(bad))}")
        if focus not in (*SPECIES, "pm10", "ox_ppb"):
            raise SimulationError("focus must be a species, pm10 or ox_ppb")
        cp = build_params(params)

        status = await asyncio.to_thread(twin.status)
        if station_values is None:
            period = status["periods"].get("pm25")
            if not period:
                raise SimulationError("the store has no usable PM2.5 observations", "twin_data_unavailable", 503)
            t0 = datetime.fromisoformat(period["dense_to"].replace("Z", "+00:00")) if init_time is None else utc_floor(init_time)
            if init_time is not None and init_time.tzinfo is None:
                raise SimulationError("init_time must include a UTC offset")
            source = "observations"
            raw = {sp: await asyncio.to_thread(twin._hour_values, sp, t0) for sp in OBSERVED.values()}
        else:
            if init_time is None:
                raise SimulationError("a model-forecast start needs the valid time of the forecast values")
            t0 = utc_floor(init_time)
            fi = forecast_info or {}
            source = "live" if fi.get("live") else "cams" if fi.get("cams") else "model_forecast"
            raw = {sp: list(station_values.get(sp, [])) for sp in OBSERVED.values()}
        if len(raw.get("pm25", [])) < IDW_MIN_STATIONS + 1:
            raise SimulationError(f"fewer than three stations have PM2.5 values for {iso(t0)}; choose another start", "no_initial_observations")

        wind = await self._sim._wind(t0, hours)
        n_hours = wind["hours"]
        key = {
            "model": MODEL_NAME, "version": MODEL_VERSION, "source": source, "init": iso(t0), "hours": n_hours, "processes": sorted(enabled), "params": asdict(cp),
            "focus": focus, "validate": bool(validate), "domain": asdict(DOMAIN),
            "inputs": {sp: _digest(np.array([[o["station_id"], o["value"]] for o in sorted(rows, key=lambda o: o["station_id"])] or [[0, 0]])) for sp, rows in raw.items()},
            "wind": _digest(wind["u"], wind["v"], wind["blh"], wind["precip"], wind["sw"]),
        }
        run_id = hashlib.sha256(json.dumps(key, sort_keys=True).encode()).hexdigest()[:16]
        cached = self.get(run_id)
        if cached:
            return {**cached, "freshness": self._freshness(t0, wind, source, forecast_info)}
        started = self._now()
        t_start = time.perf_counter()
        body = await asyncio.to_thread(self._execute, twin, key, t0, n_hours, raw, wind, enabled, cp, focus, validate)
        run = {
            "run_id": run_id,
            "model": {"name": MODEL_NAME, "version": MODEL_VERSION, "scheme": "5-species 2-D advection-diffusion with first-order couplings (see processes)",
                      "processes": [{"key": k, "enabled": k in enabled, **PROCESS_INFO[k]} for k in PROCESSES],
                      "parameters": {"diffusivity_m2s": cp.diffusivity_m2s, "aloft_ratio": cp.aloft_ratio, "so2_oxidation_per_hour": cp.so2_oxidation_per_hour,
                                     "ventilation_tau_h": cp.ventilation_tau_h,
                                     "washout_a": cp.washout_a, "washout_b": cp.washout_b, "v_dep_cm_s": dict(cp.v_dep_cm_s), "washout_efficiency": dict(cp.washout_efficiency)},
                      "not_modelled": NOT_MODELLED, "validated": False},
            "source": source, "forecast": forecast_info,
            "initialisation": iso(t0), "valid_times": [iso(t0 + k * HOUR) for k in range(n_hours + 1)],
            "extent": {"south": DOMAIN.south, "north": DOMAIN.north, "west": DOMAIN.west, "east": DOMAIN.east},
            "grid": {"rows": DOMAIN.rows, "cols": DOMAIN.cols, "dx_m": round(DOMAIN.dx_m), "dy_m": round(DOMAIN.dy_m),
                     "lats": [round(x, 4) for x in DOMAIN.lats.tolist()], "lons": [round(x, 4) for x in DOMAIN.lons.tolist()]},
            "execution": {"status": "completed" if n_hours == hours else "limited", "requested_hours": hours, "simulated_hours": n_hours,
                          "started_at": iso(started), "duration_ms": round((time.perf_counter() - t_start) * 1000), **body.pop("execution")},
            "inputs": {"stations": body.pop("obs_info"), "meteorology": wind["info"]},
            **body,
        }
        run["freshness"] = self._freshness(t0, wind, source, forecast_info)
        self._runs[run_id] = run
        if len(self._runs) > 12:
            self._runs.pop(next(iter(self._runs)))
        if self._dir:
            try:
                self._dir.mkdir(parents=True, exist_ok=True)
                (self._dir / f"{run_id}.json").write_text(json.dumps(run), encoding="utf-8")
            except OSError:
                pass
        return run

    # ------------------------------------------------------------------------------------------------ pieces
    def _freshness(self, t0: datetime, wind: dict, source: str, forecast_info: dict | None) -> dict:
        age = (self._now() - t0).total_seconds() / 3600.0
        stale = age > STALE_OBS_HOURS
        what = {"observations": "initial observations", "live": "live readings", "cams": "initial CAMS model field"}.get(source, "initial model-forecast hour")
        return {
            "initial_state_age_hours": round(age, 1), "stale": stale, "stale_after_hours": STALE_OBS_HOURS, "status": "stale" if stale else "fresh",
            "meteorology": wind["info"]["mode"], "meteorology_retrieved_at": wind["info"]["retrieved_at"],
            "note": (f"The {what} are {age:.0f} h old, so this run describes the past, not the present." if stale else f"The {what} are recent."),
        }

    def _initial(self, rows: dict[str, list[dict]], exclude: set[int] | None = None):
        """Initial fields per transported species by inverse-distance weighting, plus the coarse fraction."""
        c0: dict[str, np.ndarray] = {}
        k0: dict[str, np.ndarray] = {}
        counts: dict[str, int] = {}
        interp: dict[str, np.ndarray] = {}
        for sp, pol in OBSERVED.items():
            pts = [(o["lat"], o["lon"], o["value"], o["station_id"]) for o in rows.get(pol, []) if not exclude or o["station_id"] not in exclude]
            counts[sp] = len(pts)
            if len(pts) < IDW_MIN_STATIONS + 1:
                continue
            vals, _ = idw_grid(pts, DOMAIN.lats, DOMAIN.lons)
            if np.isfinite(vals).any():
                interp[sp] = vals
        if "pm25" in interp:
            c0["pm25"] = np.where(np.isfinite(interp["pm25"]), interp["pm25"], 0.0)
            k0["pm25"] = np.isfinite(interp["pm25"])
        if "pm25" in interp and "pm10" in interp:
            both = np.isfinite(interp["pm25"]) & np.isfinite(interp["pm10"])
            c0["pm_coarse"] = np.where(both, np.maximum(interp["pm10"] - interp["pm25"], 0.0), 0.0)  # PM10 below PM2.5 is a measurement artefact: clipped to 0
            k0["pm_coarse"] = both
        for sp in ("no2", "o3", "so2"):
            if sp in interp:
                c0[sp] = np.where(np.isfinite(interp[sp]), interp[sp], 0.0)
                k0[sp] = np.isfinite(interp[sp])
        return c0, k0, counts

    def _meteorology(self, wind: dict):
        u, v, blh = self._sim._regrid_winds(wind)
        if blh is None:
            raise SimulationError("the boundary-layer height is missing in the weather data, so the coupled model cannot run", "wind_unavailable", 503)
        precip = regrid_bilinear(wind["precip"], wind["lats"], wind["lons"], DOMAIN.lats, DOMAIN.lons)
        sw = regrid_bilinear(wind["sw"], wind["lats"], wind["lons"], DOMAIN.lats, DOMAIN.lons)
        if not (np.isfinite(precip).all() and np.isfinite(sw).all()):
            raise SimulationError("precipitation or radiation is missing in the weather data, so the coupled model cannot run", "wind_unavailable", 503)
        return u, v, blh, precip, sw

    def _execute(self, twin: TwinService, key: dict, t0: datetime, hours: int, raw: dict, wind: dict, enabled: set[str], cp: CouplingParams,
                 focus: str, validate: bool) -> dict:
        u, v, blh, precip, sw = self._meteorology(wind)
        c0, k0, counts = self._initial(raw)
        if "pm25" not in c0 or not k0["pm25"].any():
            raise SimulationError("no grid cell has two or more PM2.5 stations within the interpolation radius")
        res = run_coupled(DOMAIN, c0, k0, u, v, blh, precip, sw, cp, frozenset(enabled))
        passive = run_coupled(DOMAIN, c0, k0, u, v, blh, precip, sw, cp, frozenset())
        conc = {**res.concentration, **derived_fields(res.concentration)}
        pconc = {**passive.concentration, **derived_fields(passive.concentration)}
        T = hours + 1

        def mean_known(a: np.ndarray) -> list:
            return [None if not np.isfinite(a[k]).any() else round(float(np.nanmean(a[k])), 2) for k in range(a.shape[0])]

        species_out = {}
        for s in (*SPECIES, "pm10", "ox_ppb"):
            if s not in conc or not np.isfinite(conc[s]).any():
                continue
            unit = "ppb" if s == "ox_ppb" else "µg/m³"
            label = "Ox = O3 + NO2" if s == "ox_ppb" else ("PM10 (PM2.5 + coarse)" if s == "pm10" else LABELS[s])
            species_out[s] = {"label": label, "unit": unit, "frames": _round(conc[s], 1),
                              "initial_cells": int(np.isfinite(conc[s][0]).sum()), "domain_mean": mean_known(conc[s]),
                              "known_fraction": [round(float(np.isfinite(conc[s][k]).mean()), 3) for k in range(T)]}
        out: dict = {
            "execution": {"engine_steps": res.steps, "dt_seconds_min": round(res.dt_min_s, 1), "dt_seconds_max": round(res.dt_max_s, 1),
                          "max_courant_number": round(res.max_courant, 2), "deterministic": True, "members": ["coupled", "passive (no couplings)"]},
            "obs_info": {"time": iso(t0), "per_species": {s: counts.get(s, 0) for s in OBSERVED}, "species_initialised": sorted(c0),
                         "method": f"inverse-distance weighting (power {IDW_POWER:g}, radius {IDW_RADIUS_KM:g} km, at least {IDW_MIN_STATIONS} stations)",
                         "cells_with_initial_estimate": {s: int(k0[s].sum()) for s in k0}, "cells_total": int(DOMAIN.rows * DOMAIN.cols),
                         "species_without_initial_state": [s for s in SPECIES if s not in c0]},
            "species": species_out,
            "focus": focus if focus in species_out else "pm25",
            "meteorology": {
                "boundary_layer_height_m": [round(float(np.mean(blh[k])), 0) for k in range(T)],
                "rain_mm_per_h": [round(float(np.mean(precip[k])), 2) for k in range(T)],
                "shortwave_w_m2": [round(float(np.mean(sw[k])), 0) for k in range(T)],
                "wind_speed_m_s": [round(float(np.mean(np.hypot(u[k], v[k]))), 2) for k in range(T)],
            },
            "wind": {"lats": [round(x, 4) for x in wind["lats"].tolist()], "lons": [round(x, 4) for x in wind["lons"].tolist()],
                     "u": _round(wind["u"], 2), "v": _round(wind["v"], 2), "boundary_layer_height_m": _round(wind["blh"], 0)},
            "budget": {s: {p: round(res.budget[s][p], 4) for p in PROCESSES} for s in SPECIES if res.burden0[s] > 0},
            "budget_note": "Share of each species' initial known burden removed by each process over the run (a negative value is a gain, e.g. sulfate formed from SO2). Indicative: the known area changes as air moves.",
        }
        f = out["focus"]
        out["passive_focus"] = _round(pconc[f], 1) if f in pconc else None
        out["difference_focus"] = _round(conc[f] - pconc[f], 2) if f in pconc else None
        out["effect_of_couplings"] = {
            s: {"passive_mean_end": mean_known(pconc[s])[-1], "coupled_mean_end": mean_known(conc[s])[-1]} for s in species_out if s in pconc
        }
        # stations and observations at every valid time (for the map and the comparison)
        stations: dict[int, dict] = {}
        series: dict[str, dict[int, np.ndarray]] = {}
        for sp, pol in OBSERVED.items():
            win = twin.window(pol, t0, t0 + hours * HOUR, weather=False)
            for st in win["stations"]:
                stations.setdefault(st["station_id"], {"station_id": st["station_id"], "name": st["name"], "lat": st["lat"], "lon": st["lon"]})
            series[sp] = {st["station_id"]: np.array([np.nan if x is None else x for x in win["values"][i]], dtype=float) for i, st in enumerate(win["stations"])}
        out["stations"] = list(stations.values())
        if validate:
            out["validation"] = self._validate(raw, t0, hours, series, stations, u, v, blh, precip, sw, enabled, cp, c0, k0)
        else:
            out["validation"] = {"available": False, "reason": "validation was not requested"}
        out["limitations"] = self._limitations(enabled, cp, raw, c0)
        return out

    # ------------------------------------------------------------------------------------------------ validation
    @staticmethod
    def _sample(frame: np.ndarray, lat: float, lon: float) -> float:
        if not (DOMAIN.south <= lat <= DOMAIN.north and DOMAIN.west <= lon <= DOMAIN.east):
            return float("nan")
        fy = (lat - DOMAIN.south) / (DOMAIN.north - DOMAIN.south) * (DOMAIN.rows - 1)
        fx = (lon - DOMAIN.west) / (DOMAIN.east - DOMAIN.west) * (DOMAIN.cols - 1)
        r, c = min(int(fy), DOMAIN.rows - 2), min(int(fx), DOMAIN.cols - 2)
        ty, tx = fy - r, fx - c
        q = frame[r:r + 2, c:c + 2]
        w = np.array([[(1 - ty) * (1 - tx), (1 - ty) * tx], [ty * (1 - tx), ty * tx]])
        return float((q * w).sum()) if np.isfinite(q).all() else float("nan")

    def _validate(self, raw, t0, hours, series, stations, u, v, blh, precip, sw, enabled, cp, c0_full, k0_full) -> dict:
        withheld = {sid for sid in stations if sid % WITHHOLD_MOD == 0}
        if len(withheld) < 3:
            return {"available": False, "reason": "too few stations to withhold any for an out-of-sample check"}
        c0, k0, _ = self._initial(raw, exclude=withheld)
        if "pm25" not in c0:
            return {"available": False, "reason": "no PM2.5 field remains after withholding stations"}
        coupled = run_coupled(DOMAIN, c0, k0, u, v, blh, precip, sw, cp, frozenset(enabled))
        passive = run_coupled(DOMAIN, c0, k0, u, v, blh, precip, sw, cp, frozenset())
        cf = {**coupled.concentration, **derived_fields(coupled.concentration)}
        pf = {**passive.concentration, **derived_fields(passive.concentration)}
        per_species: dict[str, dict] = {}
        for sp, pol in (("pm25", "pm25"), ("pm10", "pm10"), ("no2", "no2"), ("o3", "o3"), ("so2", "so2")):
            if sp not in cf or pol not in series or not series[pol]:
                continue
            ec, ep, e0 = [], [], []
            for sid in withheld:
                obs = series[pol].get(sid)
                if obs is None or np.isnan(obs[0]):
                    continue
                st = stations[sid]
                for k in range(1, hours + 1):
                    o = obs[k] if k < len(obs) else np.nan
                    if np.isnan(o):
                        continue
                    c, p = self._sample(cf[sp][k], st["lat"], st["lon"]), self._sample(pf[sp][k], st["lat"], st["lon"])
                    if np.isnan(c) or np.isnan(p):
                        continue
                    ec.append(abs(c - o))
                    ep.append(abs(p - o))
                    e0.append(abs(obs[0] - o))
            if len(ec) < 6:
                per_species[sp] = {"n": len(ec), "available": False, "reason": "fewer than six withheld station-hours with both a simulated and an observed value"}
                continue
            mc, mp, m0 = float(np.mean(ec)), float(np.mean(ep)), float(np.mean(e0))
            per_species[sp] = {
                "available": True, "n": len(ec), "stations_withheld": len(withheld), "mae_coupled": round(mc, 2), "mae_passive": round(mp, 2), "mae_persistence": round(m0, 2),
                "skill_vs_persistence": None if m0 == 0 else round(1 - mc / m0, 3), "skill_vs_passive": None if mp == 0 else round(1 - mc / mp, 3),
                "beats_persistence": mc < m0, "beats_passive": mc < mp,
            }
        scored = [s for s, d in per_species.items() if d.get("available")]
        if not scored:
            verdict = "No later observations were stored for this window, so the coupled run cannot be checked against them."
        else:
            better = [s for s in scored if per_species[s]["beats_passive"]]
            beats = [s for s in scored if per_species[s]["beats_persistence"]]
            verdict = (f"Out of sample (stations {WITHHOLD_MOD}-divisible withheld): the couplings were closer to later observations than passive transport for "
                       f"{len(better)} of {len(scored)} species, and closer than simply holding the initial value for {len(beats)} of {len(scored)}. "
                       "One window is not a general result; the model has no emissions, so persistence is often hard to beat.")
        return {"available": bool(scored), "against": "later stored observations at withheld stations", "per_species": per_species, "verdict": verdict,
                "baselines": "persistence = the withheld station's own observation at the start; passive = the same engine with every coupling switched off"}

    def _limitations(self, enabled: set[str], cp: CouplingParams, raw: dict, c0: dict) -> list[str]:
        L = [
            "A reduced-form model: the couplings are first-order processes with literature-order parameters, not fitted to Delhi and not validated as a chemistry-transport model.",
            "There are no emissions. The field says where observed (or model-forecast) air goes and how weather and simple chemistry change it; it cannot say where new pollution appears.",
            "The initial field is an interpolation between stations (inverse-distance weighting); cells without two stations within range are unknown and stay unknown.",
            "Wind, boundary-layer depth, rain and radiation are weather-model output on an 8 x 10 km grid, not measurements.",
        ]
        for k in PROCESSES:
            if k not in enabled:
                L.append(f"{PROCESS_INFO[k]['label']} is switched off in this run.")
        missing = [LABELS[s] for s in SPECIES if s not in c0]
        if missing:
            L.append(f"No initial state could be built for: {', '.join(missing)} (too few stations or no trained model for it); those species are not shown.")
        L.extend(NOT_MODELLED[1:3])
        return L
