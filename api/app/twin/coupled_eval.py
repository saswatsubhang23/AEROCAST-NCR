"""Offline evaluation of the coupled model over many historical windows. Nothing is fitted: every window is run with the stated defaults and
scored at stations that were withheld from the initial field, against later observations.

    python -m app.twin.coupled_eval --from 2026-08-01 --to 2026-10-04 --step-hours 60 --hours 12

Writes docs/coupled-evaluation.json and docs/coupled-evaluation.md. One configuration per row: all default couplings, each process alone,
and the passive baseline (which every row is also scored against inside each run).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from app.core.config import get_settings
from app.history.store import HistoryStore
from app.services.weather_fields import WeatherFieldsService
from app.twin.coupled import DEFAULT_PROCESSES, PROCESSES
from app.twin.coupled_run import CoupledService
from app.twin.service import TwinService
from app.twin.simulation import SimulationError

SPECIES = ("pm25", "pm10", "no2", "o3", "so2")
CONFIGS: list[tuple[str, list[str]]] = [("defaults (deposition + washout + oxidation)", sorted(DEFAULT_PROCESSES))] + [(f"{p} only", [p]) for p in PROCESSES]


def _stat(xs: list[float]) -> dict:
    a = np.array(xs, dtype=float)
    if a.size == 0:
        return {"n": 0}
    return {"n": int(a.size), "mean": round(float(a.mean()), 3), "median": round(float(np.median(a)), 3),
            "share_positive": round(float((a > 0).mean()), 3), "p25": round(float(np.percentile(a, 25)), 3), "p75": round(float(np.percentile(a, 75)), 3)}


async def evaluate(start: datetime, end: datetime, step_h: int, hours: int, out_dir: Path) -> dict:
    s = get_settings()
    path = Path(s.ml_history_db or Path(s.data_dir) / "history.sqlite")
    store = HistoryStore(path, read_only=True)
    twin = TwinService(store)
    svc = CoupledService(WeatherFieldsService(s), store_dir=None)
    windows: list[datetime] = []
    t = start
    while t <= end:
        windows.append(t)
        t += timedelta(hours=step_h)
    rows: dict[str, dict[str, dict[str, list[float]]]] = {c[0]: {sp: {"vs_persistence": [], "vs_passive": []} for sp in SPECIES} for c in CONFIGS}
    used, skipped = [], []
    for w in windows:
        for attempt in (1, 2):  # the free weather API rate-limits bursts of archive requests: wait and retry once before skipping a window
            try:
                await _one_window(svc, twin, w, hours, rows, used)
                print(f"window {w:%Y-%m-%d %H}Z ok", flush=True)
                break
            except Exception as exc:  # noqa: BLE001 - a window that cannot be run is reported, not hidden
                if attempt == 1 and "unavailable" in str(exc):
                    await asyncio.sleep(45)
                    continue
                skipped.append({"window": w.strftime("%Y-%m-%dT%H:%MZ"), "reason": str(exc)[:160]})
                print(f"window {w:%Y-%m-%d %H}Z skipped: {str(exc)[:100]}", flush=True)
                break
    result = _finish(rows, used, skipped, hours, step_h, out_dir)
    store.close()
    return result


async def _one_window(svc, twin, w, hours, rows, used) -> None:
    staged: dict[str, dict[str, dict[str, list[float]]]] = {c[0]: {sp: {"vs_persistence": [], "vs_passive": []} for sp in SPECIES} for c in CONFIGS}
    if True:
        if True:
            first = True
            for name, procs in CONFIGS:
                run = await svc.run(twin, hours=hours, init_time=w, processes=procs, validate=True, focus="pm25")
                v = run["validation"]
                if not v.get("available"):
                    raise SimulationError(v.get("reason", "no validation"))
                for sp, d in v["per_species"].items():
                    if d.get("available"):
                        if d["skill_vs_persistence"] is not None:
                            staged[name][sp]["vs_persistence"].append(d["skill_vs_persistence"])
                        if d["skill_vs_passive"] is not None:
                            staged[name][sp]["vs_passive"].append(d["skill_vs_passive"])
    # a window counts only if every configuration ran on it, so the rows are comparable
    for name, per in staged.items():
        for sp, d in per.items():
            rows[name][sp]["vs_persistence"] += d["vs_persistence"]
            rows[name][sp]["vs_passive"] += d["vs_passive"]
    used.append(w.strftime("%Y-%m-%dT%H:%MZ"))


def _finish(rows, used, skipped, hours, step_h, out_dir: Path) -> dict:
    result = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "hours": hours, "step_hours": step_h,
        "windows_used": used, "windows_skipped": skipped,
        "scoring": "MAE at stations withheld from the initial field, leads 1..N h; skill = 1 - MAE_model / MAE_baseline (positive: closer to the observations)",
        "configs": {name: {sp: {"vs_persistence": _stat(d["vs_persistence"]), "vs_passive": _stat(d["vs_passive"])} for sp, d in per.items()} for name, per in rows.items()},
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "coupled-evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out_dir / "coupled-evaluation.md").write_text(render(result), encoding="utf-8")
    return result


def render(r: dict) -> str:
    L = ["# Coupled model: evaluation on historical windows", "",
         f"Generated {r['generated_at']}. {len(r['windows_used'])} windows of {r['hours']} h (every {r['step_hours']} h), {len(r['windows_skipped'])} skipped.",
         "Nothing is fitted: each window is run with the documented defaults and scored at stations that were withheld from the initial field.",
         f"Scoring: {r['scoring']}.", "",
         "A **median skill above 0** means the configuration was closer to later observations than the baseline in the typical window; "
         "`share>0` is the fraction of windows where it was. The model has no emissions, so beating persistence is not expected to be common.", ""]
    for base, label in (("vs_passive", "Skill against passive transport (the same engine with every coupling off)"), ("vs_persistence", "Skill against persistence (hold the station's starting value)")):
        L += [f"## {label}", "", "| Configuration | " + " | ".join(SPECIES) + " |", "|---|" + "---|" * len(SPECIES)]
        for name, per in r["configs"].items():
            cells = []
            for sp in SPECIES:
                st = per[sp][base]
                cells.append("n/a" if not st.get("n") else f"{st['median']:+.2f} ({st['share_positive']:.0%} of {st['n']})")
            L.append(f"| {name} | " + " | ".join(cells) + " |")
        L.append("")
    if r["windows_skipped"]:
        L += ["## Skipped windows", ""] + [f"* {w['window']}: {w['reason']}" for w in r["windows_skipped"]] + [""]
    return "\n".join(L)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", required=True)
    ap.add_argument("--to", dest="end", required=True)
    ap.add_argument("--step-hours", type=int, default=60)
    ap.add_argument("--hours", type=int, default=12)
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[3] / "docs"))
    a = ap.parse_args()
    parse = lambda x: datetime.fromisoformat(x).replace(tzinfo=timezone.utc)  # noqa: E731
    res = asyncio.run(evaluate(parse(a.start), parse(a.end), a.step_hours, a.hours, Path(a.out)))
    print(render(res))


if __name__ == "__main__":
    main()
