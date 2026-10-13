"""Live audit of the external data sources: what each really returns, over what period and area, how fresh it is, and under what limits.

    python -m app.envdata.audit            # writes docs/phase1/source-audit.json and prints a summary

Every fact in the report is something this script observed in a response on the day it ran (or says it could not). Keys are read from
the environment, sent only as request headers, and never written to the report. The script makes a few dozen requests in total.
"""

from __future__ import annotations

import asyncio
import json
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import get_settings

NCR_BBOX = (76.4, 27.9, 78.1, 29.2)  # west, south, east, north
DELHI = (28.6139, 77.2090)
RATE_HEADERS = ("x-ratelimit-limit", "x-ratelimit-remaining", "x-ratelimit-used", "x-ratelimit-reset", "retry-after", "ratelimit-limit", "ratelimit-remaining", "ratelimit-reset")
UA = {"User-Agent": "aerocast-ncr-audit/0.1"}


def _rate(h: httpx.Headers) -> dict:
    return {k: h[k] for k in RATE_HEADERS if k in h}


def _schema(obj, depth: int = 0) -> object:
    """Key -> type name, recursively, for a small sample (values are not copied)."""
    if isinstance(obj, dict):
        return {k: _schema(v, depth + 1) if depth < 3 else type(v).__name__ for k, v in obj.items()}
    if isinstance(obj, list):
        return [_schema(obj[0], depth + 1)] if obj else []
    return type(obj).__name__


def _age_hours(iso: str | None, now: datetime) -> float | None:
    if not iso:
        return None
    try:
        t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return round((now - t).total_seconds() / 3600.0, 1)


async def _get(c: httpx.AsyncClient, url: str, **kw) -> tuple[int, dict | list | None, httpx.Headers, float]:
    t0 = asyncio.get_event_loop().time()
    try:
        r = await c.get(url, **kw)
    except httpx.HTTPError as exc:
        return 0, {"error": type(exc).__name__}, httpx.Headers(), 0.0
    ms = (asyncio.get_event_loop().time() - t0) * 1000
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body, r.headers, ms


# ------------------------------------------------------------------------------------------------ Open-Meteo
async def open_meteo(c: httpx.AsyncClient, now: datetime) -> dict:
    out: dict = {"provider": "Open-Meteo", "licence": "CC BY 4.0 data; free API is non-commercial, 10,000 calls/day, 5,000/hour, 600/minute (their terms); commercial use needs a subscription",
                 "attribution": "Weather data by Open-Meteo.com; contains ECMWF, DWD, NOAA and other national weather services' model output"}
    hourly = "temperature_2m,relative_humidity_2m,pressure_msl,precipitation,cloud_cover,wind_speed_10m,wind_direction_10m,boundary_layer_height,shortwave_radiation,visibility"
    code, body, h, ms = await _get(c, "https://api.open-meteo.com/v1/forecast", params={"latitude": DELHI[0], "longitude": DELHI[1], "hourly": hourly, "past_days": 7, "forecast_days": 16, "timezone": "GMT"})
    f: dict = {"status": code, "latency_ms": round(ms), "rate_headers": _rate(h)}
    if isinstance(body, dict) and "hourly" in body:
        t = body["hourly"]["time"]
        f.update({
            "top_level_keys": sorted(body.keys()), "hourly_units": body.get("hourly_units"), "hours": len(t), "first": t[0], "last": t[-1],
            "snapped_to": {"lat": body.get("latitude"), "lon": body.get("longitude"), "elevation_m": body.get("elevation")},
            "null_share": {k: round(sum(v is None for v in vs) / len(vs), 3) for k, vs in body["hourly"].items() if k != "time"},
            "note": "wind speed is km/h unless wind_speed_unit=ms is requested (the app requests ms)",
        })
    out["forecast_api"] = f

    # the longest history and forecast the free API accepts
    lim: dict = {}
    for name, params in (("past_days_92", {"past_days": 92}), ("past_days_93", {"past_days": 93}), ("forecast_days_16", {"forecast_days": 16}), ("forecast_days_17", {"forecast_days": 17})):
        code, body, _, _ = await _get(c, "https://api.open-meteo.com/v1/forecast", params={"latitude": DELHI[0], "longitude": DELHI[1], "hourly": "temperature_2m", "timezone": "GMT", **params})
        lim[name] = code if code != 200 else "accepted"
    out["forecast_api"]["limits_probed"] = lim

    # archive: first and last available day
    arch: dict = {}
    code, body, h, _ = await _get(c, "https://archive-api.open-meteo.com/v1/archive", params={"latitude": DELHI[0], "longitude": DELHI[1], "hourly": "temperature_2m,pm10", "start_date": "1940-01-01", "end_date": "1940-01-02", "timezone": "GMT"})
    arch["1940-01-01"] = {"status": code, "non_null_temperature": bool(body and isinstance(body, dict) and any(v is not None for v in body.get("hourly", {}).get("temperature_2m", [])))}
    start = (now - timedelta(days=12)).date().isoformat()
    end = (now - timedelta(days=1)).date().isoformat()
    code, body, h, _ = await _get(c, "https://archive-api.open-meteo.com/v1/archive", params={"latitude": DELHI[0], "longitude": DELHI[1], "hourly": "temperature_2m", "start_date": start, "end_date": end, "timezone": "GMT"})
    if isinstance(body, dict) and "hourly" in body:
        t, v = body["hourly"]["time"], body["hourly"]["temperature_2m"]
        last = max((i for i, x in enumerate(v) if x is not None), default=None)
        arch["latest_available_hour"] = t[last] if last is not None else None
        arch["lag_hours"] = _age_hours(t[last] + ":00Z", now) if last is not None else None
    arch["rate_headers"] = _rate(h)
    out["archive_api"] = arch
    return out


