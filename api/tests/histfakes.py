"""Fakes and builders shared by the history-pipeline tests (no network, in-memory SQLite)."""

import hashlib
import json
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import get_settings
from app.history.store import HistoryStore
from app.integrations.openaq import OpenAQClient

HOUR = timedelta(hours=1)
FETCHED = "2026-02-01T00:00:00Z"


def utc(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def isoz(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def store() -> HistoryStore:
    return HistoryStore(":memory:")


def add_station(st: HistoryStore, sid=1, lat=28.61, lon=77.21, zone="Delhi", agency="Delhi (DPCC)", name="Alpha"):
    st.execute("insert or replace into stations (station_id,name,lat,lon,provider,owner,zone,agency,datetime_first,datetime_last) values (?,?,?,?,?,?,?,?,?,?)",
               (sid, name, lat, lon, "CPCB", "Delhi Pollution Control Committee", zone, agency, "2025-01-01T00:00:00Z", "2026-12-31T00:00:00Z"))


def add_sensor(st: HistoryStore, sensor_id, station_id, parameter, units="µg/m³", first="2025-01-01T00:00:00Z", last="2026-12-31T00:00:00Z"):
    st.execute("insert or replace into sensors (sensor_id,station_id,parameter,units,datetime_first,datetime_last) values (?,?,?,?,?,?)",
               (sensor_id, station_id, parameter, units, first, last))


def add_raw(st: HistoryStore, sensor_id, station_id, parameter, to_utc: str, value, units="µg/m³", coverage=100.0, fetched=FETCHED,
            span_hours=1, run="r1"):
    """One OpenAQ-style hourly row. `to_utc` is the period end, e.g. 2026-01-01T00:30:00Z (an IST-hour-ending period)."""
    end = utc(to_utc)
    start = end - span_hours * HOUR
    key = hashlib.sha1(f"{sensor_id}|{to_utc}|{value!r}|{units}|{fetched}".encode()).hexdigest()
    st.execute("insert or ignore into raw_air values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
               (key, sensor_id, station_id, parameter, units, isoz(start), to_utc, None, value, None, None, None, 4, 4, coverage, 0, fetched, run))


def add_series(st: HistoryStore, sensor_id, station_id, parameter, start_end: str, values, **kw):
    """Consecutive hourly rows; `values` may contain None (stored as a null-value row) or the string 'skip' (no row at all)."""
    end = utc(start_end)
    for i, v in enumerate(values):
        if v == "skip":
            continue
        add_raw(st, sensor_id, station_id, parameter, isoz(end + i * HOUR), v, **kw)


def add_weather_raw(st: HistoryStore, station_id: int, times, fetched=FETCHED, **overrides):
    cols = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure", "wind_speed_10m", "wind_direction_10m",
            "wind_gusts_10m", "precipitation", "cloud_cover", "boundary_layer_height", "shortwave_radiation"]
    base = dict(zip(cols, [20.0, 50.0, 10.0, 990.0, 10.0, 90.0, 20.0, 0.0, 30.0, 500.0, 100.0]))
    base.update(overrides)
    for t in times:
        vals = [base[c] for c in cols]
        key = hashlib.sha1(f"st{station_id}|{t}|{vals!r}|{fetched}".encode()).hexdigest()
        st.execute("insert or ignore into raw_weather values (?,?,?," + ",".join("?" * 11) + ",?,?)", (key, f"st{station_id}", t, *vals, fetched, "w1"))
    st.commit()


# ---------------------------------------------------------------------------------------------- a fake OpenAQ
def loc(id_, last="2026-01-10T12:00:00Z", first="2025-01-01T00:00:00Z", mobile=False, lat=28.6, lon=77.2, owner="Delhi Pollution Control Committee"):
    return {"id": id_, "name": f"Station {id_}", "locality": None, "coordinates": {"latitude": lat, "longitude": lon}, "isMobile": mobile,
            "isMonitor": True, "owner": {"name": owner}, "provider": {"name": "CPCB"}, "licenses": [], "timezone": "Asia/Kolkata",
            "datetimeFirst": {"utc": first}, "datetimeLast": {"utc": last}}


def sensor_rec(id_, name, units, first="2025-01-01T00:00:00Z", last="2026-01-10T12:00:00Z"):
    return {"id": id_, "name": f"{name} {units}", "parameter": {"id": 1, "name": name, "units": units},
            "datetimeFirst": {"utc": first}, "datetimeLast": {"utc": last}}


class FakeOpenAQ:
    """Serves /locations, /locations/{id}/sensors and /sensors/{id}/hours with IST-hour-ending periods (end at :30 UTC)."""

    def __init__(self, locations, sensors, value=lambda sid, end: 50.0 + end.hour, fail=None):
        self.locations, self.sensors, self.value, self.fail = locations, sensors, value, fail or (lambda sid, frm: False)
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path, q = request.url.path.replace("/api", "", 1), dict(request.url.params)
        self.calls.append((path, q))
        if path == "/locations":
            return httpx.Response(200, json={"meta": {}, "results": self.locations})
        if path.endswith("/sensors") and path.startswith("/locations/"):
            return httpx.Response(200, json={"meta": {}, "results": self.sensors[int(path.split("/")[2])]})
        if path.startswith("/sensors/") and path.endswith("/hours"):
            sid = int(path.split("/")[2])
            frm, to = utc(q["datetime_from"]), utc(q["datetime_to"])
            if self.fail(sid, frm):
                return httpx.Response(500)
            info = next(s for ss in self.sensors.values() for s in ss if s["id"] == sid)
            first, last = utc(info["datetimeFirst"]["utc"]), utc(info["datetimeLast"]["utc"])
            ends, e = [], frm.replace(minute=30, second=0)
            if e < frm:
                e += HOUR
            while e <= to:
                if first <= e <= last:
                    ends.append(e)
                e += HOUR
            page, limit = int(q.get("page", 1)), int(q.get("limit", 1000))
            rows = [{"value": self.value(sid, end), "flagInfo": {"hasFlags": False}, "parameter": {"id": 2, "name": "x", "units": info["parameter"]["units"]},
                     "period": {"label": "1hour", "interval": "01:00:00", "datetimeFrom": {"utc": isoz(end - HOUR), "local": "x"}, "datetimeTo": {"utc": isoz(end), "local": isoz(end + timedelta(hours=5, minutes=30))}},
                     "summary": {"min": 1.0, "max": 2.0, "sd": 0.1},
                     "coverage": {"expectedCount": 4, "observedCount": 4, "percentCoverage": 100.0}} for end in ends]
            return httpx.Response(200, json={"meta": {}, "results": rows[(page - 1) * limit: page * limit]})
        return httpx.Response(404)

    def client(self) -> OpenAQClient:
        return OpenAQClient(get_settings(), transport=httpx.MockTransport(self))

    def hour_requests(self, sensor_id=None):
        return [c for c in self.calls if c[0].endswith("/hours") and (sensor_id is None or f"/sensors/{sensor_id}/" in c[0])]


def archive_response(points: int, times, units=None, fail_unit=False):
    """Open-Meteo archive style body for `points` locations."""
    names = ["temperature_2m", "relative_humidity_2m", "dew_point_2m", "surface_pressure", "wind_speed_10m", "wind_direction_10m",
             "wind_gusts_10m", "precipitation", "cloud_cover", "boundary_layer_height", "shortwave_radiation"]
    u = {"time": "iso8601", "temperature_2m": "°C", "relative_humidity_2m": "%", "dew_point_2m": "°C", "surface_pressure": "hPa",
         "wind_speed_10m": "km/h", "wind_direction_10m": "°", "wind_gusts_10m": "km/h", "precipitation": "mm", "cloud_cover": "%",
         "boundary_layer_height": "m", "shortwave_radiation": "W/m²"}
    if fail_unit:
        u["wind_speed_10m"] = "m/s"
    items = []
    for p in range(points):
        hourly = {"time": [t for t in times]}
        for n in names:
            hourly[n] = [10.0 + p for _ in times]
        items.append({"latitude": 28.5 + p * 0.1, "longitude": 77.2, "elevation": 215.0, "hourly_units": u, "hourly": hourly})
    return items if points > 1 else items[0]
