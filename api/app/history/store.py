"""SQLite store for the historical pipeline (`DATA_DIR/history.sqlite`).

Why SQLite: PostgreSQL/PostGIS was unreachable when this pipeline was built (see `cli check-db`), and the application
already keeps its other local state in SQLite (`alerts/store.py`, `kb/registry.py`). Every column is plain SQL, so the same
tables can be created in PostgreSQL later; no PostGIS feature is used.

Layers, kept strictly apart:
  raw_*            what the providers returned, append-only, never edited (INSERT OR IGNORE on a content key)
  clean_*          one row per (station, pollutant, hour) with units, flags and provenance; derived only from raw_*
  model_ready      features derived only from clean_*; rebuilt from scratch by the pipeline
"""

import hashlib
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
create table if not exists ingest_runs (
  run_id text primary key, kind text not null, started_at text not null, finished_at text, status text not null,
  params text, requests integer default 0, rows_added integer default 0, note text
);
create table if not exists stations (
  station_id integer primary key, name text, locality text, lat real not null, lon real not null, provider text,
  owner text, license text, is_monitor integer, timezone text, datetime_first text, datetime_last text,
  zone text, agency text, discovered_at text, run_id text
);
create table if not exists sensors (
  sensor_id integer primary key, station_id integer not null, parameter text not null, units text,
  datetime_first text, datetime_last text, discovered_at text, run_id text
);
create table if not exists raw_air (
  row_key text primary key,
  sensor_id integer not null, station_id integer not null, parameter text not null, units text,
  period_from_utc text, period_to_utc text not null, period_to_local text,
  value real, summary_min real, summary_max real, summary_sd real,
  expected_count integer, observed_count integer, percent_coverage real, has_flags integer,
  fetched_at text not null, run_id text not null
);
create index if not exists ix_raw_air_sensor on raw_air(sensor_id, period_to_utc);
create index if not exists ix_raw_air_station on raw_air(station_id, parameter, period_to_utc);
create table if not exists raw_air_progress (
  sensor_id integer not null, window_from text not null, window_to text not null, status text not null,
  rows integer default 0, requests integer default 0, finished_at text, run_id text,
  primary key (sensor_id, window_from, window_to)
);
create table if not exists raw_weather (
  row_key text primary key,
  point_id text not null, time_utc text not null,
  temperature_2m real, relative_humidity_2m real, dew_point_2m real, surface_pressure real, wind_speed_10m real,
  wind_direction_10m real, wind_gusts_10m real, precipitation real, cloud_cover real, boundary_layer_height real,
  shortwave_radiation real,
  fetched_at text not null, run_id text not null
);
create index if not exists ix_raw_weather_point on raw_weather(point_id, time_utc);
create table if not exists raw_weather_meta (
  run_id text not null, point_id text not null, station_id integer, lat_requested real, lon_requested real,
  grid_lat real, grid_lon real, elevation_m real, units text, request text, fetched_at text,
  primary key (run_id, point_id, request)
);
create table if not exists raw_weather_progress (
  point_id text not null, window_from text not null, window_to text not null, status text not null,
  rows integer default 0, finished_at text, run_id text,
  primary key (point_id, window_from, window_to)
);
create table if not exists clean_air (
  station_id integer not null, pollutant text not null, label_utc text not null,
  period_from_utc text, period_to_utc text, period_to_ist text, sensor_id integer,
  orig_value real, orig_unit text, value_std real, std_unit text, coverage_pct real,
  n_candidates integer, flags text not null default '', usable integer not null,
  primary key (station_id, pollutant, label_utc)
);
create table if not exists clean_weather (
  station_id integer not null, time_utc text not null,
  temperature_2m real, relative_humidity_2m real, dew_point_2m real, surface_pressure real, wind_speed_10m real,
  wind_direction_10m real, wind_gusts_10m real, precipitation real, cloud_cover real, boundary_layer_height real,
  shortwave_radiation real,
  flags text not null default '', provisional integer not null default 0, grid_lat real, grid_lon real,
  primary key (station_id, time_utc)
);
create table if not exists sensor_unit_checks (
  sensor_id integer primary key, station_id integer, parameter text, units text, hours integer,
  median_std real, reference_std real, ratio real, suspect integer not null
);
create index if not exists ix_clean_air_pl on clean_air(pollutant, label_utc, station_id);
create index if not exists ix_clean_air_time on clean_air(label_utc);
create index if not exists ix_clean_air_usable on clean_air(pollutant, usable, station_id, label_utc);  -- covering: per-station inventories without row lookups
create index if not exists ix_clean_weather_time on clean_weather(time_utc, station_id);
create table if not exists feature_sets (
  name text primary key, created_at text, params text, columns text, rows integer, digest text
);
"""


class HistoryStore:
    def __init__(self, path: str | Path, read_only: bool = False):
        self.path = str(path)
        self._lock = threading.RLock()
        if read_only:  # request-time readers never create, migrate or write anything
            self.db = sqlite3.connect(f"file:{Path(self.path).as_posix()}?mode=ro", uri=True, check_same_thread=False, timeout=30)
            self.db.row_factory = sqlite3.Row
            return
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self.db.execute("pragma journal_mode = wal")
        self.db.execute("pragma synchronous = normal")
        self.db.executescript(SCHEMA)
        self.db.commit()

    def execute(self, sql: str, args=()):
        with self._lock:
            return self.db.execute(sql, args)

    def executemany(self, sql: str, rows):
        with self._lock:
            return self.db.executemany(sql, rows)

    def query(self, sql: str, args=()) -> list[sqlite3.Row]:
        with self._lock:
            return self.db.execute(sql, args).fetchall()

    def commit(self) -> None:
        with self._lock:
            self.db.commit()

    def close(self) -> None:
        with self._lock:
            self.db.close()

    def count(self, table: str) -> int:
        return self.query(f"select count(*) from {table}")[0][0]  # table names are constants in this package

    def digest(self, table: str, order_by: str) -> str:
        """SHA-256 over every row of `table` in a fixed order: proves two pipeline runs produced identical data."""
        h = hashlib.sha256()
        with self._lock:
            for row in self.db.execute(f"select * from {table} order by {order_by}"):
                h.update(repr(tuple(row)).encode("utf-8"))
        return h.hexdigest()
