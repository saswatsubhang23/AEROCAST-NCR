"""Does xKDR's timestamp convention line up with OpenAQ's? Tested on the one station both serve over the same period (the US Embassy monitor).

xKDR gives `period_start` as a naive IST time; the ingest assumes that is the START of the hour, so the period is (start, start + 1 h) in UTC
after subtracting 5 h 30 min. OpenAQ labels an hourly value by its period end. If the assumption is right, the two series agree best at
lag 0 once both are put on the same label; a consistent off-by-one-hour would peak at +/-1.

    python -m app.envdata.crosscheck_xkdr
"""

from __future__ import annotations

import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.history.store import HistoryStore

IST = timedelta(hours=5, minutes=30)
START, END = "2025-10-15", "2025-12-15"


def corr(a: list[float], b: list[float]) -> float | None:
    n = len(a)
    if n < 20:
        return None
    ma, mb = sum(a) / n, sum(b) / n
    va = sum((x - ma) ** 2 for x in a)
    vb = sum((y - mb) ** 2 for y in b)
    if va == 0 or vb == 0:
        return None
    return sum((x - ma) * (y - mb) for x, y in zip(a, b)) / math.sqrt(va * vb)


async def main() -> dict:
    s = get_settings()
    key = s.india_aqi_api_key.get_secret_value()
    if not key:
        return {"error": "INDIA_AQI_API_KEY is not set"}
    store = HistoryStore(Path(s.ml_history_db or Path(s.data_dir) / "history.sqlite"), read_only=True)
    st = store.query("select station_id, name from stations where lower(name) like '%us embassy%' or lower(name) like '%u.s. embassy%' or lower(provider) like '%airnow%' limit 5")
    if not st:
        return {"error": "no OpenAQ-side US Embassy station in the store"}
    sid = st[0]["station_id"]
    rows = store.query(
        "select period_to_utc, value_std as value from clean_air where station_id=? and pollutant='pm25' and usable=1 and period_to_utc>=? and period_to_utc<? order by period_to_utc",
        (sid, f"{START}T00:00:00Z", f"{END}T00:00:00Z"),
    )
    oaq = {r["period_to_utc"]: r["value"] for r in rows}
    async with httpx.AsyncClient(timeout=120.0) as c:
        r = await c.get("https://airquality.xkdr.org/v1/measurements", headers={"Authorization": f"Bearer {key}"},
                        params={"station": "DS1010001", "parameter": "PM2.5", "start": START, "end": END, "agg": "hourly"})
    data = r.json().get("data", [])
    xk = {}
    for d in data:
        if d.get("mean") is None:
            continue
        t = datetime.fromisoformat(d["period_start"]).replace(tzinfo=timezone.utc) - IST  # naive IST -> UTC, start of the period
        xk[t] = float(d["mean"])
    sample_x = sorted(xk)[:2]
    sample_o = sorted(oaq)[:2]
    out: dict = {"station": {"openaq_station_id": sid, "name": st[0]["name"], "xkdr_station_id": "DS1010001"}, "window": [START, END],
                 "n_xkdr": len(xk), "n_openaq": len(oaq), "xkdr_period_start_utc_examples": [t.strftime("%H:%M") for t in sample_x],
                 "openaq_period_to_utc_examples": [t[11:16] for t in sample_o], "lags": {}}
    # xKDR period END (start + 1 h, UTC) against OpenAQ period end, shifted by `lag` half-hour steps; the grids differ by 30 min because IST is UTC+5:30
    for step in range(-48, 49, 2):
        lag = step * 0.5
        a, b = [], []
        for t0, v in xk.items():
            end_label = (t0 + timedelta(hours=1) + timedelta(hours=lag)).strftime("%Y-%m-%dT%H:%M:%SZ")
            if end_label in oaq:
                a.append(v)
                b.append(oaq[end_label])
        cr = corr(a, b)
        mae = round(sum(abs(x - y) for x, y in zip(a, b)) / len(a), 2) if a else None
        out["lags"][f"{lag:+.1f}"] = {"n": len(a), "correlation": None if cr is None else round(cr, 4), "mae": mae}
    ok = {k: v for k, v in out["lags"].items() if v["correlation"] is not None}
    best = max(ok, key=lambda k: ok[k]["correlation"], default=None)
    out["best_shift_hours"] = None if best is None else float(best)
    out["verdict"] = (
        "No shift gives a usable overlap: the grids do not intersect." if best is None
        else "The series agree best with xKDR's period end shifted by %+.1f h relative to OpenAQ's period end." % float(best)
    )
    store.close()
    return out


if __name__ == "__main__":
    res = asyncio.run(main())
    path = Path(__file__).resolve().parents[3] / "docs" / "phase1" / "xkdr-alignment.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(res, indent=2, ensure_ascii=False))
