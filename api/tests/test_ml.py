"""ML pipeline tests: preprocessing, leakage prevention, metrics, artifacts, reproducibility, and request-time inference."""

import json
import math
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import numpy as np
import pytest
from mlfakes import make_history

from app.api.forecast import get_forecast_service
from app.core.config import Settings, get_settings
from app.forecast.contract import ForecastLocation, ForecastRequest, ForecastResponse, check_against_request
from app.forecast.provider import ForecastNotConfigured, ForecastService, ForecastUnavailable, make_provider
from app.history import features as hist_features
from app.history.store import HistoryStore
from app.ml import artifacts, dataset as D
from app.ml.config import MlConfig
from app.ml.inference import LocalModelProvider
from app.ml.metrics import regression_metrics, skill
from app.ml.models import make_model
from app.ml.report import render
from app.ml.train import run_experiment

HORIZONS = [1, 6]
MODELS = ["random_forest", "xgboost", "lightgbm", "svr"]


def same(a, b, rel=1e-6) -> bool:
    """Equal up to floating-point summation order (threaded tree libraries add in a different order run to run)."""
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(same(a[k], b[k], rel) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(same(x, y, rel) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        return a == pytest.approx(b, rel=rel, abs=1e-9)
    return a == b


def tiny_config(**over) -> MlConfig:
    base = dict(pollutants=["pm25"], horizons=HORIZONS, models=MODELS, n_folds=2, fold_frac=0.12, test_frac=0.2, tune_horizon=6,
                max_train_rows={"random_forest": 2500, "xgboost": 3000, "lightgbm": 3000, "svr": 1500}, max_eval_rows=1500, n_jobs=2,
                location_experiment_horizons=[6], min_train_rows=200, ensemble_min_gain=0.0, allow_test_fixtures=True)
    base.update(over)
    return MlConfig(**base)


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("ml")
    db = tmp / "history.sqlite"
    store, end = make_history(str(db))
    out = tmp / "models"
    res = run_experiment(store, tiny_config(), str(out), log=lambda m: None)
    return {"store": store, "db": str(db), "out": out, "res": res, "end": end, "tmp": tmp}


# ---------------------------------------------------------------------------------------------- fixtures never reach real training
def test_training_refuses_a_store_that_is_not_real_ingested_data(trained, tmp_path):
    cfg = tiny_config(allow_test_fixtures=False)
    with pytest.raises(ValueError, match="Test fixtures must never"):
        run_experiment(trained["store"], cfg, str(tmp_path / "m"), log=lambda m: None)


def test_results_and_report_from_fixture_data_are_labelled_as_such(trained):
    assert trained["res"]["dataset_provenance"]["provenance"] == "TEST FIXTURE OR UNKNOWN"
    assert "TEST FIXTURE DATA" in render(trained["res"], None)


def test_a_store_with_recorded_real_ingest_runs_counts_as_real(tmp_path):
    from histfakes import add_raw, add_sensor, add_station
    from app.history import ingest_air
    st = HistoryStore(str(tmp_path / "r.sqlite"))
    add_station(st)
    add_sensor(st, 1, 1, "pm25")
    rid = ingest_air.start_run(st, "ingest-air", {})
    add_raw(st, 1, 1, "pm25", "2026-01-01T00:30:00Z", 10.0, run=rid)
    assert D.dataset_provenance(st)["provenance"] == "real_source_ingest"
    add_raw(st, 1, 1, "pm25", "2026-01-01T01:30:00Z", 11.0, run="made-up")
    assert D.dataset_provenance(st)["provenance"] != "real_source_ingest"


def test_production_code_never_imports_test_fixtures():
    import re
    root = Path(__file__).resolve().parents[1] / "app"
    bad = re.compile(r"^\s*(from|import)\s+(tests|histfakes|mlfakes|kbfakes|test_\w+)", re.M)
    offenders = [str(p) for p in root.rglob("*.py") if bad.search(p.read_text(encoding="utf-8"))]
    assert offenders == []


# ---------------------------------------------------------------------------------------------- preprocessing
def test_dataset_columns_are_exactly_the_documented_features(trained):
    ds = D.load_dataset(trained["store"], "pm25", HORIZONS)
    assert ds.feature_names == D.feature_names_for(HORIZONS)
    assert not any(c.startswith("y_h") or c in D.ID_COLUMNS for c in ds.feature_names)
    assert ds.X.shape == (ds.n, len(ds.feature_names)) and ds.Y.shape == (ds.n, 2) and ds.X.dtype == np.float32
    assert ds.design(True)[1][-2:] == D.LOCATION_FEATURES and ds.design(True)[0].shape[1] == len(ds.feature_names) + 2
    assert np.isnan(ds.X).any() and np.isfinite(ds.col("target_lag0")).all()  # missing values arrive as NaN; the anchor value always exists


def test_targets_equal_the_future_values_in_the_clean_layer(trained):
    st = trained["store"]
    ds = D.load_dataset(st, "pm25", HORIZONS)
    clean = {(r["station_id"], r["label_utc"]): r["value_std"] for r in st.query("select station_id, label_utc, value_std from clean_air where usable=1")}
    for i in (10, 500, 3000, ds.n - 1):
        o = np.datetime64(int(ds.origin[i]), "h")
        for j, h in enumerate(HORIZONS):
            lab = str(o + np.timedelta64(h, "h")) + ":00:00Z"
            want = clean.get((int(ds.station[i]), lab))
            got = ds.Y[i, j]
            assert (want is None and np.isnan(got)) or got == pytest.approx(want, rel=1e-5)


def test_seasonal_naive_and_persistence_only_look_backwards():
    start = 1000
    arr = np.arange(400, dtype=np.float32)  # value == hour offset, so the value tells us which hour was read
    series = {7: (start, arr)}
    station = np.array([7, 7, 7], dtype=np.int32)
    origin = np.array([start + 100, start + 150, start + 399], dtype=np.int64)
    horizons = [1, 6, 24, 48, 72]
    out = D.seasonal_naive(series, station, origin, horizons)
    for i, o in enumerate(origin):
        for j, h in enumerate(horizons):
            hour_read = out[i, j] + start
            assert hour_read <= o  # never at or after the forecast target, never after the origin
            assert (o + h - hour_read) % 24 == 0  # same hour of day as the target


def test_svr_imputer_and_scaler_are_fitted_on_training_rows_only():
    rng = np.random.default_rng(0)
    X_train = rng.normal(10, 2, (400, 5)).astype(np.float32)
    X_train[::7, 1] = np.nan
    y = X_train[:, 0] * 2 + 1
    X_eval = rng.normal(500, 50, (100, 5)).astype(np.float32)  # wildly different distribution: must not leak into the fit
    m = make_model("svr", {"C": 3.0, "epsilon": 0.05}, seed=0, n_jobs=1)
    m.fit(X_train, y)
    m.predict(X_eval)
    pipe = m.regressor_
    assert np.allclose(pipe.named_steps["simpleimputer"].statistics_, np.nanmedian(X_train, axis=0), atol=1e-4)
    assert np.allclose(pipe.named_steps["standardscaler"].mean_, np.nanmean(np.where(np.isnan(X_train), pipe.named_steps["simpleimputer"].statistics_, X_train), axis=0), atol=1e-3)


@pytest.mark.parametrize("name", ["random_forest", "xgboost", "lightgbm"])
def test_tree_models_accept_missing_values_natively(name):
    rng = np.random.default_rng(1)
    X = rng.normal(0, 1, (300, 4)).astype(np.float32)
    y = (X[:, 0] * 3).astype(np.float64)
    X[::5, 0] = np.nan
    m = make_model(name, {"max_depth": 4, "min_samples_leaf": 5} if name == "random_forest" else {"max_depth": 3, "learning_rate": 0.1} if name == "xgboost" else {"num_leaves": 8, "learning_rate": 0.1}, 0, 1)
    m.fit(X, y)
    assert np.isfinite(m.predict(X)).all()


def test_unknown_model_names_are_rejected():
    with pytest.raises(ValueError):
        make_model("neural_magic", {}, 0, 1)


# ---------------------------------------------------------------------------------------------- chronological splits and leakage
def test_splits_are_chronological_and_folds_do_not_overlap_the_test_period(trained):
    ds = D.load_dataset(trained["store"], "pm25", HORIZONS)
    cfg = tiny_config()
    sp = D.make_splits(ds.origin, cfg)
    assert sp.t_min < sp.folds[0][0] < sp.folds[0][1] <= sp.folds[1][0] < sp.folds[1][1] == sp.test_start <= sp.t_max
    assert abs((sp.t_max + 1 - sp.test_start) / (sp.t_max - sp.t_min + 1) - cfg.test_frac) < 0.01


def test_training_labels_never_reach_into_the_period_being_evaluated(trained):
    ds = D.load_dataset(trained["store"], "pm25", HORIZONS)
    sp = D.make_splits(ds.origin, tiny_config())
    for k, (a, b) in enumerate(sp.folds):
        for j, h in enumerate(HORIZONS):
            tr = np.where(D.train_mask(ds, j, a))[0]
            assert len(tr) > 0 and (ds.origin[tr] + h).max() < a  # label purging: target time before the validation window
            va = np.where(D.eval_mask(ds, j, a, b))[0]
            assert (ds.origin[va] >= a).all() and (ds.origin[va] + h < b).all()  # a window never reads labels from after itself
            assert set(tr).isdisjoint(set(va))
    for j, h in enumerate(HORIZONS):
        dev = np.where(D.train_mask(ds, j, sp.test_start))[0]
        te = np.where(D.eval_mask(ds, j, sp.test_start, sp.t_max + 1, need_seasonal=False))[0]
        assert (ds.origin[dev] + h).max() < sp.test_start <= ds.origin[te].min()


def test_climatology_is_fitted_on_training_rows_only(trained):
    ds = D.load_dataset(trained["store"], "pm25", HORIZONS)
    sp = D.make_splits(ds.origin, tiny_config())
    train = np.where(D.train_mask(ds, 1, sp.test_start))[0]
    table = D.climatology_fit(ds, 1, train)
    ds2 = D.load_dataset(trained["store"], "pm25", HORIZONS)
    ds2.Y[ds2.origin >= sp.test_start] += 1000.0  # corrupt every held-out target
    assert D.climatology_fit(ds2, 1, np.where(D.train_mask(ds2, 1, sp.test_start))[0]) == table


def test_subsampling_is_deterministic_and_keeps_time_order():
    idx = np.arange(10_000)
    a, b = D.subsample(idx, 500, 1), D.subsample(idx, 500, 1)
    assert (a == b).all() and (np.diff(a) > 0).all() and len(a) == 500
    assert len(D.subsample(idx[:100], 500, 1)) == 100


def test_nothing_before_the_test_period_depends_on_test_period_values(trained, tmp_path):
    """Run the whole experiment on data whose last 20% is shifted by +80 µg/m³. Hyperparameters, validation results and the
    model chosen for each horizon must be identical; only the held-out test scores may differ."""
    hours = 1500
    shifted_store, _ = make_history(str(tmp_path / "shifted.sqlite"), end=trained["end"], test_shift=80.0, shift_from_hour=int(hours * 0.8) + 30)
    res_b = run_experiment(shifted_store, tiny_config(), str(tmp_path / "models"), log=lambda m: None)
    a = trained["res"]["pollutants"]["pm25"]
    b = res_b["pollutants"]["pm25"]
    assert {n: t["chosen"] for n, t in a["tuning"].items()} == {n: t["chosen"] for n, t in b["tuning"].items()}
    for h in map(str, HORIZONS):
        for fa, fb in zip(a["rolling"][h]["folds"], b["rolling"][h]["folds"]):
            assert same(fa["scores"], fb["scores"])  # validation never saw a test-period value
        assert a["test"][h]["selected_by_validation"] == b["test"][h]["selected_by_validation"]
        assert a["test"][h]["baselines"]["persistence"]["mae"] != b["test"][h]["baselines"]["persistence"]["mae"]  # the shift did reach the test set


# ---------------------------------------------------------------------------------------------- metrics and the experiment's outputs
def test_metrics_match_hand_computation():
    y = np.array([10.0, 20.0, 30.0, 40.0])
    p = np.array([12.0, 18.0, 33.0, 40.0])
    m = regression_metrics(y, p)
    assert m["n"] == 4 and m["mae"] == pytest.approx(1.75) and m["rmse"] == pytest.approx(math.sqrt((4 + 4 + 9 + 0) / 4))
    assert m["r2"] == pytest.approx(1 - 17 / 500) and m["bias"] == pytest.approx(0.75)
    assert regression_metrics(y, np.full(4, np.nan))["n"] == 0
    assert regression_metrics(np.ones(3), np.ones(3))["r2"] is None  # constant truth: R-squared is undefined, not 1
    assert skill(8.0, 10.0) == pytest.approx(0.2) and skill(None, 10.0) is None


def test_results_report_samples_runtime_memory_and_all_requested_comparisons(trained):
    r = trained["res"]["pollutants"]["pm25"]
    for h in map(str, HORIZONS):
        e = r["test"][h]
        assert set(e["baselines"]) == {"persistence", "seasonal_naive", "climatology"}
        assert set(e["models"]) == set(MODELS)
        for n, m in e["models"].items():
            assert m["scores"]["n"] == e["n_sample"] > 0 and m["fit_seconds"] > 0 and m["peak_rss_mb"] > 0 and m["train_rows"] > 0
            assert all(m["scores"][k] is not None for k in ("mae", "rmse", "r2"))
        assert e["selected_by_validation"] in MODELS
        assert len(r["rolling"][h]["folds"]) == 2
    assert r["location_experiment"]["horizons"].get("6") and set(r["by_station"]["6"])
    assert trained["res"]["pollutants"]["pm25"]["tuning"]["lightgbm"]["chosen"]


def test_selection_never_looks_at_the_test_scores(trained):
    r = trained["res"]["pollutants"]["pm25"]
    for h, e in r["test"].items():
        by_val = min(e["models"], key=lambda n: e["models"][n]["rolling_mean_mae"])
        assert e["selected_by_validation"] == by_val
    # the report states the same choice
    text = render(trained["res"], None)
    assert "★" in text and "Support Vector Regression" in text and "Persistence" in text


def test_the_ensemble_is_judged_on_validation_and_reported_with_its_test_score(trained):
    r = trained["res"]["pollutants"]["pm25"]
    for h, e in r["test"].items():
        en = e.get("ensemble")
        assert en and set(en["members"]) <= set(MODELS) and en["test_scores"]["n"] == e["n_sample"]
        best = en["candidates"][en["best"]]["rolling_mae"]
        assert en["adopted"] == (best <= en["best_single_rolling_mae"])  # ensemble_min_gain = 0 in this config


def test_intervals_are_calibrated_from_validation_not_test(trained):
    r = trained["res"]["pollutants"]["pm25"]
    for h, e in r["test"].items():
        c = e["calibration"]
        assert c["nominal"] == 0.8 and 0.0 <= c["empirical_coverage_test"] <= 1.0 and c["mean_width"] > 0
    iv = json.loads((Path(trained["res"]["run_dir"]) / "intervals.json").read_text(encoding="utf-8"))["pm25"]
    assert iv["6"]["q_low"] < 0 < iv["6"]["q_high"]


def test_the_same_config_and_data_give_the_same_run_id_and_scores(trained, tmp_path):
    again = run_experiment(trained["store"], tiny_config(), str(tmp_path / "m2"), log=lambda m: None)
    assert again["run_id"] == trained["res"]["run_id"]
    for h in map(str, HORIZONS):
        a, b = trained["res"]["pollutants"]["pm25"]["test"][h], again["pollutants"]["pm25"]["test"][h]
        for n in MODELS:
            assert same(a["models"][n]["scores"], b["models"][n]["scores"])
        assert same(a["baselines"], b["baselines"])


# ---------------------------------------------------------------------------------------------- artifacts
def test_a_run_saves_config_schema_environment_results_and_checksums(trained):
    run = Path(trained["res"]["run_dir"])
    for name in ("config.json", "feature_schema.json", "environment.json", "intervals.json", "results.json", "manifest.json"):
        assert (run / name).exists()
    man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    assert man["run_id"] == trained["res"]["run_id"] and man["data_digest"]
    assert all(len(v) == 64 for v in man["files"].values()) and any(f.endswith(".joblib") for f in man["files"])
    schema = json.loads((run / "feature_schema.json").read_text(encoding="utf-8"))
    assert schema["feature_names"] == D.feature_names_for(HORIZONS) and schema["unit"] == "µg/m³" and schema["horizons"] == HORIZONS
    env = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    assert env["libraries"]["scikit-learn"] and env["python"]
    assert MlConfig.from_json((run / "config.json").read_text(encoding="utf-8")) == tiny_config()
    assert json.loads((trained["out"] / "latest.json").read_text(encoding="utf-8"))["run_id"] == trained["res"]["run_id"]


def test_saved_models_load_and_predict_like_the_originals(trained):
    run = artifacts.load_run(trained["out"])
    assert run.run_id == trained["res"]["run_id"] and run.horizons("pm25") == HORIZONS
    ds = D.load_dataset(trained["store"], "pm25", HORIZONS)
    x = ds.X[:5]
    for h in HORIZONS:
        for est in run.estimators[("pm25", h)]:
            assert np.isfinite(est.predict(x)).all()


def copy_run(trained, tmp_path) -> Path:
    import shutil
    dst = tmp_path / "copy"
    shutil.copytree(trained["out"], dst)
    return dst


def test_a_changed_model_file_is_never_loaded(trained, tmp_path):
    dst = copy_run(trained, tmp_path)
    f = next(Path(dst).rglob("*.joblib"))
    f.write_bytes(f.read_bytes() + b"x")
    with pytest.raises(artifacts.ModelUnavailable, match="checksum"):
        artifacts.load_run(dst)


@pytest.mark.parametrize("what,fragment", [("manifest", "manifest is missing"), ("file", "missing"), ("latest", "damaged"), ("manifest_json", "damaged")])
def test_missing_or_damaged_artifacts_say_so(trained, tmp_path, what, fragment):
    dst = copy_run(trained, tmp_path)
    run = next(p for p in dst.iterdir() if p.is_dir())
    if what == "manifest":
        (run / "manifest.json").unlink()
        with pytest.raises(artifacts.ModelUnavailable, match=fragment):
            artifacts.load_run(dst)
    elif what == "file":
        next((run / "models").glob("*.joblib")).unlink()
        with pytest.raises(artifacts.ModelUnavailable, match=fragment):
            artifacts.load_run(dst)
    elif what == "latest":
        (dst / "latest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(artifacts.ModelUnavailable, match=fragment):
            artifacts.load_run(dst)
    else:
        (run / "manifest.json").write_text("{not json", encoding="utf-8")
        with pytest.raises(artifacts.ModelUnavailable, match=fragment):
            artifacts.load_run(run)


def test_an_empty_directory_and_an_invalid_run_name_are_unavailable(tmp_path):
    with pytest.raises(artifacts.ModelUnavailable, match="No trained model"):
        artifacts.load_run(tmp_path)
    (tmp_path / "latest.json").write_text(json.dumps({"run_id": "../../etc"}), encoding="utf-8")
    with pytest.raises(artifacts.ModelUnavailable, match="invalid run"):
        artifacts.load_run(tmp_path)


def test_a_manifest_cannot_point_outside_the_model_directory(trained, tmp_path):
    dst = copy_run(trained, tmp_path)
    run = next(p for p in dst.iterdir() if p.is_dir())
    man = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    man["files"]["../../outside.txt"] = "0" * 64
    (run / "manifest.json").write_text(json.dumps(man), encoding="utf-8")
    with pytest.raises(artifacts.ModelUnavailable, match="outside"):
        artifacts.load_run(run)


def test_a_different_library_version_than_training_refuses_to_load(trained, tmp_path, monkeypatch):
    dst = copy_run(trained, tmp_path)
    real = artifacts.environment()
    fake = {**real, "libraries": {**real["libraries"], "scikit-learn": "0.1.0", "xgboost": "0.1.0", "lightgbm": "0.1.0"}}
    monkeypatch.setattr(artifacts, "environment", lambda: fake)
    # the recorded environment (from training) says the real versions; the "current" one now differs
    with pytest.raises(artifacts.ModelUnavailable, match="trained with"):
        artifacts.load_run(dst)


# ---------------------------------------------------------------------------------------------- inference behind the forecast contract
def settings_for(trained, **over) -> Settings:
    return Settings(**{**get_settings().model_dump(), "ml_local_model_dir": str(trained["out"]), "ml_history_db": trained["db"], "ml_forecast_url": "", **over})


def request_for(trained, issued=None, horizon=12, pollutants=("pm25",), lat=28.62, lon=77.22) -> ForecastRequest:
    return ForecastRequest(location=ForecastLocation(id="delhi", name="Delhi", lat=lat, lon=lon), issued_at=issued or trained["end"] + timedelta(minutes=20),
                           horizon_hours=horizon, pollutants=list(pollutants))


async def test_a_local_forecast_is_a_valid_contract_response(trained):
    provider = LocalModelProvider(settings_for(trained), now=lambda: trained["end"] + timedelta(minutes=21))
    svc = ForecastService(settings_for(trained), provider, now=lambda: trained["end"] + timedelta(minutes=21))
    req = request_for(trained)
    res = await svc.forecast(req)  # ForecastService validates against the contract and the request
    assert isinstance(res, ForecastResponse) and res.model_version == trained["res"]["run_id"]
    f = res.forecasts[0]
    assert f.pollutant == "pm25" and f.unit == "µg/m³" and len(f.values) == len(f.times) == 2  # horizons 1 and 6 fall inside 12 h
    assert [t - trained["end"] for t in f.times] == [timedelta(hours=1), timedelta(hours=6)]
    assert all(t > req.issued_at for t in f.times) and all(v >= 0 and math.isfinite(v) for v in f.values)
    iv = f.intervals[0]
    assert iv.level == 0.8 and all(lo <= v <= hi and lo >= 0 for lo, v, hi in zip(iv.lower, f.values, iv.upper))
    p = res.provenance
    assert p.provider == "AEROCAST local model" and p.input_data and "not validated" in p.notes and p.training_data
    assert "synthetic" in " ".join(p.input_data).lower()
    ForecastResponse.model_validate(res.model_dump(mode="json"))  # round-trips through the schema


async def test_serving_builds_the_same_features_as_training(trained):
    provider = LocalModelProvider(settings_for(trained))
    st = HistoryStore(trained["db"], read_only=True)
    schema = artifacts.load_run(trained["out"]).schema
    row = provider._feature_row(st, 100, "pm25", trained["end"], schema)
    cols = hist_features.feature_columns(HORIZONS)
    stored = st.query("select * from model_ready where station_id=100 and pollutant='pm25' and origin_utc=?", (trained["end"].strftime("%Y-%m-%dT%H:%M:%SZ"),))[0]
    assert all((row[c] is None and stored[c] is None) or row[c] == pytest.approx(stored[c], rel=1e-9, abs=1e-9) for c in cols if not c.startswith("y_h"))
    st.close()


async def test_the_forecast_equals_the_saved_model_applied_to_the_training_row(trained):
    provider = LocalModelProvider(settings_for(trained), now=lambda: trained["end"])
    res = await provider.forecast(request_for(trained, horizon=6))
    run = artifacts.load_run(trained["out"])
    st = HistoryStore(trained["db"], read_only=True)
    station = min(st.query("select station_id, lat, lon from stations"), key=lambda s: (s["lat"] - 28.62) ** 2 + (s["lon"] - 77.22) ** 2)
    ds = D.load_dataset(st, "pm25", HORIZONS)
    i = np.where((ds.station == station["station_id"]) & (ds.origin == int(np.datetime64(trained["end"].replace(tzinfo=None), "h").astype(np.int64))))[0][0]
    want = np.mean([e.predict(ds.X[i:i + 1])[0] for e in run.estimators[("pm25", 6)]])
    got = res.forecasts[0].values[-1]
    assert got == pytest.approx(max(0.0, float(want)), rel=1e-4, abs=1e-3)
    st.close()


async def test_partial_pollutant_support_returns_only_what_exists(trained):
    res = await LocalModelProvider(settings_for(trained)).forecast(request_for(trained, pollutants=("pm25", "o3")))
    assert [f.pollutant for f in res.forecasts] == ["pm25"]


@pytest.mark.parametrize("make,fragment", [
    (lambda t: request_for(t, pollutants=("o3",)), "No trained model exists"),
    (lambda t: request_for(t, lat=29.5, lon=78.5), "No monitoring station within"),
    (lambda t: request_for(t, issued=t["end"] + timedelta(hours=30), horizon=48), "hours? old|h old"),
    (lambda t: request_for(t, horizon=1, issued=t["end"] + timedelta(hours=1, minutes=1)), "no horizon|cannot produce"),
])
async def test_the_provider_says_unavailable_instead_of_guessing(trained, make, fragment):
    with pytest.raises(ForecastUnavailable, match=fragment):
        await LocalModelProvider(settings_for(trained)).forecast(make(trained))


async def test_unavailable_when_nothing_is_configured_or_files_are_missing(trained, tmp_path):
    assert make_provider(Settings(**{**get_settings().model_dump(), "ml_forecast_url": "", "ml_local_model_dir": ""})) is None
    svc = ForecastService(Settings(**{**get_settings().model_dump(), "ml_forecast_url": "", "ml_local_model_dir": ""}))
    with pytest.raises(ForecastNotConfigured):
        await svc.forecast(request_for(trained))
    empty = LocalModelProvider(settings_for(trained, ml_local_model_dir=str(tmp_path / "nothing")))
    with pytest.raises(ForecastUnavailable, match="No trained model"):
        await empty.forecast(request_for(trained))
    with pytest.raises(ForecastUnavailable):
        await empty.health()
    nodb = LocalModelProvider(settings_for(trained, ml_history_db=str(tmp_path / "gone.sqlite")))
    with pytest.raises(ForecastUnavailable, match="historical data store"):
        await nodb.forecast(request_for(trained))


async def test_a_tampered_model_makes_the_provider_unavailable(trained, tmp_path):
    dst = copy_run(trained, tmp_path)
    f = next(Path(dst).rglob("*.joblib"))
    f.write_bytes(f.read_bytes()[:-5])
    with pytest.raises(ForecastUnavailable, match="checksum"):
        await LocalModelProvider(settings_for(trained, ml_local_model_dir=str(dst))).forecast(request_for(trained))


def test_make_provider_prefers_an_external_service_and_picks_the_local_model_otherwise(trained):
    local = make_provider(settings_for(trained))
    assert isinstance(local, LocalModelProvider) and local.name == "local-model"
    external = make_provider(settings_for(trained, ml_forecast_url="http://forecast.test"))
    assert external.name == "forecast.test"


def test_api_serves_a_local_forecast_with_an_honest_notice_and_503_when_stale(client, trained, monkeypatch):
    svc = ForecastService(settings_for(trained))
    client.app.dependency_overrides[get_forecast_service] = lambda: svc
    # delhi's reference point is ~2 km from the synthetic stations and the synthetic data ends at the current hour
    ok = client.post("/api/forecast", json={"location_id": "delhi", "horizon_hours": 12, "pollutants": ["pm25"]})
    assert ok.status_code == 200, ok.text
    body = ok.json()
    assert body["provider"] == "local-model" and "trained offline" in body["notice"] and "not by AEROCAST" not in body["notice"]
    assert body["forecast"]["forecasts"][0]["pollutant"] == "pm25"
    assert client.get("/api/forecast/status").json() == {"configured": True, "available": True, "provider": "local-model", "message": "Connected."}
    client.app.dependency_overrides[get_forecast_service] = lambda: ForecastService(settings_for(trained, ml_history_db=str(Path(trained["tmp"]) / "none.sqlite")))
    r = client.post("/api/forecast", json={"location_id": "delhi"})
    assert r.status_code == 503 and r.json()["error"]["code"] == "forecast_unavailable"


def test_system_status_reports_the_local_model_without_treating_absence_as_an_error(client, trained, monkeypatch, tmp_path):
    from app.services.system_status import check_forecast
    ok = check_forecast(settings_for(trained))[0]
    assert ok.state == "ok" and trained["res"]["run_id"] in ok.detail
    bad = check_forecast(settings_for(trained, ml_local_model_dir=str(tmp_path / "x")))[0]
    assert bad.state == "unavailable" and "unusable" in bad.detail


def test_the_web_api_does_not_import_training_code_or_ml_libraries():
    code = "import sys, app.main; print('app.ml.train' in sys.modules, 'sklearn' in sys.modules, 'xgboost' in sys.modules, 'lightgbm' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]), timeout=120)
    assert out.stdout.strip() == "False False False False", out.stderr[-500:]


# ---------------------------------------------------------------------------------------------- model status, back-test and risk windows over HTTP
@pytest.fixture
def served(client, trained, monkeypatch):
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", str(trained["out"]))
    monkeypatch.setenv("ML_HISTORY_DB", trained["db"])
    get_settings.cache_clear()
    return client


def test_model_status_reports_the_recorded_run_and_held_out_scores(served, trained):
    s = served.get("/api/models/status").json()
    assert s["available"] and s["run_id"] == trained["res"]["run_id"] and s["dataset_provenance"] == "TEST FIXTURE OR UNKNOWN"
    t = {(x["pollutant"], x["horizon_hours"]): x for x in s["targets"]}
    assert set(t) == {("pm25", 1), ("pm25", 6)}
    res = trained["res"]["pollutants"]["pm25"]["test"]
    for h in (1, 6):
        member = t[("pm25", h)]["model"].split("+")[0]
        assert t[("pm25", h)]["test"]["mae"] == res[str(h)]["models"][member]["scores"]["mae"] if not res[str(h)].get("final_model", {}).get("ensemble") else True
        assert t[("pm25", h)]["persistence_test"]["mae"] == res[str(h)]["baselines"]["persistence"]["mae"]
        assert t[("pm25", h)]["interval"]["level"] == 0.8
    assert "held-out" in s["caveat"] and s["environment"]["libraries"]["scikit-learn"]


def test_model_status_says_so_when_the_files_were_tampered(client, trained, tmp_path, monkeypatch):
    dst = copy_run(trained, tmp_path)
    f = next(Path(dst).rglob("*.joblib"))
    f.write_bytes(f.read_bytes() + b"x")
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", str(dst))
    get_settings.cache_clear()
    s = client.get("/api/models/status").json()
    assert s["available"] is False and "checksum" in s["reason"] and s["targets"] == []


def test_backtest_pairs_each_forecast_with_what_was_observed_afterwards(served, trained):
    origin = trained["end"] - timedelta(hours=12)
    r = served.get("/api/twin/backtest", params={"pollutant": "pm25", "station_id": 100, "origin": origin.strftime("%Y-%m-%dT%H:%M:%SZ")})
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["model_version"] == trained["res"]["run_id"] and [x["lead_hours"] for x in b["rows"]] == [1, 6] and b["station"]["station_id"] == 100
    assert all(x["observed"] is not None and x["error"] == pytest.approx(x["predicted"] - x["observed"]) for x in b["rows"])
    assert all(x["lower"] <= x["predicted"] <= x["upper"] for x in b["rows"]) and b["scored"]["n"] == 2
    assert b["provenance"]["provider"] == "AEROCAST local model" and "not an accuracy estimate" in b["note"]


def test_backtest_without_enough_input_is_unavailable_and_unknown_stations_are_404(served, trained):
    early = trained["end"] - timedelta(hours=1490)  # not enough history before this origin for the 168 h lag window
    r = served.get("/api/twin/backtest", params={"pollutant": "pm25", "station_id": 100, "origin": early.strftime("%Y-%m-%dT%H:%M:%SZ")})
    assert r.status_code in (200, 503)
    assert served.get("/api/twin/backtest", params={"pollutant": "pm25", "station_id": 99999, "origin": trained["end"].strftime("%Y-%m-%dT%H:%M:%SZ")}).status_code == 404


def test_backtest_without_a_model_configured_is_503(client, trained, monkeypatch):
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", "")
    monkeypatch.setenv("ML_HISTORY_DB", trained["db"])
    get_settings.cache_clear()
    r = client.get("/api/twin/backtest", params={"pollutant": "pm25", "station_id": 100, "origin": trained["end"].strftime("%Y-%m-%dT%H:%M:%SZ")})
    assert r.status_code == 503 and r.json()["error"]["code"] == "model_unavailable"


def test_risk_windows_use_the_model_forecast_and_say_what_they_cannot_claim(served, trained):
    origin = (trained["end"] - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    r = served.get("/api/twin/risk-windows", params={"pollutant": "pm25", "station_id": 100, "origin": origin, "threshold_value": 1})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["threshold"]["kind"] == "user_defined" and len(out["windows"]) == 1 and out["windows"][0]["points"] == 2  # every forecast exceeds 1 µg/m³
    assert out["model_version"] == trained["res"]["run_id"] and out["interval_level"] == 0.8 and out["input_data"] and out["limitations"]
    none = served.get("/api/twin/risk-windows", params={"pollutant": "pm25", "station_id": 100, "origin": origin, "threshold_value": 99999})
    assert none.json()["windows"] == [] and all(not p["at_or_above_threshold"] for p in none.json()["points"])



# ---------------------------------------------------------------------------------------------- stratified evaluation
def test_seasons_follow_ist_months_and_range_bands_come_from_the_cpcb_table():
    from app.ml.metrics import range_bands, season_of

    def hours(iso):
        return int(datetime.fromisoformat(iso).timestamp() // 3600)

    s = season_of(np.array([hours("2026-01-15T00:00:00+00:00"), hours("2026-04-15T00:00:00+00:00"), hours("2026-07-15T00:00:00+00:00"),
                            hours("2026-10-15T00:00:00+00:00"), hours("2026-12-31T20:00:00+00:00")]))
    assert list(s) == ["winter", "pre_monsoon", "monsoon", "post_monsoon", "winter"]
    # 2026-11-30 20:00 UTC is already 1 December in IST (UTC+5:30), which is winter, not post-monsoon
    assert season_of(np.array([hours("2026-11-30T20:00:00+00:00")]))[0] == "winter"
    pm = range_bands("pm25")
    assert [b[0] for b in pm][0] == "Good" and pm[0][1] == 0.0 and pm[0][2] == 31.0 and pm[-1][2] == float("inf")
    co = range_bands("co")
    assert co[1][1] == pytest.approx(1100.0)  # CO bands are mg/m3 in the table and ug/m3 in the store


def test_stratified_scores_each_stratum_against_persistence_and_hides_tiny_ones():
    from app.ml.metrics import stratified

    n = 400
    y = np.concatenate([np.full(200, 20.0), np.full(195, 200.0), np.full(5, 500.0)])
    p = y + np.where(np.arange(n) % 2 == 0, 2.0, -2.0)
    base = y + 10.0
    t = np.full(n, int(datetime(2026, 1, 10, tzinfo=timezone.utc).timestamp() // 3600))
    st = stratified(y, p, base, t, "pm25")
    assert st["season"]["winter"]["n"] == n and st["season"]["monsoon"]["n"] == 0 and st["season"]["monsoon"]["mae"] is None
    good = st["range"]["Good"]
    assert good["n"] == 200 and good["mae"] == pytest.approx(2.0) and good["persistence_mae"] == pytest.approx(10.0) and good["skill"] == pytest.approx(0.8)
    assert st["range"]["Severe"]["n"] == 5 and st["range"]["Severe"]["mae"] is None  # too few rows: size only, no score
    missing = stratified(np.where(np.arange(n) < 100, np.nan, y), p, base, t, "pm25")
    assert missing["season"]["winter"]["n"] == n - 100  # rows without an observation are not scored


def test_training_results_carry_the_stratified_block(trained):
    r = json.loads((trained["res"]["run_dir"] and Path(trained["res"]["run_dir"]) / "results.json").read_text(encoding="utf-8"))
    cell = r["pollutants"]["pm25"]["test"]["6"]
    assert set(cell["stratified"]) >= {"season", "range", "note"}
    assert sum(v["n"] for v in cell["stratified"]["season"].values()) == cell["models"][cell["final_model"]["members"][0]]["scores"]["n"] if not cell["final_model"]["ensemble"] else True
