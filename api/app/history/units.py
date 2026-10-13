"""Units, plausibility limits and quality-flag names for the historical pipeline.

Nothing here changes a stored measurement. A conversion produces a *separate* standardised value; the original value and
unit always stay beside it. The limits below are physical-plausibility limits chosen for this pipeline; they are not
regulatory standards and not claims about what Delhi can experience.
"""

import math

POLLUTANTS = ["pm25", "pm10", "no2", "so2", "co", "o3"]
STD_UNIT = "µg/m³"

# Reference conditions for gas conversions: 25 °C and 101.325 kPa (molar volume 24.45 L/mol). Real conditions differ with
# temperature and pressure, so a converted gas value carries up to a few percent of uncertainty (see docs).
MOLAR_VOLUME_L = 24.45
MOLAR_MASS = {"no2": 46.0055, "so2": 64.066, "co": 28.0101, "o3": 47.9982}  # g/mol

# Hard flags make a value unusable for modelling; soft flags are informational and the value stays usable.
HARD_FLAGS = {"NULL_VALUE", "NEGATIVE", "OUT_OF_RANGE", "UNIT_UNKNOWN", "PERIOD_IRREGULAR", "UNIT_SUSPECT"}
SOFT_FLAGS = {"LOW_COVERAGE", "FLATLINE", "UNIT_CONVERTED", "REVISED", "SENSOR_CONFLICT", "MULTI_SENSOR", "ALIGN_ROUNDED", "PROVISIONAL"}

LOW_COVERAGE_PCT = 75.0  # an hour built from fewer than this share of its expected samples
FLATLINE_MIN_RUN = 6  # identical consecutive hourly values

# A sensor whose labelled unit contradicts its magnitude: after conversion its median differs from the median of sensors that
# report this pollutant natively in µg/m³ by more than this factor (either way). Needs at least MIN_REFERENCE_SENSORS references.
# Pollutants for which no sensor can plausibly have a median below this (µg/m³), whatever its label says. Used when there are no
# native-µg/m³ sensors to compare against (the common case after old sensors drop out of the window). CO: global background air holds
# roughly 0.1 ppm (about 100 µg/m³), so a median near 1 µg/m³ means the unit label is wrong (the values behave like mg/m³), not
# that the air is clean. The floor is deliberately far below any real urban value (50 µg/m³).
PLAUSIBLE_MEDIAN_FLOOR_STD = {"co": 50.0}
UNIT_SUSPECT_FACTOR = 20.0
MIN_REFERENCE_SENSORS = 3

# Physical-plausibility limits in the standard unit (µg/m³).
RANGE_STD = {"pm25": (0.0, 3000.0), "pm10": (0.0, 5000.0), "no2": (0.0, 3000.0), "so2": (0.0, 3000.0),
             "co": (0.0, 200_000.0), "o3": (0.0, 1500.0)}

# Weather limits per Open-Meteo variable (units as returned by the archive API).
WEATHER_RANGE = {
    "temperature_2m": (-60.0, 65.0), "relative_humidity_2m": (0.0, 100.0), "dew_point_2m": (-80.0, 45.0),
    "surface_pressure": (300.0, 1100.0), "wind_speed_10m": (0.0, 400.0), "wind_direction_10m": (0.0, 360.0),
    "wind_gusts_10m": (0.0, 500.0), "precipitation": (0.0, 500.0), "cloud_cover": (0.0, 100.0),
    "boundary_layer_height": (0.0, 10_000.0), "shortwave_radiation": (0.0, 1500.0),
}
WEATHER_VARIABLES = list(WEATHER_RANGE)
EXPECTED_WEATHER_UNITS = {
    "temperature_2m": "°C", "relative_humidity_2m": "%", "dew_point_2m": "°C", "surface_pressure": "hPa",
    "wind_speed_10m": "km/h", "wind_direction_10m": "°", "wind_gusts_10m": "km/h", "precipitation": "mm",
    "cloud_cover": "%", "boundary_layer_height": "m", "shortwave_radiation": "W/m²",
}


def unit_key(unit: str | None) -> str | None:
    """Canonical spelling of a unit, or None when it is not one this pipeline understands."""
    if not unit:
        return None
    u = unit.lower().replace("µ", "u").replace("μ", "u").replace("³", "3").replace(" ", "").replace("^", "")
    return {"ug/m3": "ug/m3", "mg/m3": "mg/m3", "ppb": "ppb", "ppm": "ppm"}.get(u)


def to_standard(pollutant: str, value: float | None, unit: str | None) -> tuple[float | None, list[str]]:
    """Value in µg/m³ plus flags. Returns (None, ["UNIT_UNKNOWN"]) when no honest conversion exists."""
    if value is None or not math.isfinite(value):
        return None, ["NULL_VALUE"]
    key = unit_key(unit)
    if key == "ug/m3":
        return value, []
    if key == "mg/m3":
        return value * 1000.0, ["UNIT_CONVERTED"]
    if key in ("ppb", "ppm") and pollutant in MOLAR_MASS:
        ppb = value * (1000.0 if key == "ppm" else 1.0)
        return ppb * MOLAR_MASS[pollutant] / MOLAR_VOLUME_L, ["UNIT_CONVERTED"]
    return None, ["UNIT_UNKNOWN"]  # e.g. PM in ppb, or a unit we have never seen


def range_flags(pollutant: str, value_std: float) -> list[str]:
    lo, hi = RANGE_STD[pollutant]
    if value_std < 0:
        return ["NEGATIVE"]
    return ["OUT_OF_RANGE"] if value_std > hi or value_std < lo else []
