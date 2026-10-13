"""Does an uploaded series relate to measured pollution, and would it have helped predict it?

Given a numeric column of an uploaded table (fire counts, traffic, an event flag, a weather variable ...) and a pollutant, this
aligns the column with the network-mean of REAL station observations from the history store, then reports:

1. correlation at several lags (Pearson and Spearman) with a confidence interval that allows for autocorrelation;
2. a chronological held-out check: does adding the series (known `lag` steps earlier) reduce the error of a one-step forecast
   that already uses yesterday's value? The lag is chosen on the training part only; the test part is scored once.

What it is not: causal evidence, or a trained model. It is a screening test to decide whether a dataset deserves to become a
feature in a proper, gated training run. Nothing here changes the active forecasting model.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.kb.tables import DatasetStore, tz_label, tz_minutes
from app.kb.types import KbError

POLLUTANTS = ("pm25", "pm10", "no2", "so2", "co", "o3")
MIN_HOURS_PER_DAY = 18  # a day is used only if at least this many hourly network values exist
MIN_PAIRS = 12
MIN_TEST = 30
IMPROVEMENT_THRESHOLD = 0.02  # a 2% lower held-out MAE counts as an improvement


# ---------------------------------------------------------------------------------------------- statistics
def pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx <= 0 or syy <= 0:
        return None
    return sum((a - mx) * (b - my) for a, b in zip(x, y)) / math.sqrt(sxx * syy)


def _ranks(v: list[float]) -> list[float]:
    order = sorted(range(len(v)), key=lambda i: v[i])
    ranks = [0.0] * len(v)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and v[order[j + 1]] == v[order[i]]:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    return ranks


def spearman(x: list[float], y: list[float]) -> float | None:
    return pearson(_ranks(x), _ranks(y)) if len(x) >= 3 else None


def _lag1(v: list[float]) -> float:
    r = pearson(v[:-1], v[1:])
    return 0.0 if r is None else max(-0.99, min(0.99, r))


def effective_n(x: list[float], y: list[float]) -> float:
    """Bartlett's correction: autocorrelated series carry fewer independent pairs than their length."""
    n = len(x)
    if n < 5:
        return float(n)
    rx, ry = _lag1(x), _lag1(y)
    denom = 1 + rx * ry
    return max(3.0, n * (1 - rx * ry) / denom) if denom > 0 else float(n)


def conf_interval(r: float, n_eff: float) -> tuple[float, float] | None:
    if n_eff <= 4 or abs(r) >= 1:
        return None
    z, se = math.atanh(r), 1 / math.sqrt(n_eff - 3)
    return math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)


