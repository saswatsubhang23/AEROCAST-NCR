"""Coverage and data-quality reports computed from the store, plus the forecasting-target support assessment.

Definitions (also printed in the Markdown report)
  window hours     every hour between the requested window start and end
  active hours     hours inside both the window and the sensor lifetime the provider reports (first..last datetime of any
                   sensor for that station and pollutant); an hour a sensor did not yet exist is not a gap
  usable hour      a clean_air row with usable = 1 (no hard flag)
  coverage_active  usable hours / active hours      coverage_window  usable hours / window hours
Months are IST calendar months of the hour label.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.core.time import utc_now
from app.history.ingest_air import iso, parse_iso
from app.history.store import HistoryStore
from app.history.units import POLLUTANTS, WEATHER_VARIABLES

HOUR = timedelta(hours=1)
IST_OFFSET = timedelta(hours=5, minutes=30)
HORIZONS = [1, 3, 6, 12, 24, 48, 72]
MIN_PAIRS = 1500  # (origin, target) pairs a station needs before its series counts toward a horizon
MIN_SPAN_DAYS = 120
SUPPORTED_STATIONS = 20
LIMITED_STATIONS = 5


def month_of(label: datetime) -> str:
    return (label + IST_OFFSET).strftime("%Y-%m")


def hours_between(a: datetime, b: datetime) -> int:
    return max(0, int((b - a) / HOUR) + 1)


def month_bounds(month: str) -> tuple[datetime, datetime]:
    y, m = int(month[:4]), int(month[5:7])
    start = datetime(y, m, 1, tzinfo=timezone.utc) - IST_OFFSET  # IST midnight expressed in UTC
    end = datetime(y + (m == 12), 1 if m == 12 else m + 1, 1, tzinfo=timezone.utc) - IST_OFFSET - HOUR
    return start, end


def overlap_hours(a: datetime, b: datetime, c: datetime, d: datetime) -> int:
    lo, hi = max(a, c), min(b, d)
    return hours_between(lo, hi) if lo <= hi else 0


def _g(v, spec: str = ".3g") -> str:
    return "none (physical-plausibility floor)" if v is None else format(v, spec)


def _pct(n: int, d: int) -> float | None:
    return None if d <= 0 else round(100.0 * n / d, 1)


def build_report(store: HistoryStore, window_from: datetime, window_to: datetime, now: datetime | None = None) -> dict:
    now = now or utc_now()
    w_start, w_end = window_from.replace(minute=0, second=0, microsecond=0), (window_to - HOUR)
    window_hours = hours_between(w_start, w_end)
    stations = {r["station_id"]: dict(r) for r in store.query("select * from stations")}
    life = {}  # (station, pollutant) -> (first, last) from the provider's own sensor dates, clipped to the window
    for r in store.query("select station_id, parameter, min(datetime_first) f, max(datetime_last) l from sensors group by station_id, parameter"):
        f, l = parse_iso(r["f"]), parse_iso(r["l"])
        if f and l:
            life[(r["station_id"], r["parameter"])] = (max(f.replace(minute=0, second=0, microsecond=0), w_start), min(l, w_end))

    labels: dict[tuple[int, str], list[datetime]] = defaultdict(list)  # usable hour labels
    all_rows: dict[tuple[int, str], int] = defaultdict(int)
    for r in store.query("select station_id, pollutant, label_utc, usable from clean_air order by station_id, pollutant, label_utc"):
        all_rows[(r["station_id"], r["pollutant"])] += 1
        if r["usable"]:
            labels[(r["station_id"], r["pollutant"])].append(parse_iso(r["label_utc"]))

    # ---- by station x pollutant
    by_station = []
    for (sid, pol), life_range in sorted(life.items()):
        if pol not in POLLUTANTS or sid not in stations:
            continue
        ls = labels.get((sid, pol), [])
        active = hours_between(*life_range) if life_range[0] <= life_range[1] else 0
        gaps = [int((b - a) / HOUR) - 1 for a, b in zip(ls, ls[1:]) if b - a > HOUR]
        st = stations[sid]
        by_station.append({
            "station_id": sid, "name": st["name"], "lat": st["lat"], "lon": st["lon"], "zone": st["zone"], "agency": st["agency"],
            "pollutant": pol, "clean_rows": all_rows.get((sid, pol), 0), "usable_hours": len(ls), "active_hours": active,
            "coverage_active_pct": _pct(len(ls), active), "coverage_window_pct": _pct(len(ls), window_hours),
            "first_usable_utc": iso(ls[0]) if ls else None, "last_usable_utc": iso(ls[-1]) if ls else None,
            "gap_count": len(gaps), "longest_gap_hours": max(gaps) if gaps else 0,
        })

    # ---- aggregate helper
    def aggregate(rows: list[dict]) -> dict:
        usable = sum(r["usable_hours"] for r in rows)
        active = sum(r["active_hours"] for r in rows)
        return {"stations": len({r["station_id"] for r in rows}), "usable_hours": usable, "active_hours": active,
                "coverage_active_pct": _pct(usable, active)}

    by_pollutant = {p: aggregate([r for r in by_station if r["pollutant"] == p]) for p in POLLUTANTS}
    by_region: dict[str, dict] = {}
    for zone in sorted({r["zone"] for r in by_station}):
        by_region[zone] = {p: aggregate([r for r in by_station if r["zone"] == zone and r["pollutant"] == p]) for p in POLLUTANTS}

    # ---- by month (overall and by region): usable hours / active hours falling in the month
    months = sorted({month_of(w_start + i * HOUR) for i in range(0, window_hours, 24)} | {month_of(w_end)})
    by_month: dict[str, dict] = {}
    by_region_month: dict[str, dict] = {}
    for m in months:
        m_start, m_end = month_bounds(m)
        by_month[m] = {}
        for p in POLLUTANTS:
            usable = active = 0
            reg: dict[str, list[int]] = defaultdict(lambda: [0, 0])
            for (sid, pol), (a, b) in life.items():
                if pol != p or sid not in stations:
                    continue
                act = overlap_hours(a, b, m_start, m_end) if a <= b else 0
                use = sum(1 for t in labels.get((sid, p), []) if m_start <= t <= m_end) if act else 0
                usable += use
                active += act
                reg[stations[sid]["zone"]][0] += use
                reg[stations[sid]["zone"]][1] += act
            by_month[m][p] = {"usable_hours": usable, "active_hours": active, "coverage_active_pct": _pct(usable, active)}
            for z, (u, a_) in reg.items():
                by_region_month.setdefault(z, {}).setdefault(m, {})[p] = {"usable_hours": u, "active_hours": a_, "coverage_active_pct": _pct(u, a_)}

    # ---- flags, units, duplicates
    flag_counts = {p: defaultdict(int) for p in POLLUTANTS}
    unit_counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for r in store.query("select pollutant, flags, orig_unit, std_unit, usable from clean_air"):
        for f in (r["flags"] or "").split(","):
            if f:
                flag_counts[r["pollutant"]][f] += 1
        unit_counts[(r["pollutant"], r["orig_unit"] or "?", r["std_unit"] or "none")] += 1
    raw_n = store.count("raw_air")
    clean_n = store.count("clean_air")
    multi = store.query("select count(*) from clean_air where n_candidates > 1")[0][0]

    unit_checks = [dict(r) for r in store.query(
        "select c.sensor_id, c.station_id, s.name station, c.parameter, c.units, c.hours, c.median_std, c.reference_std, c.ratio "
        "from sensor_unit_checks c left join stations s on s.station_id = c.station_id where c.suspect = 1 order by c.parameter, c.station_id")]

    # ---- weather
    weather = {"points": 0, "rows": 0, "provisional_rows": 0, "null_rate_pct": {}, "by_month_coverage_pct": {}, "expected_rows_per_point": window_hours}
    wrows = store.query("select * from clean_weather")
    weather["rows"] = len(wrows)
    weather["points"] = len({r["station_id"] for r in wrows})
    cells = store.query("select count(*) from (select distinct grid_lat, grid_lon from raw_weather_meta where grid_lat is not null)")[0][0]
    weather["distinct_grid_cells"] = cells
    weather["provisional_rows"] = sum(r["provisional"] for r in wrows)
    for v in WEATHER_VARIABLES:
        weather["null_rate_pct"][v] = _pct(sum(1 for r in wrows if r[v] is None), len(wrows))
    per_month_pts: dict[str, int] = defaultdict(int)
    for r in wrows:
        per_month_pts[month_of(parse_iso(r["time_utc"]))] += 1
    for m in months:
        a, b = month_bounds(m)
        exp = overlap_hours(a, b, w_start, w_end) * max(weather["points"], 1)
        weather["by_month_coverage_pct"][m] = _pct(per_month_pts.get(m, 0), exp)
    weather_hours: dict[int, set[str]] = defaultdict(set)
    for r in wrows:
        weather_hours[r["station_id"]].add(r["time_utc"])

    # ---- data latency at ingestion time (how old the newest data was when it was fetched)
    latency = []
    for r in store.query("select station_id, max(period_to_utc) newest, max(fetched_at) fetched from raw_air group by station_id"):
        n, f = parse_iso(r["newest"]), parse_iso(r["fetched"])
        if n and f:
            latency.append(round((f - n).total_seconds() / 3600.0, 1))
    latency.sort()
    latency_summary = None if not latency else {"stations": len(latency), "min_h": latency[0], "median_h": latency[len(latency) // 2], "max_h": latency[-1]}

    # ---- which targets and horizons the data can support
    support = {}
    for p in POLLUTANTS:
        support[p] = {}
        for h in HORIZONS:
            ok_stations, pairs_total, spans = 0, 0, []
            for (sid, pol), ls in labels.items():
                if pol != p or not ls:
                    continue
                present = set(ls)
                wx = weather_hours.get(sid, set())
                origins = [t for t in ls if (t + h * HOUR) in present and iso(t) in wx]
                pairs_total += len(origins)
                if len(origins) >= MIN_PAIRS and (origins[-1] - origins[0]).days >= MIN_SPAN_DAYS:
                    ok_stations += 1
                spans.append(len(origins))
            verdict = "supported" if ok_stations >= SUPPORTED_STATIONS else "limited" if ok_stations >= LIMITED_STATIONS else "insufficient"
            support[p][str(h)] = {"pairs_with_weather": pairs_total, "stations_meeting_threshold": ok_stations, "verdict": verdict}

    runs = [dict(r) for r in store.query("select run_id, kind, started_at, finished_at, status, requests, rows_added, note from ingest_runs order by started_at")]
    return {
        "generated_at": iso(now),
        "window": {"from": iso(w_start), "to": iso(w_end), "hours": window_hours},
        "database": {"engine": "sqlite", "path": store.path},
        "table_rows": {t: store.count(t) for t in ("stations", "sensors", "raw_air", "raw_weather", "clean_air", "clean_weather")},
        "stations_discovered": len(stations),
        "by_pollutant": by_pollutant, "by_region": by_region, "by_month": by_month, "by_region_month": by_region_month,
        "by_station": by_station,
        "flags": {p: dict(sorted(c.items())) for p, c in flag_counts.items()},
        "units": [{"pollutant": k[0], "original_unit": k[1], "standard_unit": k[2], "hours": v} for k, v in sorted(unit_counts.items())],
        "unit_suspect_sensors": unit_checks, "duplicates": {"raw_rows": raw_n, "clean_rows": clean_n, "hours_with_multiple_candidates": multi},
        "weather": weather, "latency_at_fetch": latency_summary, "support": support,
        "support_criteria": {"min_pairs_per_station": MIN_PAIRS, "min_span_days": MIN_SPAN_DAYS, "supported_if_stations_at_least": SUPPORTED_STATIONS,
                             "limited_if_stations_at_least": LIMITED_STATIONS,
                             "note": "These thresholds are this pipeline's own conservative choices for judging whether a station-level model could be trained and tested; they are not a statistical guarantee."},
        "ingest_runs": runs,
    }


def render_markdown(r: dict) -> str:
    L: list[str] = []
    w = r["window"]
    L += ["# Historical data coverage report", "",
          f"Generated {r['generated_at']} from `{r['database']['path']}` (SQLite). Window: {w['from']} to {w['to']} ({w['hours']} hours). "
          "Every figure below is computed from the store; nothing is estimated.", "",
          "Definitions: *active hours* are the hours inside the window during which the provider says a sensor existed (first to last datetime); "
          "*usable* hours carry no hard quality flag; coverage = usable / active. Months are IST months.", "",
          "## Tables", "", "| table | rows |", "|---|---:|"]
    L += [f"| {k} | {v:,} |" for k, v in r["table_rows"].items()]
    L += ["", f"Stations discovered in the NCR box: {r['stations_discovered']}.", ""]

    def cov(d):
        return "n/a" if d["coverage_active_pct"] is None else f"{d['coverage_active_pct']}%"

    L += ["## By pollutant", "", "| pollutant | stations | usable hours | active hours | coverage |", "|---|---:|---:|---:|---:|"]
    L += [f"| {p} | {d['stations']} | {d['usable_hours']:,} | {d['active_hours']:,} | {cov(d)} |" for p, d in r["by_pollutant"].items()]
    L += ["", "## By region (nearest NCR city centre within 30 km, else Other NCR)", "", "| region | " + " | ".join(POLLUTANTS) + " |", "|---|" + "---:|" * len(POLLUTANTS)]
    for z, d in r["by_region"].items():
        L.append(f"| {z} | " + " | ".join(f"{d[p]['stations']} st / {cov(d[p])}" for p in POLLUTANTS) + " |")
    L += ["", "## By month (all stations; usable / active)", "", "| month | " + " | ".join(POLLUTANTS) + " |", "|---|" + "---:|" * len(POLLUTANTS)]
    for m, d in r["by_month"].items():
        L.append(f"| {m} | " + " | ".join(cov(d[p]) for p in POLLUTANTS) + " |")
    L += ["", "### Region x month, PM2.5", "", "| region | " + " | ".join(r["by_month"]) + " |", "|---|" + "---:|" * len(r["by_month"])]
    for z, months in r["by_region_month"].items():
        L.append(f"| {z} | " + " | ".join(cov(months[m].get("pm25", {"coverage_active_pct": None})) if m in months else "n/a" for m in r["by_month"]) + " |")

    L += ["", "## By station (PM2.5; all pollutants are in the JSON report)", "",
          "| station | zone | agency | usable h | active h | coverage | gaps | longest gap h | first usable | last usable |", "|---|---|---|---:|---:|---:|---:|---:|---|---|"]
    for s in r["by_station"]:
        if s["pollutant"] == "pm25":
            c = "n/a" if s["coverage_active_pct"] is None else f"{s['coverage_active_pct']}%"
            L.append(f"| {s['name']} ({s['station_id']}) | {s['zone']} | {s['agency']} | {s['usable_hours']:,} | {s['active_hours']:,} | {c} | {s['gap_count']} | {s['longest_gap_hours']} | {s['first_usable_utc']} | {s['last_usable_utc']} |")

    L += ["", "## Quality flags (hours carrying each flag)", "", "| pollutant | flags |", "|---|---|"]
    L += [f"| {p} | " + (", ".join(f"{k}: {v:,}" for k, v in d.items()) or "none") + " |" for p, d in r["flags"].items()]
    L += ["", "Hard flags (value unusable): NULL_VALUE, NEGATIVE, OUT_OF_RANGE, UNIT_UNKNOWN, UNIT_SUSPECT, PERIOD_IRREGULAR. Soft flags (value kept): LOW_COVERAGE, FLATLINE, UNIT_CONVERTED, REVISED, SENSOR_CONFLICT, MULTI_SENSOR, ALIGN_ROUNDED.", "",
          "## Units as received and as standardised", "", "| pollutant | original unit | standard unit | hours |", "|---|---|---|---:|"]
    L += [f"| {u['pollutant']} | {u['original_unit']} | {u['standard_unit']} | {u['hours']:,} |" for u in r["units"]]
    bad = r["unit_suspect_sensors"]
    L += ["", "## Sensors whose labelled unit contradicts their magnitude (excluded, not rescaled)", ""]
    if bad:
        L += ["After conversion to µg/m³ their median either differs by more than 20x from the median of sensors that report this pollutant natively in µg/m³, or (CO) is below the physical-plausibility floor, so the unit label cannot be right. "
              "Their values stay in the raw table unchanged; the rows are flagged UNIT_SUSPECT and are not used.", "",
              "| pollutant | labelled unit | sensors |", "|---|---|---:|"]
        groups: dict[tuple, int] = {}
        for x in bad:
            groups[(x["parameter"], x["units"])] = groups.get((x["parameter"], x["units"]), 0) + 1
        L += [f"| {k[0]} | {k[1]} | {v} |" for k, v in sorted(groups.items())]
        L += ["", "| sensor | station | pollutant | unit | median after conversion (µg/m³) | reference median (µg/m³) | ratio |", "|---:|---|---|---|---:|---:|---:|"]
        L += [f"| {x['sensor_id']} | {x['station']} ({x['station_id']}) | {x['parameter']} | {x['units']} | {x['median_std']:.3g} | {_g(x['reference_std'])} | {_g(x['ratio'], '.2g')} |" for x in bad]
    else:
        L += ["None found."]
    d = r["duplicates"]
    L += ["", f"## Duplicates", "", f"Raw rows {d['raw_rows']:,} reduced to {d['clean_rows']:,} clean hourly rows; {d['hours_with_multiple_candidates']:,} hours had more than one sensor reporting."]
    wx = r["weather"]
    L += ["", "## Weather (Open-Meteo archive, model/reanalysis values)", "", f"{wx['points']} station points served by {wx['distinct_grid_cells']} distinct provider grid cells (stations in one cell share identical weather), {wx['rows']:,} hourly rows, {wx['provisional_rows']:,} flagged provisional (fetched within 7 days of the value's time).", "",
          "| variable | null rate |", "|---|---:|"] + [f"| {k} | {v}% |" for k, v in wx["null_rate_pct"].items()]
    L += ["", "| month | weather coverage of the window |", "|---|---:|"] + [f"| {m} | {v}% |" if v is not None else f"| {m} | n/a |" for m, v in wx["by_month_coverage_pct"].items()]
    lat = r["latency_at_fetch"]
    L += ["", "## Publication latency", "",
          "Age of each station's newest hourly value at the moment it was fetched: " + ("not measured." if lat is None else f"minimum {lat['min_h']} h, median {lat['median_h']} h, maximum {lat['max_h']} h over {lat['stations']} stations.")]
    c = r["support_criteria"]
    L += ["", "## Which forecasting targets and horizons the data can support", "",
          f"A station counts toward a (pollutant, horizon) cell if it has at least {c['min_pairs_per_station']:,} origin/target pairs with weather present and a span of at least {c['min_span_days']} days. "
          f"Verdict: **supported** if at least {c['supported_if_stations_at_least']} stations qualify, **limited** if at least {c['limited_if_stations_at_least']}, else **insufficient**. {c['note']}", "",
          "| pollutant | " + " | ".join(f"+{h} h" for h in HORIZONS) + " |", "|---|" + "---|" * len(HORIZONS)]
    for p in POLLUTANTS:
        L.append(f"| {p} | " + " | ".join(f"{r['support'][p][str(h)]['verdict']} ({r['support'][p][str(h)]['stations_meeting_threshold']} st)" for h in HORIZONS) + " |")
    L += ["", "Operational caveat: the figures above say whether a model can be *trained and evaluated*. Using it live additionally requires the feed's publication latency (section above) to be smaller than the forecast horizon.", "",
          "## Ingest runs", "", "| run | kind | started | status | requests | rows | note |", "|---|---|---|---|---:|---:|---|"]
    L += [f"| {x['run_id']} | {x['kind']} | {x['started_at']} | {x['status']} | {x['requests']} | {x['rows_added']} | {x['note'] or ''} |" for x in r["ingest_runs"]]
    return "\n".join(L) + "\n"


def write_reports(store: HistoryStore, window_from: datetime, window_to: datetime, out_dir: str, now: datetime | None = None) -> dict:
    import pathlib
    rep = build_report(store, window_from, window_to, now)
    out = pathlib.Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage-report.json").write_text(json.dumps(rep, indent=1, ensure_ascii=False), encoding="utf-8")
    (out / "coverage-report.md").write_text(render_markdown(rep), encoding="utf-8")
    return rep
