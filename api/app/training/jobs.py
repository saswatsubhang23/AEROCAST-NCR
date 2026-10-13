"""One-click model training, run entirely on this machine.

A job is a fixed sequence of the project's own command-line steps, started as a separate process so that training libraries never load
into the web API and a crash cannot take it down:

    preflight -> discover -> ingest-air -> ingest-weather -> clean -> features -> train -> report

The first five (everything up to `features`) are the optional "refresh with the newest data" part. Nothing here calls a language model
or any Claude API: it is Python, scikit-learn, XGBoost and LightGBM on the local store, so it costs no tokens.

Safety rules
  * Only validated options are accepted (preset name, pollutant and horizon allow-lists, one boolean). No caller-supplied command or path is
    ever executed; arguments are assembled here from constants and checked values.
  * One job at a time. A job writes to its own candidate folder and never touches the active model.
  * Activating a candidate is a separate, explicit action: the run is loaded (which verifies every checksum and library version) before its
    folder is copied and the registry pointer is switched atomically; the previous pointer is kept for rollback.
  * Job state and the log are persisted, so a restart of the API shows what happened; a job that was running when the process died is
    marked "interrupted", never "running".
"""

import json
import logging
import os
import re
import secrets
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

logger = logging.getLogger("app.training")

API_DIR = Path(__file__).resolve().parents[2]
PRESETS = {"standard": "app/ml/configs/real_v2.json", "quick": "app/ml/configs/quick.json"}
ALLOWED_POLLUTANTS = ["pm25", "pm10", "no2", "so2", "o3"]
ALLOWED_HORIZONS = [1, 3, 6, 12, 24, 48, 72]
MIN_FREE_GB = 3.0
JOB_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")
REFRESH_OVERLAP_DAYS = 10  # re-fetch this far back: providers revise recent hours
STEP_LABELS = {
    "preflight": "Check the data store and disk space",
    "discover": "Find new monitoring sensors",
    "ingest-air": "Download the newest air-quality hours (OpenAQ)",
    "ingest-weather": "Download the newest weather (Open-Meteo archive)",
    "clean": "Standardise units, flag quality problems",
    "features": "Build lagged and rolling features",
    "train": "Train and validate the models",
    "report": "Write the comparison report",
}


class TrainingError(Exception):
    def __init__(self, message: str, code: str = "invalid_request", status: int = 422):
        super().__init__(message)
        self.message, self.code, self.status = message, code, status


@dataclass
class StepState:
    name: str
    label: str
    status: str = "pending"  # pending | running | ok | failed | skipped | cancelled
    started_at: str | None = None
    finished_at: str | None = None
    returncode: int | None = None
    detail: str | None = None


@dataclass
class JobState:
    job_id: str
    created_at: str
    options: dict
    status: str = "queued"  # queued | running | completed | failed | cancelled | interrupted
    steps: list[StepState] = field(default_factory=list)
    started_at: str | None = None
    finished_at: str | None = None
    candidate_root: str | None = None
    run_id: str | None = None
    error: str | None = None
    activated: bool = False
    notes: list[str] = field(default_factory=list)


