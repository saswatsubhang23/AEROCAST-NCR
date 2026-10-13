"""Batch air quality service: processes CSV files with coordinates, querying Open-Meteo Air Quality API
in batches and calculating PM2.5 analytics, AQI categories and aggregated summaries.
Includes persistent hourly caching, incremental checkpointing, and request suppression.
"""

from __future__ import annotations

import asyncio
import csv
import io
import logging
import math
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.config import Settings
from app.integrations.openmeteo import OpenMeteoClient, UpstreamError, UpstreamRateLimitError
from app.services.batch_hourly_cache import (
    BatchHourlyCache,
    FetchPlan,
    format_utc_iso,
    parse_utc_iso,
)

logger = logging.getLogger("app.batch_air")

# Open-Meteo multi-coordinate limits:
# The backend supports up to 1000 locations, but recommends 50-100 locations per request
# to stay within HTTP GET URL length limits (under 4KB-8KB) and prevent HTTP 414 Request-URI Too Large.
DEFAULT_BATCH_SIZE = 100
MAX_BATCH_SIZE = 100

# Open-Meteo free tier imposes a strict 600 calls/min quota. Since each location in a batch
# counts as 1 call, we throttle to 500 locations per rolling 60-second window to prevent hitting HTTP 429.
FREE_TIER_LOCATIONS_PER_MINUTE = 500
FREE_TIER_WINDOW_SECONDS = 60.0

# Guardrail against accidental uploads of massive grid files (e.g. 110k lines) exceeding free daily quota (10,000)
MAX_FREE_TIER_CSV_ROWS = 2500

# CPCB PM2.5 breakpoints and categories (24h concentration in µg/m³)
PM25_CATEGORIES = [
    ("Good", 0.0, 30.0, "#00b050"),
    ("Satisfactory", 30.01, 60.0, "#92d050"),
    ("Moderately polluted", 60.01, 90.0, "#eab308"),
    ("Poor", 90.01, 120.0, "#f97316"),
    ("Very poor", 120.01, 250.0, "#ef4444"),
    ("Severe", 250.01, float("inf"), "#b91c1c"),
]


def pm25_category(val: float | None) -> tuple[str, str]:
    """Returns (category_name, hex_color) according to CPCB PM2.5 thresholds."""
    if val is None or not math.isfinite(val):
        return ("Unknown", "#9db0cc")
    for name, low, high, color in PM25_CATEGORIES:
        if low <= val <= high:
            return (name, color)
    return ("Severe", "#b91c1c")


def parse_date_or_hour(s: str) -> datetime:
    """Parses date string ('2026-10-12') or ISO timestamp into timezone-aware UTC datetime."""
    s = s.strip()
    if len(s) == 10 and "-" in s:
        return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif "+" not in s and "-" not in s[10:]:
        s = s + "+00:00"
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def _find_column(fieldnames: list[str], candidates: list[str]) -> str | None:
    norm_fields = {fn.strip().lower().replace("_", "").replace(" ", "").replace("-", ""): fn for fn in fieldnames}
    for cand in candidates:
        norm_cand = cand.lower().replace("_", "").replace(" ", "").replace("-", "")
        if norm_cand in norm_fields:
            return norm_fields[norm_cand]
    return None


