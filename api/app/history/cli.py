"""Command line for the historical pipeline.  Run from the `api` folder:

    python -m app.history check-db
    python -m app.history sources
    python -m app.history discover     [--from 2025-10-10]
    python -m app.history ingest-air   [--from ... --to ... --max-requests N]
    python -m app.history ingest-weather
    python -m app.history clean
    python -m app.history features     [--pollutants pm25,pm10 --latency-hours 0]
    python -m app.history report       [--out ../docs/data]
    python -m app.history sync-postgis [--full]      copy stations + cleaned observations into PostgreSQL/PostGIS
    python -m app.history all

Every step is idempotent and resumable: re-running ingestion skips completed windows, and `clean`, `features` and `report`
rebuild their outputs from the layer below.
"""

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.core.time import utc_now
from app.history import clean as clean_mod
from app.history import coverage, features, ingest_air, ingest_weather, ingest_xkdr
from app.history.store import HistoryStore
from app.history.units import POLLUTANTS
from app.integrations.openaq import OpenAQClient
from app.integrations.openmeteo import OpenMeteoClient


def default_db(settings: Settings) -> str:
    return str(Path(settings.data_dir) / "history.sqlite")


def parse_day(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def window_args(args) -> tuple[datetime, datetime]:
    today = utc_now().replace(hour=0, minute=0, second=0, microsecond=0)
    start = parse_day(args.from_date) if args.from_date else today - timedelta(days=365)
    end = parse_day(args.to_date) if args.to_date else today + timedelta(days=1)
    return start, end


def check_db(settings: Settings) -> dict:
    """Is PostgreSQL/PostGIS actually reachable? The pipeline does not depend on it unless this says yes."""
    from sqlalchemy import create_engine, text
    url = settings.database_url.get_secret_value()
    out = {"configured_url_host": url.split("@")[-1].split("/")[0], "postgres": "unreachable", "postgis": "unknown", "detail": ""}
    try:
        engine = create_engine(url, connect_args={"connect_timeout": settings.database_connect_timeout_s})
        with engine.connect() as conn:
            out["postgres"] = "reachable"
            out["server_version"] = conn.execute(text("show server_version")).scalar()
            ver = conn.execute(text("select extversion from pg_extension where extname='postgis'")).scalar()
            out["postgis"] = f"installed {ver}" if ver else "extension not installed"
    except Exception as exc:  # noqa: BLE001 - report any failure, including bad credentials
        out["detail"] = type(exc).__name__
    out["pipeline_store"] = "sqlite" if out["postgres"] != "reachable" or not out["postgis"].startswith("installed") else "sqlite (PostgreSQL available but not yet used)"
    return out


async def check_sources(settings: Settings) -> list[dict]:
    """Live, read-only probes of every historical source this pipeline relies on or considered. Reproducible evidence."""
    rows: list[dict] = []

    async def probe(name: str, url: str, params: dict | None = None, headers: dict | None = None, note: str = "", decode=None):
        try:
            async with httpx.AsyncClient(timeout=30) as c:
                r = await c.get(url, params=params, headers=headers)
            detail = decode(r) if decode and r.status_code == 200 else ""
            rows.append({"source": name, "url": url, "status": r.status_code, "detail": detail or note})
        except httpx.HTTPError as exc:
            rows.append({"source": name, "url": url, "status": None, "detail": type(exc).__name__})

    key = settings.aq_api_key.get_secret_value()
    if key:
        await probe("OpenAQ v3 locations (API)", f"{settings.aq_api_base_url}/locations", {"bbox": "76.7,28.1,77.8,29.05", "monitor": "true", "limit": 1},
                    {"X-API-Key": key}, decode=lambda r: 'reachable, key accepted')
    else:
        rows.append({"source": "OpenAQ v3 (API)", "url": settings.aq_api_base_url, "status": None, "detail": "AQ_API_KEY is not set"})
    await probe("Open-Meteo archive", settings.open_meteo_archive_url,
                {"latitude": 28.61, "longitude": 77.21, "start_date": "2025-03-01", "end_date": "2025-03-01", "hourly": "temperature_2m,boundary_layer_height", "timezone": "GMT"},
                decode=lambda r: f"{len(r.json()['hourly']['time'])} hourly rows")
    await probe("Open-Meteo historical-forecast (reachable only; not ingested)", "https://historical-forecast-api.open-meteo.com/v1/forecast",
                {"latitude": 28.61, "longitude": 77.21, "start_date": "2025-03-01", "end_date": "2025-03-01", "hourly": "temperature_2m", "timezone": "GMT"},
                decode=lambda r: f"{len(r.json()['hourly']['time'])} hourly rows")
    await probe("OpenAQ public S3 archive (reachable only; not ingested)", "https://openaq-data-archive.s3.amazonaws.com/",
                {"list-type": 2, "prefix": "records/csv.gz/locationid=6932/year=2026/month=10/", "max-keys": 1},
                decode=lambda r: "per-location, per-day csv.gz files of raw (sub-hourly) records")
    rows.append({"source": "CPCB (cpcb.nic.in / CCR portal)", "url": "-", "status": None,
                 "detail": "Not used: no documented public data API was verified. CPCB data reaches this project through OpenAQ."})
    return rows


async def run(args) -> int:
    settings = get_settings()
    configure_logging(settings)
    if args.cmd == "check-db":
        print(json.dumps(check_db(settings), indent=1))
        return 0
    if args.cmd == "sources":
        for r in await check_sources(settings):
            print(f"{r['source']}\n   {r['url']}\n   HTTP {r['status']}  {r['detail']}")
        return 0

    if args.cmd == "sync-postgis":  # reads history.sqlite read-only; writes only to PostgreSQL
        from app.db.postgis_sync import sync
        from app.db.session import get_engine

        res = await asyncio.to_thread(sync, get_engine(), args.db or default_db(settings), full=args.full, progress=lambda m: print(m, flush=True))
        print(json.dumps(res, indent=1, default=str))
        return 0

    store = HistoryStore(args.db or default_db(settings))
    if args.cmd == "ingest-xkdr":  # CPCB history from the XKDR archive; its own window (it ends 2025-09-01 for Delhi-NCR)
        x_start = datetime.fromisoformat(args.from_date) if args.from_date else datetime(2022, 1, 1)
        x_end = datetime.fromisoformat(args.to_date) if args.to_date else datetime(2025, 9, 2)
        pols = [p for p in (args.pollutants or "pm25,pm10,no2,so2,o3,co").split(",") if p]
        res = await ingest_xkdr.run(store, settings.india_aqi_api_key.get_secret_value(), x_start, x_end, pols, concurrency=min(args.concurrency, 6))
        print(json.dumps(res, indent=1))
        return 0
    start, end = window_args(args)
    if not args.from_date and not args.to_date:
        # Without explicit dates, reuse the window of the most recent ingest so every step of one dataset sees the same window
        # (and so a run after UTC midnight does not silently shift the chunk boundaries).
        last = store.query("select params from ingest_runs where kind='ingest-air' order by started_at desc limit 1")
        if last:
            saved = json.loads(last[0][0])
            start, end = datetime.fromisoformat(saved["from"]), datetime.fromisoformat(saved["to"])
    say = (lambda m: print(m, flush=True))
    rate = args.rate or settings.aq_rate_per_minute
    # Backfills run for hours: retry transient failures (including HTTP 429) with a longer backoff than the interactive pages use.
    air = OpenAQClient(Settings(**{**settings.model_dump(), "aq_rate_per_minute": rate, "aq_max_attempts": max(settings.aq_max_attempts, 5),
                                   "aq_retry_backoff_s": max(settings.aq_retry_backoff_s, 4.0)}))
    meteo = OpenMeteoClient(settings)
    steps = ["discover", "ingest-air", "ingest-weather", "clean", "features", "report"] if args.cmd == "all" else [args.cmd]
    pollutants = [p for p in (args.pollutants or "pm25,pm10").split(",") if p]
    bad = [p for p in pollutants if p not in POLLUTANTS]
    if bad:
        print(f"unknown pollutant(s): {bad}", file=sys.stderr)
        return 2
    for step in steps:
        params = {"from": start.isoformat(), "to": end.isoformat()}
        if step == "discover":
            rid = ingest_air.start_run(store, "discover", params)
            res = await ingest_air.discover(store, air, start, rid)
            ingest_air.finish_run(store, rid, "ok", 0, 0, json.dumps(res))
        elif step == "ingest-air":
            rid = ingest_air.start_run(store, "ingest-air", {**params, "chunk_days": args.chunk_days})
            res = await ingest_air.backfill(store, air, start, end, rid, chunk_days=args.chunk_days, progress=say, max_requests=args.max_requests, concurrency=args.concurrency)
            ingest_air.finish_run(store, rid, "ok" if not res["failed_windows"] else "partial", res["requests"], res["rows_added"], res["note"])
        elif step == "ingest-weather":
            rid = ingest_air.start_run(store, "ingest-weather", params)
            res = await ingest_weather.backfill_weather(store, meteo, start, end, rid, progress=say)
            ingest_air.finish_run(store, rid, "ok" if not res["failed_windows"] else "partial", res["requests"], res["rows_added"], res["note"])
        elif step == "clean":
            res = {"air": clean_mod.clean_air(store), "weather": clean_mod.clean_weather(store)}
        elif step == "features":
            res = features.build_model_ready(store, pollutants, latency_hours=args.latency_hours)
        else:
            res = {"written_to": args.out}
            coverage.write_reports(store, start, end, args.out)
        print(f"[{step}] {json.dumps(res, default=str)}", flush=True)
    store.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m app.history", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["check-db", "sources", "discover", "ingest-air", "ingest-xkdr", "ingest-weather", "clean", "features", "report", "sync-postgis", "all"])
    p.add_argument("--db", help="history database path (default DATA_DIR/history.sqlite)")
    p.add_argument("--from", dest="from_date", help="window start, YYYY-MM-DD (UTC); default: the last ingest-air window, else one year ago")
    p.add_argument("--to", dest="to_date", help="window end (exclusive), YYYY-MM-DD; default tomorrow")
    p.add_argument("--chunk-days", type=int, default=40)
    p.add_argument("--concurrency", type=int, default=4, help="parallel OpenAQ requests (start times are still rate-limited)")
    p.add_argument("--max-requests", type=int, default=None)
    p.add_argument("--rate", type=int, default=None, help="OpenAQ requests per minute (default AQ_RATE_PER_MINUTE=50; the free limit is 60)")
    p.add_argument("--pollutants", help="target pollutants for `features`, comma separated (default pm25,pm10)")
    p.add_argument("--latency-hours", type=int, default=0)
    p.add_argument("--full", action="store_true", help="sync-postgis: reload every row instead of only the newest week")
    p.add_argument("--out", default="../docs/data", help="report output folder")
    return asyncio.run(run(p.parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
