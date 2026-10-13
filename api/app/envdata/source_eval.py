"""How good is CAMS (via Open-Meteo) as a pollutant source for Delhi-NCR stations, compared with simple baselines?

    python -m app.envdata.source_eval

For every pollutant it compares the CAMS value at each station's coordinates with the station's hourly observation over the most recent
period both cover, and reports bias, MAE, RMSE and correlation (per station and for the city mean), at the best of a few time shifts so
that a time-label convention cannot be blamed for a poor score. Baselines on the same hours: persistence (the observation 24 h earlier,
the information a day-ahead forecast without a model has) and the station's own long-term mean for that hour of day (climatology).

CAMS values here are the model's current best estimate for past hours (Open-Meteo returns the latest analysis/forecast mix), so this
measures how close the model's picture is to the stations, not the skill of a forecast issued a day earlier.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np

from app.core.config import get_settings
from app.history.store import HistoryStore

VARS = {"pm25": "pm2_5", "pm10": "pm10", "no2": "nitrogen_dioxide", "o3": "ozone", "so2": "sulphur_dioxide"}
MAX_STATIONS = 60
DAYS = 60


def metrics(pred: np.ndarray, obs: np.ndarray) -> dict:
    ok = np.isfinite(pred) & np.isfinite(obs)
    p, o = pred[ok], obs[ok]
    if p.size < 50:
        return {"n": int(p.size)}
    err = p - o
    r = float(np.corrcoef(p, o)[0, 1]) if p.std() > 0 and o.std() > 0 else None
    return {"n": int(p.size), "bias": round(float(err.mean()), 2), "mae": round(float(np.abs(err).mean()), 2), "rmse": round(float(math.sqrt((err ** 2).mean())), 2),
            "r": None if r is None else round(r, 3), "obs_mean": round(float(o.mean()), 2)}


async def main() -> dict:
    s = get_settings()
    store = HistoryStore(Path(s.ml_history_db or Path(s.data_dir) / "history.sqlite"), read_only=True)
    end = datetime.fromisoformat(store.query("select max(label_utc) m from clean_air where pollutant='pm25' and usable=1")[0]["m"].replace("Z", "+00:00"))
    # use the last DAYS days that end at the newest well-covered hour of the store
    start = end - timedelta(days=DAYS)
    stations = [dict(r) for r in store.query("select station_id, name, lat, lon from stations where lat between 27.9 and 29.2 and lon between 76.4 and 78.1")]
    out: dict = {"window": [start.strftime("%Y-%m-%dT%H:%MZ"), end.strftime("%Y-%m-%dT%H:%MZ")], "per_pollutant": {}, "notes": []}
    hours = [start + timedelta(hours=i) for i in range(DAYS * 24 + 1)]
    index = {h.strftime("%Y-%m-%dT%H:%M:%SZ"): i for i, h in enumerate(hours)}

    async with httpx.AsyncClient(timeout=90.0) as c:
        for pol, var in VARS.items():
            rows = store.query(
                "select station_id, label_utc, value_std v from clean_air where pollutant=? and usable=1 and label_utc>=? and label_utc<=?",
                (pol, start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")))
            by_station: dict[int, np.ndarray] = {}
            for r in rows:
                i = index.get(r["label_utc"])
                if i is None:
                    continue
                by_station.setdefault(r["station_id"], np.full(len(hours), np.nan))[i] = r["v"]
            chosen = [st for st in stations if st["station_id"] in by_station and np.isfinite(by_station[st["station_id"]]).sum() > 24 * 20][:MAX_STATIONS]
            if len(chosen) < 5:
                out["per_pollutant"][pol] = {"error": "fewer than five stations with 20 days of data in the window"}
                continue
            # CAMS at the stations' coordinates, in chunks
            cams = {}
            past_days = min(92, (datetime.now(timezone.utc) - start).days + 2)
            for k in range(0, len(chosen), 30):
                chunk = chosen[k:k + 30]
                r = await c.get("https://air-quality-api.open-meteo.com/v1/air-quality", params={
                    "latitude": ",".join(str(x["lat"]) for x in chunk), "longitude": ",".join(str(x["lon"]) for x in chunk), "hourly": var, "past_days": past_days,
                    "forecast_days": 1, "timezone": "GMT"})
                body = r.json()
                body = body if isinstance(body, list) else [body]
                for st, b in zip(chunk, body):
                    t = [x + ":00Z" for x in b["hourly"]["time"]]
                    arr = np.full(len(hours), np.nan)
                    for ti, v in zip(t, b["hourly"][var]):
                        j = index.get(ti)
                        if j is not None and v is not None:
                            arr[j] = v
                    cams[st["station_id"]] = arr
                await asyncio.sleep(0.5)
            res: dict = {"stations": len(chosen)}
            # best time shift of the CAMS series (to rule out a label convention), city-mean correlation
            obs_mean = np.nanmean(np.stack([by_station[st["station_id"]] for st in chosen]), axis=0)
            cams_mean = np.nanmean(np.stack([cams[st["station_id"]] for st in chosen]), axis=0)
            shifts = {}
            for sh in range(-6, 7):
                p = np.roll(cams_mean, sh)
                m = metrics(p, obs_mean)
                shifts[sh] = m.get("r")
            best = max((k for k, v in shifts.items() if v is not None), key=lambda k: shifts[k], default=0)
            res["best_shift_hours"] = best
            res["city_mean_correlation_by_shift"] = shifts
            P = np.concatenate([np.roll(cams[st["station_id"]], best) for st in chosen])
            O = np.concatenate([by_station[st["station_id"]] for st in chosen])
            res["cams_vs_stations"] = metrics(P, O)
            res["cams_vs_stations_raw_unshifted"] = metrics(np.concatenate([cams[st["station_id"]] for st in chosen]), O)
            # per-station correlation distribution
            rs = []
            for st in chosen:
                m = metrics(np.roll(cams[st["station_id"]], best), by_station[st["station_id"]])
                if m.get("r") is not None:
                    rs.append(m["r"])
            res["per_station_r"] = {"median": round(float(np.median(rs)), 3), "p25": round(float(np.percentile(rs, 25)), 3), "p75": round(float(np.percentile(rs, 75)), 3)} if rs else None
            # baselines on the same hours
            pers = np.concatenate([np.roll(by_station[st["station_id"]], 24) for st in chosen])
            res["persistence_24h"] = metrics(pers, O)
            clim = []
            for st in chosen:
                o = by_station[st["station_id"]]
                hod = np.array([h.hour for h in hours])
                c_ = np.array([np.nanmean(o[hod == k]) for k in range(24)])
                clim.append(c_[hod])
            res["hour_of_day_climatology"] = metrics(np.concatenate(clim), O)
            # does a single multiplicative bias correction (fitted on the first half, scored on the second) help? Shown as information, not applied.
            half = len(hours) // 2
            Ph = np.concatenate([np.roll(cams[st["station_id"]], best)[:half] for st in chosen])
            Oh = np.concatenate([by_station[st["station_id"]][:half] for st in chosen])
            okh = np.isfinite(Ph) & np.isfinite(Oh) & (Ph > 0)
            k_scale = float(np.nansum(Oh[okh]) / np.nansum(Ph[okh])) if okh.any() else 1.0
            P2 = np.concatenate([np.roll(cams[st["station_id"]], best)[half:] * k_scale for st in chosen])
            O2 = np.concatenate([by_station[st["station_id"]][half:] for st in chosen])
            res["cams_scaled_on_second_half"] = {"scale_fitted_on_first_half": round(k_scale, 3), **metrics(P2, O2)}
            out["per_pollutant"][pol] = res
    out["notes"].append("CAMS cells over NCR are about 0.4 degrees (44 km), so stations inside one cell share one value.")
    store.close()
    return out


if __name__ == "__main__":
    res = asyncio.run(main())
    path = Path(__file__).resolve().parents[3] / "docs" / "phase1" / "cams-vs-stations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, indent=2), encoding="utf-8")
    for pol, r in res["per_pollutant"].items():
        if "cams_vs_stations" in r:
            c, p, k = r["cams_vs_stations"], r["persistence_24h"], r["hour_of_day_climatology"]
            print(f"{pol:5s} stations {r['stations']:3d} shift {r['best_shift_hours']:+d}h | CAMS bias {c.get('bias')} MAE {c.get('mae')} r {c.get('r')} | persist24 MAE {p.get('mae')} | climatology MAE {k.get('mae')} | obs mean {c.get('obs_mean')}")
        else:
            print(pol, r)
