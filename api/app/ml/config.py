"""Training configuration. Everything that influences a result lives here, is written next to the artifacts and hashed into the
run id, so a run can be repeated exactly (same config + same data digest -> same run id)."""

import hashlib
import json
from dataclasses import asdict, dataclass, field

MODELS = ["random_forest", "xgboost", "lightgbm", "svr"]


@dataclass
class MlConfig:
    pollutants: list[str] = field(default_factory=lambda: ["pm25", "pm10"])
    horizons: list[int] = field(default_factory=lambda: [1, 3, 6, 12, 24])
    models: list[str] = field(default_factory=lambda: list(MODELS))
    seed: int = 20261010
    # chronological split of origin times: dev = first (1 - test_frac) of the time span, test = the last test_frac, touched once
    test_frac: float = 0.20
    n_folds: int = 3  # rolling-origin (expanding window) validation folds inside dev
    fold_frac: float = 0.10  # length of each validation window as a share of the whole span
    tune_horizon: int = 6  # hyperparameters are chosen on the last fold at this horizon, then reused for every horizon
    max_train_rows: dict = field(default_factory=lambda: {"random_forest": 120_000, "xgboost": 300_000, "lightgbm": 300_000, "svr": 12_000})
    max_eval_rows: int = 30_000  # every model and baseline is scored on the same capped sample of each evaluation set
    n_jobs: int = 6
    location_features: bool = False  # main comparison: no coordinates (the location experiment compares both)
    unseen_station_frac: float = 0.20
    location_experiment_horizons: list[int] = field(default_factory=lambda: [6, 24])
    interval_level: float = 0.8
    ensemble_min_gain: float = 0.01  # an ensemble is adopted only if it lowers validation MAE by at least this share
    min_train_rows: int = 2000
    # Training on a store whose raw rows are not tied to a recorded real-source ingest run is refused unless this is set. Only the
    # automated tests set it (their stores are synthetic fixtures); results trained that way are labelled TEST FIXTURE.
    allow_test_fixtures: bool = False

    def to_json(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, indent=1)

    @staticmethod
    def from_json(text: str) -> "MlConfig":
        return MlConfig(**json.loads(text))

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()
