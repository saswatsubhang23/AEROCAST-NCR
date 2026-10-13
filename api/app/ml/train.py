"""Training and evaluation. This module is for offline use only: the FastAPI app never imports it (request-time inference lives in
app/ml/inference.py and only loads saved artifacts).

Protocol (every step is chronological and uses only information that exists at its own point in time)
  1. Origins are split by time: dev = first 80% of the span, test = last 20% (touched exactly once, at the end).
  2. Rolling-origin validation: n_folds expanding-window folds inside dev; each fold trains on origins whose *target time* is
     before the fold's validation window and is scored on that window.
  3. Hyperparameters: a small grid per model, scored on the last fold at one horizon (tune_horizon) and reused for the others.
     The test period is never used for any choice.
  4. Model choice per horizon: lowest mean rolling-fold MAE. Training accuracy is never used.
  5. Final models are refit on all of dev and scored once on test. Baselines are scored on the same rows.
  6. Ensembles are formed from validation results only and adopted only if they beat the best single model on validation by at
     least `ensemble_min_gain`; their test score is then reported whatever it is.
"""

import hashlib
import json
import logging
import time
from datetime import datetime, timezone

import numpy as np

from app.history.store import HistoryStore
from app.ml import artifacts
from app.ml.config import MlConfig
from app.ml.dataset import (
    Dataset, climatology_fit, dataset_provenance, climatology_predict, eval_mask, load_dataset, make_splits, persistence, subsample, train_mask,
)
from app.ml.metrics import stratified, regression_metrics, skill
from app.ml.models import GRIDS, fit_predict

logger = logging.getLogger("app.ml")
BASELINES = ["persistence", "seasonal_naive", "climatology"]


def _train_rows(ds: Dataset, j: int, end: int, cfg: MlConfig, name: str, seed: int, exclude_stations: np.ndarray | None = None) -> np.ndarray:
    m = train_mask(ds, j, end)
    if exclude_stations is not None and len(exclude_stations):
        m &= ~np.isin(ds.station, exclude_stations)
    idx = np.where(m)[0]
    return subsample(idx, cfg.max_train_rows[name], seed)  # the cap is applied to training rows only


def _eval_rows(ds: Dataset, j: int, start: int, end: int, cfg: MlConfig, seed: int) -> np.ndarray:
    return subsample(np.where(eval_mask(ds, j, start, end))[0], cfg.max_eval_rows, seed)


def _baseline_preds(ds: Dataset, j: int, train_end: int, rows: np.ndarray, cfg: MlConfig, seed: int) -> dict[str, np.ndarray]:
    train = np.where(train_mask(ds, j, train_end))[0]
    table = climatology_fit(ds, j, train)  # training rows only
    return {"persistence": persistence(ds, rows).astype(np.float64), "seasonal_naive": ds.seasonal[rows, j].astype(np.float64),
            "climatology": climatology_predict(table, ds, j, rows)}


def _score(ds: Dataset, j: int, rows: np.ndarray, preds: np.ndarray) -> dict:
    return regression_metrics(ds.Y[rows, j].astype(np.float64), preds)


