"""Cleaning: `raw_*` to `clean_*`. Rebuilt from scratch on every run, so the output is a pure function of the raw tables.

What cleaning does and does not do
  * It NEVER edits or imputes a measurement. A bad value keeps its number and gets a flag; "usable" says whether a model
    may use it. Missing hours are not filled: they simply have no row (coverage reports count them).
  * Timestamps: `label_utc` is the *midpoint* of the provider's hourly period, rounded to the hour. OpenAQ's CPCB hours run
    on India's local hour (05:00-06:00 IST = 23:30-00:30 UTC), so the period ends at :30 UTC and its midpoint is on the
    hour, which is where Open-Meteo's hourly stamps sit. The raw period start/end and the IST end time are kept.
  * Units: `value_std` is µg/m³ (see units.py); the original value and unit stay in `orig_value`/`orig_unit`.
  * Duplicates: several raw rows for one (station, pollutant, hour) are reduced to one by a fixed rule, and the reduction is
    flagged (REVISED = same sensor re-fetched with a different value; MULTI_SENSOR/SENSOR_CONFLICT = several sensors).
"""

import logging
from datetime import datetime, timedelta, timezone

from app.core.time import to_ist
from app.history.ingest_air import iso, parse_iso
from app.history.ingest_weather import PROVISIONAL_DAYS
from app.history.store import HistoryStore
from app.history.units import (
    FLATLINE_MIN_RUN, HARD_FLAGS, LOW_COVERAGE_PCT, MIN_REFERENCE_SENSORS, PLAUSIBLE_MEDIAN_FLOOR_STD, POLLUTANTS, STD_UNIT, UNIT_SUSPECT_FACTOR, WEATHER_RANGE,
    WEATHER_VARIABLES, range_flags, to_standard, unit_key,
)

logger = logging.getLogger("app.history")
HOUR = timedelta(hours=1)


def hour_label(period_from: datetime, period_to: datetime) -> tuple[datetime, bool]:
    """(label, rounded): midpoint of the period rounded half-up to the hour; `rounded` is True if it was not already on the hour."""
    mid = period_from + (period_to - period_from) / 2
    floor = mid.replace(minute=0, second=0, microsecond=0)
    rounded = mid != floor
    return (floor + HOUR if (mid - floor) >= timedelta(minutes=30) else floor), rounded


def _median(v: list[float]) -> float:
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def unit_sanity(store: HistoryStore) -> set[int]:
    """Sensors whose labelled unit contradicts their magnitude (e.g. CO labelled ppb but reading ~1, which is ~1000x too small
    for ppb). Evidence is recorded in `sensor_unit_checks`; the sensors' rows are flagged UNIT_SUSPECT and excluded from use,
    never rescaled: guessing the right unit would be inventing data."""
    store.execute("delete from sensor_unit_checks")
    per_sensor: dict[int, dict] = {}
    cur = store.query("select sensor_id, station_id, parameter, units, value from raw_air where value is not null order by sensor_id")
    for r in cur:
        d = per_sensor.setdefault(r["sensor_id"], {"station": r["station_id"], "p": r["parameter"], "u": r["units"], "vals": []})
        std, flags = to_standard(r["parameter"], r["value"], r["units"])
        if std is not None and std >= 0:
            d["vals"].append(std)
    medians = {sid: (d, _median(d["vals"])) for sid, d in per_sensor.items() if d["vals"] and d["p"] in POLLUTANTS}
    reference: dict[str, float] = {}
    for p in POLLUTANTS:
        native = [m for d, m in medians.values() if d["p"] == p and unit_key(d["u"]) == "ug/m3"]
        if len(native) >= MIN_REFERENCE_SENSORS:
            reference[p] = _median(native)
    suspect: set[int] = set()
    for sid, (d, m) in sorted(medians.items()):
        ref = reference.get(d["p"])
        ratio = None if not ref or m <= 0 else m / ref
        bad = ref is not None and (m <= 0 or ratio > UNIT_SUSPECT_FACTOR or ratio < 1 / UNIT_SUSPECT_FACTOR) and unit_key(d["u"]) != "ug/m3"
        floor = PLAUSIBLE_MEDIAN_FLOOR_STD.get(d["p"])
        if floor is not None and m < floor:
            bad = True  # physically implausible median: the unit label cannot be right (no reference sensors needed)
        store.execute("insert into sensor_unit_checks values (?,?,?,?,?,?,?,?,?)", (sid, d["station"], d["p"], d["u"], len(d["vals"]), m, ref, ratio, int(bad)))
        if bad:
            suspect.add(sid)
    store.commit()
    return suspect


