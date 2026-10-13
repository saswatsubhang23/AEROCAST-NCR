from datetime import datetime, timedelta, timezone

import pytest

from app.services.aqi import Hourly, compute_aqi, normalize_unit, pollutant_result, sub_index
from app.services.indicators import hours_since_rain, ventilation_index

ANCHOR = datetime(2026, 10, 9, 6, 0, tzinfo=timezone.utc)
UG = "µg/m³"


def hours(values, anchor=ANCHOR):
    """Hourly rows ending at `anchor`, oldest first. None = missing hour."""
    n = len(values)
    return [Hourly(anchor - timedelta(hours=n - 1 - i), v) for i, v in enumerate(values)]


def const(v, n=24):
    return hours([v] * n)


# ------------------------------------------------------------------ sub-index (CPCB worked example) ------
@pytest.mark.parametrize("c,expected", [(31, 51), (45, 75), (60, 100)])
def test_pm25_matches_the_cpcb_worked_example(c, expected):
    assert sub_index("pm25", c)[0] == expected


@pytest.mark.parametrize("pollutant,c,expected,category", [
    ("pm25", 0, 0, "Good"),
    ("pm25", 30, 50, "Good"),
    ("pm10", 100, 100, "Satisfactory"),
    ("pm10", 250, 200, "Moderately polluted"),
    ("pm10", 251, 201, "Poor"),
    ("no2", 400, 400, "Very poor"),
    ("so2", 40, 50, "Good"),
    ("o3", 168, 200, "Moderately polluted"),
    ("co", 2.0, 100, "Satisfactory"),
    ("co", 10.1, 201, "Poor"),
])
def test_band_edges(pollutant, c, expected, category):
    value, cat, lower = sub_index(pollutant, c)
    assert (value, cat, lower) == (expected, category, False)


def test_concentrations_are_truncated_not_rounded():
    assert sub_index("pm25", 30.99)[0] == 50  # truncates to 30, not rounded up into the next band
    assert sub_index("co", 1.09)[0] == 50  # CO keeps one decimal: 1.0


def test_open_ended_severe_band_is_only_a_lower_bound():
    value, category, lower = sub_index("pm25", 300)
    assert (value, category, lower) == (401, "Severe", True)  # CPCB gives no upper breakpoint


# ------------------------------------------------------------------ units --------------------------------
def test_unit_handling():
    assert normalize_unit("pm25", UG, 10) == (10, None)
    assert normalize_unit("pm25", "ug/m3", 10) == (10, None)
    assert normalize_unit("co", "mg/m³", 2.0) == (2.0, None)
    assert normalize_unit("co", UG, 2000) == (2.0, None)  # exact conversion
    value, why = normalize_unit("no2", "ppm", 0.03)
    assert value is None and "ppm" in why
    assert normalize_unit("pm25", None, 1)[0] is None


# ------------------------------------------------------------------ per-pollutant eligibility ------------
def test_sub_index_needs_16_valid_hours_in_the_last_24():
    ok = pollutant_result("pm25", hours([45] * 16 + [None] * 8), UG, ANCHOR)
    assert ok.used and ok.sub_index == 75 and ok.valid_hours == 16
    # 16 valid hours must all be inside the window: put only 15 there
    short = pollutant_result("pm25", hours([45] * 15 + [None] * 9), UG, ANCHOR)
    assert not short.used and "15" in short.reason


def test_values_older_than_24_hours_are_ignored():
    rows = hours([45] * 40)  # 40 hours of data; only the last 24 count
    r = pollutant_result("pm25", rows[:20] + hours([None] * 20), UG, ANCHOR)
    assert not r.used


def test_24h_average_is_the_mean_of_valid_hours():
    r = pollutant_result("pm25", hours([20] * 12 + [40] * 12), UG, ANCHOR)
    assert r.average == 30.0 and r.sub_index == 50 and r.averaging == "24h"


