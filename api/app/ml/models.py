"""Model factories and hyperparameter grids. All preprocessing that learns anything (imputation, scaling) lives inside the
estimator, so it is fitted on the training rows passed to `fit` and nothing else.

Missing values: Random Forest (scikit-learn >= 1.4), XGBoost and LightGBM handle NaN natively, so no imputation is applied to
them and the "was it observed" information is kept (the `*_n_*` counters). Support Vector Regression cannot, so it gets a
median imputer and a standard scaler, both fitted on its training rows only.
"""

import warnings

import numpy as np
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.svm import SVR

from app.ml.metrics import measure

# Small, deliberately modest grids: the point is a fair comparison on one CPU, not an exhaustive search.
GRIDS: dict[str, list[dict]] = {
    "random_forest": [{"max_depth": 12, "min_samples_leaf": 10}, {"max_depth": 20, "min_samples_leaf": 5}],
    "xgboost": [{"max_depth": 4, "learning_rate": 0.05}, {"max_depth": 6, "learning_rate": 0.05}],
    "lightgbm": [{"num_leaves": 31, "learning_rate": 0.05}, {"num_leaves": 63, "learning_rate": 0.05}],
    "svr": [{"C": 3.0, "epsilon": 0.05}, {"C": 10.0, "epsilon": 0.05}],
}


# scikit-learn warns that StandardScaler's inverse is "not strictly inverse" for float32 inputs; the difference is rounding only.
warnings.filterwarnings("ignore", message="The provided functions or transformer are not strictly inverse", category=UserWarning)


def make_model(name: str, params: dict, seed: int, n_jobs: int):
    if name == "random_forest":
        return RandomForestRegressor(n_estimators=100, max_features=0.4, max_samples=0.6, n_jobs=n_jobs, random_state=seed, **params)
    if name == "xgboost":
        from xgboost import XGBRegressor
        return XGBRegressor(n_estimators=300, subsample=0.8, colsample_bytree=0.8, min_child_weight=5, tree_method="hist", n_jobs=n_jobs,
                            random_state=seed, **params)
    if name == "lightgbm":
        from lightgbm import LGBMRegressor
        return LGBMRegressor(n_estimators=300, subsample=0.8, subsample_freq=1, colsample_bytree=0.8, min_child_samples=40, n_jobs=n_jobs,
                             random_state=seed, deterministic=True, force_row_wise=True, verbose=-1, **params)
    if name == "svr":
        base = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), SVR(kernel="rbf", gamma="scale", C=params["C"], epsilon=params["epsilon"]))
        return TransformedTargetRegressor(regressor=base, transformer=StandardScaler())  # target scaling is fitted on training targets only
    raise ValueError(f"unknown model {name!r}")


def fit_predict(name: str, params: dict, seed: int, n_jobs: int, X_train: np.ndarray, y_train: np.ndarray, X_eval: list[np.ndarray]):
    """Fit on the training rows, predict each evaluation matrix. Returns (model, predictions, timing/memory facts)."""
    model = make_model(name, params, seed, n_jobs)
    with measure() as fit_stats:
        model.fit(X_train, y_train)
    with measure() as pred_stats:
        preds = [np.asarray(model.predict(X), dtype=np.float64) for X in X_eval]
    facts = {"fit_seconds": fit_stats["seconds"], "predict_seconds": pred_stats["seconds"], "peak_rss_mb": max(fit_stats["peak_rss_mb"], pred_stats["peak_rss_mb"]),
             "fit_rss_growth_mb": fit_stats["rss_growth_mb"], "train_rows": int(len(y_train))}
    return model, preds, facts