def clean_air(store: HistoryStore, station_ids: list[int] | None = None) -> dict:
    """Rebuild `clean_air` from `raw_air`: for every station, or only for `station_ids` (the other stations' rows are left untouched)."""
    if station_ids:
        marks = ",".join("?" * len(station_ids))
        store.execute(f"delete from clean_air where station_id in ({marks})", tuple(station_ids))
    else:
        store.execute("delete from clean_air")
    suspect = unit_sanity(store)
    out_rows = 0
    flagged = {}
    pairs = store.query("select distinct station_id, parameter from raw_air order by station_id, parameter")
    if station_ids:
        wanted = set(station_ids)
        pairs = [p for p in pairs if p["station_id"] in wanted]
    sensor_last = {r["sensor_id"]: r["datetime_last"] or "" for r in store.query("select sensor_id, datetime_last from sensors")}
    for pair in pairs:
        station_id, pollutant = pair["station_id"], pair["parameter"]
        if pollutant not in POLLUTANTS:
            continue
        rows = store.query("select * from raw_air where station_id=? and parameter=? order by period_to_utc, sensor_id, fetched_at", (station_id, pollutant))
        by_label: dict[datetime, list] = {}
        meta: dict[int, tuple[bool, bool]] = {}  # id(row) -> (irregular, rounded)
        for r in rows:
            p_from, p_to = parse_iso(r["period_from_utc"]), parse_iso(r["period_to_utc"])
            if p_to is None:
                continue
            if p_from is None:
                p_from = p_to - HOUR
            label, rounded = hour_label(p_from, p_to)
            meta[r["row_key"]] = (p_to - p_from != HOUR, rounded)
            by_label.setdefault(label, []).append(r)

        built: list[dict] = []
        for label in sorted(by_label):
            cands = by_label[label]
            per_sensor: dict[int, list] = {}
            for r in cands:
                per_sensor.setdefault(r["sensor_id"], []).append(r)
            evaluated = []
            for sensor_id, versions in per_sensor.items():
                latest = max(versions, key=lambda x: (x["fetched_at"], x["row_key"]))
                revised = len({(v["value"], v["units"]) for v in versions}) > 1
                std, flags = to_standard(pollutant, latest["value"], latest["units"])
                if std is not None:
                    flags += range_flags(pollutant, std)
                if sensor_id in suspect:
                    flags.append("UNIT_SUSPECT")
                irregular, rounded = meta[latest["row_key"]]
                if irregular:
                    flags.append("PERIOD_IRREGULAR")
                if rounded:
                    flags.append("ALIGN_ROUNDED")
                if revised:
                    flags.append("REVISED")
                cov = latest["percent_coverage"]
                if cov is not None and cov < LOW_COVERAGE_PCT:
                    flags.append("LOW_COVERAGE")
                evaluated.append((latest, std, flags))

            def rank(e):
                latest, std, flags = e
                ok = std is not None and not (set(flags) & HARD_FLAGS)
                return (ok, latest["percent_coverage"] if latest["percent_coverage"] is not None else -1.0,
                        sensor_last.get(latest["sensor_id"], ""), latest["sensor_id"])

            best = max(evaluated, key=rank)
            latest, std, flags = best
            usable_vals = [e[1] for e in evaluated if e[1] is not None and not (set(e[2]) & HARD_FLAGS)]
            if len(usable_vals) > 1:
                hi, lo = max(usable_vals), min(usable_vals)
                flags = flags + (["SENSOR_CONFLICT"] if hi - lo > max(0.1 * hi, 2.0) else ["MULTI_SENSOR"])
            hard = bool(set(flags) & HARD_FLAGS)
            built.append({
                "label": label, "latest": latest, "std": std, "flags": sorted(set(flags)), "n": len(per_sensor),
                "usable": std is not None and not hard,
            })

        # Flat-line runs: identical consecutive hourly values (a stuck instrument looks like this). Flagged, never removed.
        i = 0
        while i < len(built):
            j = i
            v = built[i]["latest"]["value"]
            while (j + 1 < len(built) and built[j + 1]["label"] - built[j]["label"] == HOUR and built[j + 1]["latest"]["value"] == v
                   and v is not None):
                j += 1
            if j - i + 1 >= FLATLINE_MIN_RUN:
                for k in range(i, j + 1):
                    built[k]["flags"] = sorted(set(built[k]["flags"]) | {"FLATLINE"})
            i = j + 1

        batch = []
        for b in built:
            r = b["latest"]
            p_to = parse_iso(r["period_to_utc"])
            batch.append((station_id, pollutant, iso(b["label"]), r["period_from_utc"], r["period_to_utc"], to_ist(p_to).isoformat(),
                          r["sensor_id"], r["value"], r["units"], b["std"], STD_UNIT if b["std"] is not None else None, r["percent_coverage"],
                          b["n"], ",".join(b["flags"]), int(b["usable"])))
            for f in b["flags"]:
                flagged[f] = flagged.get(f, 0) + 1
        store.executemany("insert into clean_air values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", batch)
        out_rows += len(batch)
    store.commit()
    return {"clean_air_rows": out_rows, "unit_suspect_sensors": len(suspect), "flag_counts": dict(sorted(flagged.items()))}


