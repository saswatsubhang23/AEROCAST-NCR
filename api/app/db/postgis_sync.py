"""Copy the cleaned historical layer (`history.sqlite`) into PostgreSQL/PostGIS (`env_station`, `env_record`).

SQLite stays the pipeline's working store (ingest, clean, features, training all read it). PostGIS is the serving/spatial copy: it
adds point geometries with GiST indexes, so "which stations are within r km of here" and "latest value per station" are indexed
queries instead of Python loops. Nothing is invented: every row is a `clean_air` row, mapped one to one.

Mapping (matches app/envdata/schema.py so identities agree with `EnvRecord.record_id`):
  kind          observation (clean_air is only ever measurements)
  source        `xkdr` when the chosen sensor id is a synthetic xKDR id (>= ingest_xkdr.ID_OFFSET), else `openaq`
  value / unit  value_std / µg/m³ (unit conversion and plausibility flags were already applied by the clean step)
  usable        carried over; unusable rows are kept with their flags, never dropped
  retrieved_at  `raw_air.fetched_at` of the matching raw row; rows with no match are flagged RETRIEVED_AT_UNKNOWN
                and get the sync time, so the column is never silently wrong
  support/geom  point, from the station's coordinates

Re-running is safe: rows upsert on `record_id`. By default only the tail is re-read (the newest stored hour minus
OVERLAP_DAYS, so late corrections from a re-clean are picked up); `full=True` reloads everything.
"""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.engine import Engine

from app.history.ingest_xkdr import ID_OFFSET

logger = logging.getLogger("app.db.postgis_sync")

OVERLAP_DAYS = 7
BATCH_ROWS = 250_000
UNIT = "µg/m³"
SOURCE_OPENAQ, SOURCE_XKDR = "openaq", "xkdr"

ADD_ON_STATION_COLUMNS = ("station_id", "name", "provider", "zone", "lat", "lon", "datetime_first", "datetime_last")


def source_for_sensor(sensor_id: int) -> str:
    return SOURCE_XKDR if sensor_id >= ID_OFFSET else SOURCE_OPENAQ


def record_id(source: str, variable: str, station_id: int, valid_from_utc: str, valid_to_utc: str) -> str:
    """Identical to `EnvRecord.record_id` for an observation (kind|source|variable|location|from|to|-)."""
    iso_from, iso_to = valid_from_utc.replace("Z", "+00:00"), valid_to_utc.replace("Z", "+00:00")
    key = "|".join(["observation", source, variable, f"station:{station_id}", iso_from, iso_to, "-"])
    return hashlib.sha1(key.encode()).hexdigest()


def _flags_literal(flags: str | None, extra: tuple[str, ...] = ()) -> str:
    items = [f for f in (flags or "").split(",") if f] + list(extra)
    return "{" + ",".join(sorted(set(items))) + "}"


def _ts(text: str | None) -> str | None:
    return text.replace("Z", "+00:00") if text else None


def transform(row: sqlite3.Row | tuple, synced_at: str) -> tuple:
    """One joined clean_air/raw_air row -> one COPY tuple for the staging table."""
    station_id, pollutant, p_from, p_to, sensor_id, orig_v, orig_u, value, flags, usable, fetched_at = row
    source = source_for_sensor(int(sensor_id))
    extra = () if fetched_at else ("RETRIEVED_AT_UNKNOWN",)
    return (
        record_id(source, pollutant, int(station_id), p_from, p_to), source, pollutant, value, UNIT, orig_v, orig_u,
        _ts(p_from), _ts(p_to), _ts(fetched_at) or _ts(synced_at), int(station_id), _flags_literal(flags, extra), bool(usable),
    )


SOURCE_SQL = """
select c.station_id, c.pollutant, c.period_from_utc, c.period_to_utc, c.sensor_id, c.orig_value, c.orig_unit,
       c.value_std, c.flags, c.usable, r.fetched_at
from clean_air c
left join raw_air r on r.sensor_id = c.sensor_id and r.period_to_utc = c.period_to_utc
{where}
"""

STAGE_DDL = """
create temp table if not exists env_record_stage (
  record_id char(40), source text, variable text, value double precision, unit text, original_value double precision,
  original_unit text, valid_from timestamptz, valid_to timestamptz, retrieved_at timestamptz, station_id bigint,
  quality_flags text[], usable boolean
) on commit preserve rows
"""

