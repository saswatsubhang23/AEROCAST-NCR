"""Historical air-quality ingestion from OpenAQ v3 into `raw_air` (append-only, resumable).

Endpoints used, all documented in OpenAQ's OpenAPI spec and exercised during development:
  GET /v3/locations?bbox=...            station inventory (reuses OpenAQClient.locations)
  GET /v3/locations/{id}/sensors        every sensor of a station with its own datetimeFirst/datetimeLast
  GET /v3/sensors/{id}/hours            hourly aggregates (period from/to in UTC and local time, coverage, summary)
Nothing is invented: a sensor or window with no data simply yields no rows.
"""

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta, timezone

from app.core.time import utc_now
from app.history.regions import agency_of, zone_of
from app.history.store import HistoryStore
from app.history.units import POLLUTANTS
from app.integrations.http import UpstreamAuthError, UpstreamError
from app.integrations.openaq import AqNotConfigured, OpenAQClient
from app.services.air_quality import AQ_BBOX

logger = logging.getLogger("app.history")
PAGE_LIMIT = 1000
MAX_CONSECUTIVE_FAILURES = 5
REFRESH_DAYS = 10  # a window ending more recently than this is re-fetched on every run, because providers revise recent data


def iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def start_run(store: HistoryStore, kind: str, params: dict, now: datetime | None = None) -> str:
    run_id = uuid.uuid4().hex[:12]
    store.execute("insert into ingest_runs (run_id, kind, started_at, status, params) values (?,?,?,?,?)",
                  (run_id, kind, iso(now or utc_now()), "running", json.dumps(params, sort_keys=True, default=str)))
    store.commit()
    return run_id


def finish_run(store: HistoryStore, run_id: str, status: str, requests: int, rows: int, note: str = "", now: datetime | None = None) -> None:
    store.execute("update ingest_runs set finished_at=?, status=?, requests=?, rows_added=?, note=? where run_id=?",
                  (iso(now or utc_now()), status, requests, rows, note, run_id))
    store.commit()


def _utc(obj) -> str | None:
    return (obj or {}).get("utc") if isinstance(obj, dict) else None


