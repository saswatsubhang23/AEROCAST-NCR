"""Historical weather ingestion from the Open-Meteo archive API into `raw_weather` (append-only, resumable).

Endpoint: GET https://archive-api.open-meteo.com/v1/archive (documented by Open-Meteo, no key). Verified during
development: it returns hourly values in UTC (`timezone=GMT`) with the grid cell actually used (latitude/longitude/elevation).
Two behaviours that matter and are handled here:
  * for recent days the archive blends in forecast-model output and it returns hours of the *current day that have not
    happened yet*. Rows stamped after the fetch time are dropped, and rows within PROVISIONAL_DAYS of the fetch are flagged
    provisional by the cleaning step (the 7-day figure is a conservative choice of this pipeline, not a provider statement);
  * values are model/reanalysis output for a grid cell, not station measurements.
"""

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from app.core.time import utc_now
from app.history.ingest_air import MAX_CONSECUTIVE_FAILURES, iso, parse_iso
from app.history.store import HistoryStore
from app.history.units import EXPECTED_WEATHER_UNITS, WEATHER_VARIABLES
from app.integrations.http import UpstreamError
from app.integrations.openmeteo import OpenMeteoClient

logger = logging.getLogger("app.history")
BATCH_POINTS = 5
WINDOW_DAYS = 90
PROVISIONAL_DAYS = 7
FINAL_AFTER_DAYS = 10  # windows ending more recently than this are re-fetched on every run (values can be revised)


def point_id(station_id: int) -> str:
    return f"st{station_id}"


def parse_time(s: str) -> datetime | None:
    return parse_iso(s if s.endswith("Z") or "+" in s else s + "Z")  # archive times are UTC without a suffix


INSERT = ("insert or ignore into raw_weather (row_key,point_id,time_utc," + ",".join(WEATHER_VARIABLES) +
          ",fetched_at,run_id) values (?,?,?," + ",".join("?" * len(WEATHER_VARIABLES)) + ",?,?)")


def rows_from_response(item: dict, pid: str, fetched_at: datetime, run_id: str) -> tuple[list[tuple], list[str]]:
    """Raw rows for one location of a response, never including hours after `fetched_at`. Also returns problems seen."""
    hourly = item.get("hourly") or {}
    times = hourly.get("time") or []
    problems: list[str] = []
    units = item.get("hourly_units") or {}
    for var in WEATHER_VARIABLES:
        if var in hourly and units.get(var) != EXPECTED_WEATHER_UNITS[var]:
            problems.append(f"{var}: unit {units.get(var)!r}, expected {EXPECTED_WEATHER_UNITS[var]!r}")
    out = []
    for i, t in enumerate(times):
        ts = parse_time(t)
        if ts is None or ts > fetched_at:
            continue
        vals = []
        for var in WEATHER_VARIABLES:
            col = hourly.get(var)
            v = col[i] if col is not None and i < len(col) else None
            vals.append(float(v) if isinstance(v, (int, float)) else None)
        key = hashlib.sha1(f"{pid}|{iso(ts)}|{vals!r}".encode()).hexdigest()
        out.append((key, pid, iso(ts), *vals, iso(fetched_at), run_id))
    return out, problems


async def backfill_weather(
    store: HistoryStore, client: OpenMeteoClient, window_from: datetime, window_to: datetime, run_id: str, *,
    now: Callable[[], datetime] = utc_now, progress: Callable[[str], None] | None = None,
) -> dict:
    stations = store.query("select distinct s.station_id, s.lat, s.lon from stations s join sensors x on x.station_id = s.station_id order by s.station_id")
    requests = rows_added = failed = skipped = consecutive = 0
    problems: list[str] = []
    for w_start in range(0, (window_to - window_from).days + 1, WINDOW_DAYS):
        w_from = window_from + timedelta(days=w_start)
        w_to = min(w_from + timedelta(days=WINDOW_DAYS), window_to)
        if w_from >= window_to:
            break
        todo = [s for s in stations if not store.query(
            "select 1 from raw_weather_progress where point_id=? and window_from=? and window_to=? and status='done'",
            (point_id(s["station_id"]), iso(w_from), iso(w_to)))]
        skipped += len(stations) - len(todo)
        for b in range(0, len(todo), BATCH_POINTS):
            batch = todo[b:b + BATCH_POINTS]
            fetched = now()
            params = {
                "latitude": ",".join(str(round(s["lat"], 4)) for s in batch), "longitude": ",".join(str(round(s["lon"], 4)) for s in batch),
                "start_date": w_from.date().isoformat(), "end_date": (w_to - timedelta(days=1)).date().isoformat(),
                "hourly": ",".join(WEATHER_VARIABLES), "timezone": "GMT", "temperature_unit": "celsius",
                "wind_speed_unit": "kmh", "precipitation_unit": "mm",
            }
            try:
                body = await client.get_archive(params)
                requests += 1
            except UpstreamError as exc:
                requests += 1
                failed += 1
                consecutive += 1
                logger.warning("weather window %s failed: %s", w_from.date(), exc)
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    return {"requests": requests, "rows_added": rows_added, "failed_windows": failed, "skipped_windows": skipped,
                            "problems": problems, "note": f"stopped after {MAX_CONSECUTIVE_FAILURES} consecutive failures; run again to resume"}
                continue
            consecutive = 0
            items = body if isinstance(body, list) else [body]
            if len(items) != len(batch):
                failed += 1
                problems.append(f"expected {len(batch)} locations, received {len(items)}")
                continue
            final = w_to <= fetched - timedelta(days=FINAL_AFTER_DAYS)
            for st, item in zip(batch, items):
                pid = point_id(st["station_id"])
                rows, probs = rows_from_response(item, pid, fetched, run_id)
                problems += [f"{pid}: {p}" for p in probs]
                before = store.db.total_changes
                store.executemany(INSERT, rows)
                rows_added += store.db.total_changes - before
                store.execute(
                    "insert or ignore into raw_weather_meta (run_id,point_id,station_id,lat_requested,lon_requested,grid_lat,grid_lon,elevation_m,units,request,fetched_at) "
                    "values (?,?,?,?,?,?,?,?,?,?,?)",
                    (run_id, pid, st["station_id"], st["lat"], st["lon"], item.get("latitude"), item.get("longitude"), item.get("elevation"),
                     json.dumps(item.get("hourly_units") or {}, sort_keys=True), json.dumps({k: v for k, v in params.items() if k not in ("latitude", "longitude")}, sort_keys=True) + f"@{pid}", iso(fetched)),
                )
                store.execute("insert or replace into raw_weather_progress (point_id,window_from,window_to,status,rows,finished_at,run_id) values (?,?,?,?,?,?,?)",
                              (pid, iso(w_from), iso(w_to), "done" if final else "partial", len(rows), iso(fetched), run_id))
            store.commit()
            if progress:
                progress(f"weather {w_from.date()}..{w_to.date()} points {batch[0]['station_id']}..{batch[-1]['station_id']}: rows so far {rows_added}")
    return {"requests": requests, "rows_added": rows_added, "failed_windows": failed, "skipped_windows": skipped, "problems": sorted(set(problems))[:20], "note": ""}
