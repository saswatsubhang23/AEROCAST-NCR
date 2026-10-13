"""Loading the validated model-ready table, chronological splits, and baseline predictions.

Leakage rules enforced here (each has a test):
  * origins are split by time, never at random;
  * a training row for horizon h needs its *target time* (origin + h) inside the training period, so no training label lies in
    a later period than the data used for validation or testing (label purging);
  * climatology is computed from training rows only; the seasonal-naive and persistence baselines look strictly backwards.
"""

import math
import sqlite3
from dataclasses import dataclass, field

import numpy as np

from app.history.features import HORIZONS, feature_columns
from app.history.ingest_air import parse_iso
from app.history.store import HistoryStore
from app.ml.config import MlConfig

ID_COLUMNS = {"station_id", "pollutant", "origin_utc", "origin_ist"}
LOCATION_FEATURES = ["station_lat", "station_lon"]


def feature_names_for(horizons: list[int] | None = None, location: bool = False) -> list[str]:
    """Ordered model inputs: every model_ready column except identifiers and targets (and optionally the station coordinates)."""
    cols = [c for c in feature_columns(horizons or HORIZONS) if c not in ID_COLUMNS and not c.startswith("y_h")]
    return cols + (LOCATION_FEATURES if location else [])


@dataclass
class Dataset:
    pollutant: str
    horizons: list[int]
    feature_names: list[str]  # model_ready numeric columns (no location features); X has exactly these columns
    X: np.ndarray  # float32, NaN = missing
    station: np.ndarray  # int64 (synthetic XKDR-only station ids exceed int32)
    origin: np.ndarray  # int64, hours since the Unix epoch (the hour label, UTC)
    Y: np.ndarray  # float32 (n, len(horizons)); NaN where the target hour has no usable observation
    lat: np.ndarray
    lon: np.ndarray
    seasonal: np.ndarray  # (n, len(horizons)) seasonal-naive prediction; NaN if that hour was not observed
    meta: dict = field(default_factory=dict)

    @property
    def n(self) -> int:
        return len(self.origin)

    def col(self, name: str) -> np.ndarray:
        return self.X[:, self.feature_names.index(name)]

    def design(self, location: bool = False) -> tuple[np.ndarray, list[str]]:
        """Model input matrix and its column names."""
        if not location:
            return self.X, self.feature_names
        return np.column_stack([self.X, self.lat, self.lon]).astype(np.float32), self.feature_names + LOCATION_FEATURES


def hours_since_epoch(origin_utc: list[str]) -> np.ndarray:
    return np.array([s[:-1] for s in origin_utc], dtype="datetime64[s]").astype("datetime64[h]").astype(np.int64)


def _series_arrays(store: HistoryStore, pollutant: str) -> dict[int, tuple[int, np.ndarray]]:
    """station -> (first hour, usable values by hour); NaN where there is no usable observation."""
    out: dict[int, tuple[int, np.ndarray]] = {}
    rows = store.query("select station_id, label_utc, value_std from clean_air where pollutant=? and usable=1 order by station_id, label_utc", (pollutant,))
    by: dict[int, list] = {}
    for r in rows:
        by.setdefault(r["station_id"], []).append((r["label_utc"], r["value_std"]))
    for sid, items in by.items():
        hrs = hours_since_epoch([x[0] for x in items])
        start = int(hrs.min())
        arr = np.full(int(hrs.max()) - start + 1, np.nan, dtype=np.float32)
        arr[hrs - start] = [x[1] for x in items]
        out[sid] = (start, arr)
    return out


def seasonal_naive(series: dict[int, tuple[int, np.ndarray]], station: np.ndarray, origin: np.ndarray, horizons: list[int]) -> np.ndarray:
    """Value at the same hour of day, most recently *before or at* the origin: o + h - 24 * ceil(h / 24). Strictly backward-looking."""
    out = np.full((len(origin), len(horizons)), np.nan, dtype=np.float32)
    for j, h in enumerate(horizons):
        back = origin + h - 24 * math.ceil(h / 24)
        for sid in np.unique(station):
            if sid not in series:
                continue
            start, arr = series[sid]
            idx = np.where(station == sid)[0]
            k = back[idx] - start
            ok = (k >= 0) & (k < len(arr))
            out[idx[ok], j] = arr[k[ok]]
    return out


def dataset_provenance(store: HistoryStore) -> dict:
    """Is this store built from recorded real-source ingestion? Every raw row must carry the run id of an `ingest-air` run in
    `ingest_runs` (written only by the ingestion CLI). Rows without one (hand-built test fixtures) make the store a fixture."""
    air_runs = store.query("select count(*) from ingest_runs where kind like 'ingest-air%'")[0][0]
    raw = store.count("raw_air")
    orphan = store.query("select count(*) from raw_air where run_id not in (select run_id from ingest_runs)")[0][0]
    real = air_runs > 0 and raw > 0 and orphan == 0
    return {"provenance": "real_source_ingest" if real else "TEST FIXTURE OR UNKNOWN", "ingest_air_runs": air_runs, "raw_air_rows": raw,
            "raw_rows_without_a_recorded_run": orphan}


