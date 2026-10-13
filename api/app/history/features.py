"""Model-ready features from `clean_*`. No model is trained here.

The no-leakage rule, in one sentence: a row describes a forecast *origin* hour `o`, and every feature may only use data whose
timestamp is <= o - latency (pollutants) or <= o (weather); the targets `y_h<H>` are the only values taken from after `o`,
and they are never inputs.

  * `origin_utc` is the hour label (midpoint of the provider's hourly period, see clean.py). A period labelled `o` finishes
    30 minutes after `o` (in IST hours), so the forecast really starts at o+30 min; using o as "the last observed hour" is
    therefore a slightly conservative reading, not an optimistic one.
  * `latency_hours` models publication delay. Observed delay in the live OpenAQ/CPCB feed was about two days; with
    latency_hours = 0 the training rows describe an instantaneous feed that does not exist operationally (the report says so).
  * Weather features come from the archive (reanalysis-like). They use hours <= o only. Weather *at or after* o, which a
    real system would have to take from a weather forecast, is deliberately not provided: feeding archive weather from the
    future hours of the target would be leakage of a perfect forecast.
  * Rolling statistics and lags look backwards only and use usable observations only; missing hours are skipped, never
    filled, and every window reports how many observations it contained (`*_n`).
  * Time features are computed in IST (the human daily cycle), from the origin timestamp only.
"""

import json
import math
from collections import deque
from datetime import datetime, timedelta, timezone

from app.core.time import to_ist, utc_now
from app.history.ingest_air import iso, parse_iso
from app.history.store import HistoryStore
from app.history.units import POLLUTANTS, WEATHER_VARIABLES

HOUR = timedelta(hours=1)
LAGS = [0, 1, 2, 3, 6, 12, 24, 48, 168]
WINDOWS = [3, 6, 12, 24, 72]
HORIZONS = [1, 3, 6, 12, 24, 48, 72]
WX_LAGS = [3, 6]
RAIN_MM = 0.1
MAX_LOOKBACK = 168  # longest look-back of any feature; "hours since rain" beyond it is unknown, so a serving window of that length gives the same value as full history


# ---------------------------------------------------------------------------------------------- small numeric helpers
def wind_components(speed_kmh: float | None, direction_deg: float | None) -> tuple[float | None, float | None, float | None]:
    """(speed m/s, u eastward, v northward). Meteorological convention: direction is where the wind blows FROM, so a 0° wind
    (from the north) has v < 0. Returns Nones if either input is missing."""
    if speed_kmh is None or direction_deg is None:
        return None, None, None
    ms = speed_kmh / 3.6
    rad = math.radians(direction_deg)
    return ms, -ms * math.sin(rad), -ms * math.cos(rad)


def rolling(arr: list[float | None], w: int) -> tuple[list, list, list, list, list]:
    """Backward-looking window [i-w+1, i] statistics ignoring None: mean, sample std, min, max, count. O(n)."""
    n = len(arr)
    s1 = [0.0] * (n + 1)
    s2 = [0.0] * (n + 1)
    cnt = [0] * (n + 1)
    for i, v in enumerate(arr):
        s1[i + 1] = s1[i] + (v or 0.0)
        s2[i + 1] = s2[i] + ((v * v) if v is not None else 0.0)
        cnt[i + 1] = cnt[i] + (v is not None)
    mn_q: deque[int] = deque()
    mx_q: deque[int] = deque()
    means, stds, mins, maxs, counts = [], [], [], [], []
    for i, v in enumerate(arr):
        if v is not None:
            while mn_q and arr[mn_q[-1]] >= v:
                mn_q.pop()
            mn_q.append(i)
            while mx_q and arr[mx_q[-1]] <= v:
                mx_q.pop()
            mx_q.append(i)
        while mn_q and mn_q[0] <= i - w:
            mn_q.popleft()
        while mx_q and mx_q[0] <= i - w:
            mx_q.popleft()
        lo = max(0, i - w + 1)
        c = cnt[i + 1] - cnt[lo]
        counts.append(c)
        if c == 0:
            means.append(None), stds.append(None), mins.append(None), maxs.append(None)
            continue
        m = (s1[i + 1] - s1[lo]) / c
        means.append(m)
        stds.append(math.sqrt(max(0.0, ((s2[i + 1] - s2[lo]) - c * m * m) / (c - 1))) if c > 1 else None)
        mins.append(arr[mn_q[0]])
        maxs.append(arr[mx_q[0]])
    return means, stds, mins, maxs, counts