async def cams(c: httpx.AsyncClient, now: datetime) -> dict:
    """Open-Meteo Air Quality (CAMS): variables, units, period, and the real cell size over Delhi."""
    base = "https://air-quality-api.open-meteo.com/v1/air-quality"
    out: dict = {"provider": "Open-Meteo Air Quality API (ECMWF CAMS)", "licence": "CC BY 4.0 data via Open-Meteo; CAMS data are Copernicus products (free, with attribution). The free API is non-commercial.",
                 "attribution": "Generated using Copernicus Atmosphere Monitoring Service information; Open-Meteo.com"}
    vars_ = "pm10,pm2_5,carbon_monoxide,nitrogen_dioxide,sulphur_dioxide,ozone,nitrogen_monoxide,aerosol_optical_depth,dust,uv_index"
    code, body, h, ms = await _get(c, base, params={"latitude": DELHI[0], "longitude": DELHI[1], "hourly": vars_, "past_days": 92, "forecast_days": 7, "timezone": "GMT"})
    r: dict = {"status": code, "latency_ms": round(ms), "rate_headers": _rate(h)}
    if isinstance(body, dict) and "hourly" in body:
        t = body["hourly"]["time"]
        r.update({"hourly_units": body.get("hourly_units"), "hours": len(t), "first": t[0], "last": t[-1],
                  "null_share": {k: round(sum(v is None for v in vs) / len(vs), 3) for k, vs in body["hourly"].items() if k != "time"}})
    out["request_92d_7d"] = r
    probes = {}
    for name, params in (("past_days_93", {"past_days": 93}), ("forecast_days_8", {"forecast_days": 8})):
        code, _, _, _ = await _get(c, base, params={"latitude": DELHI[0], "longitude": DELHI[1], "hourly": "pm2_5", "timezone": "GMT", **params})
        probes[name] = code if code != 200 else "accepted"
    out["limits_probed"] = probes
    # cell size: step along a parallel and a meridian, count distinct values at one hour
    lons = [round(76.7 + 0.05 * i, 3) for i in range(23)]
    code, body, _, _ = await _get(c, base, params={"latitude": ",".join(["28.6"] * len(lons)), "longitude": ",".join(str(x) for x in lons), "hourly": "pm2_5", "past_hours": 1, "forecast_hours": 1, "timezone": "GMT"})
    if isinstance(body, list):
        vals = [b["hourly"]["pm2_5"][0] for b in body]
        edges = [lons[i] for i in range(1, len(vals)) if vals[i] != vals[i - 1]]
        out["cell_size_probe"] = {"distinct_values_over_1.1_deg_of_longitude": len(set(vals)), "value_changes_at_longitude": edges,
                                  "inferred_cell_width_deg": round(statistics.mean([b - a for a, b in zip(edges, edges[1:])]), 2) if len(edges) > 1 else None}
    return out