def run_experiment(store: HistoryStore, cfg: MlConfig, out_root: str, log=print) -> dict:
    started = time.perf_counter()
    results: dict = {"created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "config": cfg.to_json(), "environment": artifacts.environment(),
                     "pollutants": {}, "data": {}}
    prov = dataset_provenance(store)
    if prov["provenance"] != "real_source_ingest" and not cfg.allow_test_fixtures:
        raise ValueError("Refusing to train: the history store is not tied to a recorded real-source ingestion "
                         f"({prov}). Test fixtures must never be used for training or evaluation.")
    results["dataset_provenance"] = prov
    saved_models: list[dict] = []
    intervals: dict = {}
    digest = None
    schema: dict = {}
    for pollutant in cfg.pollutants:
        log(f"[{pollutant}] loading dataset")
        ds = load_dataset(store, pollutant, cfg.horizons)
        digest = digest or ds.meta["digest"]
        splits = make_splits(ds.origin, cfg)
        zone = {r["station_id"]: r["zone"] for r in store.query("select station_id, zone from stations")}
        data_info = {"rows": ds.n, "stations": int(len(np.unique(ds.station))), "feature_count": len(ds.feature_names), "digest": ds.meta["digest"],
                     "split": splits.describe(), "latency_hours": json.loads(ds.meta["feature_params"]).get("latency_hours") if ds.meta.get("feature_params") else None}
        res = _run_pollutant(store, ds, splits, cfg, zone, log)
        res["data"] = data_info
        results["pollutants"][pollutant] = res["result"]
        results["data"][pollutant] = data_info
        saved_models += res["models"]
        intervals[pollutant] = res["intervals"]
        schema = {"feature_names": ds.design(cfg.location_features)[1], "location_features": cfg.location_features, "unit": "µg/m³",
                  "missing_value_policy": "NaN passed to the model (trees handle it natively; SVR imputes with training medians inside its pipeline)",
                  "horizons": cfg.horizons, "latency_hours": data_info["latency_hours"], "origin": "hour label (UTC); features use data at or before it"}
    results["runtime_seconds"] = time.perf_counter() - started
    run_id = hashlib.sha256((cfg.digest() + str(digest)).encode()).hexdigest()[:12]
    results["run_id"] = run_id
    run_dir = artifacts.save_run(out_root, run_id, config_json=cfg.to_json(), schema=schema, models=saved_models, intervals=intervals, results=results, data_digest=digest)
    results["run_dir"] = str(run_dir)
    log(f"saved run {run_id} to {run_dir} in {results['runtime_seconds']:.0f}s")
    return results


