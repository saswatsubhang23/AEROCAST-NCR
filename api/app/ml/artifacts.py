"""Saving and loading trained models together with everything needed to reproduce and audit them.

A run directory contains: config.json, feature_schema.json, environment.json, intervals.json, results.json, manifest.json and
models/<pollutant>_h<H>.joblib. `manifest.json` holds the SHA-256 of every other file; loading refuses a run whose files do
not match (a tampered or truncated artifact is never unpickled), whose library versions differ from the training
environment, or that lacks a required file. Pickles are only ever read from a directory the operator configured.
"""

import hashlib
import importlib.metadata as md
import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import joblib

LIBS = ["numpy", "scipy", "scikit-learn", "xgboost", "lightgbm", "joblib", "psutil"]
MODEL_LIBS = {"random_forest": "scikit-learn", "svr": "scikit-learn", "xgboost": "xgboost", "lightgbm": "lightgbm"}


class ModelUnavailable(Exception):
    """No usable trained model: nothing was trained, files are missing or damaged, or the environment does not match."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def environment() -> dict:
    versions = {}
    for lib in LIBS:
        try:
            versions[lib] = md.version(lib)
        except md.PackageNotFoundError:
            versions[lib] = None
    return {"python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(), "libraries": versions}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False, default=str), encoding="utf-8")


def save_run(root: str | Path, run_id: str, *, config_json: str, schema: dict, models: list[dict], intervals: dict, results: dict,
             data_digest: str | None) -> Path:
    """`models` items: {pollutant, horizon, members: [{name, params, estimator}, ...]}; several members are averaged (an ensemble
    that was adopted on validation evidence). Returns the run directory."""
    run = Path(root) / run_id
    (run / "models").mkdir(parents=True, exist_ok=True)
    (run / "config.json").write_text(config_json, encoding="utf-8")
    _write_json(run / "feature_schema.json", schema)
    _write_json(run / "environment.json", environment())
    _write_json(run / "intervals.json", intervals)
    _write_json(run / "results.json", results)
    entries = []
    for m in models:
        for i, mem in enumerate(m["members"]):
            rel = f"models/{m['pollutant']}_h{m['horizon']}_{i}_{mem['name']}.joblib"
            joblib.dump(mem["estimator"], run / rel, compress=3)
            entries.append({"pollutant": m["pollutant"], "horizon": m["horizon"], "member": i, "name": mem["name"], "params": mem["params"], "file": rel})
    files = {rel: sha256_file(run / rel) for rel in ["config.json", "feature_schema.json", "environment.json", "intervals.json", "results.json"]
             + [e["file"] for e in entries]}
    _write_json(run / "manifest.json", {"run_id": run_id, "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                        "data_digest": data_digest, "files": files, "models": entries})
    _write_json(Path(root) / "latest.json", {"run_id": run_id})
    return run


@dataclass
class LoadedRun:
    run_id: str
    path: Path
    manifest: dict
    schema: dict
    intervals: dict
    results: dict
    environment: dict
    estimators: dict = field(default_factory=dict)  # (pollutant, horizon) -> list of fitted estimators (averaged)

    def horizons(self, pollutant: str) -> list[int]:
        return sorted(h for (p, h) in self.estimators if p == pollutant)


def resolve_run_dir(root: str | Path) -> Path:
    root = Path(root)
    if (root / "manifest.json").exists():
        return root
    latest = root / "latest.json"
    if not latest.exists():
        raise ModelUnavailable("No trained model is available: no run has been saved in the model directory.")
    try:
        run_id = json.loads(latest.read_text(encoding="utf-8"))["run_id"]
    except (ValueError, KeyError) as exc:
        raise ModelUnavailable("The model registry file (latest.json) is damaged.") from exc
    if not isinstance(run_id, str) or not run_id.replace("-", "").replace("_", "").isalnum():
        raise ModelUnavailable("The model registry file (latest.json) names an invalid run.")
    return root / run_id


_RUN_CACHE: dict[str, tuple[tuple, "LoadedRun"]] = {}


def load_run(root: str | Path) -> "LoadedRun":
    """Loading verifies every artifact checksum and deserialises every estimator (seconds, hundreds of MB), so a loaded run is reused
    until the run pointer or its manifest changes on disk. Failures are never cached."""
    root_p = Path(root)
    run = resolve_run_dir(root_p)
    pointer = root_p / "latest.json"
    stamp = (str(run), pointer.stat().st_mtime_ns if pointer.exists() else -1, (run / "manifest.json").stat().st_mtime_ns if (run / "manifest.json").exists() else -1)
    key = str(root_p.resolve())
    hit = _RUN_CACHE.get(key)
    if hit and hit[0] == stamp:
        return hit[1]
    loaded = _load_run_uncached(root_p)
    _RUN_CACHE[key] = (stamp, loaded)
    return loaded


def _load_run_uncached(root: str | Path) -> LoadedRun:
    run = resolve_run_dir(root)
    mf = run / "manifest.json"
    if not mf.exists():
        raise ModelUnavailable("The trained model's manifest is missing.")
    try:
        manifest = json.loads(mf.read_text(encoding="utf-8"))
        files, entries = manifest["files"], manifest["models"]
    except (ValueError, KeyError) as exc:
        raise ModelUnavailable("The trained model's manifest is damaged.") from exc
    base = run.resolve()
    for rel, digest in files.items():
        path = (run / rel).resolve()
        if base not in path.parents:
            raise ModelUnavailable("The manifest refers to a file outside the model directory.")
        if not path.exists():
            raise ModelUnavailable(f"A model file is missing: {rel}.")
        if sha256_file(path) != digest:
            raise ModelUnavailable(f"A model file does not match its recorded checksum: {rel}. It was changed or damaged.")
    env = json.loads((run / "environment.json").read_text(encoding="utf-8"))
    now = environment()["libraries"]
    for name in {e["name"] for e in entries}:
        lib = MODEL_LIBS.get(name)
        trained, current = (env["libraries"] or {}).get(lib), now.get(lib)
        if lib and (trained is None or current is None or trained.split(".")[:2] != current.split(".")[:2]):
            raise ModelUnavailable(f"{lib} {current} is installed but the model was trained with {trained}; retrain or install that version.")
    loaded = LoadedRun(run_id=manifest["run_id"], path=run, manifest=manifest, environment=env,
                       schema=json.loads((run / "feature_schema.json").read_text(encoding="utf-8")),
                       intervals=json.loads((run / "intervals.json").read_text(encoding="utf-8")),
                       results=json.loads((run / "results.json").read_text(encoding="utf-8")))
    for e in entries:
        try:
            loaded.estimators.setdefault((e["pollutant"], int(e["horizon"])), []).append(joblib.load(run / e["file"]))
        except Exception as exc:  # noqa: BLE001 - any unpickling failure means the model is unusable
            raise ModelUnavailable(f"A model could not be loaded ({type(exc).__name__}).") from exc
    if not loaded.estimators:
        raise ModelUnavailable("The run contains no models.")
    return loaded
