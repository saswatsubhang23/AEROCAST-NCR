"""Persistent hourly cache and checkpoint tracker for batch air quality coordinate requests.

Features:
- Stores hourly PM2.5 observations and model outputs per coordinate in SQLite.
- Tracks `latest_time_utc` checkpoint for each coordinate.
- Inspects whether data for requested date/hour has already been fetched.
- If already fetched up to time T, continues fetching from T + 1 hour.
- If no new data is available yet after T, suppresses upstream request completely (0 API calls).
- Merges historical cached hours with newly fetched delta hours into a continuous series.
"""

from __future__ import annotations

import logging
import math
import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("app.services.batch_hourly_cache")


def parse_utc_iso(ts_str: str) -> datetime:
    """Parses ISO timestamp strings into UTC datetime objects."""
    s = ts_str.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif "+" not in s and "-" not in s[10:]:
        s = s + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def format_utc_iso(dt: datetime) -> str:
    """Formats datetime to standard ISO format with Z."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def coord_key(lat: float, lon: float) -> str:
    """Generates standard coordinate key rounded to 4 decimals (~11m resolution)."""
    return f"{round(lat, 4):.4f}:{round(lon, 4):.4f}"


@dataclass
class FetchPlan:
    should_fetch: bool
    reason: str
    start_hour: str | None = None
    end_hour: str | None = None
    existing_hours_count: int = 0
    continued_from: str | None = None


class BatchHourlyCache:
    """Thread-safe SQLite-backed hourly cache for batch coordinate requests."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None or str(db_path) == ":memory:":
            self._db_path = ":memory:"
        else:
            p = Path(db_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            self._db_path = str(p)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self) -> None:
        with self._conn:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_hourly_records (
                    coord_key TEXT NOT NULL,
                    time_utc TEXT NOT NULL,
                    pm25 REAL,
                    elevation_m REAL,
                    fetched_at TEXT NOT NULL,
                    PRIMARY KEY (coord_key, time_utc)
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_batch_hourly_coord_time
                ON batch_hourly_records(coord_key, time_utc)
            """)
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS batch_coord_checkpoint (
                    coord_key TEXT PRIMARY KEY,
                    latitude REAL NOT NULL,
                    longitude REAL NOT NULL,
                    earliest_time_utc TEXT,
                    latest_time_utc TEXT,
                    last_checked_at TEXT
                )
            """)

    def get_checkpoint(self, lat: float, lon: float) -> tuple[str | None, str | None]:
        """Returns (earliest_time_utc, latest_time_utc) for coordinate if recorded."""
        ck = coord_key(lat, lon)
        row = self._conn.execute(
            "SELECT earliest_time_utc, latest_time_utc FROM batch_coord_checkpoint WHERE coord_key = ?",
            (ck,),
        ).fetchone()
        if row:
            return row["earliest_time_utc"], row["latest_time_utc"]
        return None, None

    def get_cached_hours(
        self,
        lat: float,
        lon: float,
        start_utc: str | None = None,
        end_utc: str | None = None,
    ) -> list[dict[str, Any]]:
        """Retrieves ordered hourly records for coordinate within optional time bounds."""
        ck = coord_key(lat, lon)
        query = "SELECT time_utc, pm25, elevation_m FROM batch_hourly_records WHERE coord_key = ?"
        params: list[Any] = [ck]

        if start_utc:
            query += " AND time_utc >= ?"
            params.append(start_utc)
        if end_utc:
            query += " AND time_utc <= ?"
            params.append(end_utc)

        query += " ORDER BY time_utc ASC"
        rows = self._conn.execute(query, params).fetchall()
        return [{"time_utc": r["time_utc"], "pm25": r["pm25"], "elevation_m": r["elevation_m"]} for r in rows]

    def save_hourly_response(
        self,
        lat: float,
        lon: float,
        times: list[str],
        pm25_vals: list[float | None],
        elevation: float | None = None,
        now: datetime | None = None,
    ) -> int:
        """Persists hourly records and updates coordinate checkpoint."""
        if not times:
            return 0

        ck = coord_key(lat, lon)
        fetch_now_str = format_utc_iso(now or datetime.now(timezone.utc))

        formatted_times: list[str] = []
        for t in times:
            t_clean = t.strip()
            if not t_clean.endswith("Z") and "+" not in t_clean:
                t_clean = t_clean + ":00Z" if len(t_clean) == 16 else t_clean + "Z"
            formatted_times.append(t_clean)

        records_to_insert = []
        for t_iso, val in zip(formatted_times, pm25_vals):
            pm_num = float(val) if val is not None and not math.isnan(float(val)) else None
            records_to_insert.append((ck, t_iso, pm_num, elevation, fetch_now_str))

        min_new_time = min(formatted_times)
        max_new_time = max(formatted_times)

        with self._conn:
            self._conn.executemany(
                """
                INSERT INTO batch_hourly_records (coord_key, time_utc, pm25, elevation_m, fetched_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(coord_key, time_utc) DO UPDATE SET
                    pm25 = excluded.pm25,
                    elevation_m = coalesce(excluded.elevation_m, elevation_m),
                    fetched_at = excluded.fetched_at
                """,
                records_to_insert,
            )

            # Update checkpoint
            curr_earliest, curr_latest = self.get_checkpoint(lat, lon)
            eff_earliest = min(min_new_time, curr_earliest) if curr_earliest else min_new_time
            eff_latest = max(max_new_time, curr_latest) if curr_latest else max_new_time

            self._conn.execute(
                """
                INSERT INTO batch_coord_checkpoint (coord_key, latitude, longitude, earliest_time_utc, latest_time_utc, last_checked_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(coord_key) DO UPDATE SET
                    earliest_time_utc = excluded.earliest_time_utc,
                    latest_time_utc = excluded.latest_time_utc,
                    last_checked_at = excluded.last_checked_at
                """,
                (ck, round(lat, 4), round(lon, 4), eff_earliest, eff_latest, fetch_now_str),
            )

        return len(records_to_insert)

    def plan_fetch(
        self,
        lat: float,
        lon: float,
        target_start: datetime,
        target_end: datetime,
        now: datetime | None = None,
        max_forecast_lead_hours: int = 72,
    ) -> FetchPlan:
        """Determines whether an upstream API request is necessary, and computes delta window.

        Rules:
        1. If already fetched up to or beyond target_end:
           DO NOT INVOKE upstream (reason='already_cached_complete').
        2. If fetched up to T, and T < target_end:
           Continue from T + 1 hour.
        3. If T + 1 hour is beyond what the upstream API can provide (or no new hour has arrived):
           DO NOT INVOKE upstream (reason='no_new_data_available_yet').
        4. Otherwise:
           Invoke for delta: [T + 1 hour, target_end].
        """
        now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        latest_available_upstream = now_utc.replace(minute=0, second=0, microsecond=0) + timedelta(
            hours=max_forecast_lead_hours
        )

        effective_target_end = min(target_end, latest_available_upstream)
        if effective_target_end < target_start:
            return FetchPlan(
                should_fetch=False,
                reason="target_range_in_future_not_available",
                existing_hours_count=0,
            )

        _, latest_cached_str = self.get_checkpoint(lat, lon)

        if latest_cached_str is not None:
            latest_cached_dt = parse_utc_iso(latest_cached_str)

            # Check if cache already satisfies the target window
            if latest_cached_dt >= effective_target_end:
                cached_items = self.get_cached_hours(
                    lat, lon, format_utc_iso(target_start), format_utc_iso(target_end)
                )
                return FetchPlan(
                    should_fetch=False,
                    reason="already_cached_complete",
                    existing_hours_count=len(cached_items),
                )

            # If cache has data, continue from the very next hour after latest_cached_dt
            continuation_start_dt = latest_cached_dt + timedelta(hours=1)

            # Check if the continuation point is beyond available upstream data
            if continuation_start_dt > effective_target_end:
                cached_items = self.get_cached_hours(
                    lat, lon, format_utc_iso(target_start), format_utc_iso(target_end)
                )
                return FetchPlan(
                    should_fetch=False,
                    reason="no_new_data_available_yet",
                    existing_hours_count=len(cached_items),
                    continued_from=latest_cached_str,
                )

            # Delta needed: fetch only from continuation_start_dt to effective_target_end
            start_str = continuation_start_dt.strftime("%Y-%m-%dT%H:00")
            end_str = effective_target_end.strftime("%Y-%m-%dT%H:00")
            cached_items = self.get_cached_hours(lat, lon)

            return FetchPlan(
                should_fetch=True,
                reason="incremental_continuation",
                start_hour=start_str,
                end_hour=end_str,
                existing_hours_count=len(cached_items),
                continued_from=latest_cached_str,
            )

        # No cache exists for coordinate: fetch the full target window
        start_str = target_start.strftime("%Y-%m-%dT%H:00")
        end_str = effective_target_end.strftime("%Y-%m-%dT%H:00")
        return FetchPlan(
            should_fetch=True,
            reason="initial_fetch",
            start_hour=start_str,
            end_hour=end_str,
            existing_hours_count=0,
        )