def _solve(a: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for c in range(n):
        piv = max(range(c, n), key=lambda r: abs(m[r][c]))
        if abs(m[piv][c]) < 1e-12:
            return None
        m[c], m[piv] = m[piv], m[c]
        for r in range(n):
            if r != c:
                f = m[r][c] / m[c][c]
                for k in range(c, n + 1):
                    m[r][k] -= f * m[c][k]
    return [m[i][n] / m[i][i] for i in range(n)]


def ols(rows: list[list[float]], y: list[float]) -> list[float] | None:
    """Least squares with an intercept via the normal equations (a handful of features, so this is exact enough)."""
    k = len(rows[0]) + 1
    xtx = [[0.0] * k for _ in range(k)]
    xty = [0.0] * k
    for r, t in zip(rows, y):
        v = [1.0, *r]
        for i in range(k):
            xty[i] += v[i] * t
            for j in range(k):
                xtx[i][j] += v[i] * v[j]
    return _solve(xtx, xty)


def _predict(beta: list[float], row: list[float]) -> float:
    return beta[0] + sum(b * v for b, v in zip(beta[1:], row))


# ---------------------------------------------------------------------------------------------- observations
def observed_series(history_db: Path, pollutant: str, zone: str | None, start: datetime, end: datetime, tz_min: int, resolution: str) -> tuple[dict, dict]:
    """Network-mean observed series keyed by bucket start (UTC ISO). Returns (series, info)."""
    if not history_db.exists():
        raise KbError("no_observations", "The historical observation store does not exist, so there is nothing to compare with.", 503)
    s, e = start.strftime("%Y-%m-%dT%H:%M:%SZ"), end.strftime("%Y-%m-%dT%H:%M:%SZ")
    sql = ("select c.label_utc t, avg(c.value_std) v, count(distinct c.station_id) n from clean_air c "
           + ("join stations st on st.station_id = c.station_id " if zone else "")
           + "where c.pollutant = ? and c.usable = 1 and c.value_std is not null and c.label_utc >= ? and c.label_utc <= ? "
           + ("and st.zone = ? " if zone else "") + "group by c.label_utc order by c.label_utc")
    args: list = [pollutant, s, e] + ([zone] if zone else [])
    db = sqlite3.connect(f"file:{history_db.as_posix()}?mode=ro", uri=True, timeout=30)
    try:
        rows = db.execute(sql, args).fetchall()
    finally:
        db.close()
    if not rows:
        raise KbError("no_observations", "The observation store has no usable readings for that pollutant, zone and period.", 422)
    hours = {r[0]: (r[1], r[2]) for r in rows}
    stations = [r[2] for r in rows]
    info = {"hourly_values": len(rows), "stations_per_hour_median": sorted(stations)[len(stations) // 2], "stations_per_hour_max": max(stations)}
    if resolution == "hourly":
        return {k: v[0] for k, v in hours.items()}, info
    by_day: dict[str, list[float]] = defaultdict(list)
    offset = timedelta(minutes=tz_min)
    for t, (v, _) in hours.items():
        local = datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc) + offset
        by_day[local.strftime("%Y-%m-%d")].append(v)
    days = {d: sum(vs) / len(vs) for d, vs in by_day.items() if len(vs) >= MIN_HOURS_PER_DAY}
    info["days_used"], info["days_dropped_for_gaps"] = len(days), len(by_day) - len(days)
    return days, info


def dataset_buckets(series: list[tuple[datetime, float]], tz_min: int, resolution: str) -> dict[str, float]:
    offset = timedelta(minutes=tz_min)
    acc: dict[str, list[float]] = defaultdict(list)
    for t, v in series:
        if resolution == "hourly":
            key = t.replace(minute=0, second=0, microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
        else:
            key = (t + offset).strftime("%Y-%m-%d")  # the day in the dataset's own time zone
        acc[key].append(v)
    return {k: sum(v) / len(v) for k, v in acc.items()}


def _step(key: str, resolution: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H:%M:%SZ" if resolution == "hourly" else "%Y-%m-%d")


# ---------------------------------------------------------------------------------------------- the test
def relationship(
    store: DatasetStore, doc_id: str, column: str, pollutant: str, history_db: Path, *, zone: str | None = None,
    max_lag: int | None = None, known_in_advance: bool = False,
) -> dict:
    if pollutant not in POLLUTANTS:
        raise KbError("invalid_pollutant", f"pollutant must be one of: {', '.join(POLLUTANTS)}.", 422)
    profile = store.profile(doc_id)
    if profile is None:
        raise KbError("not_a_dataset", "This document is not a table.", 422)
    if not profile.get("time_column"):
        raise KbError("no_time_column", "This table has no date or time column, so it cannot be aligned with observations.", 422)
    tz_min = tz_minutes(profile["timezone_assumed"].split(" (")[0])
    resolution = "hourly" if profile.get("resolution") == "hourly" else "daily"
    raw = store.series(doc_id, profile["time_column"], column)
    if len(raw) < MIN_PAIRS:
        raise KbError("too_little_data", f"The column has only {len(raw)} usable values; at least {MIN_PAIRS} are needed.", 422)
    x_by = dataset_buckets(raw, tz_min, resolution)
    first = min(raw)[0] - timedelta(days=2)
    last = max(raw)[0] + timedelta(days=2)
    y_by, info = observed_series(history_db, pollutant, zone, first, last, tz_min, resolution)

    unit = timedelta(hours=1) if resolution == "hourly" else timedelta(days=1)
    lags = [0, 1, 2, 3, 6, 12, 24] if resolution == "hourly" else list(range(0, 8))
    if max_lag is not None:
        lags = [l for l in lags if l <= max_lag]

    # Align on a regular grid: y(t) with x(t - lag).
    keys = sorted(set(x_by) | set(y_by), key=lambda k: _step(k, resolution))
    grid: list[str] = []
    cur, stop = _step(keys[0], resolution), _step(keys[-1], resolution)
    fmt = "%Y-%m-%dT%H:%M:%SZ" if resolution == "hourly" else "%Y-%m-%d"
    while cur <= stop:
        grid.append(cur.strftime(fmt))
        cur += unit
    x_val = {k: x_by.get(k) for k in grid}
    y_val = {k: y_by.get(k) for k in grid}

    def pairs(lag: int, lo: int = 0, hi: int | None = None):
        xs, ys = [], []
        for i in range(max(lag, lo), len(grid) if hi is None else hi):
            x, y = x_val[grid[i - lag]], y_val[grid[i]]
            if x is not None and y is not None:
                xs.append(x)
                ys.append(y)
        return xs, ys

    corr = []
    for lag in lags:
        xs, ys = pairs(lag)
        if len(xs) < MIN_PAIRS:
            corr.append({"lag": lag, "n": len(xs), "pearson": None, "spearman": None, "ci95": None})
            continue
        r = pearson(xs, ys)
        ci = conf_interval(r, effective_n(xs, ys)) if r is not None else None
        corr.append({"lag": lag, "n": len(xs), "n_effective": round(effective_n(xs, ys), 1), "pearson": _r(r), "spearman": _r(spearman(xs, ys)),
                     "ci95": None if ci is None else [_r(ci[0]), _r(ci[1])]})
    usable = [c for c in corr if c["pearson"] is not None]
    if not usable:
        raise KbError("no_overlap", "The table and the observations share too few aligned values to compare "
                                    f"(need at least {MIN_PAIRS}).", 422)

    # A series is usable at lag 0 for prediction only if its value for the target time is known beforehand (a weather forecast, a
    # calendar). The caller must say so; otherwise only values from earlier steps are allowed.
    check = _heldout(grid, x_val, y_val, [l for l in lags if l >= (0 if known_in_advance else 1)], known_in_advance)
    period = [g for g in grid if x_val[g] is not None and y_val[g] is not None]
    caveats = [
        "Correlation is not causation; a third factor (season, weather) can drive both series.",
        "Pearson intervals use an effective sample size that allows for autocorrelation; they are still approximate.",
        f"Timestamps without an offset were read as {profile['timezone_assumed']}.",
        "Observations are the mean over the stations with usable readings; the station mix changes over time.",
        "The held-out check adds one series to a linear one-step model. A nonlinear model with other features could behave differently, "
        "so a negative result here is not proof that a series is useless, and a positive one is not proof it will help in a trained model.",
    ]
    if resolution == "daily":
        caveats.append(f"Daily values use days with at least {MIN_HOURS_PER_DAY} hourly network values ({info.get('days_dropped_for_gaps', 0)} days dropped).")
    if check.get("note"):
        caveats.append(check["note"])
    return {
        "dataset_id": doc_id, "column": column, "pollutant": pollutant, "zone": zone, "resolution": resolution,
        "timezone": f"{tz_label(tz_min)}", "observations": {"source": "history store, clean_air (usable readings only)", **info},
        "aligned_pairs_lag0": next((c["n"] for c in corr if c["lag"] == 0), None),
        "overlap_start": period[0] if period else None, "overlap_end": period[-1] if period else None,
        "correlations": corr, "best_lag_by_abs_pearson": max(usable, key=lambda c: abs(c["pearson"]))["lag"],
        "known_in_advance": known_in_advance, "heldout_check": check, "caveats": caveats,
        "not_applied": "This is a screening test. The active forecasting model was not changed and was not retrained.",
    }


def _r(v: float | None) -> float | None:
    return None if v is None else round(v, 3)


def _heldout(grid: list[str], x_val: dict, y_val: dict, lags: list[int], known_in_advance: bool = False) -> dict:
    """Chronological 70/30. Features known one step ahead: y(t-1) and x(t-lag). Lag chosen on train only."""
    if not lags:
        return {"status": "skipped", "note": "No usable lag was requested, so the held-out check was not run."}
    rows = []
    for i in range(1, len(grid)):
        y, yp = y_val[grid[i]], y_val[grid[i - 1]]
        if y is None or yp is None:
            continue
        rows.append((i, y, yp))
    if len(rows) < MIN_PAIRS * 2:
        return {"status": "skipped", "note": f"Only {len(rows)} consecutive observed steps are available; the held-out check needs more."}
    cut = int(len(rows) * 0.7)
    train, test = rows[:cut], rows[cut:]

    def feats(i: int, lag: int):
        return x_val[grid[i - lag]] if i - lag >= 0 else None

    best = None
    for lag in lags:
        xs = [(feats(i, lag), y) for i, y, _ in train if feats(i, lag) is not None]
        if len(xs) < MIN_PAIRS:
            continue
        r = pearson([a for a, _ in xs], [b for _, b in xs])
        if r is not None and (best is None or abs(r) > abs(best[1])):
            best = (lag, r)
    if best is None:
        return {"status": "skipped", "note": "No lag had enough overlapping values in the training part."}
    lag = best[0]
    tr = [(yp, feats(i, lag), y) for i, y, yp in train if feats(i, lag) is not None]
    te = [(yp, feats(i, lag), y) for i, y, yp in test if feats(i, lag) is not None]
    if len(tr) < MIN_PAIRS or not te:
        return {"status": "skipped", "note": "Too few aligned steps remain after requiring the series at the chosen lag."}
    base = ols([[yp] for yp, _, _ in tr], [y for _, _, y in tr])
    aug = ols([[yp, x] for yp, x, _ in tr], [y for _, _, y in tr])
    if base is None or aug is None:
        return {"status": "skipped", "note": "The regression was degenerate (a constant series)."}
    mae = lambda errs: sum(errs) / len(errs)  # noqa: E731
    persist = mae([abs(y - yp) for yp, _, y in te])
    m_base = mae([abs(y - _predict(base, [yp])) for yp, _, y in te])
    m_aug = mae([abs(y - _predict(aug, [yp, x])) for yp, x, y in te])
    gain = (m_base - m_aug) / m_base if m_base > 0 else 0.0
    if len(te) < MIN_TEST:
        verdict = f"Inconclusive: only {len(te)} held-out steps (need {MIN_TEST})."
    elif gain >= IMPROVEMENT_THRESHOLD:
        verdict = (f"Adding the series lowered the held-out error by {gain * 100:.1f}% relative to the yesterday-only model. "
                   "That is a reason to include it as a candidate feature in a proper training run, not proof that it helps.")
    elif gain <= -IMPROVEMENT_THRESHOLD:
        verdict = f"Adding the series made the held-out error {abs(gain) * 100:.1f}% worse; there is no evidence it helps."
    else:
        verdict = "No meaningful change in held-out error; there is no evidence the series adds predictive value."
    return {
        "status": "ok", "chosen_lag_steps": lag, "chosen_on": "training part only", "train_steps": len(tr), "test_steps": len(te),
        "test_mae": {"persistence": round(persist, 2), "yesterday_only_model": round(m_base, 2), "with_series": round(m_aug, 2)},
        "relative_change_vs_yesterday_only": round(gain, 4), "verdict": verdict,
        "note": "One chronological split of a single series; a different split could give a different answer.",
        "assumption": ("The series value for the target time is assumed to be known when the forecast is made (you marked it as known in advance)."
                       if known_in_advance and lag == 0 else "The series value is taken from earlier steps only, so it would be available when forecasting."),
    }
