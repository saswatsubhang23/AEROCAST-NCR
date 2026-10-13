"""Model comparison report, generated from a run's results.json. Every number in it is read from the saved results; nothing is
typed in by hand and nothing is recomputed from a different source."""

import json
from pathlib import Path

BASE = ["persistence", "seasonal_naive", "climatology"]
LABEL = {"persistence": "Persistence", "seasonal_naive": "Seasonal naive (same hour, previous day)", "climatology": "Climatology (train mean by station and hour)",
         "random_forest": "Random Forest", "xgboost": "XGBoost", "lightgbm": "LightGBM", "svr": "Support Vector Regression"}


def f(v, d=2) -> str:
    return "n/a" if v is None else f"{v:.{d}f}"


def pct(v) -> str:
    return "n/a" if v is None else f"{100 * v:+.1f}%"


def render(results: dict, coverage: dict | None = None) -> str:
    L: list[str] = []
    cfg = json.loads(results["config"])
    env = results["environment"]
    prov = results.get("dataset_provenance", {})
    banner = [] if prov.get("provenance") == "real_source_ingest" else ["> **TEST FIXTURE DATA: these results come from synthetic test data and are not evidence of forecasting accuracy.**", ""]
    L += banner
    L += ["# Model comparison report", "",
          f"Run `{results['run_id']}`, created {results['created_at']}, total training and evaluation time {results['runtime_seconds'] / 60:.1f} min. "
          "Generated from the run's `results.json`; every figure below was computed by the pipeline, none is typed in. Scores are in µg/m³. "
          + (f"Dataset provenance: **{prov['provenance']}** ({prov.get('raw_air_rows', 0):,} raw OpenAQ rows from {prov.get('ingest_air_runs', 0)} recorded ingest runs).", "")[0] if prov else "", "",
          "Libraries: " + ", ".join(f"{k} {v}" for k, v in env["libraries"].items()) + f"; Python {env['python']}; {env['platform']}.", ""]

    if coverage:
        L += ["## Targets and horizons chosen from the data", "",
              "Targets were not assumed. The historical data pipeline's support table (`docs/data/coverage-report.md`) judges every pollutant and horizon; "
              f"this run trained only {', '.join(cfg['pollutants'])} at horizons {', '.join(f'+{h} h' for h in cfg['horizons'])}.", "",
              "| pollutant | " + " | ".join(f"+{h} h" for h in coverage["support"]["pm25"]) + " |", "|---|" + "---|" * len(coverage["support"]["pm25"])]
        for p, d in coverage["support"].items():
            L.append(f"| {p} | " + " | ".join(f"{v['verdict']} ({v['stations_meeting_threshold']} st)" for v in d.values()) + " |")
        L += [""]

    L += ["## Protocol", "",
          f"* **Chronological split.** Origins are split by time: development = first {100 - int(cfg['test_frac'] * 100)}% of the time span, held-out test = the last {int(cfg['test_frac'] * 100)}%, scored once at the end.",
          f"* **Rolling-origin validation.** {cfg['n_folds']} expanding-window folds inside development, each validating on a window of {int(cfg['fold_frac'] * 100)}% of the span. A training row for horizon h is used only if its target time (origin + h) precedes the validation window (label purging).",
          f"* **Hyperparameters** come from a small grid scored on the last fold at +{cfg['tune_horizon']} h and are reused for the other horizons. The test period is never used for any choice.",
          "* **Model selection** per horizon is the lowest mean rolling-fold MAE. Training accuracy is not used anywhere.",
          "* **Preprocessing** that learns anything (SVR median imputation and scaling) is inside the estimator and fitted on its training rows only. Trees receive NaN as is.",
          f"* **Samples.** Training rows are capped per model ({', '.join(f'{k} {v:,}' for k, v in cfg['max_train_rows'].items())}), evaluation sets at {cfg['max_eval_rows']:,} rows; the cap is a deterministic random subsample and every model and baseline is scored on the *same* rows. Tree models are also scored on every available test row (`full test`).",
          f"* **Inputs** are the validated model-ready features (pollutant lags and rolling statistics, weather at or before the origin, wind vectors, IST time features); location features are {'included' if cfg['location_features'] else 'not included'} in the main comparison. Pollutant publication latency used when the features were built: {next(iter(results['data'].values()))['latency_hours']} h.", ""]

    for pol, r in results["pollutants"].items():
        d = results["data"][pol]
        sp = d["split"]
        L += [f"## {pol}", "",
              f"{d['rows']:,} origin rows from {d['stations']} stations, {d['feature_count']} input features, data digest `{(d['digest'] or '')[:12]}`. "
              f"Data {sp['data_from']} to {sp['data_to']}; development before {sp['dev_to_exclusive']}; **test from {sp['test_from']}**. "
              "Validation windows: " + "; ".join(f"{x['validation_from']} to {x['validation_to_exclusive']}" for x in sp["folds"]) + ".", ""]
        L += ["### Held-out test results", ""]
        for h, e in r["test"].items():
            sel = e.get("final_model") or {}
            L += [f"**+{h} h** — test sample {e['n_sample']:,} of {e['n_available']:,} available rows. Model chosen on validation: "
                  f"**{LABEL.get(e['selected_by_validation'], e['selected_by_validation'])}**" + (" (adopted ensemble: " + " + ".join(sel["members"]) + ")" if sel.get("ensemble") else "") + ".", "",
                  "| method | MAE | RMSE | R² | bias | n | skill vs persistence | validation MAE (mean of folds) | fit s | predict s | peak process RSS MB | train rows |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
            pm = e["baselines"]["persistence"]["mae"]
            for b in BASE:
                s = e["baselines"][b]
                L.append(f"| {LABEL[b]} | {f(s['mae'])} | {f(s['rmse'])} | {f(s['r2'], 3)} | {f(s['bias'])} | {s['n']:,} | {pct(None if b == 'persistence' else (1 - s['mae'] / pm))} | | | | | |")
            for n, m in e["models"].items():
                s = m["scores"]
                star = " ★" if n == e["selected_by_validation"] else ""
                L.append(f"| {LABEL[n]}{star} | {f(s['mae'])} | {f(s['rmse'])} | {f(s['r2'], 3)} | {f(s['bias'])} | {s['n']:,} | {pct(m['skill_vs_persistence'])} | {f(m['rolling_mean_mae'])} | {f(m['fit_seconds'], 1)} | {f(m['predict_seconds'], 1)} | {f(m['peak_rss_mb'], 0)} | {m['train_rows']:,} |")
            if "ensemble" in e:
                en = e["ensemble"]
                L.append(f"| Ensemble `{en['best']}` ({' + '.join(en['members'])}){' — adopted' if en['adopted'] else ' — not adopted'} | {f(en['test_scores']['mae'])} | {f(en['test_scores']['rmse'])} | {f(en['test_scores']['r2'], 3)} | {f(en['test_scores']['bias'])} | {en['test_scores']['n']:,} | {pct(1 - en['test_scores']['mae'] / pm)} | {f(en['candidates'][en['best']]['rolling_mae'])} | | | | |")
            full = [(n, m) for n, m in e["models"].items() if "scores_full_test" in m]
            if full:
                L += ["", "Full test set (every available row, tree models): " + "; ".join(f"{LABEL[n]} MAE {f(m['scores_full_test']['mae'])} vs persistence {f(m['full_test_persistence']['mae'])} (n={m['scores_full_test']['n']:,})" for n, m in full) + "."]
            L += [""]

        L += ["### Rolling-origin validation (MAE by fold)", "", "| horizon | method | " + " | ".join(f"fold {i}" for i in range(len(sp['folds']))) + " | mean | sd |", "|---|---|" + "---:|" * (len(sp["folds"]) + 2)]
        import statistics
        for h, rr in r["rolling"].items():
            names = list(rr["folds"][0]["scores"])
            for n in names:
                vals = [fo["scores"][n]["mae"] for fo in rr["folds"] if n in fo["scores"]]
                L.append(f"| +{h} h | {LABEL[n]} | " + " | ".join(f(v) for v in vals) + f" | {f(statistics.fmean(vals))} | {f(statistics.pstdev(vals)) if len(vals) > 1 else 'n/a'} |")
        L += ["", "### Hyperparameter search (last fold, validation only)", "", "| model | tuned at | candidate | validation MAE | fit s | chosen |", "|---|---|---|---:|---:|---|"]
        for n, t in r["tuning"].items():
            for tr in t["trials"]:
                L.append(f"| {LABEL[n]} | +{t['tuned_at_horizon']} h | `{tr['params']}` | {f(tr['validation_mae'])} | {f(tr['fit_seconds'], 1)} | {'yes' if tr['params'] == t['chosen'] else ''} |")

        L += ["", "### Ensembles (decided on validation)", "", f"An ensemble is adopted only if its mean rolling-fold MAE is at least {int(cfg['ensemble_min_gain'] * 100)}% below the best single model.", "",
              "| horizon | best single (validation MAE) | best ensemble (validation MAE) | adopted | test MAE of the ensemble | test MAE of the best single |", "|---|---|---|---|---:|---:|"]
        for h, e in r["test"].items():
            en = e.get("ensemble")
            if en:
                bs = en["best_single"]
                L.append(f"| +{h} h | {LABEL[bs]} ({f(en['best_single_rolling_mae'])}) | {en['best']} ({f(en['candidates'][en['best']]['rolling_mae'])}) | {'yes' if en['adopted'] else 'no'} | {f(en['test_scores']['mae'])} | {f(e['models'][bs]['scores']['mae'])} |")

        L += ["", "### Performance by location (final model, test sample)", "", "| horizon | stations | station MAE min / median / max | mean MAE by region |", "|---|---:|---|---|"]
        for h, e in r["test"].items():
            s = e.get("per_station_summary")
            if s:
                L.append(f"| +{h} h | {s['stations']} | {f(s['mae_min'])} / {f(s['mae_median'])} / {f(s['mae_max'])} | " + ", ".join(f"{z} {f(v)}" for z, v in sorted(s["by_zone_mean_mae"].items(), key=lambda x: str(x[0]))) + " |")
        lx = r.get("location_experiment", {})
        if lx.get("horizons"):
            L += ["", f"### Generalisation to unseen stations", "", f"{len(lx['unseen_stations'])} randomly chosen stations ({', '.join(map(str, lx['unseen_stations']))}) were removed from training; the same model type was scored on the test period for stations it had seen and ones it had not. Lower is better.", "",
                  "| horizon | model | inputs | seen MAE | unseen MAE | persistence seen / unseen | n seen / unseen |", "|---|---|---|---:|---:|---|---|"]
            for h, x in lx["horizons"].items():
                for v in ("no_location", "with_station_coordinates"):
                    if v in x:
                        L.append(f"| +{h} h | {LABEL[x['model']]} | {v.replace('_', ' ')} | {f(x[v]['seen']['mae'])} | {f(x[v]['unseen']['mae'])} | {f(x['persistence_mae']['seen'])} / {f(x['persistence_mae']['unseen'])} | {x['n_seen']:,} / {x['n_unseen']:,} |")
        L += ["", "### Prediction-interval calibration", "", "Intervals use signed validation-residual quantiles of the final model (never test residuals). Empirical coverage is measured on the test sample.", "",
              "| horizon | nominal | empirical coverage (test) | mean width |", "|---|---:|---:|---:|"]
        for h, e in r["test"].items():
            c = e.get("calibration")
            if c:
                L.append(f"| +{h} h | {c['nominal']:.0%} | {c['empirical_coverage_test']:.1%} | {f(c['mean_width'], 1)} |")
        strat = [(h, e["stratified"]) for h, e in r["test"].items() if e.get("stratified")]
        if strat:
            L += ["", "### Performance by season and by concentration range (final model, test sample)", "",
                  "Season is that of the target hour in IST (IMD seasons). Range bands are the CPCB category bands of the pollutant, applied to the OBSERVED value. "
                  "A stratum with fewer than 30 scored rows shows no score. Skill is 1 - MAE / persistence MAE; negative means worse than holding the last observation.", "",
                  "| horizon | stratum | n | MAE | persistence MAE | skill |", "|---|---|---:|---:|---:|---:|"]
            for h, st in strat:
                for kind in ("season", "range"):
                    for name, v in st[kind].items():
                        L.append(f"| +{h} h | {kind}: {name.replace('_', ' ')} | {v['n']:,} | {f(v['mae'])} | {f(v['persistence_mae'])} | {f(v['skill'], 2)} |")
        imps = r.get("importance")
        if imps:
            L += ["", "### Most influential features (tree-model impurity/gain importance at the tuning horizon; indicative, not causal)", ""]
            for n, items in imps.items():
                L.append(f"* **{LABEL[n]}**: " + ", ".join(f"`{i['feature']}` {i['importance']:.1%}" for i in items[:8]))
        L += [""]
    return "\n".join(L) + "\n"


def write_report(run_dir: str | Path, out_md: str | Path, coverage_json: str | Path | None = None) -> str:
    results = json.loads((Path(run_dir) / "results.json").read_text(encoding="utf-8"))
    cov = json.loads(Path(coverage_json).read_text(encoding="utf-8")) if coverage_json and Path(coverage_json).exists() else None
    text = render(results, cov)
    Path(out_md).write_text(text, encoding="utf-8")
    return text
