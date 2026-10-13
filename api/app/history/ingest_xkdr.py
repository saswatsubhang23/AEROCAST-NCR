"""Second air-quality source: the XKDR "India air quality" archive (https://airquality.xkdr.org, key in INDIA_AQI_API_KEY).

What it is (from its own `/v1/meta`): CPCB CAAQM station readings (plus US-embassy monitors) from 2009, one reading per hour in
most cases (`n` = 1), timestamps naive in IST. For Delhi-NCR it ends on 2025-09-01, i.e. it is a *history*, not a live feed, but it
sits directly before the OpenAQ window (from 2025-10-09) and so lengthens the training period from one year to several.

Rows go into the same `raw_air` layer as OpenAQ so cleaning, flags, features and training are shared. Differences, all recorded:
  * ids: stations that match an existing OpenAQ station (same normalised name, or within 300 m) reuse its id, so one station is one
    series; unmatched stations get 9_000_000_000 + the numeric part of the XKDR id. Sensor ids are synthetic (9e9 + site*10 + parameter).
  * time: `period_start` is read as the start of an IST hour, i.e. the period (start, start+1 h) like the CPCB hours OpenAQ serves;
    this alignment is an ASSUMPTION that could not be cross-checked (no overlapping period with OpenAQ exists), at most one hour off.
  * coverage: XKDR gives a reading count, not a coverage percentage, so `percent_coverage` is left empty (no LOW_COVERAGE flag).
The key is sent only in the Authorization header and is never logged.
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

import httpx

from app.core.places import distance_km
from app.history.ingest_air import INSERT_RAW, finish_run, iso, start_run
from app.history.regions import agency_of, zone_of
from app.history.store import HistoryStore

logger = logging.getLogger("app.history.xkdr")

BASE_URL = "https://airquality.xkdr.org"
ID_OFFSET = 9_000_000_000
PARAMS = {"PM2.5": "pm25", "PM10": "pm10", "NO2": "no2", "SO2": "so2", "Ozone": "o3", "CO": "co"}
PARAM_INDEX = {p: i for i, p in enumerate(PARAMS.values())}
IST = timedelta(hours=5, minutes=30)
# xKDR's metadata says `collected_at` is a naive IST time. That holds for the CPCB stations (their daily PM2.5 minimum falls at 16-17 IST in the
# xKDR period and in the later OpenAQ period alike), but NOT for the US-Embassy monitor: the same hourly series is served by OpenAQ, and
# the two agree perfectly (r = 1.000, MAE 0.0 over 1,306 hours, docs/phase1/xkdr-alignment.json) only when xKDR's times are read as UTC.
# Read as IST they put the daily minimum at 10:00, which is physically implausible for Delhi. Sources listed here are therefore read as UTC.
UTC_NAIVE_SOURCES = frozenset({"us_embassy"})
MATCH_KM = 0.3
NCR_BOX = (27.9, 29.2, 76.4, 78.1)  # lat_min, lat_max, lon_min, lon_max: same area the OpenAQ discovery covers
KIND = "ingest-air-xkdr"


class XkdrError(Exception):
    pass


def _norm(name: str | None) -> str:
    return "".join(ch for ch in (name or "").lower() if ch.isalnum())


def site_number(station_id: str) -> int:
    digits = "".join(ch for ch in station_id if ch.isdigit())
    return int(digits) if digits else int(hashlib.sha1(station_id.encode()).hexdigest()[:8], 16)


def sensor_id_for(station_id: str, pollutant: str) -> int:
    return ID_OFFSET + site_number(station_id) * 10 + PARAM_INDEX[pollutant]


class XkdrClient:
    def __init__(self, api_key: str, transport: httpx.AsyncBaseTransport | None = None, base_url: str = BASE_URL, timeout: float = 120.0):
        if not api_key:
            raise XkdrError("INDIA_AQI_API_KEY is not set.")
        self._key, self._transport, self._base, self._timeout = api_key, transport, base_url.rstrip("/"), timeout
        self.requests = 0

    async def get(self, path: str, params: dict) -> dict:
        last = "unknown"
        for attempt in range(1, 5):
            self.requests += 1
            try:
                async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as c:
                    r = await c.get(f"{self._base}{path}", params=params, headers={"Authorization": f"Bearer {self._key}"})
            except httpx.HTTPError as exc:
                last = type(exc).__name__
            else:
                if r.status_code in (401, 403):
                    raise XkdrError("The India air-quality API rejected the configured key.")
                if r.status_code == 200:
                    try:
                        return r.json()
                    except ValueError:
                        last = "not JSON"
                else:
                    last = f"HTTP {r.status_code}"
            await asyncio.sleep(2.0 * attempt)
        raise XkdrError(f"India air-quality API request failed ({last}).")


def in_ncr(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and NCR_BOX[0] <= lat <= NCR_BOX[1] and NCR_BOX[2] <= lon <= NCR_BOX[3]


async def discover(store: HistoryStore, client: XkdrClient, run_id: str) -> dict:
    """Station list for the NCR box, matched to existing stations; registers new stations and one sensor per (station, pollutant)."""
    body = await client.get("/v1/stations", {})
    existing = [dict(r) for r in store.query("select station_id, name, lat, lon from stations where station_id < ?", (ID_OFFSET,))]
    by_name = {_norm(e["name"]): e for e in existing}
    now = iso(datetime.now(timezone.utc))
    mapping: dict[str, int] = {}
    sources: dict[str, str] = {}
    matched = created = 0
    for s in body.get("data", []):
        lat, lon = s.get("latitude"), s.get("longitude")
        if not in_ncr(lat, lon):
            continue
        sid = s["station_id"]
        hit = by_name.get(_norm(s.get("station_name"))) or next((e for e in existing if distance_km(lat, lon, e["lat"], e["lon"]) <= MATCH_KM), None)
        if hit:
            station_id, matched = hit["station_id"], matched + 1
        else:
            station_id, created = ID_OFFSET + site_number(sid), created + 1
            store.execute(
                "insert or ignore into stations (station_id,name,locality,lat,lon,provider,owner,license,is_monitor,timezone,datetime_first,datetime_last,"
                "zone,agency,discovered_at,run_id) values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (station_id, s.get("station_name"), s.get("city_name"), lat, lon, "XKDR India air quality archive", s.get("source"), None, 1, "Asia/Kolkata",
                 s.get("first_seen"), s.get("last_seen"), zone_of(lat, lon), agency_of(s.get("state_name")), now, run_id))
        mapping[sid] = station_id
        sources[sid] = str(s.get("source") or "")
        for name in s.get("parameters") or []:
            pol = PARAMS.get(name)
            if pol:
                store.execute("insert or replace into sensors (sensor_id,station_id,parameter,units,datetime_first,datetime_last,discovered_at,run_id) values (?,?,?,?,?,?,?,?)",
                              (sensor_id_for(sid, pol), station_id, pol, None, s.get("first_seen"), s.get("last_seen"), now, run_id))
    store.commit()
    return {"stations": len(mapping), "matched_existing": matched, "created": created, "map": mapping, "sources": sources}


def parse_row(station_id: int, sensor_id: int, pollutant: str, row: dict, fetched_at: str, run_id: str, naive_is_utc: bool = False) -> tuple | None:
    """`naive_is_utc`: the source's naive timestamps are UTC (see UTC_NAIVE_SOURCES); otherwise they are IST, as xKDR documents."""
    start = row.get("period_start")
    value = row.get("mean")
    if not start or not isinstance(value, (int, float)):
        return None
    try:
        naive = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
        t_from = naive if naive_is_utc else naive - IST  # naive IST -> UTC, or already UTC
    except ValueError:
        return None
    t_to = t_from + timedelta(hours=1)
    units = row.get("unit")
    key = hashlib.sha1(f"xkdr|{sensor_id}|{iso(t_to)}|{value!r}|{units}".encode()).hexdigest()
    num = lambda v: float(v) if isinstance(v, (int, float)) else None  # noqa: E731
    return (key, sensor_id, station_id, pollutant, units, iso(t_from), iso(t_to), (t_to + IST).strftime("%Y-%m-%dT%H:%M:%S+05:30"),
            float(value), num(row.get("min")), num(row.get("max")), None, row.get("n"), row.get("n"), None, 0, fetched_at, run_id)


