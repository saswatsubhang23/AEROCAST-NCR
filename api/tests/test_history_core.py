"""Units, timestamps, wind vectors, rolling statistics and the leakage guarantees of the feature builder."""

import math
import random
from datetime import datetime, timedelta, timezone

import pytest

from app.history import features as F
from app.history.clean import hour_label
from app.history.regions import agency_of, zone_of
from app.history.units import POLLUTANTS, WEATHER_VARIABLES, range_flags, to_standard, unit_key

T0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)


# ---------------------------------------------------------------------------------------------- units
@pytest.mark.parametrize("raw,key", [("µg/m³", "ug/m3"), ("μg/m³", "ug/m3"), ("ug/m3", "ug/m3"), ("mg/m³", "mg/m3"), ("ppb", "ppb"), ("ppm", "ppm"),
                                     ("c", None), ("", None), (None, None), ("furlongs", None)])
def test_unit_spellings(raw, key):
    assert unit_key(raw) == key


def test_conversions_keep_the_original_and_flag_the_change():
    assert to_standard("pm25", 80.0, "µg/m³") == (80.0, [])
    v, f = to_standard("no2", 20.0, "ppb")
    assert v == pytest.approx(20 * 46.0055 / 24.45) and f == ["UNIT_CONVERTED"]
    assert to_standard("no2", 0.02, "ppm")[0] == pytest.approx(v)
    assert to_standard("co", 1.2, "mg/m³") == (pytest.approx(1200.0), ["UNIT_CONVERTED"])


@pytest.mark.parametrize("pollutant,value,unit,flag", [("pm25", 10.0, "ppb", "UNIT_UNKNOWN"), ("no2", 5.0, "furlongs", "UNIT_UNKNOWN"),
                                                       ("o3", None, "µg/m³", "NULL_VALUE"), ("o3", float("nan"), "µg/m³", "NULL_VALUE")])
def test_values_without_an_honest_conversion_are_not_converted(pollutant, value, unit, flag):
    assert to_standard(pollutant, value, unit) == (None, [flag])


def test_range_flags():
    assert range_flags("pm25", 120.0) == []
    assert range_flags("pm25", -1.0) == ["NEGATIVE"]
    assert range_flags("pm25", 5000.0) == ["OUT_OF_RANGE"]
    assert range_flags("co", 150_000.0) == []


# ---------------------------------------------------------------------------------------------- time alignment
def test_cpcb_local_hours_get_the_label_on_the_hour_with_no_rounding():
    # 05:00-06:00 IST is 23:30-00:30 UTC; its midpoint is 00:00 UTC
    label, rounded = hour_label(datetime(2026, 2, 28, 23, 30, tzinfo=timezone.utc), datetime(2026, 3, 1, 0, 30, tzinfo=timezone.utc))
    assert label == datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc) and rounded is False


def test_utc_aligned_hours_are_rounded_and_say_so():
    label, rounded = hour_label(datetime(2026, 3, 1, 0, 0, tzinfo=timezone.utc), datetime(2026, 3, 1, 1, 0, tzinfo=timezone.utc))
    assert label == datetime(2026, 3, 1, 1, 0, tzinfo=timezone.utc) and rounded is True


def test_regions():
    assert zone_of(28.61, 77.21) == "Delhi"
    assert zone_of(28.54, 77.39) == "Noida"
    assert zone_of(27.0, 75.0) == "Other NCR"
    assert agency_of("Delhi Pollution Control Committee") == "Delhi (DPCC)"
    assert agency_of(None) == "Other/unknown"


# ---------------------------------------------------------------------------------------------- wind vectors
@pytest.mark.parametrize("speed,direction,u,v", [(36.0, 0.0, 0.0, -10.0), (36.0, 90.0, -10.0, 0.0), (36.0, 180.0, 0.0, 10.0), (36.0, 270.0, 10.0, 0.0)])
def test_wind_components_follow_the_meteorological_convention(speed, direction, u, v):
    ms, uu, vv = F.wind_components(speed, direction)
    assert ms == pytest.approx(10.0) and uu == pytest.approx(u, abs=1e-9) and vv == pytest.approx(v, abs=1e-9)


def test_wind_components_are_missing_when_an_input_is_missing():
    assert F.wind_components(None, 10.0) == (None, None, None)
    assert F.wind_components(10.0, None) == (None, None, None)