def _iso(t: datetime | None = None) -> str:
    return (t or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def validate_options(preset: str, refresh_data: bool, pollutants: list[str] | None, horizons: list[int] | None) -> dict:
    if preset not in PRESETS:
        raise TrainingError(f"preset must be one of {', '.join(PRESETS)}")
    if pollutants is not None:
        if not pollutants or any(p not in ALLOWED_POLLUTANTS for p in pollutants) or len(set(pollutants)) != len(pollutants):
            raise TrainingError(f"pollutants must be a non-empty, non-repeating subset of {', '.join(ALLOWED_POLLUTANTS)}")
    if horizons is not None:
        if not horizons or any(h not in ALLOWED_HORIZONS for h in horizons) or len(set(horizons)) != len(horizons):
            raise TrainingError(f"horizons must be a non-empty, non-repeating subset of {ALLOWED_HORIZONS}")
    return {"preset": preset, "refresh_data": bool(refresh_data), "pollutants": pollutants, "horizons": sorted(horizons) if horizons else None}


class TrainingManager:
    def __init__(self, data_dir: str | Path, model_dir: str | Path, history_db: str | Path | None = None, api_dir: Path = API_DIR,
                 python: str | None = None, step_commands=None, now=None):
        self.data_dir = Path(data_dir)
        self.model_dir = Path(model_dir)
        self.history_db = Path(history_db) if history_db else self.data_dir / "history.sqlite"
        self.jobs_dir = self.data_dir / "training_jobs"
        self.candidates_dir = self.data_dir / "models_candidates"
        self.api_dir = api_dir
        self.python = python or sys.executable
        self._step_commands = step_commands  # tests substitute harmless commands; production uses the project's own CLI
        self._lock = threading.Lock()
        self._procs: dict[str, subprocess.Popen] = {}
        self._cancel: set[str] = set()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._mark_interrupted()

    # ------------------------------------------------------------------------------------------ persistence
    def _path(self, job_id: str) -> Path:
        if not JOB_ID.match(job_id):
            raise TrainingError("invalid job id")
        return self.jobs_dir / job_id

    def _save(self, job: JobState) -> None:
        d = self._path(job.job_id)
        d.mkdir(parents=True, exist_ok=True)
        tmp = d / "job.json.tmp"
        tmp.write_text(json.dumps(asdict(job), indent=1), encoding="utf-8")
        for attempt in range(40):  # on Windows the replace fails while a reader has the file open; readers are brief, so retry
            try:
                os.replace(tmp, d / "job.json")
                return
            except PermissionError:
                time.sleep(0.05)
        os.replace(tmp, d / "job.json")

    def load(self, job_id: str) -> JobState | None:
        p = self._path(job_id) / "job.json"
        if not p.exists():
            return None
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            raw["steps"] = [StepState(**s) for s in raw.get("steps", [])]
            return JobState(**raw)
        except (OSError, ValueError, TypeError):
            return None

    def list_jobs(self, limit: int = 20) -> list[JobState]:
        if not self.jobs_dir.exists():
            return []
        ids = sorted((d.name for d in self.jobs_dir.iterdir() if d.is_dir() and JOB_ID.match(d.name)), reverse=True)[:limit]
        return [j for j in (self.load(i) for i in ids) if j]

    def _mark_interrupted(self) -> None:
        for j in self.list_jobs(50):
            if j.status in ("queued", "running"):
                j.status = "interrupted"
                j.error = "The API stopped while this job was running; the partial output was kept but the job did not finish."
                j.finished_at = _iso(self._now())
                for s in j.steps:
                    if s.status == "running":
                        s.status = "failed"
                        s.detail = "interrupted"
                self._save(j)

    def active(self) -> JobState | None:
        for j in self.list_jobs(5):
            if j.status in ("queued", "running"):
                return j
        return None

    def log_tail(self, job_id: str, lines: int = 200) -> str:
        p = self._path(job_id) / "log.txt"
        if not p.exists():
            return ""
        size = p.stat().st_size
        with p.open("rb") as f:
            f.seek(max(0, size - 64_000))
            data = f.read().decode("utf-8", errors="replace")
        return "\n".join(data.splitlines()[-max(1, min(lines, 1000)):])

    # ------------------------------------------------------------------------------------------ readiness
    def readiness(self) -> dict:
        info: dict = {"store_exists": self.history_db.exists(), "latest_observation": None, "latest_weather": None, "feature_set": None, "ingest_runs": [], "free_disk_gb": None}
        try:
            info["free_disk_gb"] = round(shutil.disk_usage(self.data_dir).free / 1e9, 1)
        except OSError:
            pass
        if not self.history_db.exists():
            return info
        from app.history.store import HistoryStore

        try:
            st = HistoryStore(self.history_db, read_only=True)
            info["latest_observation"] = (st.query("select max(label_utc) m from clean_air")[0]["m"])
            info["latest_weather"] = (st.query("select max(time_utc) m from clean_weather")[0]["m"])
            fs = st.query("select name, created_at, rows, digest, params from feature_sets order by created_at desc limit 1")
            if fs:
                info["feature_set"] = {"name": fs[0]["name"], "created_at": fs[0]["created_at"], "rows": fs[0]["rows"], "digest": fs[0]["digest"]}
            info["ingest_runs"] = [dict(r) for r in st.query("select run_id, kind, started_at, finished_at, status, rows_added from ingest_runs order by started_at desc limit 6")]
            st.close()
        except Exception as exc:  # noqa: BLE001 - reported, not raised: the page must still open
            info["error"] = f"{type(exc).__name__}: the history store could not be read"
        return info

    # ------------------------------------------------------------------------------------------ steps
    def _window(self) -> tuple[str, str]:
        latest = self.readiness().get("latest_observation")
        base = datetime.fromisoformat(latest.replace("Z", "+00:00")) if latest else self._now() - timedelta(days=30)
        start = (base - timedelta(days=REFRESH_OVERLAP_DAYS)).date().isoformat()
        end = (self._now() + timedelta(days=1)).date().isoformat()
        return start, end

    def build_steps(self, job: JobState) -> list[tuple[str, list[str]]]:
        """(step name, argv) in order. Arguments come from constants and validated options only."""
        o = job.options
        py = [self.python, "-u", "-m"]
        steps: list[tuple[str, list[str]]] = [("preflight", [])]
        pols = o.get("pollutants") or (["pm25"] if o["preset"] == "quick" else ["pm25", "pm10", "no2", "o3"])
        if o["refresh_data"]:
            start, end = self._window()
            steps += [
                ("discover", [*py, "app.history", "discover", "--from", start, "--to", end]),
                ("ingest-air", [*py, "app.history", "ingest-air", "--from", start, "--to", end, "--rate", "45", "--concurrency", "7"]),
                ("ingest-weather", [*py, "app.history", "ingest-weather", "--from", start, "--to", end]),
                ("clean", [*py, "app.history", "clean"]),
                ("features", [*py, "app.history", "features", "--pollutants", ",".join(pols)]),
            ]
        train = [*py, "app.ml", "train", "--config", PRESETS[o["preset"]], "--out", str(self.candidates_dir / job.job_id)]
        if o.get("pollutants"):
            train += ["--pollutants", ",".join(o["pollutants"])]
        if o.get("horizons"):
            train += ["--horizons", ",".join(str(h) for h in o["horizons"])]
        steps.append(("train", train))
        steps.append(("report", [*py, "app.ml", "report", "--run", str(self.candidates_dir / job.job_id), "--out", str(self._path(job.job_id) / "report.md")]))
        if self._step_commands:
            steps = self._step_commands(job, steps)
        return steps

    # ------------------------------------------------------------------------------------------ run
    def start(self, preset: str = "standard", refresh_data: bool = True, pollutants: list[str] | None = None, horizons: list[int] | None = None) -> JobState:
        options = validate_options(preset, refresh_data, pollutants, horizons)
        with self._lock:
            if any(j.status in ("queued", "running") for j in self.list_jobs(10)):
                raise TrainingError("A training job is already running. Wait for it or cancel it first.", "job_running", 409)
            if not self.history_db.exists():
                raise TrainingError("There is no historical store to train on. Build it with python -m app.history all.", "no_data", 503)
            job = JobState(job_id=f"{self._now().strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}", created_at=_iso(self._now()), options=options)
            job.candidate_root = str(self.candidates_dir / job.job_id)
            job.steps = [StepState(n, STEP_LABELS[n]) for n, _ in self.build_steps(job)]
            job.notes = [
                "Runs on this computer with the project's own scripts. No language model and no Claude tokens are involved.",
                "The active model is not changed until you press Activate on a finished job.",
            ]
            self._save(job)
        threading.Thread(target=self._run, args=(job.job_id,), name=f"training-{job.job_id}", daemon=True).start()
        return job

    def cancel(self, job_id: str) -> JobState:
        job = self.load(job_id)
        if job is None:
            raise TrainingError("No such job.", "not_found", 404)
        if job.status not in ("queued", "running"):
            raise TrainingError("That job is not running.", "not_running", 409)
        self._cancel.add(job_id)
        proc = self._procs.get(job_id)
        if proc and proc.poll() is None:
            self._kill_tree(proc)
        return job

    @staticmethod
    def _kill_tree(proc: subprocess.Popen) -> None:
        try:
            import psutil

            parent = psutil.Process(proc.pid)
            for c in parent.children(recursive=True):
                c.kill()
            parent.kill()
        except Exception:  # noqa: BLE001
            proc.kill()

    def _preflight(self, job: JobState) -> str | None:
        try:
            free = shutil.disk_usage(self.data_dir).free / 1e9
        except OSError:
            free = 0.0
        if free < MIN_FREE_GB:
            return f"Only {free:.1f} GB of disk space is free; at least {MIN_FREE_GB:g} GB is needed for features and artifacts."
        if job.options["refresh_data"] and not os.environ.get("AQ_API_KEY") and not self._env_has_key():
            return "AQ_API_KEY is not configured, so newer air-quality data cannot be downloaded. Turn off the data refresh or add the key to api/.env."
        return None

    def _env_has_key(self) -> bool:
        try:
            env = (self.api_dir / ".env").read_text(encoding="utf-8")
        except OSError:
            return False
        return any(line.strip().startswith("AQ_API_KEY=") and line.split("=", 1)[1].strip() for line in env.splitlines())

    def _run(self, job_id: str) -> None:
        job = self.load(job_id)
        if job is None:
            return
        job.status, job.started_at = "running", _iso(self._now())
        self._save(job)
        log_path = self._path(job_id) / "log.txt"
        steps = dict(self.build_steps(job))
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        try:
            with log_path.open("ab") as log:
                for st in job.steps:
                    if job_id in self._cancel:
                        st.status = "cancelled"
                        continue
                    st.status, st.started_at = "running", _iso(self._now())
                    self._save(job)
                    log.write(f"\n=== {st.label} ({st.name}) {st.started_at} ===\n".encode())
                    log.flush()
                    if st.name == "preflight":
                        problem = self._preflight(job)
                        st.status, st.finished_at, st.returncode = ("failed", _iso(self._now()), 1) if problem else ("ok", _iso(self._now()), 0)
                        st.detail = problem
                        if problem:
                            job.error = problem
                            break
                        continue
                    argv = steps[st.name]
                    proc = subprocess.Popen(argv, cwd=str(self.api_dir), stdout=log, stderr=subprocess.STDOUT, env=env,
                                            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
                    self._procs[job_id] = proc
                    while proc.poll() is None:
                        time.sleep(0.5)
                        if job_id in self._cancel:
                            self._kill_tree(proc)
                            break
                    rc = proc.wait()
                    self._procs.pop(job_id, None)
                    st.returncode, st.finished_at = rc, _iso(self._now())
                    if job_id in self._cancel:
                        st.status = "cancelled"
                        break
                    if rc != 0:
                        st.status = "failed"
                        st.detail = f"exit code {rc}; see the log"
                        job.error = f"The step '{st.label}' failed (exit code {rc})."
                        break
                    st.status = "ok"
                    self._save(job)
        except Exception as exc:  # noqa: BLE001
            job.error = f"{type(exc).__name__}: {exc}"
            logger.exception("training job failed")
        finally:
            for st in job.steps:
                if st.status in ("pending",):
                    st.status = "skipped" if not (job_id in self._cancel) else "cancelled"
            job.finished_at = _iso(self._now())
            if job_id in self._cancel:
                job.status = "cancelled"
            elif job.error or any(s.status == "failed" for s in job.steps):
                job.status = "failed"
            else:
                job.status = "completed"
                job.run_id = self._candidate_run_id(job)
                if job.run_id is None:
                    job.status, job.error = "failed", "Training finished but no model run was saved."
            self._cancel.discard(job_id)
            self._save(job)

    def _candidate_run_id(self, job: JobState) -> str | None:
        p = Path(job.candidate_root or "") / "latest.json"
        try:
            return json.loads(p.read_text(encoding="utf-8"))["run_id"]
        except (OSError, ValueError, KeyError):
            return None

    # ------------------------------------------------------------------------------------------ activation
    def activate(self, job_id: str) -> dict:
        job = self.load(job_id)
        if job is None:
            raise TrainingError("No such job.", "not_found", 404)
        if job.status != "completed" or not job.run_id:
            raise TrainingError("Only a completed job with a saved model can be activated.", "not_ready", 409)
        from app.ml.artifacts import ModelUnavailable, load_run

        src_root = Path(job.candidate_root or "")
        try:
            run = load_run(src_root)  # verifies every checksum and the library versions before anything is copied
        except ModelUnavailable as exc:
            raise TrainingError(f"The candidate model cannot be loaded: {exc.message}", "invalid_model", 422) from None
        dest = self.model_dir / run.run_id
        self.model_dir.mkdir(parents=True, exist_ok=True)
        if not dest.exists():
            shutil.copytree(run.path, dest)
        pointer = self.model_dir / "latest.json"
        previous = None
        if pointer.exists():
            try:
                previous = json.loads(pointer.read_text(encoding="utf-8")).get("run_id")
            except (OSError, ValueError):
                previous = None
        if previous and previous != run.run_id:
            (self.model_dir / "previous.json").write_text(json.dumps({"run_id": previous, "replaced_at": _iso(self._now())}), encoding="utf-8")
        tmp = self.model_dir / "latest.json.tmp"
        tmp.write_text(json.dumps({"run_id": run.run_id}), encoding="utf-8")
        os.replace(tmp, pointer)  # atomic: readers see the old or the new pointer, never half of one
        job.activated = True
        self._save(job)
        return {"activated": run.run_id, "previous": previous}

    def rollback(self) -> dict:
        prev = self.model_dir / "previous.json"
        if not prev.exists():
            raise TrainingError("There is no earlier model to return to.", "no_previous", 409)
        run_id = json.loads(prev.read_text(encoding="utf-8")).get("run_id")
        if not isinstance(run_id, str) or not (self.model_dir / run_id / "manifest.json").exists():
            raise TrainingError("The earlier model's files are no longer present.", "no_previous", 409)
        cur = None
        pointer = self.model_dir / "latest.json"
        if pointer.exists():
            cur = json.loads(pointer.read_text(encoding="utf-8")).get("run_id")
        tmp = self.model_dir / "latest.json.tmp"
        tmp.write_text(json.dumps({"run_id": run_id}), encoding="utf-8")
        os.replace(tmp, pointer)
        if cur and cur != run_id:
            prev.write_text(json.dumps({"run_id": cur, "replaced_at": _iso(self._now())}), encoding="utf-8")
        return {"activated": run_id, "previous": cur}