def _run_pollutant(store: HistoryStore, ds: Dataset, sp, cfg: MlConfig, zone: dict, log) -> dict:
    H = ds.horizons
    loc = cfg.location_features
    X_all, _ = ds.design(loc)
    last_fold = sp.folds[-1]
    jt = H.index(cfg.tune_horizon) if cfg.tune_horizon in H else len(H) // 2
    models = [m for m in cfg.models]
    out: dict = {"tuning": {}, "rolling": {}, "test": {}}

    # ---- 3. hyperparameters (last fold, one horizon). Test period is not touched.
    chosen: dict[str, dict] = {}
    val_rows = _eval_rows(ds, jt, last_fold[0], last_fold[1], cfg, cfg.seed)
    for name in models:
        trials = []
        for params in GRIDS[name]:
            tr = _train_rows(ds, jt, last_fold[0], cfg, name, cfg.seed)
            if len(tr) < cfg.min_train_rows or len(val_rows) == 0:
                continue
            _, (pred,), facts = fit_predict(name, params, cfg.seed, cfg.n_jobs, X_all[tr], ds.Y[tr, jt], [X_all[val_rows]])
            trials.append({"params": params, "validation_mae": _score(ds, jt, val_rows, pred)["mae"], **facts})
            log(f"[{ds.pollutant}] tune {name} {params}: val MAE {trials[-1]['validation_mae']:.3f} ({facts['fit_seconds']:.0f}s)")
        if trials:
            chosen[name] = min(trials, key=lambda t: t["validation_mae"])["params"]
        out["tuning"][name] = {"tuned_at_horizon": H[jt], "trials": trials, "chosen": chosen.get(name)}
    models = [m for m in models if m in chosen]

    # ---- 2. rolling-origin folds with the tuned parameters
    fold_pred: dict = {}  # (fold, j) -> (rows, {name: preds})
    for k, (a, b) in enumerate(sp.folds):
        for j, h in enumerate(H):
            rows = _eval_rows(ds, j, a, b, cfg, cfg.seed + k)
            if len(rows) == 0:
                continue
            base = _baseline_preds(ds, j, a, rows, cfg, cfg.seed)
            preds = dict(base)
            facts_by_model = {}
            for name in models:
                tr = _train_rows(ds, j, a, cfg, name, cfg.seed)
                if len(tr) < cfg.min_train_rows:
                    continue
                _, (p,), facts = fit_predict(name, chosen[name], cfg.seed, cfg.n_jobs, X_all[tr], ds.Y[tr, j], [X_all[rows]])
                preds[name] = p
                facts_by_model[name] = facts
            fold_pred[(k, j)] = (rows, preds)
            r = out["rolling"].setdefault(str(h), {"folds": []})
            r["folds"].append({"fold": k, "validation_from": sp.describe()["folds"][k]["validation_from"], "n": int(len(rows)),
                               "scores": {n: _score(ds, j, rows, p) for n, p in preds.items()},
                               "runtime": {n: {"fit_seconds": f["fit_seconds"], "train_rows": f["train_rows"]} for n, f in facts_by_model.items()}})
            log(f"[{ds.pollutant}] fold {k} h={h}: " + ", ".join(f"{n} {r['folds'][-1]['scores'][n]['mae']:.2f}" for n in preds))

    # ---- 4. selection from rolling results only
    def mean_mae(name: str, j: int) -> float | None:
        vals = [_score(ds, j, rows, preds[name])["mae"] for (k, jj), (rows, preds) in fold_pred.items() if jj == j and name in preds]
        return float(np.mean(vals)) if vals else None

    # ---- 6. ensembles judged on validation only
    ens_defs: dict[int, dict] = {}
    for j, h in enumerate(H):
        scores = {n: mean_mae(n, j) for n in models if mean_mae(n, j) is not None}
        if len(scores) < 2:
            continue
        order = sorted(scores, key=scores.get)
        cands = {"mean_top2": order[:2], "mean_all": order}
        best_single = scores[order[0]]
        evals = {}
        for cname, members in cands.items():
            vals = [_score(ds, j, rows, np.mean([preds[m] for m in members], axis=0))["mae"] for (k, jj), (rows, preds) in fold_pred.items()
                    if jj == j and all(m in preds for m in members)]
            if vals:
                evals[cname] = {"members": members, "rolling_mae": float(np.mean(vals))}
        if evals:
            best = min(evals, key=lambda c: evals[c]["rolling_mae"])
            adopted = evals[best]["rolling_mae"] <= best_single * (1.0 - cfg.ensemble_min_gain)
            ens_defs[j] = {"candidates": evals, "best": best, "adopted": bool(adopted), "best_single": order[0], "best_single_rolling_mae": best_single}

    # ---- 5. final fit on all of dev, single look at the test period
    final_models: dict = {}
    for j, h in enumerate(H):
        test_rows_full = np.where(eval_mask(ds, j, sp.test_start, sp.t_max + 1, need_seasonal=False))[0]
        test_rows = _eval_rows(ds, j, sp.test_start, sp.t_max + 1, cfg, cfg.seed + 99)
        if len(test_rows) == 0:
            continue
        base = _baseline_preds(ds, j, sp.test_start, test_rows, cfg, cfg.seed)
        entry = {"n_sample": int(len(test_rows)), "n_available": int(len(test_rows_full)), "baselines": {n: _score(ds, j, test_rows, p) for n, p in base.items()},
                 "models": {}}
        preds_test = dict(base)
        for name in models:
            tr = _train_rows(ds, j, sp.test_start, cfg, name, cfg.seed)
            if len(tr) < cfg.min_train_rows:
                continue
            eval_sets = [X_all[test_rows]] + ([X_all[test_rows_full]] if name != "svr" else [])
            model, preds, facts = fit_predict(name, chosen[name], cfg.seed, cfg.n_jobs, X_all[tr], ds.Y[tr, j], eval_sets)
            preds_test[name] = preds[0]
            m = {"scores": _score(ds, j, test_rows, preds[0]), **facts, "params": chosen[name],
                 "skill_vs_persistence": skill(_score(ds, j, test_rows, preds[0])["mae"], entry["baselines"]["persistence"]["mae"]),
                 "rolling_mean_mae": mean_mae(name, j)}
            if name != "svr":
                m["scores_full_test"] = _score(ds, j, test_rows_full, preds[1])
                m["full_test_persistence"] = regression_metrics(ds.Y[test_rows_full, j].astype(np.float64), persistence(ds, test_rows_full).astype(np.float64))
            entry["models"][name] = m
            final_models[(j, name)] = model
            log(f"[{ds.pollutant}] test h={h} {name}: MAE {m['scores']['mae']:.3f} (persistence {entry['baselines']['persistence']['mae']:.3f})")
            if name != "svr" and h == H[jt] and hasattr(model, "feature_importances_"):
                names = ds.design(loc)[1]
                imp = np.asarray(model.feature_importances_, dtype=float)
                out.setdefault("importance", {})[name] = [{"feature": names[i], "importance": float(imp[i] / max(imp.sum(), 1e-12))} for i in np.argsort(-imp)[:15]]
        ranked = sorted((n for n in entry["models"] if entry["models"][n]["rolling_mean_mae"] is not None), key=lambda n: entry["models"][n]["rolling_mean_mae"])
        entry["selected_by_validation"] = ranked[0] if ranked else None
        ed = ens_defs.get(j)
        if ed:
            members = ed["candidates"][ed["best"]]["members"]
            if all(m in preds_test for m in members):
                entry["ensemble"] = {**ed, "test_scores": _score(ds, j, test_rows, np.mean([preds_test[m] for m in members], axis=0)),
                                     "members": members}
        entry["_rows"], entry["_preds"] = test_rows, preds_test  # working data, removed before results are written
        out["test"][str(h)] = entry

    # ---- intervals: signed validation residual quantiles of the selected model, evaluated for coverage on test
    lo_q, hi_q = (1 - cfg.interval_level) / 2, 1 - (1 - cfg.interval_level) / 2
    iv: dict = {}
    saved: list[dict] = []
    for j, h in enumerate(H):
        e = out["test"].get(str(h))
        if not e or not e["selected_by_validation"]:
            continue
        use_ens = bool(e.get("ensemble", {}).get("adopted"))
        members = e["ensemble"]["members"] if use_ens else [e["selected_by_validation"]]
        res = []
        for (k, jj), (rows, preds) in fold_pred.items():
            if jj == j and all(m in preds for m in members):
                res.append(ds.Y[rows, j].astype(np.float64) - np.mean([preds[m] for m in members], axis=0))
        if not res:
            continue
        r = np.concatenate(res)
        qlo, qhi = float(np.quantile(r, lo_q)), float(np.quantile(r, hi_q))
        p_test = np.mean([e["_preds"][m] for m in members], axis=0)
        y_test = ds.Y[e["_rows"], j].astype(np.float64)
        lower, upper = np.maximum(0.0, p_test + qlo), p_test + qhi
        iv[str(h)] = {"level": cfg.interval_level, "q_low": qlo, "q_high": qhi, "residuals_n": int(len(r))}
        e["calibration"] = {"nominal": cfg.interval_level, "empirical_coverage_test": float(np.mean((y_test >= lower) & (y_test <= upper))),
                            "mean_width": float(np.mean(upper - lower))}
        e["final_model"] = {"members": members, "ensemble": use_ens}
        saved.append({"pollutant": ds.pollutant, "horizon": h,
                      "members": [{"name": m, "params": chosen[m], "estimator": final_models[(j, m)]} for m in members]})

    # ---- by station / region for the final model, then unseen-station experiment
    out["by_station"] = {}
    for h_s, e in out["test"].items():
        j = H.index(int(h_s))
        sel = e.get("final_model")
        if not sel:
            continue
        p = np.mean([e["_preds"][m] for m in sel["members"]], axis=0)
        rows = e["_rows"]
        per: dict = {}
        for s in np.unique(ds.station[rows]):
            m = ds.station[rows] == s
            if m.sum() >= 50:
                per[int(s)] = {**regression_metrics(ds.Y[rows[m], j].astype(np.float64), p[m]), "zone": zone.get(int(s)),
                               "persistence_mae": regression_metrics(ds.Y[rows[m], j].astype(np.float64), e["_preds"]["persistence"][m])["mae"]}
        maes = np.array([v["mae"] for v in per.values()])
        zones: dict = {}
        for s, v in per.items():
            zones.setdefault(v["zone"], []).append(v["mae"])
        target_hours = ds.origin[rows].astype(np.int64) + int(h_s)
        e["stratified"] = stratified(ds.Y[rows, j].astype(np.float64), p, e["_preds"]["persistence"], target_hours, ds.pollutant)
        e["per_station_summary"] = {"stations": len(per), "mae_min": float(maes.min()) if len(maes) else None, "mae_median": float(np.median(maes)) if len(maes) else None,
                                    "mae_max": float(maes.max()) if len(maes) else None,
                                    "by_zone_mean_mae": {z: float(np.mean(v)) for z, v in zones.items()}}
        out["by_station"][h_s] = per

    out["location_experiment"] = _location_experiment(ds, sp, cfg, chosen, out, log)
    for e in out["test"].values():  # drop working arrays before the results are serialised
        e.pop("_rows", None)
        e.pop("_preds", None)
    return {"result": out, "models": saved, "intervals": iv, "data": None}