def test_calm_wind_has_zero_vector():
    ms, u, v = F.wind_components(0.0, 200.0)
    assert (ms, abs(u), abs(v)) == (0.0, 0.0, 0.0)


# ---------------------------------------------------------------------------------------------- rolling statistics
def naive(arr, w):
    out = []
    for i in range(len(arr)):
        win = [x for x in arr[max(0, i - w + 1): i + 1] if x is not None]
        if not win:
            out.append((None, None, None, None, 0))
            continue
        m = sum(win) / len(win)
        sd = None if len(win) < 2 else math.sqrt(sum((x - m) ** 2 for x in win) / (len(win) - 1))
        out.append((m, sd, min(win), max(win), len(win)))
    return out


@pytest.mark.parametrize("seed,w", [(1, 3), (2, 6), (3, 24), (4, 72)])
def test_rolling_matches_a_brute_force_implementation(seed, w):
    rng = random.Random(seed)
    arr = [None if rng.random() < 0.3 else rng.uniform(0, 300) for _ in range(300)]
    got = list(zip(*F.rolling(arr, w)))
    for g, e in zip(got, naive(arr, w)):
        assert g[4] == e[4]
        for a, b in zip(g[:4], e[:4]):
            assert (a is None and b is None) or a == pytest.approx(b, rel=1e-6, abs=1e-6)


# ---------------------------------------------------------------------------------------------- feature rows
def make_inputs(n=400, seed=0, gaps=True):
    rng = random.Random(seed)
    times = [T0 + i * HOUR for i in range(n)]
    series = {q: [None if (gaps and rng.random() < 0.08) else rng.uniform(5, 300) for _ in range(n)] for q in POLLUTANTS}
    series["pm25"][0] = 50.0
    weather = {v: [rng.uniform(1, 30) for _ in range(n)] for v in WEATHER_VARIABLES}
    weather["wind_direction_10m"] = [rng.uniform(0, 360) for _ in range(n)]
    weather["precipitation"] = [0.0 if rng.random() < 0.8 else rng.uniform(0.1, 5) for _ in range(n)]
    return times, series, weather, [0] * n, [0] * n


def rows_by_origin(rows, horizons=F.HORIZONS):
    cols = F.feature_columns(horizons)
    return {r[cols.index("origin_utc")]: dict(zip(cols, r)) for r in rows}


def test_columns_are_unique_and_targets_are_clearly_named():
    cols = F.feature_columns(F.HORIZONS)
    assert len(cols) == len(set(cols))
    targets = [c for c in cols if c.startswith("y_h")]
    assert targets == F.target_columns(F.HORIZONS)
    assert not any(c.startswith("y_") for c in cols if c not in targets)


def test_lags_and_targets_are_aligned_to_the_origin():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    rows = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))
    i = 200
    r = rows[times[i].strftime("%Y-%m-%dT%H:%M:%SZ")]
    t = series["pm25"]
    assert r["target_lag0"] == t[i] and r["target_lag1"] == t[i - 1] and r["target_lag24"] == t[i - 24] and r["target_lag168"] == t[i - 168]
    assert r["y_h1"] == t[i + 1] and r["y_h24"] == t[i + 24] and r["y_h72"] == t[i + 72]
    assert r["target_mean_3h"] == pytest.approx(sum(t[i - 2: i + 1]) / 3)
    assert r["target_n_24h"] == 24
    assert r["obs_no2"] == series["no2"][i]


def test_missing_values_stay_missing_and_are_counted():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    series["pm25"][190:200] = [None] * 10
    rows = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))
    r = rows[times[205].strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert r["target_n_12h"] == 6 and r["target_lag6"] is None and r["target_lag3"] is not None
    assert r["target_n_24h"] == 14
    # an origin whose own target hour is missing has no row at all (rows are anchored on an observation)
    assert times[195].strftime("%Y-%m-%dT%H:%M:%SZ") not in rows


def test_windows_with_fewer_than_half_their_hours_are_unknown_not_averaged():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    series["pm25"][190:204] = [None] * 14  # 24 h window ending at 204 then holds 10 observations
    r = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))[times[204].strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert r["target_n_24h"] == 10 and r["target_mean_24h"] is None and r["target_std_24h"] is None
    series["pm25"][202:204] = [10.0, 10.0]  # now 12 hours missing (190..201): exactly half observed, so it is reported
    r = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))[times[204].strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert r["target_n_24h"] == 12 and r["target_mean_24h"] is not None


def test_time_features_use_ist():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    r = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))["2026-01-01T00:00:00Z"]
    assert r["hour_ist"] == 5 and r["origin_ist"] == "2026-01-01T05:30:00+05:30"
    assert r["dow_ist"] == 3 and r["is_weekend_ist"] == 0  # 2026-01-01 is a Thursday
    assert r["hour_sin"] ** 2 + r["hour_cos"] ** 2 == pytest.approx(1.0)