def load_dataset(store: HistoryStore, pollutant: str, horizons: list[int], table: str = "model_ready") -> Dataset:
    cols_all = [r[1] for r in store.query(f"pragma table_info({table})")]
    feats = [c for c in cols_all if c not in ID_COLUMNS and not c.startswith("y_h")]
    missing = [h for h in horizons if f"y_h{h}" not in cols_all]
    if missing:
        raise ValueError(f"model_ready has no targets for horizons {missing}; rebuild it with those horizons")
    sel = ["station_id", "origin_utc"] + feats + [f"y_h{h}" for h in horizons]
    cur = store.db.execute(f"select {','.join(sel)} from {table} where pollutant=? order by origin_utc, station_id", (pollutant,))
    chunks, ids, origins = [], [], []
    while True:
        rows = cur.fetchmany(50_000)
        if not rows:
            break
        arr = np.array([[np.nan if v is None else v for v in r[2:]] for r in rows], dtype=np.float32)
        chunks.append(arr)
        ids += [r[0] for r in rows]
        origins += [r[1] for r in rows]
    if not chunks:
        raise ValueError(f"no {pollutant} rows in {table}")
    full = np.vstack(chunks)
    station = np.array(ids, dtype=np.int64)
    coords = {r["station_id"]: (r["lat"], r["lon"]) for r in store.query("select station_id, lat, lon from stations")}
    lat = np.array([coords.get(int(s), (np.nan, np.nan))[0] for s in station], dtype=np.float32)
    lon = np.array([coords.get(int(s), (np.nan, np.nan))[1] for s in station], dtype=np.float32)
    origin = hours_since_epoch(origins)
    series = _series_arrays(store, pollutant)
    fs = store.query("select digest, params from feature_sets where name=?", (table,))
    return Dataset(
        pollutant=pollutant, horizons=list(horizons), feature_names=feats, X=full[:, : len(feats)], station=station, origin=origin,
        Y=full[:, len(feats):], lat=lat, lon=lon, seasonal=seasonal_naive(series, station, origin, horizons),
        meta={"table": table, "digest": fs[0]["digest"] if fs else None, "feature_params": fs[0]["params"] if fs else None},
    )


# ---------------------------------------------------------------------------------------------- chronological splits
@dataclass
class Splits:
    t_min: int
    t_max: int
    test_start: int  # first origin hour of the held-out test period
    folds: list[tuple[int, int]]  # (validation_start, validation_end) of each rolling-origin fold, oldest first

    def describe(self) -> dict:
        h = lambda x: np.datetime64(int(x), "h").astype(str)  # noqa: E731
        return {"data_from": h(self.t_min), "data_to": h(self.t_max), "dev_to_exclusive": h(self.test_start), "test_from": h(self.test_start),
                "folds": [{"validation_from": h(a), "validation_to_exclusive": h(b)} for a, b in self.folds]}


def make_splits(origin: np.ndarray, cfg: MlConfig) -> Splits:
    t_min, t_max = int(origin.min()), int(origin.max())
    span = t_max - t_min + 1
    test_start = t_min + int(round(span * (1.0 - cfg.test_frac)))
    w = int(round(span * cfg.fold_frac))
    folds = []
    for k in range(cfg.n_folds):
        v_end = test_start - (cfg.n_folds - 1 - k) * w
        folds.append((v_end - w, v_end))
    if folds[0][0] <= t_min:
        raise ValueError("the configured folds do not fit in the available time span")
    return Splits(t_min, t_max, test_start, folds)


def train_mask(ds: Dataset, j: int, end: int) -> np.ndarray:
    """Rows usable for training horizon index j when training data must end at hour `end` (exclusive): the *target time*
    origin + h must lie before `end`, so no label comes from the period being validated or tested."""
    h = ds.horizons[j]
    return (ds.origin + h < end) & np.isfinite(ds.Y[:, j])


def eval_mask(ds: Dataset, j: int, start: int, end: int, need_seasonal: bool = True) -> np.ndarray:
    """Rows to score in the window [start, end): origin inside it AND target time inside it, so a validation window never
    reads a label from the period after it (the last fold must not see the test period)."""
    h = ds.horizons[j]
    m = (ds.origin >= start) & (ds.origin < end) & (ds.origin + h < end) & np.isfinite(ds.Y[:, j])
    return m & np.isfinite(ds.seasonal[:, j]) if need_seasonal else m


def subsample(idx: np.ndarray, cap: int, seed: int) -> np.ndarray:
    """Deterministic uniform subsample of row indices (sorted, so time order is kept)."""
    if len(idx) <= cap:
        return idx
    rng = np.random.default_rng(seed)
    return np.sort(rng.choice(idx, size=cap, replace=False))


# ---------------------------------------------------------------------------------------------- baselines
def persistence(ds: Dataset, rows: np.ndarray) -> np.ndarray:
    return ds.col("target_lag0")[rows]


def climatology_fit(ds: Dataset, j: int, train_rows: np.ndarray) -> dict:
    """Mean target by (station, IST hour of the target time), from TRAINING rows only, with station and global fallbacks."""
    h = ds.horizons[j]
    hour = ((ds.origin[train_rows] + h) + 5) % 24
    y = ds.Y[train_rows, j].astype(np.float64)
    st = ds.station[train_rows]
    table: dict = {}
    for s in np.unique(st):
        sm = st == s
        table[(int(s), None)] = float(y[sm].mean())
        for hr in range(24):
            m = sm & (hour == hr)
            if m.any():
                table[(int(s), hr)] = float(y[m].mean())
    table[(None, None)] = float(y.mean())
    return table


def climatology_predict(table: dict, ds: Dataset, j: int, rows: np.ndarray) -> np.ndarray:
    h = ds.horizons[j]
    out = np.empty(len(rows), dtype=np.float64)
    for i, r in enumerate(rows):
        s, hr = int(ds.station[r]), int((ds.origin[r] + h + 5) % 24)
        out[i] = table.get((s, hr), table.get((s, None), table[(None, None)]))
    return out