def test_co_and_o3_use_8h_average_and_require_6_of_8():
    # first 16 hours low, last 8 hours high: the 8-hour average must drive the result
    rows = hours([0.2] * 16 + [3.0] * 8)
    r = pollutant_result("co", rows, "mg/m³", ANCHOR)
    assert r.averaging == "8h" and r.average == 3.0 and r.sub_index == 112  # (200-101)/(10-2.1)*(3.0-2.1)+101 = 112.3
    sparse = hours([0.2] * 19 + [3.0] * 5)
    for h in sparse[-8:-5]:
        h.value = None  # leaves 5 valid hours in the last 8 (one short of the 6 required)
    r = pollutant_result("co", sparse, "mg/m³", ANCHOR)
    assert not r.used and "only 5 valid hours in the last 8" in r.reason
    sparse[-8].value = 3.0  # 6 valid: exactly meets the requirement
    assert pollutant_result("co", sparse, "mg/m³", ANCHOR).used


def test_o3_uses_the_1h_value_when_the_8h_average_exceeds_208():
    rows = hours([250] * 23 + [400])
    r = pollutant_result("o3", rows, UG, ANCHOR)
    assert r.used and r.average == 400 and "1-hour" in r.note
    assert r.sub_index == 336  # (400-301)/(748-209)*(400-209)+301 = 336.1


def test_ppm_pollutant_is_excluded_with_a_reason_not_converted():
    r = pollutant_result("no2", const(0.03), "ppm", ANCHOR)
    assert not r.used and "ppm" in r.reason and r.sub_index is None


# ------------------------------------------------------------------ overall AQI ----------------------------
def full_station():
    return {
        "pm25": (const(45), UG), "pm10": (const(120), UG), "no2": (const(50), UG),
        "so2": (const(10), UG), "co": (const(1.5), "mg/m³"), "o3": (const(60), UG),
    }


def test_overall_aqi_is_the_worst_sub_index_with_its_dominant_pollutant():
    r = compute_aqi(full_station(), ANCHOR)
    assert r.status == "available"
    assert r.aqi == 114 and r.dominant == "pm10" and r.category == "Moderately polluted"
    subs = {p.pollutant: p.sub_index for p in r.pollutants}
    assert subs["pm25"] == 75 and subs["no2"] == 62


def test_aqi_requires_three_pollutants():
    r = compute_aqi({"pm25": (const(45), UG), "pm10": (const(120), UG)}, ANCHOR)
    assert r.status == "insufficient_data" and r.aqi is None and "at least 3" in r.reason
    # the per-pollutant sub-indices are still reported, as CPCB allows
    assert [p.sub_index for p in r.pollutants] == [75, 114]


def test_aqi_requires_pm25_or_pm10():
    data = {"no2": (const(50), UG), "so2": (const(10), UG), "o3": (const(60), UG)}
    r = compute_aqi(data, ANCHOR)
    assert r.status == "insufficient_data" and "PM2.5 nor PM10" in r.reason


def test_pollutant_with_insufficient_hours_does_not_count_toward_the_three():
    data = full_station()
    for k in ("no2", "so2", "co", "o3"):
        data[k] = (hours([50] * 10 + [None] * 14), data[k][1])
    r = compute_aqi(data, ANCHOR)
    assert r.status == "insufficient_data"


def test_one_unusable_unit_can_make_the_station_insufficient():
    data = {"pm25": (const(45), UG), "pm10": (const(120), UG), "no2": (const(0.03), "ppm")}
    assert compute_aqi(data, ANCHOR).status == "insufficient_data"


# ------------------------------------------------------------------ indicators --------------------------------
def test_ventilation_index_is_blh_times_wind_in_m_per_s():
    assert ventilation_index([1000.0, None, 500.0], [18.0, 10.0, None]) == [5000.0, None, None]


def test_hours_since_rain():
    assert hours_since_rain([0, 0, 1.0, 0, 0, 0]) == [None, None, 0, 1, 2, 3]


def test_hours_since_rain_is_unknown_across_missing_precipitation():
    assert hours_since_rain([1.0, 0, None, 0, 1.0, 0]) == [0, 1, None, None, 0, 1]
