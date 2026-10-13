"""Atmospheric regimes learned from stored weather, and how PM2.5 behaves in each (offline; results saved as JSON).

Method (every step is data-driven; no regime is named in advance)
  1. Inputs per station-hour from the Open-Meteo archive rows in the history store: wind speed (m/s), boundary layer height (m),
     relative humidity (%), a wet flag (precipitation >= 0.1 mm), temperature (°C). Rows with any missing input are skipped.
  2. Standardisation (mean/std) and K-means are fitted on the DEVELOPMENT period only (before the held-out test period).
  3. k = 2..5 is chosen by silhouette score on a seeded subsample of development rows.
  4. Regimes are named only from their own centroids ("low wind", "shallow boundary layer", ...): a part is added when the centroid
     is at least 0.5 standard deviations from the overall mean on that variable. The names describe the weather, not the pollution.
  5. Validation: the fitted regimes are applied to the held-out test period and PM2.5 is compared across regimes with a
     Kruskal-Wallis test, with medians and sample counts for development and test. The result is an association between weather
     state and concentration, not a causal claim, and a regime with few test samples is flagged.
Assignment at request time needs only NumPy and the saved JSON (no scikit-learn).
"""

import json
from datetime import datetime
from pathlib import Path

import numpy as np

from app.history.ingest_air import iso
from app.history.store import HistoryStore

FEATURES = ["wind_ms", "blh_m", "rh_pct", "wet", "temp_c"]
# Names are RELATIVE to this dataset (a centroid at least half a standard deviation above or below the overall mean), so
# "higher wind" can still be a light breeze in absolute terms; the centroid values are served with every regime.
NAMES = {"wind_ms": ("lower wind", "higher wind"), "blh_m": ("shallower boundary layer", "deeper boundary layer"), "rh_pct": ("drier air", "more humid air"),
         "wet": ("no rain", "rain"), "temp_c": ("cooler", "warmer")}
MIN_TEST_SAMPLES = 200


def feature_matrix(rows) -> tuple[np.ndarray, list[tuple[int, str]]]:
    X, keys = [], []
    for r in rows:
        ws, blh, rh, pr, t = r["wind_speed_10m"], r["boundary_layer_height"], r["relative_humidity_2m"], r["precipitation"], r["temperature_2m"]
        if None in (ws, blh, rh, pr, t):
            continue
        X.append([ws / 3.6, blh, rh, 1.0 if pr >= 0.1 else 0.0, t])
        keys.append((r["station_id"], r["time_utc"]))
    return np.array(X, dtype=np.float64), keys


def assign(X: np.ndarray, model: dict) -> np.ndarray:
    """Nearest-centroid regime index per row, using the saved standardisation and centroids."""
    Z = (X - np.array(model["mean"])) / np.array(model["std"])
    C = np.array(model["centroids_z"])
    return np.argmin(((Z[:, None, :] - C[None, :, :]) ** 2).sum(axis=2), axis=1)


def name_regime(centroid_z: list[float]) -> str:
    parts = []
    for f, z in zip(FEATURES, centroid_z):
        lo, hi = NAMES[f]
        if f == "wet":
            if z >= 0.5:
                parts.append(hi)
        elif z <= -0.5:
            parts.append(lo)
        elif z >= 0.5:
            parts.append(hi)
    return ", ".join(parts) if parts else "mid-range conditions"


def fit_regimes(store: HistoryStore, dev_end: datetime, seed: int = 20261010, pollutant: str = "pm25", max_fit_rows: int = 60_000) -> dict:
    from scipy.stats import kruskal
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score

    cols = "station_id, time_utc, wind_speed_10m, boundary_layer_height, relative_humidity_2m, precipitation, temperature_2m"
    dev = store.query(f"select {cols} from clean_weather where time_utc < ? and flags not like '%OUT_OF_RANGE%'", (iso(dev_end),))
    test = store.query(f"select {cols} from clean_weather where time_utc >= ? and flags not like '%OUT_OF_RANGE%'", (iso(dev_end),))
    Xd, kd = feature_matrix(dev)
    Xt, kt = feature_matrix(test)
    if len(Xd) < 1000 or len(Xt) < 200:
        raise ValueError("not enough complete weather rows to fit and validate regimes")
    mean, std = Xd.mean(axis=0), Xd.std(axis=0)
    std[std == 0] = 1.0
    Zd = (Xd - mean) / std
    rng = np.random.default_rng(seed)
    fit_idx = rng.choice(len(Zd), size=min(max_fit_rows, len(Zd)), replace=False)
    sil_idx = rng.choice(len(fit_idx), size=min(5000, len(fit_idx)), replace=False)
    trials = []
    for k in range(2, 6):
        km = KMeans(n_clusters=k, n_init=5, random_state=seed).fit(Zd[fit_idx])
        trials.append({"k": k, "silhouette": float(silhouette_score(Zd[fit_idx][sil_idx], km.labels_[sil_idx])), "model": km})
    best = max(trials, key=lambda t: t["silhouette"])
    km = best["model"]
    order = np.argsort(km.cluster_centers_[:, 0])  # stable ordering: by wind speed
    centroids_z = km.cluster_centers_[order]
    model = {"features": FEATURES, "mean": mean.tolist(), "std": std.tolist(), "centroids_z": centroids_z.tolist(), "k": int(best["k"]),
             "centroids": (centroids_z * std + mean).tolist(), "labels": [name_regime(c) for c in centroids_z.tolist()]}

    idx = {(r["station_id"], r["label_utc"]): r["value_std"] for r in store.query(
        "select station_id, label_utc, value_std from clean_air where pollutant=? and usable=1", (pollutant,))}

    def pm_by_regime(X, keys):
        reg = assign(X, model)
        groups: dict[int, list[float]] = {i: [] for i in range(model["k"])}
        weather_hours = {i: 0 for i in range(model["k"])}
        for key, g in zip(keys, reg):
            weather_hours[int(g)] += 1
            v = idx.get(key)
            if v is not None:
                groups[int(g)].append(v)
        stats = {i: {"weather_hours": weather_hours[i], "pm_n": len(v), "pm_median": float(np.median(v)) if v else None,
                     "pm_q25": float(np.quantile(v, 0.25)) if v else None, "pm_q75": float(np.quantile(v, 0.75)) if v else None} for i, v in groups.items()}
        return stats, groups

    dev_stats, dev_groups = pm_by_regime(Xd, kd)
    test_stats, test_groups = pm_by_regime(Xt, kt)
    usable = [g for g in test_groups.values() if len(g) >= 5]
    kw = None
    if len(usable) >= 2:
        h, p = kruskal(*usable)
        kw = {"statistic": float(h), "p_value": float(p), "groups_tested": len(usable)}
    return {"method": "k-means on standardised weather, fitted on development period only", "dev_end": iso(dev_end), "seed": seed, "model": model,
            "selection": [{"k": t["k"], "silhouette": t["silhouette"]} for t in trials], "pollutant": pollutant,
            "development": {"rows": int(len(Xd)), "pm": dev_stats}, "test": {"rows": int(len(Xt)), "pm": test_stats, "kruskal_wallis": kw,
                                                                         "small_samples": [i for i, s in test_stats.items() if s["pm_n"] < MIN_TEST_SAMPLES]},
            "caveat": "Regimes describe weather states. Differences in concentration between them are associations, not proof of cause."}


def save(result: dict, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(result, indent=1), encoding="utf-8")
