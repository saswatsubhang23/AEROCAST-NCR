"""Metrics and resource tracking. Nothing here is estimated: every score is computed from predictions and observations."""

import math
import threading
import time
from contextlib import contextmanager

import numpy as np
import psutil


def regression_metrics(y: np.ndarray, p: np.ndarray) -> dict:
    """MAE, RMSE, R-squared, bias and the sample count, over rows where both values exist."""
    ok = np.isfinite(y) & np.isfinite(p)
    n = int(ok.sum())
    if n == 0:
        return {"n": 0, "mae": None, "rmse": None, "r2": None, "bias": None}
    e = p[ok] - y[ok]
    sst = float(np.sum((y[ok] - y[ok].mean()) ** 2))
    return {"n": n, "mae": float(np.mean(np.abs(e))), "rmse": float(math.sqrt(np.mean(e ** 2))),
            "r2": None if sst <= 0 else float(1.0 - np.sum(e ** 2) / sst), "bias": float(np.mean(e))}


def skill(mae: float | None, mae_ref: float | None) -> float | None:
    """1 - MAE/MAE_reference: positive means better than the reference (persistence)."""
    return None if mae is None or not mae_ref else float(1.0 - mae / mae_ref)


@contextmanager
def measure():
    """Wall time and peak resident-memory growth (MB) of the block, sampled every 50 ms from a helper thread."""
    proc = psutil.Process()
    base = proc.memory_info().rss
    peak = [base]
    stop = threading.Event()

    def poll():
        while not stop.is_set():
            peak[0] = max(peak[0], proc.memory_info().rss)
            time.sleep(0.05)

    t = threading.Thread(target=poll, daemon=True)
    out = {}
    t.start()
    started = time.perf_counter()
    try:
        yield out
    finally:
        out["seconds"] = time.perf_counter() - started
        stop.set()
        t.join()
        peak[0] = max(peak[0], proc.memory_info().rss)
        out["peak_rss_mb"] = peak[0] / 1e6
        out["rss_growth_mb"] = (peak[0] - base) / 1e6


# ---------------------------------------------------------------------------------------------- stratified evaluation
SEASONS = {  # India Meteorological Department seasons, by calendar month in IST
    12: "winter", 1: "winter", 2: "winter", 3: "pre_monsoon", 4: "pre_monsoon", 5: "pre_monsoon",
    6: "monsoon", 7: "monsoon", 8: "monsoon", 9: "monsoon", 10: "post_monsoon", 11: "post_monsoon",
}
SEASON_ORDER = ["winter", "pre_monsoon", "monsoon", "post_monsoon"]
MIN_STRATUM = 30  # fewer scored rows than this and a stratum reports its size but no score


def season_of(epoch_hours: np.ndarray) -> np.ndarray:
    """Season name of each instant given as hours since the Unix epoch (UTC); the month is taken in IST (UTC+5:30)."""
    ist = np.asarray(epoch_hours, dtype="int64") * 3600 + int(5.5 * 3600)
    months = ist.astype("datetime64[s]").astype("datetime64[M]").astype(int) % 12 + 1
    return np.array([SEASONS[int(m)] for m in months])


def range_bands(pollutant: str) -> list[tuple[str, float, float]]:
    """The CPCB category bands of a pollutant as (label, low, high) in the standard unit (ug/m3), from the application's one AQI table."""
    from app.services.aqi import AQI_BANDS, BREAKPOINTS, CATEGORIES  # noqa: PLC0415 - keeps the metrics module importable on its own

    bands = BREAKPOINTS[pollutant][3]
    scale = 1000.0 if BREAKPOINTS[pollutant][1] == "mg/m³" else 1.0
    out = []
    for i, (lo, hi) in enumerate(bands):
        upper = float("inf") if hi is None or i == len(bands) - 1 else bands[i + 1][0] * scale  # contiguous: the next band's start
        out.append((CATEGORIES[i], lo * scale if i else 0.0, upper))
    return out


def _stratum(y: np.ndarray, p: np.ndarray, base: np.ndarray, mask: np.ndarray) -> dict:
    n = int(mask.sum())
    if n < MIN_STRATUM:
        return {"n": n, "mae": None, "rmse": None, "persistence_mae": None, "skill": None, "note": f"fewer than {MIN_STRATUM} scored rows"}
    m = regression_metrics(y[mask], p[mask])
    b = regression_metrics(y[mask], base[mask])
    return {"n": m["n"], "mae": m["mae"], "rmse": m["rmse"], "bias": m["bias"], "persistence_mae": b["mae"], "skill": skill(m["mae"], b["mae"])}


def stratified(y: np.ndarray, p: np.ndarray, base: np.ndarray, target_epoch_hours: np.ndarray, pollutant: str) -> dict:
    """Score by season of the target hour and by observed concentration band, with the persistence baseline in each stratum. Rows where the
    target, the prediction or the baseline is missing are not scored (the same rule as every other score here)."""
    ok = np.isfinite(y) & np.isfinite(p) & np.isfinite(base)
    seasons = season_of(target_epoch_hours)
    out: dict = {"season": {}, "range": {}}
    for s in SEASON_ORDER:
        out["season"][s] = _stratum(y, p, base, ok & (seasons == s))
    for label, lo, hi in range_bands(pollutant):
        r = _stratum(y, p, base, ok & (y >= lo) & (y < hi))
        r["from"], r["to"] = lo, None if hi == float("inf") else hi
        out["range"][label] = r
    out["note"] = ("Range strata are defined by the OBSERVED value, so the model's bias in them is partly regression to the mean; "
                   "season strata use the target hour in IST. A stratum with too few rows reports no score.")
    return out
