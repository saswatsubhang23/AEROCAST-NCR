"""Spatial queries served from PostgreSQL/PostGIS (the synced copy of the cleaned station history).

These endpoints answer "where" questions with indexed spatial SQL (GiST on `env_station.geom`). They return measured station
observations only, labelled with source, period and quality flags; nothing is interpolated here. When PostgreSQL is down they return
503 `geo_unavailable` and the rest of the application is unaffected.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import get_engine
from app.history.ingest_air import iso

router = APIRouter(prefix="/geo", tags=["geospatial (PostGIS)"])

GeoVariable = Literal["pm25", "pm10", "no2", "so2", "co", "o3"]

# Latest usable observation per station for one variable. The LATERAL lookup uses ix_env_record_loc (location_id, variable, valid_to desc).
LATEST = """
left join lateral (
  select r.valid_from, r.valid_to, r.value, r.unit, r.source, r.quality_flags, r.retrieved_at
  from env_record r
  where r.location_id = 'station:' || s.station_id and r.variable = :variable and r.kind = 'observation' and r.usable
  order by r.valid_to desc limit 1
) o on true
"""


def _run(sql: str, params: dict | None = None):
    try:
        with get_engine().connect() as conn:
            return conn.execute(text(sql), params or {}).mappings().all()
    except SQLAlchemyError as exc:
        raise HTTPException(503, {"code": "geo_unavailable", "message": f"PostgreSQL/PostGIS is not reachable ({type(exc).__name__})."}) from exc


def _observation(row) -> dict | None:
    if row["valid_to"] is None:
        return None
    return {
        "value": row["value"], "unit": row["unit"], "source": row["source"], "kind": "observation",
        "period_from": iso(row["valid_from"]), "period_to": iso(row["valid_to"]),
        "retrieved_at": iso(row["retrieved_at"]), "quality_flags": list(row["quality_flags"] or []),
    }


@router.get("/status", summary="What the PostGIS copy contains and when it was last synced")
def status():
    stations = _run("select count(*) as n from env_station")[0]["n"]
    postgis = _run("select postgis_version() as v")[0]["v"]
    run = _run(
        "select run_id, started_at, finished_at, status, mode, stations, rows_read, rows_total, summary"
        " from env_sync_run where status = 'ok' order by started_at desc limit 1"
    )
    last = None
    series: list = []
    if run:
        r = dict(run[0])
        series = r.pop("summary") or []
        last = {k: (iso(v) if hasattr(v, "isoformat") else v) for k, v in r.items()}
    return {
        "postgis": postgis,
        "stations": stations,
        "records": last["rows_total"] if last else 0,
        "first_valid_from": min((s["first"] for s in series), default=None),
        "last_valid_to": max((s["newest"] for s in series), default=None),
        "series": series,
        "last_sync": last,
        "note": "Observations only. Coverage is the summary taken at the last sync; run `python -m app.history sync-postgis` to refresh.",
    }


@router.get("/stations/nearby", summary="Stations within a radius of a point, nearest first, with their latest usable observation")
def nearby(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius_km: float = Query(15.0, gt=0, le=200),
    variable: GeoVariable = "pm25",
    limit: int = Query(10, ge=1, le=100),
):
    rows = _run(
        f"""
        with p as (select st_setsrid(st_makepoint(:lon, :lat), 4326)::geography as g)
        select s.station_id, s.name, s.provider, s.zone, st_y(s.geom) as lat, st_x(s.geom) as lon,
               st_distance(s.geom::geography, p.g) / 1000.0 as distance_km,
               o.valid_from, o.valid_to, o.value, o.unit, o.source, o.quality_flags, o.retrieved_at
        from env_station s cross join p
        {LATEST}
        where st_dwithin(s.geom::geography, p.g, :radius_m)
        order by s.geom::geography <-> p.g
        limit :limit
        """,
        {"lat": lat, "lon": lon, "radius_m": radius_km * 1000.0, "variable": variable, "limit": limit},
    )
    return {
        "query": {"lat": lat, "lon": lon, "radius_km": radius_km, "variable": variable},
        "stations": [
            {"station_id": r["station_id"], "name": r["name"], "provider": r["provider"], "zone": r["zone"], "lat": r["lat"], "lon": r["lon"],
             "distance_km": round(r["distance_km"], 2), "latest": _observation(r)}
            for r in rows
        ],
        "note": "Station measurements, not interpolated. `latest` is the newest usable hour stored, which may be old: check period_to.",
    }


@router.get("/stations.geojson", summary="All stations as GeoJSON, with the latest usable observation of one variable")
def stations_geojson(variable: GeoVariable = "pm25"):
    rows = _run(
        f"""
        select s.station_id, s.name, s.provider, s.zone, st_y(s.geom) as lat, st_x(s.geom) as lon,
               o.valid_from, o.valid_to, o.value, o.unit, o.source, o.quality_flags, o.retrieved_at
        from env_station s
        {LATEST}
        order by s.station_id
        """,
        {"variable": variable},
    )
    return {
        "type": "FeatureCollection",
        "properties": {"variable": variable, "kind": "observation"},
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [r["lon"], r["lat"]]},
             "properties": {"station_id": r["station_id"], "name": r["name"], "provider": r["provider"], "zone": r["zone"], "latest": _observation(r)}}
            for r in rows
        ],
    }


@router.get("/stations/{station_id}/series", summary="Hourly usable observations of one variable at one station")
def series(
    station_id: int,
    variable: GeoVariable = "pm25",
    hours: int = Query(48, ge=1, le=24 * 31),
):
    exists = _run("select name, zone from env_station where station_id = :id", {"id": station_id})
    if not exists:
        raise HTTPException(404, {"code": "station_not_found", "message": f"No station {station_id} in the PostGIS copy."})
    rows = _run(
        """
        select valid_from, valid_to, value, unit, source, quality_flags
        from env_record
        where location_id = :loc and variable = :variable and kind = 'observation' and usable
          and valid_to > (select max(valid_to) from env_record where location_id = :loc and variable = :variable) - make_interval(hours => :hours)
        order by valid_to
        """,
        {"loc": f"station:{station_id}", "variable": variable, "hours": hours},
    )
    return {
        "station": {"station_id": station_id, "name": exists[0]["name"], "zone": exists[0]["zone"]},
        "variable": variable, "kind": "observation", "hours_requested": hours,
        "points": [
            {"period_from": iso(r["valid_from"]), "period_to": iso(r["valid_to"]), "value": r["value"], "unit": r["unit"],
             "source": r["source"], "quality_flags": list(r["quality_flags"] or [])}
            for r in rows
        ],
    }
