"""One-click training: validated options, one job at a time, cancel, failure handling, persistence, and explicit activation with rollback.

The step commands are replaced by harmless Python one-liners; real artifacts for the activation tests come from a tiny fixture training."""

import json
import sys
import time
from pathlib import Path

import pytest
from mlfakes import make_history

from app.core.config import get_settings
from app.ml.config import MlConfig
from app.ml.train import run_experiment
from app.training.jobs import JOB_ID, PRESETS, TrainingError, TrainingManager, validate_options

PY = sys.executable


def stubs(plan):
    """plan: step name -> python source for `python -c`. Steps not named in the plan succeed instantly."""
    def build(job, steps):
        out = []
        for name, argv in steps:
            if name == "preflight":
                out.append((name, argv))
            else:
                src = plan.get(name, "print('ok')").replace("{root}", (job.candidate_root or "").replace("\\", "/"))
                out.append((name, [PY, "-c", src]))
        return out
    return build


def wait(mgr, job_id, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        j = mgr.load(job_id)
        if j and j.status not in ("queued", "running"):
            return j
        time.sleep(0.1)
    raise AssertionError("job did not finish")


@pytest.fixture
def env(tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    (data / "history.sqlite").write_bytes(b"")  # exists; the step commands are stubbed so it is never opened for training
    return {"data": data, "models": data / "models"}


def manager(env, plan=None, **kw):
    return TrainingManager(env["data"], env["models"], history_db=env["data"] / "history.sqlite", api_dir=Path(env["data"]).parent,
                           step_commands=stubs(plan or {}), **kw)


# ---------------------------------------------------------------------------------------------- options
def test_options_are_checked_against_allow_lists():
    ok = validate_options("quick", True, ["pm25", "no2"], [6, 1])
    assert ok["horizons"] == [1, 6]
    for bad in (
        dict(preset="evil.json", refresh_data=True, pollutants=None, horizons=None),
        dict(preset="quick", refresh_data=True, pollutants=["pm25; rm -rf /"], horizons=None),
        dict(preset="quick", refresh_data=True, pollutants=["co"], horizons=None),
        dict(preset="quick", refresh_data=True, pollutants=[], horizons=None),
        dict(preset="quick", refresh_data=True, pollutants=None, horizons=[5]),
        dict(preset="quick", refresh_data=True, pollutants=["pm25", "pm25"], horizons=None),
    ):
        with pytest.raises(TrainingError):
            validate_options(**bad)
    assert set(PRESETS) == {"standard", "quick"}


def test_commands_are_assembled_from_constants_and_validated_values_only(env):
    mgr = TrainingManager(env["data"], env["models"], history_db=env["data"] / "history.sqlite", api_dir=env["data"].parent)
    mgr.jobs_dir.mkdir(parents=True, exist_ok=True)
    job = type("J", (), {"job_id": "20261010T120000Z-abc123", "options": validate_options("standard", True, ["pm25"], [1, 6])})()
    names = [n for n, _ in mgr.build_steps(job)]
    assert names == ["preflight", "discover", "ingest-air", "ingest-weather", "clean", "features", "train", "report"]
    train = dict(mgr.build_steps(job))["train"]
    assert train[:4] == [mgr.python, "-u", "-m", "app.ml"]
    assert str(mgr.candidates_dir) in train[train.index("--out") + 1]
    assert train[train.index("--pollutants") + 1] == "pm25" and train[train.index("--horizons") + 1] == "1,6"
    no_refresh = type("J", (), {"job_id": job.job_id, "options": validate_options("quick", False, None, None)})()
    assert [n for n, _ in mgr.build_steps(no_refresh)] == ["preflight", "train", "report"]


# ---------------------------------------------------------------------------------------------- running
def test_a_successful_job_records_steps_log_and_candidate(env):
    plan = {"train": "import json,pathlib; r=pathlib.Path(r'{root}'); r.mkdir(parents=True, exist_ok=True); (r/'latest.json').write_text(json.dumps({'run_id':'abc123'})); print('[pm25] tune random_forest done')"}
    mgr = manager(env, plan)
    job = mgr.start("quick", refresh_data=True)
    j = wait(mgr, job.job_id)
    assert j.status == "completed" and j.run_id == "abc123" and j.error is None
    assert [s.name for s in j.steps] == ["preflight", "discover", "ingest-air", "ingest-weather", "clean", "features", "train", "report"]
    assert all(s.status == "ok" for s in j.steps) and j.finished_at and j.started_at
    assert "[pm25] tune random_forest done" in mgr.log_tail(j.job_id)
    assert mgr.list_jobs()[0].job_id == job.job_id
    assert j.activated is False  # finishing never changes the active model


def test_candidate_run_is_required_for_success(env):
    mgr = manager(env)
    j = wait(mgr, mgr.start("quick", refresh_data=False).job_id)
    assert j.status == "failed" and "no model run was saved" in (j.error or "")


def test_a_failing_step_stops_the_job_and_skips_the_rest(env):
    mgr = manager(env, {"ingest-air": "import sys; print('boom'); sys.exit(3)"})
    j = wait(mgr, mgr.start("quick", refresh_data=True).job_id)
    by = {s.name: s for s in j.steps}
    assert j.status == "failed" and by["ingest-air"].status == "failed" and by["ingest-air"].returncode == 3
    assert by["discover"].status == "ok" and by["clean"].status == "skipped" and by["train"].status == "skipped"
    assert "boom" in mgr.log_tail(j.job_id)
    assert "ingest-air" in (j.error or "") or "air-quality" in (j.error or "")


def test_only_one_job_runs_at_a_time_and_a_running_job_can_be_cancelled(env):
    mgr = manager(env, {"train": "import time; time.sleep(60)"})
    a = mgr.start("quick", refresh_data=False)
    time.sleep(1.0)
    with pytest.raises(TrainingError) as e:
        mgr.start("quick", refresh_data=False)
    assert e.value.status == 409 and e.value.code == "job_running"
    assert mgr.active().job_id == a.job_id
    t = time.time()
    mgr.cancel(a.job_id)
    j = wait(mgr, a.job_id, 15)
    assert j.status == "cancelled" and time.time() - t < 12
    assert mgr.active() is None
    with pytest.raises(TrainingError):
        mgr.cancel(a.job_id)  # not running any more


def test_a_job_left_running_by_a_dead_process_is_marked_interrupted(env):
    mgr = manager(env)
    jid = "20261010T120000Z-aaaaaa"
    d = mgr.jobs_dir / jid
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({
        "job_id": jid, "created_at": "2026-10-10T12:00:00Z", "options": {}, "status": "running",
        "steps": [{"name": "train", "label": "x", "status": "running"}],
    }), encoding="utf-8")
    again = manager(env)
    j = again.load(jid)
    assert j.status == "interrupted" and j.steps[0].status == "failed" and again.active() is None


def test_start_refuses_without_a_historical_store(tmp_path):
    mgr = TrainingManager(tmp_path / "d", tmp_path / "m", api_dir=tmp_path, step_commands=stubs({}))
    with pytest.raises(TrainingError) as e:
        mgr.start("quick", refresh_data=False)
    assert e.value.status == 503


def test_job_ids_are_validated_before_touching_the_filesystem(env):
    mgr = manager(env)
    for bad in ("../../etc", "x", "20261010T120000Z-ZZZZZZ", ""):
        with pytest.raises(TrainingError):
            mgr.load(bad)
    assert JOB_ID.match("20261010T120000Z-0a1b2c")


# ---------------------------------------------------------------------------------------------- activation and rollback (real artifacts)
@pytest.fixture(scope="module")
def candidate(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("cand")
    store, _ = make_history(str(tmp / "h.sqlite"), hours=700, stations=4)
    cfg = MlConfig(pollutants=["pm25"], horizons=[1], models=["random_forest"], n_folds=2, fold_frac=0.12, test_frac=0.2, tune_horizon=1,
                   max_train_rows={"random_forest": 1500}, max_eval_rows=800, n_jobs=2, location_experiment_horizons=[1], min_train_rows=100,
                   ensemble_min_gain=0.0, allow_test_fixtures=True)
    res = run_experiment(store, cfg, str(tmp / "cand_root"), log=lambda m: None)
    return {"root": tmp / "cand_root", "run_id": res["run_id"]}


def completed_job(mgr, candidate_root, run_id, jid="20261010T120000Z-bbbbbb"):
    d = mgr.jobs_dir / jid
    d.mkdir(parents=True, exist_ok=True)
    (d / "job.json").write_text(json.dumps({
        "job_id": jid, "created_at": "2026-10-10T12:00:00Z", "options": {"preset": "quick"}, "status": "completed", "steps": [],
        "candidate_root": str(candidate_root), "run_id": run_id,
    }), encoding="utf-8")
    return jid


def test_activation_verifies_copies_and_switches_atomically_then_rolls_back(env, candidate):
    mgr = manager(env)
    jid = completed_job(mgr, candidate["root"], candidate["run_id"])
    out = mgr.activate(jid)
    assert out == {"activated": candidate["run_id"], "previous": None}
    assert json.loads((env["models"] / "latest.json").read_text())["run_id"] == candidate["run_id"]
    assert (env["models"] / candidate["run_id"] / "manifest.json").exists()
    assert mgr.load(jid).activated is True
    # a damaged candidate must be refused, and the active model must not change
    import shutil

    other = env["data"] / "cand2"
    shutil.copytree(candidate["root"], other)
    run_dir = other / candidate["run_id"]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    victim = next(rel for rel in manifest["files"] if rel.endswith((".joblib", ".pkl", ".json")) and rel != "manifest.json")
    with (run_dir / victim).open("ab") as f:
        f.write(b" tampered")
    j2 = completed_job(mgr, other, candidate["run_id"], "20261010T130000Z-cccccc")
    with pytest.raises(TrainingError) as e:
        mgr.activate(j2)
    assert e.value.code == "invalid_model" and e.value.status == 422
    assert json.loads((env["models"] / "latest.json").read_text())["run_id"] == candidate["run_id"]
    assert mgr.load(j2).activated is False


def test_only_completed_jobs_with_a_run_can_be_activated(env):
    mgr = manager(env)
    d = mgr.jobs_dir / "20261010T140000Z-dddddd"
    d.mkdir(parents=True)
    (d / "job.json").write_text(json.dumps({"job_id": "20261010T140000Z-dddddd", "created_at": "x", "options": {}, "status": "failed", "steps": []}), encoding="utf-8")
    with pytest.raises(TrainingError) as e:
        mgr.activate("20261010T140000Z-dddddd")
    assert e.value.status == 409
    with pytest.raises(TrainingError):
        mgr.rollback()  # nothing to return to


# ---------------------------------------------------------------------------------------------- HTTP
def test_http_api_validates_and_reports(client, env, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(env["data"]))
    monkeypatch.setenv("ML_LOCAL_MODEL_DIR", str(env["models"]))
    monkeypatch.setenv("ML_HISTORY_DB", str(env["data"] / "history.sqlite"))
    get_settings.cache_clear()
    from app.api.training import get_training_manager

    get_training_manager.cache_clear()
    h = {"X-AEROCAST-Action": "training"}
    bad = client.post("/api/training/jobs", json={"preset": "quick", "pollutants": ["pm25; drop table"]}, headers=h)
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_request"
    st = client.get("/api/training/status")
    assert st.status_code == 200 and st.json()["active_job"] is None and "no Claude tokens" in " ".join(st.json()["notes"])
    assert st.json()["options"]["presets"] == ["standard", "quick"]
    assert client.get("/api/training/jobs/20261010T120000Z-eeeeee").status_code == 404
    assert client.get("/api/training/jobs/../secret").status_code in (404, 422)
    assert client.post("/api/training/rollback", headers=h).status_code == 409
    get_training_manager.cache_clear()


@pytest.mark.parametrize("path", ["/api/training/jobs", "/api/training/jobs/20261010T120000Z-eeeeee/cancel",
                                  "/api/training/jobs/20261010T120000Z-eeeeee/activate", "/api/training/rollback"])
def test_state_changing_training_calls_need_the_action_header(client, path):
    """Without the header (what a cross-site form or image tag would send) nothing is started, cancelled or activated."""
    for headers in (None, {"X-AEROCAST-Action": "wrong"}):
        r = client.post(path, json={"preset": "quick"}, headers=headers)
        assert r.status_code == 403 and r.json()["error"]["code"] == "missing_action_header"
    # reads stay open
    assert client.get("/api/training/status").status_code == 200