def at(arr: list, i: int):
    return arr[i] if 0 <= i < len(arr) else None


# ---------------------------------------------------------------------------------------------- column layout
def feature_columns(horizons: list[int]) -> list[str]:
    cols = ["station_id", "pollutant", "origin_utc", "origin_ist"]
    cols += ["hour_ist", "dow_ist", "month_ist", "is_weekend_ist", "hour_sin", "hour_cos", "doy_sin", "doy_cos"]
    cols += [f"target_lag{k}" for k in LAGS]
    for w in WINDOWS:
        cols += [f"target_mean_{w}h", f"target_std_{w}h", f"target_min_{w}h", f"target_max_{w}h", f"target_n_{w}h"]
    cols += [f"obs_{q}" for q in POLLUTANTS]
    cols += ["wx_temp", "wx_rh", "wx_dew", "wx_pressure", "wx_wind_ms", "wx_wind_u", "wx_wind_v", "wx_gust_ms", "wx_precip", "wx_cloud", "wx_blh", "wx_sw"]
    cols += ["wx_pressure_tend_3h"]
    for k in WX_LAGS:
        cols += [f"wx_{n}_lag{k}" for n in ("temp", "rh", "wind_u", "wind_v", "blh")]
    cols += ["wx_precip_sum_24h", "wx_wind_ms_mean_6h", "wx_wind_ms_mean_24h", "wx_blh_mean_6h", "wx_blh_mean_24h", "wx_hours_since_rain"]
    cols += ["wx_provisional", "target_low_coverage"]
    cols += [f"y_h{h}" for h in horizons]
    return cols


def target_columns(horizons: list[int]) -> list[str]:
    return [f"y_h{h}" for h in horizons]


