"""CPCB National AQI, computed from hourly observations.

Method source: CPCB, "How is AQI Calculated?" (https://airquality.cpcb.gov.in/ccr_docs/How_AQI_Calculated.pdf).
Rules taken from that document:
  * sub-index from the 24-hour average concentration (8-hour for CO and O3) and the health breakpoints;
  * a sub-index needs at least 16 hours of data;
  * overall AQI needs at least three pollutants, one of which is PM2.5 or PM10;
  * overall AQI is the worst sub-index; that pollutant is the dominant one;
  * concentrations are truncated; when the O3 8-hour average exceeds 208 ug/m3 the 1-hour value is used.

The document does not state how complete an 8-hour window must be. We require at least 6 of its 8 hours on top of the
16-hour rule; this is our assumption and is reported with every result.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.schemas.air import AqiPollutant

CATEGORIES = ["Good", "Satisfactory", "Moderately polluted", "Poor", "Very poor", "Severe"]
AQI_BANDS = [(0, 50), (51, 100), (101, 200), (201, 300), (301, 400), (401, 500)]

# pollutant -> (averaging hours, canonical unit, decimals kept after truncation, breakpoints per category).
# A band's upper bound of None means "and above" (the document gives no upper limit for Severe).
BREAKPOINTS: dict[str, tuple[int, str, int, list[tuple[float, float | None]]]] = {
    "pm10": (24, "µg/m³", 0, [(0, 50), (51, 100), (101, 250), (251, 350), (351, 430), (430, None)]),
    "pm25": (24, "µg/m³", 0, [(0, 30), (31, 60), (61, 90), (91, 120), (121, 250), (250, None)]),
    "no2": (24, "µg/m³", 0, [(0, 40), (41, 80), (81, 180), (181, 280), (281, 400), (400, None)]),
    "o3": (8, "µg/m³", 0, [(0, 50), (51, 100), (101, 168), (169, 208), (209, 748), (748, None)]),
    "co": (8, "mg/m³", 1, [(0, 1.0), (1.1, 2.0), (2.1, 10), (10.1, 17), (17.1, 34), (34, None)]),
    "so2": (24, "µg/m³", 0, [(0, 40), (41, 80), (81, 380), (381, 800), (801, 1600), (1600, None)]),
}

MIN_HOURS_FOR_SUB_INDEX = 16  # within the last 24 hours (CPCB)
MIN_HOURS_IN_8H_WINDOW = 6  # AEROCAST assumption; not specified by CPCB

ASSUMPTIONS = [
    "Hourly values are averaged over the 24 hours (8 hours for CO and O3) ending at the latest observed hour.",
    f"At least {MIN_HOURS_FOR_SUB_INDEX} valid hourly values in the last 24 hours are required per pollutant (CPCB).",
    f"For CO and O3, at least {MIN_HOURS_IN_8H_WINDOW} of the last 8 hours must also be valid (AEROCAST assumption: "
    "CPCB does not state the 8-hour completeness).",
    "Concentrations reported in ppm/ppb are not converted (that needs temperature and pressure), so those pollutants "
    "are excluded; CO reported in µg/m³ is converted exactly to mg/m³.",
]

_UG = {"µg/m³", "μg/m³", "ug/m3", "µg/m3", "μg/m3", "ug/m³"}
_MG = {"mg/m³", "mg/m3"}


def normalize_unit(pollutant: str, unit: str | None, value: float) -> tuple[float | None, str | None]:
    """Return (value in the unit CPCB requires, None) or (None, reason it cannot be used)."""
    canonical = BREAKPOINTS[pollutant][1]
    u = (unit or "").strip().lower().replace(" ", "")
    is_ug = u in {x.lower() for x in _UG}
    is_mg = u in {x.lower() for x in _MG}
    if canonical == "µg/m³":
        if is_ug:
            return value, None
    else:  # mg/m³ (CO)
        if is_mg:
            return value, None
        if is_ug:
            return value / 1000.0, None
    return None, f"unit '{unit}' cannot be used without conversion assumptions (CPCB needs {canonical})"


def _truncate(value: float, decimals: int) -> float:
    f = 10**decimals
    return int(value * f + 1e-9) / f


def sub_index(pollutant: str, concentration: float) -> tuple[int, str, bool]:
    """CPCB linear sub-index. Returns (value, category, lower_bound_only)."""
    _, _, decimals, bps = BREAKPOINTS[pollutant]
    c = _truncate(concentration, decimals)
    for i, (lo, hi) in enumerate(bps):
        ilo, ihi = AQI_BANDS[i]
        if hi is None:
            # Open-ended Severe band: the document gives no upper breakpoint, so only "at least 401" is known.
            return ilo, CATEGORIES[i], True
        if c <= hi:
            value = (ihi - ilo) / (hi - lo) * (c - lo) + ilo
            return round(value), CATEGORIES[i], False
    raise AssertionError("unreachable")  # the last band is open-ended


@dataclass
class Hourly:
    end: datetime  # hour-ending timestamp, UTC
    value: float | None


def _window(rows: Sequence[Hourly], anchor: datetime, hours: int) -> list[float]:
    start = anchor - timedelta(hours=hours)
    return [r.value for r in rows if r.value is not None and start < r.end <= anchor]


def pollutant_result(pollutant: str, rows: Sequence[Hourly], unit: str | None, anchor: datetime) -> AqiPollutant:
    avg_hours = BREAKPOINTS[pollutant][0]
    averaging = "24h" if avg_hours == 24 else "8h"

    def excluded(reason: str, valid: int = 0, average: float | None = None) -> AqiPollutant:
        return AqiPollutant(
            pollutant=pollutant, used=False, reason=reason, averaging=averaging, average=average,
            unit=BREAKPOINTS[pollutant][1], valid_hours=valid, sub_index=None, category=None,
        )

    converted: list[Hourly] = []
    for r in rows:
        if r.value is None:
            converted.append(r)
            continue
        v, why = normalize_unit(pollutant, unit, r.value)
        if why:
            return excluded(why)
        converted.append(Hourly(r.end, v))

    day = _window(converted, anchor, 24)
    if len(day) < MIN_HOURS_FOR_SUB_INDEX:
        return excluded(f"only {len(day)} valid hours in the last 24 (need {MIN_HOURS_FOR_SUB_INDEX})", len(day))

    note = None
    if avg_hours == 24:
        concentration = sum(day) / len(day)
        valid = len(day)
    else:
        window = _window(converted, anchor, 8)
        if len(window) < MIN_HOURS_IN_8H_WINDOW:
            return excluded(f"only {len(window)} valid hours in the last 8 (need {MIN_HOURS_IN_8H_WINDOW})", len(window))
        concentration = sum(window) / len(window)
        valid = len(window)
        if pollutant == "o3" and _truncate(concentration, 0) > 208:
            latest = next((r.value for r in converted if r.end == anchor and r.value is not None), None)
            if latest is None:
                return excluded("8-hour O3 average exceeds 208 µg/m³ and no 1-hour value exists for the latest hour", valid, concentration)
            note = "8-hour average exceeded 208 µg/m³, so the 1-hour value was used (CPCB rule)"
            concentration = latest

    idx, category, lower = sub_index(pollutant, concentration)
    return AqiPollutant(
        pollutant=pollutant, used=True, reason=None, averaging=averaging, average=round(concentration, 2),
        unit=BREAKPOINTS[pollutant][1], valid_hours=valid, sub_index=idx, category=category,
        lower_bound_only=lower, note=note,
    )


def category_for(aqi: int) -> str:
    for (lo, hi), name in zip(AQI_BANDS, CATEGORIES):
        if aqi <= hi:
            return name
    return CATEGORIES[-1]


@dataclass
class AqiComputation:
    status: str
    aqi: int | None
    category: str | None
    lower_bound_only: bool
    dominant: str | None
    reason: str | None
    pollutants: list[AqiPollutant]


def compute_aqi(
    data: dict[str, tuple[Sequence[Hourly], str | None]],
    anchor: datetime,
) -> AqiComputation:
    """`data` maps pollutant -> (hourly rows, source unit). Pollutants without a sensor are simply absent."""
    results = [pollutant_result(p, rows, unit, anchor) for p, (rows, unit) in data.items() if p in BREAKPOINTS]
    used = [r for r in results if r.used]
    particulate = any(r.pollutant in ("pm25", "pm10") for r in used)

    if len(used) < 3 or not particulate:
        if len(used) < 3:
            why = f"only {len(used)} pollutant(s) have sufficient data; CPCB requires at least 3"
        else:
            why = "neither PM2.5 nor PM10 has sufficient data; CPCB requires one of them"
        return AqiComputation("insufficient_data", None, None, False, None, why, results)

    worst = max(used, key=lambda r: (r.sub_index or 0, not r.lower_bound_only))
    assert worst.sub_index is not None
    return AqiComputation(
        "available", worst.sub_index, category_for(worst.sub_index), worst.lower_bound_only,
        worst.pollutant, None, results,
    )
