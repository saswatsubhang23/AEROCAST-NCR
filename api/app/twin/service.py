"""Read-only data service behind the digital-twin workspace.

Everything returned here is read from the historical store (`history.sqlite`, built by the ingestion CLI from OpenAQ and the
Open-Meteo archive) or computed from it by a documented method. Nothing is generated: a missing hour is `null`, a missing
station is absent, and an unavailable store is reported as such. The store holds *history up to its last ingestion*, so this
workspace is a replay and analysis tool; it is not a live feed.

Spatial estimate (inverse-distance weighting) is the only interpolation offered. Its method, radius and leave-one-out error for
the displayed hour are part of the response. Pollutant transport is NOT modelled anywhere in this module.
"""

import math
from datetime import datetime, timedelta, timezone

from app.core.places import distance_km
from app.history.features import wind_components
from app.history.ingest_air import iso, parse_iso
from app.history.store import HistoryStore
from app.history.units import POLLUTANTS
from app.services.aqi import BREAKPOINTS, Hourly, compute_aqi

HOUR = timedelta(hours=1)
MAX_WINDOW_HOURS = 336
IDW_RADIUS_KM = 12.0
IDW_POWER = 2.0
IDW_MIN_STATIONS = 2
GRID = 36


_STATUS_CACHE: dict[tuple, dict] = {}  # (database path, modification time) -> status; the summary scans millions of rows, so it is computed once per ingest
_STATIONS_CACHE: dict = {}


class TwinDataUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class TwinService:
    def __init__(self, store: HistoryStore):
        self.store = store

    # ---- inventory -----------------------------------------------------------------------------------
    def status(self) -> dict:
        import os

        try:
            key = (self.store.path, os.stat(self.store.path).st_mtime_ns)
        except OSError:
            key = None
        if key is not None and key in _STATUS_CACHE:
            return _STATUS_CACHE[key]
        out = self._status()
        if key is not None:
            _STATUS_CACHE.clear()
            _STATUS_CACHE[key] = out
            self._warm(out.get("pollutants", []))
        return out

    def _warm(self, pollutants: list[str]) -> None:
        """Fill the station inventory in the background on its own read-only connection, so the first window request after a start-up
        (or an ingest) does not pay for scanning millions of rows on a cold file cache."""
        import threading

        path = self.store.path
        if path == ":memory:":
            return

        def run() -> None:
            try:
                svc = TwinService(HistoryStore(path, read_only=True))
                for p in pollutants:
                    svc.stations(p)
            except Exception:  # noqa: BLE001 - warm-up only; a real request will surface any problem
                pass

        threading.Thread(target=run, name="twin-warm", daemon=True).start()

    def _status(self) -> dict:
        q = self.store.query
        tables = {r[0] for r in q("select name from sqlite_master where type='table'")}
        if "clean_air" not in tables or not q("select 1 from clean_air limit 1"):
            raise TwinDataUnavailable("The historical store has no cleaned observations yet. Run the history pipeline (python -m app.history all).")
        span = None
        pollutants = [r[0] for r in q("select distinct pollutant from clean_air order by pollutant")
                      if q("select 1 from clean_air where pollutant = ? and usable = 1 limit 1", (r[0],))]  # a pollutant with no usable hour (e.g. CO) is not offered
        def dense_to(pol: str, last: str) -> str:
            """Latest hour at which at least half of the typical number of stations reported: where a replay is informative. A lone
            late station (the US embassy monitor) would otherwise make the default window end on an almost empty map."""
            cutoff = iso(datetime.fromisoformat(last.replace("Z", "+00:00")) - 400 * HOUR)
            counts = q("select label_utc, count(*) c from clean_air where pollutant = ? and usable = 1 and label_utc >= ? group by label_utc order by label_utc", (pol, cutoff))
            if not counts:
                return last
            typical = sorted(r["c"] for r in counts)[len(counts) // 2]
            ok = [r["label_utc"] for r in counts if r["c"] >= max(3, typical // 2)]
            return ok[-1] if ok else last

        periods = {p: {"from": q("select label_utc from clean_air where pollutant = ? and usable = 1 order by label_utc asc limit 1", (p,))[0][0],
                       "to": q("select label_utc from clean_air where pollutant = ? and usable = 1 order by label_utc desc limit 1", (p,))[0][0]} for p in pollutants}
        for p, v in periods.items():
            v["dense_to"] = dense_to(p, v["to"])
        if ("pm25" in periods or "pm10" in periods) and len([p for p in periods if p in BREAKPOINTS]) >= 3:
            base = periods["pm25"] if "pm25" in periods else periods["pm10"]
            periods["aqi"] = dict(base)  # AQI needs 16 h of history, so its first valid hour is later than this start
            pollutants = [*pollutants, "aqi"]
        if periods:  # the span of usable observations, not of every stored row
            span = {"a": min(v["from"] for v in periods.values()), "b": max(v["to"] for v in periods.values())}
        else:
            span = dict(q("select min(label_utc) a, max(label_utc) b from clean_air")[0])
        stations = q("select count(*) from (select distinct station_id from clean_air where pollutant = ? and usable = 1)", (pollutants[0],))[0][0] if pollutants else 0
        wx = q("select count(*) c, min(time_utc) a, max(time_utc) b from clean_weather")[0]
        runs = [dict(r) for r in q("select run_id, kind, started_at, finished_at, status from ingest_runs order by started_at desc limit 5")]
        return {
            "available": True, "from": span["a"], "to": span["b"], "periods": periods, "pollutants": [p for p in pollutants if p in POLLUTANTS or p == "aqi"], "stations": stations,
            "weather": {"rows": wx["c"], "from": wx["a"], "to": wx["b"]}, "latest_ingest_runs": runs,
            "data_note": "Historical replay of stored observations. The newest stored hour is the last one the providers had published when the data were ingested.",
        }

    def stations(self, pollutant: str) -> list[dict]:
        """Per-station inventory. It aggregates every usable hour of the pollutant (millions of rows once several years are stored), so the
        result is cached against the store file's modification time; an ingest or clean run changes that time and invalidates it."""
        import os

        try:
            key = (self.store.path, pollutant, os.stat(self.store.path).st_mtime_ns)
        except OSError:
            key = None
        if key is not None and key in _STATIONS_CACHE:
            return _STATIONS_CACHE[key]
        out = self._stations_uncached(pollutant)
        if key is not None:
            for stale in [k for k in _STATIONS_CACHE if k[:2] == key[:2]]:
                del _STATIONS_CACHE[stale]
            _STATIONS_CACHE[key] = out
        return out

    def _stations_uncached(self, pollutant: str) -> list[dict]:
        rows = self.store.query(
            "select s.station_id, s.name, s.lat, s.lon, s.zone, s.agency, s.provider, s.owner, a.first, a.last, a.hours "
            "from (select station_id, min(label_utc) first, max(label_utc) last, count(*) hours from clean_air where pollutant = ? and usable = 1 group by station_id) a "
            "join stations s on s.station_id = a.station_id order by s.name", (pollutant,))
        return [dict(r) for r in rows]

    # ---- observed matrix over a time window ---------------------------------------------------------
    def window(self, pollutant: str, start: datetime, end: datetime, weather: bool = True) -> dict:
        if end < start:
            raise ValueError("end is before start")
        hours = int((end - start) / HOUR) + 1
        if hours > MAX_WINDOW_HOURS:
            raise ValueError(f"the window is limited to {MAX_WINDOW_HOURS} hours")
        if pollutant == "aqi":
            return self.aqi_window(start, end, weather)
        times = [start + i * HOUR for i in range(hours)]
        index = {iso(t): i for i, t in enumerate(times)}
        stations = self.stations(pollutant)
        pos = {s["station_id"]: k for k, s in enumerate(stations)}
        values = [[None] * hours for _ in stations]
        soft = [[0] * hours for _ in stations]
        for r in self.store.query("select station_id, label_utc, value_std, flags from clean_air where pollutant=? and usable=1 and label_utc between ? and ?",
                                  (pollutant, iso(start), iso(end))):
            k, i = pos.get(r["station_id"]), index.get(r["label_utc"])
            if k is not None and i is not None:
                values[k][i] = r["value_std"]
                soft[k][i] = int(bool(r["flags"]) and any(f in ("LOW_COVERAGE", "FLATLINE", "SENSOR_CONFLICT") for f in r["flags"].split(",")))
        out = {"pollutant": pollutant, "unit": "µg/m³", "from": iso(start), "to": iso(end), "times": [iso(t) for t in times], "stations": stations,
               "values": values, "quality_flag": soft,
               "provenance": {"observations": "OpenAQ hourly aggregates (CPCB and other providers), standardised to µg/m³; usable hours only",
                              "status": "observed", "gaps": "null = no usable observation for that hour; nothing is filled in"}}
        if weather:
            out["weather"] = self._weather_for(stations, start, end, times)
        return out

    def _weather_for(self, stations: list[dict], start: datetime, end: datetime, times: list[datetime]) -> dict:
        """Open-Meteo archive values stored for each station's grid point, as u/v components (see the convention in the provenance)."""
        hours = len(times)
        index = {iso(t): i for i, t in enumerate(times)}
        pos = {s["station_id"]: k for k, s in enumerate(stations)}
        u = [[None] * hours for _ in stations]
        v = [[None] * hours for _ in stations]
        blh = [[None] * hours for _ in stations]
        temp = [[None] * hours for _ in stations]
        for r in self.store.query("select station_id, time_utc, wind_speed_10m ws, wind_direction_10m wd, boundary_layer_height b, temperature_2m t from clean_weather "
                                  "where time_utc between ? and ?", (iso(start), iso(end))):
            k, i = pos.get(r["station_id"]), index.get(r["time_utc"])
            if k is None or i is None:
                continue
            _, uu, vv = wind_components(r["ws"], r["wd"])
            u[k][i], v[k][i], blh[k][i], temp[k][i] = uu, vv, r["b"], r["t"]
        return {"wind_u_ms": u, "wind_v_ms": v, "boundary_layer_height_m": blh, "temperature_c": temp,
                "provenance": {"source": "Open-Meteo archive (reanalysis/model values for the grid cell, not station measurements)",
                               "status": "weather_forecast", "wind_convention": "u eastward, v northward, m/s; direction is where the wind blows from"}}

    # ---- spatial estimate ---------------------------------------------------------------------------
    def estimate(self, pollutant: str, at: datetime) -> dict:
        """Inverse-distance-weighted estimate on a regular grid for one hour, with its coverage and leave-one-out error."""
        if pollutant == "aqi":
            raise ValueError("AQI is a derived index, not a concentration; it is not interpolated between stations")
        pts = [(s["lat"], s["lon"], s["value"], s["station_id"]) for s in self._hour_values(pollutant, at)]
        if len(pts) < IDW_MIN_STATIONS + 1:
            raise TwinDataUnavailable("Fewer than three stations have an observation for that hour, so no spatial estimate is made.")
        lats, lons = [p[0] for p in pts], [p[1] for p in pts]
        south, north, west, east = min(lats) - 0.05, max(lats) + 0.05, min(lons) - 0.05, max(lons) + 0.05

        def idw(lat: float, lon: float, exclude: int | None = None):
            return idw_point(pts, lat, lon, exclude)

        cells = []
        for gy in range(GRID):
            lat = south + (north - south) * gy / (GRID - 1)
            row = []
            for gx in range(GRID):
                lon = west + (east - west) * gx / (GRID - 1)
                val, n, nearest = idw(lat, lon)
                row.append({"value": val, "stations": n, "nearest_km": None if nearest is None else round(nearest, 1)})
            cells.append(row)
        errs = []
        for la, lo, val, sid in pts:
            est, n, _ = idw(la, lo, exclude=sid)
            if est is not None:
                errs.append(est - val)
        loo = None
        if errs:
            loo = {"n": len(errs), "mae": sum(abs(e) for e in errs) / len(errs), "rmse": math.sqrt(sum(e * e for e in errs) / len(errs)),
                   "bias": sum(errs) / len(errs), "stations_total": len(pts)}
        return {"pollutant": pollutant, "unit": "µg/m³", "time": iso(at), "bounds": {"south": south, "north": north, "west": west, "east": east}, "grid": GRID,
                "values": [[c["value"] for c in row] for row in cells], "stations_in_range": [[c["stations"] for c in row] for row in cells],
                "nearest_station_km": [[c["nearest_km"] for c in row] for row in cells],
                "method": {"name": "inverse-distance weighting", "power": IDW_POWER, "radius_km": IDW_RADIUS_KM, "min_stations": IDW_MIN_STATIONS,
                           "no_estimate": "cells with fewer than the minimum stations inside the radius are left empty (null)"},
                "leave_one_out": loo, "provenance": {"status": "estimate", "inputs": f"{len(pts)} station observations at {iso(at)}",
                                                     "caveat": "An interpolation between stations. It is not measured at the cell, ignores terrain, sources and wind, and is only as good as the leave-one-out error shows."}}

    def aqi_window(self, start: datetime, end: datetime, weather: bool = True) -> dict:
        """CPCB National AQI per station and hour, computed from the stored hourly concentrations with the application's one AQI
        implementation (`app/services/aqi.py`: 24 h averages, 16 h minimum, at least three pollutants including PM2.5 or PM10). Hours that do
        not meet those rules are null. It is a derived index, never a measurement, and it is not a concentration."""
        hours = int((end - start) / HOUR) + 1
        times = [start + i * HOUR for i in range(hours)]
        pols = [p for p in BREAKPOINTS if p in POLLUTANTS]
        lo, hi = iso(start - 24 * HOUR), iso(end)
        q = ",".join("?" for _ in pols)
        rows = self.store.query(
            f"select station_id, pollutant, label_utc, value_std from clean_air where usable=1 and pollutant in ({q}) and label_utc between ? and ?",
            (*pols, lo, hi))
        by_station: dict[int, dict[str, list[Hourly]]] = {}
        for r in rows:
            t = parse_iso(r["label_utc"])
            if t is None:
                continue
            # the store labels an hour by its midpoint; CPCB windows are hour-ending, so the period ends 30 minutes later
            by_station.setdefault(r["station_id"], {}).setdefault(r["pollutant"], []).append(Hourly(t + timedelta(minutes=30), r["value_std"]))
        inventory = {s["station_id"]: s for p in ("pm25", "pm10") for s in self.stations(p)}
        ids = [sid for sid in sorted(by_station, key=lambda x: inventory.get(x, {}).get("name") or "") if sid in inventory]
        values: list[list[int | None]] = []
        dominant: list[list[str | None]] = []
        lower: list[list[bool]] = []
        for sid in ids:
            series = {p: sorted(v, key=lambda h: h.end) for p, v in by_station[sid].items()}
            v_row, d_row, l_row = [], [], []
            for t in times:
                anchor = t + timedelta(minutes=30)
                window = {p: ([h for h in hs if anchor - 24 * HOUR < h.end <= anchor], "µg/m³") for p, hs in series.items()}
                res = compute_aqi(window, anchor)
                ok = res.status == "available" and res.aqi is not None
                v_row.append(res.aqi if ok else None)
                d_row.append(res.dominant if ok else None)
                l_row.append(bool(res.lower_bound_only) if ok else False)
            values.append(v_row)
            dominant.append(d_row)
            lower.append(l_row)
        keep = [k for k, row in enumerate(values) if any(v is not None for v in row)]
        stations = [inventory[ids[k]] for k in keep]
        out = {
            "pollutant": "aqi", "unit": "AQI", "from": iso(start), "to": iso(end), "times": [iso(t) for t in times], "stations": stations,
            "values": [values[k] for k in keep], "quality_flag": [[0 if v is not None else 1 for v in values[k]] for k in keep],
            "aqi": {"dominant": [dominant[k] for k in keep], "lower_bound_only": [lower[k] for k in keep]},
            "provenance": {"observations": "CPCB National AQI computed from stored hourly concentrations (derived, not measured)", "status": "derived",
                           "method": "24-hour averages (8-hour for CO and O3), at least 16 valid hours per pollutant, at least three pollutants including PM2.5 or PM10; the worst sub-index is the AQI",
                           "gaps": "an hour that does not meet the rules is null; nothing is filled in"},
        }
        if weather and keep:
            wx = self._weather_for(stations, start, end, times)
            if wx:
                out["weather"] = wx
        return out

    def validate_estimates(self, pollutant: str, start: datetime, end: datetime, n_hours: int = 24) -> dict:
        """Out-of-sample check of the spatial estimate over many hours: every station is withheld in turn (leave-one-out) and predicted from the
        others, then compared with a baseline that predicts the mean of the other stations. Hours are sampled evenly across the window."""
        if end < start:
            raise ValueError("end is before start")
        if pollutant == "aqi":
            raise ValueError("AQI is a derived index; the interpolation check applies to concentrations")
        n_hours = max(1, min(int(n_hours), 72))
        total = int((end - start) / HOUR) + 1
        picks = sorted({start + HOUR * round(i * (total - 1) / max(n_hours - 1, 1)) for i in range(min(n_hours, total))})
        err_idw, err_mean, used_hours, per_hour = [], [], 0, []
        for t in picks:
            pts = [(r["lat"], r["lon"], r["value"], r["station_id"]) for r in self._hour_values(pollutant, t)]
            if len(pts) < IDW_MIN_STATIONS + 2:
                continue
            e_i, e_m = [], []
            for la, lo, val, sid in pts:
                est, _, _ = idw_point(pts, la, lo, exclude=sid)
                others = [p[2] for p in pts if p[3] != sid]
                if est is not None and others:
                    e_i.append(est - val)
                    e_m.append(sum(others) / len(others) - val)
            if e_i:
                used_hours += 1
                err_idw += e_i
                err_mean += e_m
                per_hour.append({"time": iso(t), "n": len(e_i), "mae_idw": round(sum(abs(x) for x in e_i) / len(e_i), 2),
                                 "mae_mean": round(sum(abs(x) for x in e_m) / len(e_m), 2)})
        if not err_idw:
            raise TwinDataUnavailable("No hour in the window has enough stations to evaluate the spatial estimate.")

        def stats(e: list[float]) -> dict:
            return {"mae": round(sum(abs(x) for x in e) / len(e), 2), "rmse": round(math.sqrt(sum(x * x for x in e) / len(e)), 2), "bias": round(sum(e) / len(e), 2)}

        mi, mm = stats(err_idw), stats(err_mean)
        return {"pollutant": pollutant, "unit": "\u00b5g/m\u00b3", "from": iso(start), "to": iso(end), "hours_sampled": len(picks), "hours_used": used_hours,
                "predictions": len(err_idw),
                "method": f"inverse-distance weighting (power {IDW_POWER:g}, radius {IDW_RADIUS_KM:g} km, at least {IDW_MIN_STATIONS} stations)",
                "idw": mi, "baseline_mean_of_other_stations": mm,
                "skill_vs_mean": None if mm["mae"] == 0 else round(1 - mi["mae"] / mm["mae"], 3), "beats_baseline": mi["mae"] < mm["mae"],
                "per_hour": per_hour,
                "note": "Leave-one-out: each station is predicted from the others and compared with its own observation. Stations with no neighbour inside the "
                        "radius cannot be scored and are excluded, so this is an optimistic view of coverage."}

    def _hour_values(self, pollutant: str, at: datetime) -> list[dict]:
        return [{"station_id": r["station_id"], "lat": r["lat"], "lon": r["lon"], "value": r["value_std"]} for r in self.store.query(
            "select c.station_id, s.lat, s.lon, c.value_std from clean_air c join stations s on s.station_id = c.station_id "
            "where c.pollutant=? and c.usable=1 and c.label_utc=?", (pollutant, iso(at)))]

    # ---- observed values after an origin, for observed-vs-predicted ---------------------------------
    def observed(self, pollutant: str, station_id: int, times: list[datetime]) -> list[float | None]:
        got = {r["label_utc"]: r["value_std"] for r in self.store.query(
            "select label_utc, value_std from clean_air where station_id=? and pollutant=? and usable=1 and label_utc between ? and ?",
            (station_id, pollutant, iso(min(times)), iso(max(times))))}
        return [got.get(iso(t)) for t in times]


def idw_point(pts: list[tuple], lat: float, lon: float, exclude: int | None = None):
    """The twin's one interpolation method, shared by the map estimate, the validation and the transport initial field.
    pts are (lat, lon, value, station_id). Returns (value or None, stations used, nearest distance km or None)."""
    num = den = 0.0
    n = 0
    nearest = math.inf
    for la, lo, val, sid in pts:
        if sid == exclude:
            continue
        d = distance_km(lat, lon, la, lo)
        if d > IDW_RADIUS_KM:
            continue
        w = 1.0 / max(d, 0.5) ** IDW_POWER
        num += w * val
        den += w
        n += 1
        nearest = min(nearest, d)
    return (num / den, n, nearest) if n >= IDW_MIN_STATIONS else (None, n, nearest if n else None)


def idw_grid(pts: list[tuple], lats, lons):
    """The same method as idw_point on a regular grid, vectorised. Returns (values with NaN where fewer than the minimum stations are in
    range, station counts). Equality with idw_point is asserted by a test."""
    import numpy as np

    la = np.asarray(lats, dtype=float)[:, None, None]
    lo = np.asarray(lons, dtype=float)[None, :, None]
    p_la = np.array([p[0] for p in pts], dtype=float)[None, None, :]
    p_lo = np.array([p[1] for p in pts], dtype=float)[None, None, :]
    val = np.array([p[2] for p in pts], dtype=float)[None, None, :]
    r1, r2 = np.radians(la), np.radians(p_la)
    a = np.sin((r2 - r1) / 2) ** 2 + np.cos(r1) * np.cos(r2) * np.sin(np.radians(p_lo - lo) / 2) ** 2
    d = 6371.0 * 2 * np.arcsin(np.sqrt(a))
    inside = d <= IDW_RADIUS_KM
    w = np.where(inside, 1.0 / np.maximum(d, 0.5) ** IDW_POWER, 0.0)
    n = inside.sum(axis=2)
    den = w.sum(axis=2)
    out = np.where(n >= IDW_MIN_STATIONS, (w * val).sum(axis=2) / np.where(den > 0, den, 1.0), np.nan)
    return out, n


def utc_floor(dt: datetime) -> datetime:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