# ---------------------------------------------------------------------------------------------- the pure core
def compute_rows(
    station_id: int, pollutant: str, times: list[datetime], series: dict[str, list[float | None]],
    weather: dict[str, list[float | None]], provisional: list[int], soft_flagged: list[int],
    horizons: list[int] = HORIZONS, latency_hours: int = 0,
) -> list[tuple]:
    """Feature rows for one station and target pollutant over an hourly grid `times` (consecutive hours, UTC).

    series[q]    usable µg/m³ values per pollutant (None = missing or unusable)
    weather[var] archive values per Open-Meteo variable name (None = missing or out of range)
    Row i uses series data only at indices <= i - latency_hours and weather at indices <= i.
    """
    n = len(times)
    target = series[pollutant]
    cols = feature_columns(horizons)
    roll = {w: rolling(target, w) for w in WINDOWS}

    ms: list[float | None] = []
    uu: list[float | None] = []
    vv: list[float | None] = []
    for s, d in zip(weather["wind_speed_10m"], weather["wind_direction_10m"]):
        a, b, c = wind_components(s, d)
        ms.append(a), uu.append(b), vv.append(c)
    gust = [None if g is None else g / 3.6 for g in weather["wind_gusts_10m"]]
    precip = weather["precipitation"]
    blh = weather["boundary_layer_height"]
    precip24 = rolling(precip, 24)
    ms6, ms24 = rolling(ms, 6)[0], rolling(ms, 24)[0]
    blh6, blh24 = rolling(blh, 6)[0], rolling(blh, 24)[0]
    # precipitation 24 h *sum* (not mean): sum = mean * count; only trusted when the window is complete
    precip_sum = [None if (m is None or c < 24) else m * c for m, c in zip(precip24[0], precip24[4])]
    last_rain = -1
    since_rain: list[int | None] = []
    for i, p in enumerate(precip):
        if p is not None and p >= RAIN_MM:
            last_rain = i
        since_rain.append(i - last_rain if last_rain >= 0 and i - last_rain <= MAX_LOOKBACK else None)

    rows: list[tuple] = []
    for i in range(n):
        c = i - latency_hours  # newest pollutant index this row may use
        if c < 0 or target[c] is None:
            continue
        t = times[i]
        ist = to_ist(t)
        doy = ist.timetuple().tm_yday
        rec: dict[str, object] = {
            "station_id": station_id, "pollutant": pollutant, "origin_utc": iso(t), "origin_ist": ist.isoformat(),
            "hour_ist": ist.hour, "dow_ist": ist.weekday(), "month_ist": ist.month, "is_weekend_ist": int(ist.weekday() >= 5),
            "hour_sin": math.sin(2 * math.pi * ist.hour / 24), "hour_cos": math.cos(2 * math.pi * ist.hour / 24),
            "doy_sin": math.sin(2 * math.pi * doy / 366), "doy_cos": math.cos(2 * math.pi * doy / 366),
        }
        for k in LAGS:
            rec[f"target_lag{k}"] = at(target, c - k)
        for w in WINDOWS:
            mean, std, mn, mx, cnt = roll[w]
            ok = cnt[c] >= math.ceil(w / 2)  # a window with fewer than half its hours observed is reported as unknown
            rec[f"target_mean_{w}h"] = mean[c] if ok else None
            rec[f"target_std_{w}h"] = std[c] if ok else None
            rec[f"target_min_{w}h"] = mn[c] if ok else None
            rec[f"target_max_{w}h"] = mx[c] if ok else None
            rec[f"target_n_{w}h"] = cnt[c]
        for q in POLLUTANTS:
            rec[f"obs_{q}"] = at(series[q], c)
        rec.update({
            "wx_temp": weather["temperature_2m"][i], "wx_rh": weather["relative_humidity_2m"][i], "wx_dew": weather["dew_point_2m"][i],
            "wx_pressure": weather["surface_pressure"][i], "wx_wind_ms": ms[i], "wx_wind_u": uu[i], "wx_wind_v": vv[i],
            "wx_gust_ms": gust[i], "wx_precip": precip[i], "wx_cloud": weather["cloud_cover"][i], "wx_blh": blh[i],
            "wx_sw": weather["shortwave_radiation"][i],
        })
        p0, p3 = weather["surface_pressure"][i], at(weather["surface_pressure"], i - 3)
        rec["wx_pressure_tend_3h"] = None if p0 is None or p3 is None else p0 - p3
        for k in WX_LAGS:
            for name, arr in (("temp", weather["temperature_2m"]), ("rh", weather["relative_humidity_2m"]), ("wind_u", uu),
                              ("wind_v", vv), ("blh", blh)):
                rec[f"wx_{name}_lag{k}"] = at(arr, i - k)
        rec["wx_precip_sum_24h"] = precip_sum[i]
        rec["wx_wind_ms_mean_6h"], rec["wx_wind_ms_mean_24h"] = ms6[i], ms24[i]
        rec["wx_blh_mean_6h"], rec["wx_blh_mean_24h"] = blh6[i], blh24[i]
        rec["wx_hours_since_rain"] = since_rain[i]
        rec["wx_provisional"] = provisional[i]
        rec["target_low_coverage"] = soft_flagged[c]
        for h in horizons:
            rec[f"y_h{h}"] = at(target, i + h)  # the ONLY values taken from after the origin; targets, never inputs
        rows.append(tuple(rec[col] for col in cols))
    return rows


# ---------------------------------------------------------------------------------------------- store integration
def _grid(store: HistoryStore, station_id: int, pollutant: str, start: datetime | None = None, end: datetime | None = None):
    if start is not None and end is not None:
        return store.query("select label_utc, value_std, usable, flags from clean_air where station_id=? and pollutant=? "
                           "and label_utc between ? and ? order by label_utc", (station_id, pollutant, iso(start), iso(end)))
    return store.query("select label_utc, value_std, usable, flags from clean_air where station_id=? and pollutant=? order by label_utc",
                       (station_id, pollutant))