UPSERT_SQL = """
insert into env_record (record_id, kind, source, variable, value, unit, original_value, original_unit, valid_from, valid_to,
                        issued_at, retrieved_at, location_id, geom, support, resolution_km, quality_flags, usable)
select distinct on (g.record_id) g.record_id, 'observation', g.source, g.variable, g.value, g.unit, g.original_value, g.original_unit,
       g.valid_from, g.valid_to, null, g.retrieved_at, 'station:' || g.station_id, s.geom, 'point', null, g.quality_flags, g.usable
from env_record_stage g
join env_station s on s.station_id = g.station_id
order by g.record_id, g.retrieved_at desc
on conflict (record_id) do update set
  value = excluded.value, original_value = excluded.original_value, original_unit = excluded.original_unit,
  retrieved_at = excluded.retrieved_at, quality_flags = excluded.quality_flags, usable = excluded.usable
"""

STATION_UPSERT = """
insert into env_station (station_id, name, provider, zone, geom, datetime_first, datetime_last)
values (%s, %s, %s, %s, st_setsrid(st_makepoint(%s, %s), 4326), %s, %s)
on conflict (station_id) do update set
  name = excluded.name, provider = excluded.provider, zone = excluded.zone, geom = excluded.geom,
  datetime_first = excluded.datetime_first, datetime_last = excluded.datetime_last
"""


def sync_stations(sqlite_db: sqlite3.Connection, pg) -> int:
    rows = sqlite_db.execute("select station_id, name, provider, zone, lat, lon, datetime_first, datetime_last from stations").fetchall()
    with pg.cursor() as cur:
        cur.executemany(
            STATION_UPSERT,
            [(r[0], r[1] or f"station {r[0]}", r[2], r[3], r[5], r[4], _ts(r[6]), _ts(r[7])) for r in rows],
        )
    pg.commit()
    return len(rows)


def _since(pg, full: bool) -> str | None:
    if full:
        return None
    with pg.cursor() as cur:
        cur.execute("select max(valid_to) from env_record where kind = 'observation'")
        newest = cur.fetchone()[0]
    if newest is None:
        return None
    return (newest - timedelta(days=OVERLAP_DAYS)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def sync_observations(sqlite_db: sqlite3.Connection, pg, *, full: bool = False, synced_at: str, progress=None) -> dict:
    since = _since(pg, full)
    where, args = ("where c.period_to_utc > ?", (since,)) if since else ("", ())
    cursor = sqlite_db.execute(SOURCE_SQL.format(where=where), args)
    read = 0
    with pg.cursor() as cur:
        cur.execute(STAGE_DDL)
    while True:
        rows = cursor.fetchmany(BATCH_ROWS)
        if not rows:
            break
        with pg.cursor() as cur:
            cur.execute("truncate env_record_stage")
            with cur.copy("copy env_record_stage from stdin") as cp:
                for r in rows:
                    cp.write_row(transform(r, synced_at))
            cur.execute(UPSERT_SQL)
        pg.commit()
        read += len(rows)
        if progress:
            progress(f"  {read:,} rows processed")
    return {"mode": "full" if since is None else f"incremental (from {since})", "rows_read": read}


def sync(engine: Engine, history_db: str, *, full: bool = False, progress=None) -> dict:
    """Run one sync and record it in `env_sync_run`. Returns a summary dict."""
    run_id = uuid.uuid4().hex[:12]
    synced_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sq = sqlite3.connect(f"file:{history_db}?mode=ro", uri=True, timeout=30)
    raw = engine.raw_connection()
    pg = raw.driver_connection
    try:
        with pg.cursor() as cur:
            cur.execute("insert into env_sync_run (run_id, started_at, status, note) values (%s, now(), 'running', %s)", (run_id, history_db))
        pg.commit()
        try:
            n_stations = sync_stations(sq, pg)
            res = sync_observations(sq, pg, full=full, synced_at=synced_at, progress=progress)
        except Exception as exc:
            pg.rollback()
            with pg.cursor() as cur:
                cur.execute("update env_sync_run set finished_at = now(), status = 'failed', note = %s where run_id = %s", (type(exc).__name__, run_id))
            pg.commit()
            raise
        with pg.cursor() as cur:
            cur.execute(
                "select source, variable, count(*), to_char(min(valid_from) at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"'),"
                " to_char(max(valid_to) at time zone 'utc', 'YYYY-MM-DD\"T\"HH24:MI:SS\"Z\"') from env_record group by 1, 2 order by 1, 2"
            )
            series = [{"source": s, "variable": v, "records": n, "first": a, "newest": b} for s, v, n, a, b in cur.fetchall()]
            total = sum(s["records"] for s in series)
            cur.execute(
                "update env_sync_run set finished_at = now(), status = 'ok', stations = %s, rows_read = %s, rows_total = %s, mode = %s, summary = %s"
                " where run_id = %s",
                (n_stations, res["rows_read"], total, res["mode"], json.dumps(series), run_id),
            )
            cur.execute("analyze env_record")
        pg.commit()
        return {"run_id": run_id, "stations": n_stations, **res, "rows_in_postgis": total}
    finally:
        sq.close()
        raw.close()