def test_weather_wind_vector_columns():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    weather["wind_speed_10m"] = [36.0] * len(times)
    weather["wind_direction_10m"] = [90.0] * len(times)
    r = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))[times[50].strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert r["wx_wind_ms"] == pytest.approx(10.0) and r["wx_wind_u"] == pytest.approx(-10.0) and r["wx_wind_v"] == pytest.approx(0.0, abs=1e-9)
    assert r["wx_wind_u_lag3"] == pytest.approx(-10.0)


def test_hours_since_rain_and_24h_sum():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    weather["precipitation"] = [0.0] * len(times)
    weather["precipitation"][100] = 2.0
    weather["precipitation"][110] = 1.0
    rows = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft))
    r = rows[times[115].strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert r["wx_hours_since_rain"] == 5 and r["wx_precip_sum_24h"] == pytest.approx(3.0)
    assert rows[times[50].strftime("%Y-%m-%dT%H:%M:%SZ")]["wx_hours_since_rain"] is None  # no rain seen yet: unknown, not 0
    assert rows[times[110 + 168].strftime("%Y-%m-%dT%H:%M:%SZ")]["wx_hours_since_rain"] == 168
    assert rows[times[110 + 169].strftime("%Y-%m-%dT%H:%M:%SZ")]["wx_hours_since_rain"] is None  # older than any look-back: unknown


# ---------------------------------------------------------------------------------------------- no future leakage
def perturb(arrs: dict, start: int, rng):
    for name, arr in arrs.items():
        for i in range(start, len(arr)):
            if arr[i] is not None:
                arr[i] = arr[i] + rng.uniform(50, 500)


@pytest.mark.parametrize("latency", [0, 1, 6, 24])
@pytest.mark.parametrize("k", [150, 233])
def test_changing_the_future_never_changes_features_of_the_past(latency, k):
    times, series, weather, prov, soft = make_inputs(seed=11)
    base = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft, latency_hours=latency))

    s2 = {q: list(v) for q, v in series.items()}
    w2 = {v: list(a) for v, a in weather.items()}
    perturb(s2, k - latency + 1, random.Random(5))  # pollutant data newer than the cutoff of origin k
    perturb(w2, k + 1, random.Random(6))  # weather after origin k
    got = rows_by_origin(F.compute_rows(7, "pm25", times, s2, w2, prov, soft, latency_hours=latency))

    cols = F.feature_columns(F.HORIZONS)
    feature_cols = [c for c in cols if not c.startswith("y_h")]
    compared = 0
    for i in range(0, k + 1):
        key = times[i].strftime("%Y-%m-%dT%H:%M:%SZ")
        if key in base:
            assert key in got
            for c in feature_cols:
                assert base[key][c] == got[key][c], f"{c} at origin index {i} depends on the future"
            compared += 1
    assert compared > 50
    # the perturbation really did reach the targets, so the test could have caught a leak
    assert any(base[k_][c] != got[k_][c] for k_ in base if k_ in got for c in F.target_columns(F.HORIZONS))


def test_latency_shifts_pollutant_features_back_but_not_the_clock_or_targets():
    times, series, weather, prov, soft = make_inputs(gaps=False)
    r = rows_by_origin(F.compute_rows(7, "pm25", times, series, weather, prov, soft, latency_hours=24))[times[200].strftime("%Y-%m-%dT%H:%M:%SZ")]
    assert r["target_lag0"] == series["pm25"][176] and r["y_h1"] == series["pm25"][201]
    assert r["hour_ist"] == (times[200] + timedelta(hours=5, minutes=30)).hour