def year_windows(start: datetime, end: datetime) -> list[tuple[str, str]]:
    out, cur = [], start
    while cur < end:
        nxt = min(datetime(cur.year + 1, 1, 1), end)
        out.append((cur.date().isoformat(), nxt.date().isoformat()))
        cur = nxt
    return out


async def backfill(store: HistoryStore, client: XkdrClient, mapping: dict[str, int], start: datetime, end: datetime, run_id: str,
                   pollutants: list[str] | None = None, concurrency: int = 4, sources: dict[str, str] | None = None) -> dict:
    wanted = pollutants or list(PARAMS.values())
    api_name = {v: k for k, v in PARAMS.items()}
    sensors = {r["sensor_id"] for r in store.query("select sensor_id from sensors where sensor_id >= ?", (ID_OFFSET,))}
    todo = []
    for sid, station_id in mapping.items():
        for pol in wanted:
            sensor_id = sensor_id_for(sid, pol)
            if sensor_id not in sensors:
                continue
            for w_from, w_to in year_windows(start, end):
                done = store.query("select status from raw_air_progress where sensor_id=? and window_from=? and window_to=?", (sensor_id, w_from, w_to))
                if not done or done[0]["status"] != "ok":
                    todo.append((sid, station_id, pol, sensor_id, w_from, w_to))
    rows_total = failed = 0
    queue: asyncio.Queue = asyncio.Queue()
    for item in todo:
        queue.put_nowait(item)

    async def worker():
        nonlocal rows_total, failed
        while True:
            try:
                sid, station_id, pol, sensor_id, w_from, w_to = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                body = await client.get("/v1/measurements", {"station": sid, "parameter": api_name[pol], "start": w_from, "end": w_to, "agg": "hourly"})
                fetched = iso(datetime.now(timezone.utc))
                utc = (sources or {}).get(sid) in UTC_NAIVE_SOURCES
                batch = [p for r in body.get("data", []) if (p := parse_row(station_id, sensor_id, pol, r, fetched, run_id, naive_is_utc=utc))]
                if body.get("meta", {}).get("truncated"):
                    raise XkdrError("response was truncated")
                store.executemany(INSERT_RAW, batch)
                status, n = "ok", len(batch)
            except XkdrError as exc:
                if "rejected the configured key" in str(exc):
                    raise
                status, n = "failed", 0
                failed += 1
            store.execute("insert or replace into raw_air_progress (sensor_id,window_from,window_to,status,rows,requests,finished_at,run_id) values (?,?,?,?,?,?,?,?)",
                          (sensor_id, w_from, w_to, status, n, 1, iso(datetime.now(timezone.utc)), run_id))
            store.commit()
            rows_total += n

    await asyncio.gather(*[worker() for _ in range(max(1, concurrency))])
    return {"windows": len(todo), "rows": rows_total, "failed_windows": failed}


async def run(store: HistoryStore, api_key: str, start: datetime, end: datetime, pollutants: list[str] | None = None, concurrency: int = 4,
              transport: httpx.AsyncBaseTransport | None = None) -> dict:
    client = XkdrClient(api_key, transport=transport)
    run_id = start_run(store, KIND, {"source": BASE_URL, "start": iso(start), "end": iso(end), "pollutants": pollutants or list(PARAMS.values())})
    try:
        d = await discover(store, client, run_id)
        res = await backfill(store, client, d["map"], start, end, run_id, pollutants, concurrency, sources=d.get("sources"))
    except Exception as exc:
        finish_run(store, run_id, "failed", client.requests, 0, type(exc).__name__)
        raise
    finish_run(store, run_id, "ok" if not res["failed_windows"] else "partial", client.requests, res["rows"], f"failed_windows={res['failed_windows']}")
    return {"run_id": run_id, **{k: v for k, v in d.items() if k not in ("map", "sources")}, **res, "requests": client.requests}