def _location_experiment(ds: Dataset, sp, cfg: MlConfig, chosen: dict, out: dict, log) -> dict:
    """Does a model generalise to stations it never saw? Train without a random 20% of stations; score the test period on both
    groups; compare inputs with and without station coordinates."""
    stations = np.unique(ds.station)
    rng = np.random.default_rng(cfg.seed)
    unseen = np.sort(rng.choice(stations, size=max(1, int(round(len(stations) * cfg.unseen_station_frac))), replace=False))
    res: dict = {"unseen_stations": [int(s) for s in unseen], "horizons": {}}
    for h in cfg.location_experiment_horizons:
        if h not in ds.horizons or str(h) not in out["test"]:
            continue
        j = ds.horizons.index(h)
        e = out["test"][str(h)]
        name = e["selected_by_validation"]
        if not name:
            continue
        rows = e["_rows"]
        is_unseen = np.isin(ds.station[rows], unseen)
        if is_unseen.sum() < 100 or (~is_unseen).sum() < 100:
            continue
        entry = {"model": name, "n_seen": int((~is_unseen).sum()), "n_unseen": int(is_unseen.sum()),
                 "persistence_mae": {"seen": regression_metrics(ds.Y[rows[~is_unseen], j].astype(np.float64), e["_preds"]["persistence"][~is_unseen])["mae"],
                                     "unseen": regression_metrics(ds.Y[rows[is_unseen], j].astype(np.float64), e["_preds"]["persistence"][is_unseen])["mae"]}}
        for variant, use_loc in (("no_location", False), ("with_station_coordinates", True)):
            X, _ = ds.design(use_loc)
            tr = _train_rows(ds, j, sp.test_start, cfg, name, cfg.seed, exclude_stations=unseen)
            if len(tr) < cfg.min_train_rows:
                continue
            _, (p,), _ = fit_predict(name, chosen[name], cfg.seed, cfg.n_jobs, X[tr], ds.Y[tr, j], [X[rows]])
            y = ds.Y[rows, j].astype(np.float64)
            entry[variant] = {"seen": regression_metrics(y[~is_unseen], p[~is_unseen]), "unseen": regression_metrics(y[is_unseen], p[is_unseen])}
            log(f"[{ds.pollutant}] location experiment h={h} {variant}: seen MAE {entry[variant]['seen']['mae']:.2f}, unseen MAE {entry[variant]['unseen']['mae']:.2f}")
        res["horizons"][str(h)] = entry
    return res