# ------------------------------------------------------------------------------------------------ OpenAQ
async def openaq(c: httpx.AsyncClient, now: datetime, key: str) -> dict:
    out: dict = {"provider": "OpenAQ v3", "licence": "Per data provider (each location lists its licences; mostly CC BY 4.0 for government data); API terms require attribution"}
    if not key:
        out["error"] = "AQ_API_KEY is not set: nothing probed"
        return out
    hdr = {"X-API-Key": key, **UA}
    code, body, h, ms = await _get(c, "https://api.openaq.org/v3/locations", params={"bbox": ",".join(str(v) for v in NCR_BBOX), "limit": 1000, "monitor": "true"}, headers=hdr)
    out["locations"] = {"status": code, "latency_ms": round(ms), "rate_headers": _rate(h)}
    if isinstance(body, dict) and "results" in body:
        res = body["results"]
        out["locations"].update({"meta": body.get("meta"), "count_returned": len(res), "result_schema": _schema(res[0]) if res else None})
        last = [_age_hours((r.get("datetimeLast") or {}).get("utc"), now) for r in res]
        last = [x for x in last if x is not None]
        if last:
            s = sorted(last)
            out["freshness_hours_since_last_datum"] = {"n": len(s), "min": s[0], "p25": s[len(s) // 4], "median": s[len(s) // 2], "p75": s[3 * len(s) // 4], "max": s[-1],
                                                       "within_3h": sum(x <= 3 for x in s), "within_24h": sum(x <= 24 for x in s), "older_than_7d": sum(x > 168 for x in s)}
        lic: dict[str, int] = {}
        prov: dict[str, int] = {}
        for r in res:
            for L in r.get("licenses") or []:
                lic[str(L.get("name"))] = lic.get(str(L.get("name")), 0) + 1
            pv = (r.get("provider") or {}).get("name")
            prov[str(pv)] = prov.get(str(pv), 0) + 1
        out["licences_listed"] = dict(sorted(lic.items(), key=lambda kv: -kv[1])[:8])
        out["providers"] = dict(sorted(prov.items(), key=lambda kv: -kv[1])[:8])
        units: dict[str, set] = {}
        for r in res:
            for s in r.get("sensors") or []:
                p = (s.get("parameter") or {})
                units.setdefault(str(p.get("name")), set()).add(str(p.get("units")))
        out["parameter_units_seen"] = {k: sorted(v) for k, v in sorted(units.items())}
        # one hourly series: period and shape
        sid = next((s["id"] for r in res if (r.get("datetimeLast") or {}).get("utc") for s in r.get("sensors") or [] if (s.get("parameter") or {}).get("name") == "pm25"), None)
        if sid:
            code, b2, h2, _ = await _get(c, f"https://api.openaq.org/v3/sensors/{sid}/hours", params={"limit": 3}, headers=hdr)
            out["hours_endpoint"] = {"status": code, "rate_headers": _rate(h2), "result_schema": _schema(b2["results"][0]) if isinstance(b2, dict) and b2.get("results") else None}
    return out


# ------------------------------------------------------------------------------------------------ xKDR
async def xkdr(c: httpx.AsyncClient, now: datetime, key: str) -> dict:
    out: dict = {"provider": "xKDR India air quality archive", "licence": "Not stated in the responses inspected; to be confirmed with xKDR before redistribution"}
    if not key:
        out["error"] = "INDIA_AQI_API_KEY is not set: nothing probed"
        return out
    hdr = {"Authorization": f"Bearer {key}", **UA}
    code, body, h, ms = await _get(c, "https://airquality.xkdr.org/v1/meta", headers=hdr)
    out["meta"] = {"status": code, "latency_ms": round(ms), "rate_headers": _rate(h), "body": body if isinstance(body, (dict, list)) else None}
    code, body, h, _ = await _get(c, "https://airquality.xkdr.org/v1/stations", headers=hdr)
    out["stations"] = {"status": code, "rate_headers": _rate(h)}
    if isinstance(body, dict) and isinstance(body.get("data"), list):
        data = body["data"]
        ncr = [s for s in data if isinstance(s.get("latitude"), (int, float)) and 27.9 <= s["latitude"] <= 29.2 and 76.4 <= s["longitude"] <= 78.1]
        out["stations"].update({
            "total": len(data), "in_ncr_box": len(ncr), "result_schema": _schema(data[0]) if data else None,
            "last_seen_hours_ago": (lambda xs: {"min": min(xs), "median": sorted(xs)[len(xs) // 2], "max": max(xs)} if xs else None)(
                [a for a in (_age_hours(s.get("last_seen") if (s.get("last_seen") or "").endswith("Z") else (s.get("last_seen") or "") + "+05:30", now) for s in ncr) if a is not None]),
            "first_seen_min": min((s.get("first_seen") for s in ncr if s.get("first_seen")), default=None),
        })
        if ncr:
            s0 = ncr[0]
            code, b2, h2, _ = await _get(c, "https://airquality.xkdr.org/v1/measurements", headers=hdr,
                                         params={"station": s0["station_id"], "parameter": (s0.get("parameters") or ["PM2.5"])[0], "start": "2025-08-01", "end": "2025-08-02", "agg": "hourly"})
            out["measurements"] = {"status": code, "rate_headers": _rate(h2), "result_schema": _schema(b2["data"][0]) if isinstance(b2, dict) and b2.get("data") else None}
    return out


async def run() -> dict:
    s = get_settings()
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=60.0, headers=UA) as c:
        report = {
            "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "open_meteo": await open_meteo(c, now),
            "cams_via_open_meteo": await cams(c, now),
            "openaq": await openaq(c, now, s.aq_api_key.get_secret_value()),
            "xkdr": await xkdr(c, now, s.india_aqi_api_key.get_secret_value()),
        }
    return report


def main() -> None:
    rep = asyncio.run(run())
    out = Path(__file__).resolve().parents[3] / "docs" / "phase1"
    out.mkdir(parents=True, exist_ok=True)
    (out / "source-audit.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out / 'source-audit.json'}")
    print(json.dumps({k: (v if k == "generated_at" else "ok") for k, v in rep.items()}, indent=2))


if __name__ == "__main__":
    main()
