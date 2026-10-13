"""One-off repair: re-ingest the xKDR US-Embassy series with its timestamps read as UTC (they were read as IST, a 5.5 h shift).

    python -m app.history.repair_xkdr_utc            # dry run: shows what would change
    python -m app.history.repair_xkdr_utc --apply    # backs the old rows up, re-ingests, re-cleans and re-featurises that one station

Why: docs/phase1/xkdr-alignment.json. Only the US-Embassy station (xKDR DS1010001, OpenAQ station 8118) is affected; CPCB stations are
correct as ingested. The repair touches only that station: its xKDR raw rows are removed (after being written to a compressed backup), the
same period is fetched again with the corrected rule, and only that station's cleaned rows and feature rows are rebuilt.
It does not train anything and does not change the active model.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import json
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import get_settings
from app.history import clean as clean_mod
from app.history import features, ingest_xkdr
from app.history.store import HistoryStore

XKDR_STATION = "DS1010001"
OPENAQ_STATION = 8118
START = datetime(2021, 12, 31)  # naive, like the CLI passes them (the ingest builds its year windows from naive datetimes)
END = datetime(2025, 9, 2)


def _min_hour(store: HistoryStore, a: str, b: str) -> int | None:
    from collections import defaultdict
    from datetime import timedelta

    d: dict[int, list[float]] = defaultdict(list)
    for r in store.query("select label_utc, value_std v from clean_air where station_id=? and pollutant='pm25' and usable=1 and label_utc>=? and label_utc<?", (OPENAQ_STATION, a, b)):
        t = datetime.fromisoformat(r["label_utc"].replace("Z", "+00:00")) + timedelta(hours=5, minutes=30)
        d[t.hour].append(r["v"])
    if sum(len(v) for v in d.values()) < 240:
        return None
    m = {h: sum(v) / len(v) for h, v in d.items()}
    return min(m, key=m.get)


async def main(apply: bool) -> dict:
    s = get_settings()
    path = Path(s.ml_history_db or Path(s.data_dir) / "history.sqlite")
    store = HistoryStore(path)
    sensor = ingest_xkdr.sensor_id_for(XKDR_STATION, "pm25")
    n = store.query("select count(*) c, min(period_to_utc) a, max(period_to_utc) b from raw_air where sensor_id=?", (sensor,))[0]
    report: dict = {"station": OPENAQ_STATION, "xkdr_sensor_id": sensor, "raw_rows": n["c"], "from": n["a"], "to": n["b"],
                    "daily_minimum_hour_ist_before": _min_hour(store, "2025-06-01T00:00:00Z", "2025-09-01T00:00:00Z"), "applied": False}
    if not apply:
        report["note"] = "dry run: nothing changed. Re-run with --apply."
        store.close()
        return report
    if n["c"] == 0:
        report["note"] = "no raw rows to back up (a previous run already removed them); re-ingesting"
    backup = path.parent / "backups"
    backup.mkdir(parents=True, exist_ok=True)
    if n["c"] > 0:
        bfile = backup / f"raw_air_xkdr_us_embassy_before_utc_fix_{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.csv.gz"
        cols = [r[1] for r in store.query("pragma table_info(raw_air)")]
        with gzip.open(bfile, "wt", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(cols)
            for r in store.query("select * from raw_air where sensor_id=?", (sensor,)):
                w.writerow([r[c] for c in cols])
        report["backup"] = str(bfile)
    store.execute("delete from raw_air where sensor_id=?", (sensor,))
    store.execute("delete from raw_air_progress where sensor_id=?", (sensor,))
    store.commit()
    res = await ingest_xkdr.run(store, s.india_aqi_api_key.get_secret_value(), START, END, ["pm25"], concurrency=2)
    report["reingest"] = {k: v for k, v in res.items() if k in ("rows", "failed_windows", "requests", "stations", "matched_existing", "created")}
    clean_mod.clean_air(store, station_ids=[OPENAQ_STATION])
    report["features"] = features.refresh_stations(store, [OPENAQ_STATION], ["pm25"])
    report["daily_minimum_hour_ist_after"] = _min_hour(store, "2025-06-01T00:00:00Z", "2025-09-01T00:00:00Z")
    report["applied"] = True
    store.close()
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    out = asyncio.run(main(ap.parse_args().apply))
    p = Path(__file__).resolve().parents[3] / "docs" / "phase1" / "xkdr-utc-repair.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