def load_station_inputs(store: HistoryStore, station_id: int, pollutant: str, start: datetime | None = None, end: datetime | None = None):
    """Aligned arrays for one station and target pollutant, or None if there is nothing usable.

    With `start`/`end` the grid covers exactly that hourly range (used at serving time so that a prediction is built by the same
    code as a training row); without them it spans the station's first to last usable target hour."""
    target_rows = _grid(store, station_id, pollutant, start, end)
    usable_labels = [parse_iso(r["label_utc"]) for r in target_rows if r["usable"]]
    if not usable_labels:
        return None
    windowed = start is not None and end is not None
    if not windowed:
        start, end = usable_labels[0], usable_labels[-1]
    # the grid ends at the last usable target hour, so horizons that would run past the data are None (never filled)
    n = int((end - start) / HOUR) + 1
    times = [start + i * HOUR for i in range(n)]
    index = {iso(t): i for i, t in enumerate(times)}

    def aligned(rows_):
        arr: list[float | None] = [None] * n
        for r in rows_:
            i = index.get(r["label_utc"])
            if i is not None and r["usable"]:
                arr[i] = r["value_std"]
        return arr

    series = {q: aligned(_grid(store, station_id, q, start if windowed else None, end if windowed else None)) for q in POLLUTANTS}
    # Only a flag that depends on the row itself may be a feature. FLATLINE (needs later hours) and REVISED (needs a later fetch)
    # describe the future of the row, so they stay visible in clean_air but never enter model_ready.
    soft = [0] * n
    for r in target_rows:
        i = index.get(r["label_utc"])
        if i is not None and "LOW_COVERAGE" in (r["flags"] or "").split(","):
            soft[i] = 1
    weather: dict[str, list[float | None]] = {v: [None] * n for v in WEATHER_VARIABLES}
    provisional = [0] * n
    for r in store.query("select * from clean_weather where station_id=? and time_utc between ? and ? order by time_utc",
                         (station_id, iso(start), iso(end))):
        i = index.get(r["time_utc"])
        if i is None:
            continue
        bad = {f.split(":", 1)[1] for f in (r["flags"] or "").split(",") if f.startswith("OUT_OF_RANGE:")}
        for v in WEATHER_VARIABLES:
            weather[v][i] = None if v in bad else r[v]
        provisional[i] = r["provisional"]
    return times, series, weather, provisional, soft


def refresh_stations(store: HistoryStore, station_ids: list[int], pollutants: list[str], horizons: list[int] = HORIZONS, latency_hours: int = 0,
                     name: str = "model_ready") -> dict:
    """Recompute the feature rows of some stations in an existing feature table (after their cleaned data changed), leaving all other
    stations' rows as they are. The set's digest and row count are updated so a later training run records what it really used."""
    cols = feature_columns(horizons)
    marks = ",".join("?" * len(station_ids))
    store.execute(f"delete from {name} where station_id in ({marks})", tuple(station_ids))
    added = 0
    for pollutant in pollutants:
        for sid in station_ids:
            loaded = load_station_inputs(store, sid, pollutant)
            if loaded is None:
                continue
            rows = compute_rows(sid, pollutant, *loaded, horizons=horizons, latency_hours=latency_hours)
            store.executemany(f"insert or replace into {name} values ({','.join('?' * len(cols))})", rows)
            added += len(rows)
    store.commit()
    total = store.query(f"select count(*) from {name}")[0][0]
    digest = store.digest(name, "station_id, pollutant, origin_utc")
    store.execute("update feature_sets set rows=?, digest=? where name=?", (total, digest, name))
    store.commit()
    return {"rows_added": added, "rows_total": total, "digest": digest}


def build_model_ready(store: HistoryStore, pollutants: list[str], horizons: list[int] = HORIZONS, latency_hours: int = 0,
                      name: str = "model_ready", now: datetime | None = None) -> dict:
    cols = feature_columns(horizons)
    store.execute(f"drop table if exists {name}")
    defs = []
    for c in cols:
        kind = "integer" if c in ("station_id", "hour_ist", "dow_ist", "month_ist", "is_weekend_ist", "wx_provisional", "target_low_coverage") or c.endswith(("_n_3h", "_n_6h", "_n_12h", "_n_24h", "_n_72h")) else "text" if c in ("pollutant", "origin_utc", "origin_ist") else "real"
        defs.append(f"{c} {kind}")
    store.execute(f"create table {name} ({', '.join(defs)}, primary key (station_id, pollutant, origin_utc))")
    total = 0
    for pollutant in pollutants:
        for st in store.query("select distinct station_id from clean_air where pollutant=? and usable=1 order by station_id", (pollutant,)):
            loaded = load_station_inputs(store, st["station_id"], pollutant)
            if loaded is None:
                continue
            rows = compute_rows(st["station_id"], pollutant, *loaded, horizons=horizons, latency_hours=latency_hours)
            store.executemany(f"insert into {name} values ({','.join('?' * len(cols))})", rows)
            total += len(rows)
    store.commit()
    digest = store.digest(name, "station_id, pollutant, origin_utc")
    params = {"pollutants": pollutants, "horizons": horizons, "latency_hours": latency_hours, "lags": LAGS, "windows": WINDOWS}
    store.execute("insert or replace into feature_sets (name, created_at, params, columns, rows, digest) values (?,?,?,?,?,?)",
                  (name, iso(now or utc_now()), json.dumps(params), json.dumps(cols), total, digest))
    store.commit()
    return {"rows": total, "columns": len(cols), "digest": digest, "targets": target_columns(horizons)}