# ---------------------------------------------------------------------------------------------- discovery
async def discover(store: HistoryStore, client: OpenAQClient, window_from: datetime, run_id: str, now: datetime | None = None) -> dict:
    """Store every station in the NCR box and the sensors of those that reported on/after `window_from`."""
    now = now or utc_now()
    raw = await client.locations(AQ_BBOX)
    stations = 0
    relevant: list[int] = []
    for loc in raw:
        try:
            sid = int(loc["id"])
            lat, lon = float(loc["coordinates"]["latitude"]), float(loc["coordinates"]["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        if loc.get("isMobile"):
            continue
        last = parse_iso(_utc(loc.get("datetimeLast")))
        owner = (loc.get("owner") or {}).get("name")
        lic = ", ".join(x.get("name", "") for x in (loc.get("licenses") or []) if isinstance(x, dict)) or None
        store.execute(
            "insert or replace into stations (station_id,name,locality,lat,lon,provider,owner,license,is_monitor,timezone,"
            "datetime_first,datetime_last,zone,agency,discovered_at,run_id) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, loc.get("name"), loc.get("locality"), lat, lon, (loc.get("provider") or {}).get("name"), owner, lic,
             int(bool(loc.get("isMonitor"))), loc.get("timezone"), _utc(loc.get("datetimeFirst")), _utc(loc.get("datetimeLast")),
             zone_of(lat, lon), agency_of(owner), iso(now), run_id),
        )
        stations += 1
        if last is not None and last >= window_from:
            relevant.append(sid)
    store.commit()

    sensors = 0
    for sid in relevant:
        for s in await client.sensors(sid):
            param = (s.get("parameter") or {}).get("name")
            if param not in POLLUTANTS:
                continue
            store.execute(
                "insert or replace into sensors (sensor_id,station_id,parameter,units,datetime_first,datetime_last,discovered_at,run_id) "
                "values (?,?,?,?,?,?,?,?)",
                (int(s["id"]), sid, param, (s.get("parameter") or {}).get("units"), _utc(s.get("datetimeFirst")),
                 _utc(s.get("datetimeLast")), iso(now), run_id),
            )
            sensors += 1
        store.commit()
    return {"stations": stations, "stations_in_window": len(relevant), "sensors": sensors}


# ---------------------------------------------------------------------------------------------- backfill
def windows(start: datetime, end: datetime, days: int) -> list[tuple[datetime, datetime]]:
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        out.append((cur, nxt))
        cur = nxt
    return out


def parse_hour_row(sensor_id: int, station_id: int, parameter: str, row: dict, fetched_at: str, run_id: str) -> tuple | None:
    """One OpenAQ hourly aggregate to a raw_air row. The provider's own fields are kept as given."""
    period = row.get("period") or {}
    to_utc = _utc(period.get("datetimeTo"))
    if not to_utc:
        return None
    cov = row.get("coverage") or {}
    summ = row.get("summary") or {}
    value = row.get("value")
    units = (row.get("parameter") or {}).get("units")
    key = hashlib.sha1(f"{sensor_id}|{to_utc}|{value!r}|{units}".encode()).hexdigest()
    num = lambda v: float(v) if isinstance(v, (int, float)) else None  # noqa: E731
    return (key, sensor_id, station_id, parameter, units, _utc(period.get("datetimeFrom")), to_utc,
            (period.get("datetimeTo") or {}).get("local"), num(value), num(summ.get("min")), num(summ.get("max")), num(summ.get("sd")),
            cov.get("expectedCount"), cov.get("observedCount"), num(cov.get("percentCoverage")),
            int(bool((row.get("flagInfo") or {}).get("hasFlags"))), fetched_at, run_id)


INSERT_RAW = ("insert or ignore into raw_air (row_key,sensor_id,station_id,parameter,units,period_from_utc,period_to_utc,period_to_local,"
              "value,summary_min,summary_max,summary_sd,expected_count,observed_count,percent_coverage,has_flags,fetched_at,run_id) "
              "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")


async def backfill(
    store: HistoryStore, client: OpenAQClient, window_from: datetime, window_to: datetime, run_id: str, *,
    chunk_days: int = 40, now: Callable[[], datetime] = utc_now, progress: Callable[[str], None] | None = None,
    max_requests: int | None = None, parameters: list[str] | None = None, concurrency: int = 4,
) -> dict:
    """Fetch every (sensor, window) not yet completed. Re-running resumes; completed windows are skipped.

    `concurrency` overlaps network latency only: the client still spaces request *starts* to stay under the provider's rate
    limit, and all database writes happen on the event loop one at a time."""
    params = parameters or POLLUTANTS
    sensors = store.query("select * from sensors where parameter in (%s) order by station_id, parameter, sensor_id" % ",".join("?" * len(params)), tuple(params))
    jobs: list[tuple] = []
    skipped = 0
    for sensor in sensors:
        first, last = parse_iso(sensor["datetime_first"]), parse_iso(sensor["datetime_last"])
        for w_from, w_to in windows(window_from, window_to, chunk_days):
            if (first and w_to < first - timedelta(days=1)) or (last and w_from > last + timedelta(days=1)):
                continue  # the sensor has no data in this window by its own first/last dates
            done = store.query("select status from raw_air_progress where sensor_id=? and window_from=? and window_to=?",
                               (sensor["sensor_id"], iso(w_from), iso(w_to)))
            if done and done[0][0] == "done":
                skipped += 1
                continue
            jobs.append((sensor, w_from, w_to))

    state = {"requests": 0, "rows": 0, "failed": 0, "consecutive": 0, "note": "", "stop": False}
    queue: asyncio.Queue = asyncio.Queue()
    for j in jobs:
        queue.put_nowait(j)

    async def fetch(sensor, w_from, w_to):
        page, results_all, requests = 1, [], 0
        while True:
            results = await client.hours_page(sensor["sensor_id"], w_from, w_to, page, PAGE_LIMIT)
            requests += 1
            results_all += results
            if len(results) < PAGE_LIMIT:
                return results_all, requests
            page += 1

    async def worker():
        while not state["stop"]:
            try:
                sensor, w_from, w_to = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            if max_requests is not None and state["requests"] >= max_requests:
                state["note"] = f"stopped at the request budget ({max_requests}); run again to resume"
                state["stop"] = True
                return
            fetched_at = iso(now())
            ok, results, req = True, [], 1
            try:
                results, req = await fetch(sensor, w_from, w_to)
            except (AqNotConfigured, UpstreamAuthError):
                state["stop"] = True
                raise
            except UpstreamError as exc:
                logger.warning("sensor %s window %s failed: %s", sensor["sensor_id"], iso(w_from), exc)
                ok = False
            state["requests"] += req
            chunk_rows = 0
            if ok:
                batch = [r for r in (parse_hour_row(sensor["sensor_id"], sensor["station_id"], sensor["parameter"], x, fetched_at, run_id) for x in results) if r]
                before = store.db.total_changes
                store.executemany(INSERT_RAW, batch)
                chunk_rows = store.db.total_changes - before
                state["rows"] += chunk_rows
                state["consecutive"] = 0
                store.execute("insert or replace into raw_air_progress (sensor_id,window_from,window_to,status,rows,requests,finished_at,run_id) "
                              "values (?,?,?,?,?,?,?,?)", (sensor["sensor_id"], iso(w_from), iso(w_to), "done" if w_to <= now() - timedelta(days=REFRESH_DAYS) else "partial",
                                              chunk_rows, req, iso(now()), run_id))
            else:
                state["failed"] += 1
                state["consecutive"] += 1
            store.commit()
            if progress:
                progress(f"sensor {sensor['sensor_id']} {sensor['parameter']} {w_from.date()}..{w_to.date()}: "
                         f"{'ok' if ok else 'FAILED'} +{chunk_rows} rows (requests so far {state['requests']}, queue {queue.qsize()})")
            if state["consecutive"] >= MAX_CONSECUTIVE_FAILURES:
                state["note"] = f"stopped after {MAX_CONSECUTIVE_FAILURES} consecutive failures (possible rate limit); run again to resume"
                state["stop"] = True

    await asyncio.gather(*[worker() for _ in range(max(1, concurrency))])
    return _summary(state["requests"], state["rows"], state["failed"], skipped, state["note"])


def _summary(requests: int, rows: int, failed: int, skipped: int, note: str) -> dict:
    return {"requests": requests, "rows_added": rows, "failed_windows": failed, "skipped_windows": skipped, "note": note}