def clean_weather(store: HistoryStore) -> dict:
    store.execute("delete from clean_weather")
    meta = {}
    for m in store.query("select point_id, grid_lat, grid_lon, fetched_at from raw_weather_meta order by fetched_at"):
        meta[m["point_id"]] = (m["grid_lat"], m["grid_lon"])
    stations = {f"st{r['station_id']}": r["station_id"] for r in store.query("select station_id from stations")}
    total = 0
    flagged: dict[str, int] = {}
    for pid in [r[0] for r in store.query("select distinct point_id from raw_weather order by point_id")]:
        station_id = stations.get(pid)
        if station_id is None:
            continue
        rows = store.query("select * from raw_weather where point_id=? order by time_utc, fetched_at, row_key", (pid,))
        last_by_time: dict[str, list] = {}
        for r in rows:
            last_by_time.setdefault(r["time_utc"], []).append(r)
        batch = []
        for t in sorted(last_by_time):
            versions = last_by_time[t]
            r = versions[-1]
            flags: list[str] = []
            if len({tuple(v[c] for c in WEATHER_VARIABLES) for v in versions}) > 1:
                flags.append("REVISED")
            ts, fetched = parse_iso(t), parse_iso(r["fetched_at"])
            provisional = int(ts is not None and fetched is not None and fetched - ts < timedelta(days=PROVISIONAL_DAYS))
            if provisional:
                flags.append("PROVISIONAL")
            for var in WEATHER_VARIABLES:
                v = r[var]
                lo, hi = WEATHER_RANGE[var]
                if v is not None and not (lo <= v <= hi):
                    flags.append(f"OUT_OF_RANGE:{var}")
            for f in flags:
                flagged[f.split(":")[0]] = flagged.get(f.split(":")[0], 0) + 1
            grid = meta.get(pid, (None, None))
            batch.append((station_id, t, *[r[c] for c in WEATHER_VARIABLES], ",".join(sorted(set(flags))), provisional, grid[0], grid[1]))
        store.executemany("insert into clean_weather values (?,?," + ",".join("?" * len(WEATHER_VARIABLES)) + ",?,?,?,?)", batch)
        total += len(batch)
    store.commit()
    return {"clean_weather_rows": total, "flag_counts": dict(sorted(flagged.items()))}