class BatchAirQualityService:
    def __init__(
        self,
        settings: Settings,
        client: OpenMeteoClient | None = None,
        cache: BatchHourlyCache | None = None,
    ):
        self._settings = settings
        self._client = client or OpenMeteoClient(settings)
        if cache is not None:
            self._cache = cache
        else:
            data_dir = getattr(settings, "data_dir", "./data")
            db_path = os.path.join(data_dir, "batch_hourly_cache.sqlite")
            self._cache = BatchHourlyCache(db_path)
        self._window_lock = asyncio.Lock()
        self._request_history: list[tuple[float, int]] = []  # (monotonic_timestamp, count)

    @property
    def cache(self) -> BatchHourlyCache:
        return self._cache

    async def _wait_for_rate_budget(self, count: int, has_api_key: bool) -> None:
        """Throttles free-tier requests within a 60s rolling window to stay below 600 calls/min."""
        if has_api_key:
            return

        async with self._window_lock:
            while True:
                now = time.monotonic()
                # Prune records older than 60 seconds
                self._request_history = [
                    (t, c) for t, c in self._request_history if now - t < FREE_TIER_WINDOW_SECONDS
                ]
                current_total = sum(c for _, c in self._request_history)

                if current_total + count <= FREE_TIER_LOCATIONS_PER_MINUTE:
                    # Budget available
                    self._request_history.append((now, count))
                    return

                # Exceeds quota in the current window: calculate required sleep
                oldest_time = self._request_history[0][0]
                sleep_needed = max(1.0, (oldest_time + FREE_TIER_WINDOW_SECONDS) - now + 1.0)
                logger.info(
                    "Open-Meteo free tier quota limit (%d locations/min) approached. Pausing for %.1fs before next chunk...",
                    FREE_TIER_LOCATIONS_PER_MINUTE,
                    sleep_needed,
                )
                await asyncio.sleep(sleep_needed)

    def parse_csv_content(self, raw_csv: str, max_rows: int = MAX_FREE_TIER_CSV_ROWS) -> tuple[list[dict[str, Any]], list[str]]:
        """Parses raw CSV string and returns (parsed_rows, original_fieldnames)."""
        raw_csv = raw_csv.lstrip("\ufeff").strip()
        if not raw_csv:
            raise ValueError("CSV content is empty.")

        # Detect delimiter (comma or semicolon)
        first_line = raw_csv.splitlines()[0]
        delimiter = ";" if ";" in first_line and "," not in first_line else ","

        reader = csv.DictReader(io.StringIO(raw_csv), delimiter=delimiter)
        if not reader.fieldnames:
            raise ValueError("CSV has no header row.")

        fieldnames = [f.strip() for f in reader.fieldnames if f]

        lat_col = _find_column(fieldnames, ["latitude", "lat", "latdeg", "latdd", "y"])
        lon_col = _find_column(fieldnames, ["longitude", "long", "lon", "lng", "londeg", "londd", "x"])
        place_col = _find_column(fieldnames, ["place", "city", "location", "station", "stationname", "placename", "district", "town", "area", "name"])
        state_col = _find_column(fieldnames, ["statename", "state", "province", "region", "ut"])

        if not lat_col or not lon_col:
            raise ValueError(
                f"Could not identify coordinate columns in header: {fieldnames}. "
                "Expected columns matching Latitude/Lat and Longitude/Lon."
            )

        rows: list[dict[str, Any]] = []
        for idx, row in enumerate(reader, start=1):
            cleaned_row = {k.strip(): (v.strip() if v else "") for k, v in row.items() if k}
            lat_str = cleaned_row.get(lat_col, "")
            lon_str = cleaned_row.get(lon_col, "")
            place_val = cleaned_row.get(place_col, f"Location {idx}") if place_col else f"Location {idx}"
            state_val = cleaned_row.get(state_col, "Unknown") if state_col else "Unknown"

            lat_val: float | None = None
            lon_val: float | None = None
            err_msg: str | None = None

            try:
                lat_val = float(lat_str)
                lon_val = float(lon_str)
                if not (-90.0 <= lat_val <= 90.0 and -180.0 <= lon_val <= 180.0):
                    err_msg = f"Coordinates out of bounds (lat: {lat_val}, lon: {lon_val})"
            except (ValueError, TypeError):
                err_msg = f"Invalid coordinate numbers (lat: '{lat_str}', lon: '{lon_str}')"

            rows.append({
                "index": idx,
                "state": state_val or "Unknown",
                "place": place_val or f"Point {idx}",
                "latitude": lat_val,
                "longitude": lon_val,
                "raw_data": cleaned_row,
                "valid": err_msg is None,
                "error": err_msg,
            })

        if len(rows) > max_rows:
            raise ValueError(
                f"CSV contains {len(rows):,} rows, which exceeds the safe batch limit of {max_rows:,}. "
                "Open-Meteo's free tier has a daily limit of 10,000 calls and 600 calls/minute (where 1 location = 1 call). "
                f"Please reduce your CSV to under {max_rows:,} rows or provide an Open-Meteo API key."
            )

        return rows, fieldnames

    async def fetch_pm25_for_batch(
        self,
        rows: list[dict[str, Any]],
        forecast_hours: int = 24,
        batch_size: int | None = None,
        api_key: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        force_refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Queries Open-Meteo in batched chunks for all valid coordinates and annotates each row.

        Smart caching & checkpointing:
        - Checks local store to see if coordinate has already fetched data up to target time.
        - If already fetched, continues from that time (T + 1 hour).
        - If after that time no new data is available yet, suppresses request completely.
        """
        valid_indices = [i for i, r in enumerate(rows) if r["valid"]]
        if not valid_indices:
            return rows

        now = datetime.now(timezone.utc)
        if start_date:
            target_start = parse_date_or_hour(start_date)
        else:
            target_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)

        if end_date:
            target_end = parse_date_or_hour(end_date)
        else:
            target_end = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=forecast_hours)

        needs_fetch: list[tuple[int, FetchPlan]] = []

        # 1. Evaluate cache & plans for all coordinates
        for idx in valid_indices:
            r = rows[idx]
            plan = self._cache.plan_fetch(
                lat=r["latitude"],
                lon=r["longitude"],
                target_start=target_start,
                target_end=target_end,
                now=now,
                max_forecast_lead_hours=forecast_hours,
            )

            if not force_refresh and not plan.should_fetch:
                # Upstream invocation NOT needed: serve directly from cache
                cached_hours = self._cache.get_cached_hours(
                    r["latitude"],
                    r["longitude"],
                    start_utc=format_utc_iso(target_start),
                    end_utc=format_utc_iso(target_end),
                )
                times = [h["time_utc"] for h in cached_hours]
                vals = [h["pm25"] for h in cached_hours]
                elevation = cached_hours[0]["elevation_m"] if cached_hours else None

                numeric_vals = [float(v) for v in vals if v is not None and not math.isnan(float(v))]
                avg_24h = round(sum(numeric_vals) / len(numeric_vals), 1) if numeric_vals else None
                min_24h = min(numeric_vals) if numeric_vals else None
                max_24h = max(numeric_vals) if numeric_vals else None
                pm25_curr = numeric_vals[-1] if numeric_vals else None

                cat_name, cat_color = pm25_category(pm25_curr if pm25_curr is not None else avg_24h)

                r.update({
                    "current_pm25": pm25_curr,
                    "forecast_24h_avg": avg_24h,
                    "forecast_min": min_24h,
                    "forecast_max": max_24h,
                    "elevation_m": elevation,
                    "aqi_category": cat_name,
                    "aqi_color": cat_color,
                    "hourly_times": times,
                    "hourly_pm25": vals,
                    "from_cache": True,
                    "cache_hit": True,
                    "fetch_reason": plan.reason,
                    "continued_from": plan.continued_from,
                })
            else:
                needs_fetch.append((idx, plan))

        if not needs_fetch:
            # 100% satisfied from cache: zero upstream calls!
            logger.info("Batch air quality: All %d coordinates satisfied from local hourly cache (0 API calls).", len(valid_indices))
            return rows

        effective_key = api_key or (
            self._settings.open_meteo_api_key.get_secret_value()
            if hasattr(self._settings, "open_meteo_api_key")
            else ""
        )
        has_api_key = bool(effective_key)

        effective_batch_size = max(
            10,
            min(
                batch_size or getattr(self._settings, "open_meteo_batch_chunk_size", DEFAULT_BATCH_SIZE),
                MAX_BATCH_SIZE,
            ),
        )

        chunks = [
            needs_fetch[i : i + effective_batch_size]
            for i in range(0, len(needs_fetch), effective_batch_size)
        ]

        sem = asyncio.Semaphore(5 if has_api_key else 1)

        async def fetch_chunk(chunk_items: list[tuple[int, FetchPlan]]) -> list[tuple[int, FetchPlan, dict]]:
            chunk_indices = [idx for idx, _ in chunk_items]
            lats = [str(rows[i]["latitude"]) for i in chunk_indices]
            lons = [str(rows[i]["longitude"]) for i in chunk_indices]

            params: dict[str, Any] = {
                "latitude": ",".join(lats),
                "longitude": ",".join(lons),
                "current": "pm2_5",
                "hourly": "pm2_5",
                "timezone": "GMT",
            }
            if effective_key:
                params["apikey"] = effective_key

            # Check if chunk items share common start and end hour
            plans = [p for _, p in chunk_items]
            valid_starts = [p.start_hour for p in plans if p.start_hour]
            valid_ends = [p.end_hour for p in plans if p.end_hour]

            if valid_starts and valid_ends and len(set(valid_starts)) == 1 and len(set(valid_ends)) == 1:
                params["start_hour"] = valid_starts[0]
                params["end_hour"] = valid_ends[0]
            elif start_date and end_date:
                params["start_date"] = start_date[:10]
                params["end_date"] = end_date[:10]
            else:
                params["forecast_hours"] = forecast_hours
                params["past_hours"] = 24

            async with sem:
                await self._wait_for_rate_budget(len(chunk_indices), has_api_key)
                attempts = 3
                for attempt in range(1, attempts + 1):
                    try:
                        res = await self._client.get_air_quality(params)
                        items = res if isinstance(res, list) else [res]
                        return [(c_idx, c_plan, itm) for (c_idx, c_plan), itm in zip(chunk_items, items)]
                    except UpstreamError as exc:
                        err_str = str(exc).lower()
                        is_rate_limit = (
                            isinstance(exc, UpstreamRateLimitError)
                            or "429" in err_str
                            or "limit exceeded" in err_str
                        )
                        if is_rate_limit and attempt < attempts:
                            wait_seconds = getattr(exc, "retry_after", 62.0)
                            if not wait_seconds or wait_seconds < 10.0:
                                wait_seconds = 62.0
                            logger.warning(
                                "Open-Meteo rate limit hit (attempt %d/%d). Sleeping %.1fs before retrying: %s",
                                attempt,
                                attempts,
                                wait_seconds,
                                exc,
                            )
                            async with self._window_lock:
                                self._request_history.clear()
                            await asyncio.sleep(wait_seconds)
                            continue
                        raise

        results_by_chunk = await asyncio.gather(*[fetch_chunk(c) for c in chunks])
        for chunk_res in results_by_chunk:
            for idx, plan, item in chunk_res:
                current_data = item.get("current") or {}
                hourly_data = item.get("hourly") or {}
                elevation = item.get("elevation")

                pm25_curr = current_data.get("pm2_5")
                hourly_vals = hourly_data.get("pm2_5") or []
                times = hourly_data.get("time") or []

                # Format timestamps to standard UTC
                utc_times = [t if t.endswith("Z") else t + ":00Z" if len(t) == 16 else t for t in times]

                # Save newly received hourly slice to persistent cache
                r_lat = rows[idx]["latitude"]
                r_lon = rows[idx]["longitude"]
                if times and hourly_vals:
                    self._cache.save_hourly_response(
                        lat=r_lat,
                        lon=r_lon,
                        times=utc_times,
                        pm25_vals=hourly_vals,
                        elevation=elevation,
                        now=now,
                    )

                # Retrieve complete merged continuous history from cache
                merged_hours = self._cache.get_cached_hours(
                    r_lat,
                    r_lon,
                    start_utc=format_utc_iso(target_start),
                    end_utc=format_utc_iso(target_end),
                )
                if not merged_hours and times:
                    merged_times = utc_times
                    merged_vals = hourly_vals
                else:
                    merged_times = [h["time_utc"] for h in merged_hours]
                    merged_vals = [h["pm25"] for h in merged_hours]

                numeric_hourly = [float(v) for v in merged_vals if v is not None and not math.isnan(float(v))]
                avg_24h = round(sum(numeric_hourly) / len(numeric_hourly), 1) if numeric_hourly else None
                min_24h = min(numeric_hourly) if numeric_hourly else None
                max_24h = max(numeric_hourly) if numeric_hourly else None

                if pm25_curr is None and numeric_hourly:
                    pm25_curr = numeric_hourly[-1]
                elif pm25_curr is not None:
                    pm25_curr = round(float(pm25_curr), 1)

                cat_name, cat_color = pm25_category(pm25_curr if pm25_curr is not None else avg_24h)

                rows[idx].update({
                    "current_pm25": pm25_curr,
                    "forecast_24h_avg": avg_24h,
                    "forecast_min": min_24h,
                    "forecast_max": max_24h,
                    "elevation_m": elevation,
                    "aqi_category": cat_name,
                    "aqi_color": cat_color,
                    "hourly_times": merged_times,
                    "hourly_pm25": [round(v, 1) if isinstance(v, (int, float)) else None for v in merged_vals],
                    "from_cache": False,
                    "cache_hit": False,
                    "fetch_reason": plan.reason,
                    "continued_from": plan.continued_from,
                })

        return rows

    def calculate_summary(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        """Calculates dataset-wide metrics, distribution and state-by-state aggregations."""
        valid_rows = [r for r in rows if r["valid"] and r.get("current_pm25") is not None]
        total_rows = len(rows)
        valid_count = len(valid_rows)
        invalid_count = total_rows - len([r for r in rows if r["valid"]])

        pm_values = [r["current_pm25"] for r in valid_rows]
        avg_pm25 = round(sum(pm_values) / len(pm_values), 1) if pm_values else None

        min_record = min(valid_rows, key=lambda x: x["current_pm25"]) if valid_rows else None
        max_record = max(valid_rows, key=lambda x: x["current_pm25"]) if valid_rows else None

        # Category breakdown
        category_counts: dict[str, int] = {cat[0]: 0 for cat in PM25_CATEGORIES}
        for r in valid_rows:
            cat = r.get("aqi_category")
            if cat in category_counts:
                category_counts[cat] += 1

        # State aggregations
        states_map: dict[str, list[float]] = {}
        for r in valid_rows:
            st = r["state"]
            states_map.setdefault(st, []).append(r["current_pm25"])

        state_summaries = []
        for state, vals in states_map.items():
            state_summaries.append({
                "state": state,
                "count": len(vals),
                "avg_pm25": round(sum(vals) / len(vals), 1),
                "min_pm25": round(min(vals), 1),
                "max_pm25": round(max(vals), 1),
                "aqi_category": pm25_category(sum(vals) / len(vals))[0],
                "aqi_color": pm25_category(sum(vals) / len(vals))[1],
            })
        state_summaries.sort(key=lambda s: s["avg_pm25"], reverse=True)

        cache_hits = sum(1 for r in valid_rows if r.get("from_cache") is True)
        cache_misses = len(valid_rows) - cache_hits

        return {
            "total_rows": total_rows,
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "avg_pm25": avg_pm25,
            "cache_hits": cache_hits,
            "cache_misses": cache_misses,
            "api_calls_avoided": cache_hits,
            "min_location": {
                "place": min_record["place"],
                "state": min_record["state"],
                "value": min_record["current_pm25"],
                "category": min_record["aqi_category"],
            } if min_record else None,
            "max_location": {
                "place": max_record["place"],
                "state": max_record["state"],
                "value": max_record["current_pm25"],
                "category": max_record["aqi_category"],
            } if max_record else None,
            "category_distribution": category_counts,
            "state_summaries": state_summaries,
            "retrieved_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    def generate_enriched_csv(self, rows: list[dict[str, Any]], fieldnames: list[str]) -> str:
        """Generates enriched CSV string containing original columns plus PM2.5 metrics."""
        output = io.StringIO()
        added_cols = [
            "Current_PM25_ug_m3",
            "Forecast_24h_Avg_PM25_ug_m3",
            "Min_PM25_ug_m3",
            "Max_PM25_ug_m3",
            "AQI_Category",
            "Elevation_m",
            "From_Cache",
            "Status",
        ]
        out_fieldnames = list(fieldnames) + [col for col in added_cols if col not in fieldnames]
        writer = csv.DictWriter(output, fieldnames=out_fieldnames)
        writer.writeheader()

        for r in rows:
            out_row = dict(r["raw_data"])
            out_row["Current_PM25_ug_m3"] = str(r.get("current_pm25", "")) if r.get("current_pm25") is not None else ""
            out_row["Forecast_24h_Avg_PM25_ug_m3"] = str(r.get("forecast_24h_avg", "")) if r.get("forecast_24h_avg") is not None else ""
            out_row["Min_PM25_ug_m3"] = str(r.get("forecast_min", "")) if r.get("forecast_min") is not None else ""
            out_row["Max_PM25_ug_m3"] = str(r.get("forecast_max", "")) if r.get("forecast_max") is not None else ""
            out_row["AQI_Category"] = r.get("aqi_category", "Unknown")
            out_row["Elevation_m"] = str(r.get("elevation_m", "")) if r.get("elevation_m") is not None else ""
            out_row["From_Cache"] = "Yes" if r.get("from_cache") else "No"
            out_row["Status"] = "OK" if r["valid"] else (r.get("error") or "Invalid")
            writer.writerow(out_row)

        return output.getvalue()

    def generate_pdf_report(
        self,
        summary: dict[str, Any],
        rows: list[dict[str, Any]],
        title: str = "Batch PM2.5 Coordinate Analysis Report",
    ) -> bytes:
        """Renders an executive multi-page PDF report for batch PM2.5 coordinate data."""
        from app.reports.batch_pdf import render_batch_pdf

        return render_batch_pdf(summary, rows, title=title)
