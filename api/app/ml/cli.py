"""Offline training and reporting.  Run from the `api` folder:

    python -m app.ml targets --coverage ../docs/data/coverage-report.json     # which pollutants/horizons the data supports
    python -m app.ml train   [--pollutants pm25,pm10 --horizons 1,3,6,12,24 --config my.json]
    python -m app.ml report  [--run <dir>] [--out ../docs/ml-model-comparison.md]
    python -m app.ml check                                                     # is a saved model loadable?
    python -m app.ml regimes                                                   # atmospheric regimes + PM2.5 by regime (needs a run for its split date)

Training is never run by the web API. The API only loads the saved artifacts (app/ml/inference.py).
"""

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from app.core.config import get_settings
from app.history.store import HistoryStore
from app.ml import artifacts
from app.ml.config import MlConfig
from app.ml.report import write_report
from app.ml.train import run_experiment

VERDICT_RANK = {"insufficient": 0, "limited": 1, "supported": 2}


def targets_from_coverage(path: str, minimum: str = "supported") -> dict[str, list[int]]:
    """Pollutant -> horizons whose support verdict (computed by the data pipeline) is at least `minimum`. Nothing is assumed."""
    cov = json.loads(Path(path).read_text(encoding="utf-8"))
    out: dict[str, list[int]] = {}
    for p, hs in cov["support"].items():
        ok = sorted(int(h) for h, v in hs.items() if VERDICT_RANK[v["verdict"]] >= VERDICT_RANK[minimum])
        if ok:
            out[p] = ok
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m app.ml", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["targets", "train", "report", "check", "regimes"])
    ap.add_argument("--db", help="history database (default DATA_DIR/history.sqlite)")
    ap.add_argument("--out", help="train: model root (default DATA_DIR/models); report: markdown path")
    ap.add_argument("--config", help="JSON file with MlConfig fields to override")
    ap.add_argument("--pollutants")
    ap.add_argument("--horizons")
    ap.add_argument("--coverage", default="../docs/data/coverage-report.json")
    ap.add_argument("--minimum", default="supported", choices=["limited", "supported"])
    ap.add_argument("--run", help="run directory (default: latest in the model root)")
    ap.add_argument("--dev-end", help="regimes: end of the development period, ISO UTC (default: the split date of the run)")
    args = ap.parse_args(argv)
    settings = get_settings()
    root = Path(settings.data_dir) / "models"

    if args.cmd == "targets":
        t = targets_from_coverage(args.coverage, args.minimum)
        print(json.dumps(t) if t else "No pollutant/horizon meets the support criteria.")
        return 0 if t else 1
    if args.cmd == "check":
        try:
            run = artifacts.load_run(args.run or root)
        except artifacts.ModelUnavailable as exc:
            print(f"UNAVAILABLE: {exc.message}")
            return 1
        print(f"OK run {run.run_id}: " + ", ".join(f"{p} +{h}h x{len(v)}" for (p, h), v in sorted(run.estimators.items())))
        return 0
    if args.cmd == "report":
        run_dir = artifacts.resolve_run_dir(args.run or root)
        out = args.out or "../docs/ml-model-comparison.md"
        write_report(run_dir, out, args.coverage)
        print(f"wrote {out} from {run_dir}")
        return 0

    if args.cmd == "regimes":
        from datetime import datetime, timezone

        from app.ml.regimes import fit_regimes, save
        store = HistoryStore(args.db or str(Path(settings.data_dir) / "history.sqlite"), read_only=True)
        if args.dev_end:
            dev_end = datetime.fromisoformat(args.dev_end.replace("Z", "+00:00"))
        else:
            run_dir = artifacts.resolve_run_dir(args.run or root)
            results = json.loads((run_dir / "results.json").read_text(encoding="utf-8"))
            split = next(iter(results["data"].values()))["split"]
            dev_end = datetime.fromisoformat(split["dev_to_exclusive"] + ":00:00+00:00")
        res = fit_regimes(store, dev_end)
        out = Path(args.out) if args.out else root / "regimes.json"
        save(res, out)
        print(f"k={res['model']['k']} regimes, labels: {res['model']['labels']}; KW test-period: {res['test']['kruskal_wallis']}; saved {out}")
        return 0
    cfg = MlConfig.from_json(Path(args.config).read_text(encoding="utf-8")) if args.config else MlConfig()
    if args.pollutants:
        cfg.pollutants = args.pollutants.split(",")
    if args.horizons:
        cfg.horizons = [int(h) for h in args.horizons.split(",")]
    store = HistoryStore(args.db or str(Path(settings.data_dir) / "history.sqlite"))
    res = run_experiment(store, cfg, args.out or str(root), log=lambda m: print(m, flush=True))
    store.close()
    (Path(res["run_dir"]) / "config_used.json").write_text(json.dumps(asdict(cfg), indent=1), encoding="utf-8")
    print(f"run {res['run_id']} saved to {res['run_dir']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
