"""Vertical temperature profile from model pressure-level data, with inversion detection."""

from datetime import datetime

from app.schemas.weather import Inversion, ProfileHour, ProfilePoint

SURFACE_SENSOR_HEIGHT_M = 2.0  # temperature_2m is valid at 2 m above ground


def build_profile_hours(
    times: list[datetime],
    series: dict[str, list[float | None]],
    elevation_m: float | None,
    levels: list[int],
    lo: int,
    hi: int,
) -> list[ProfileHour]:
    hours: list[ProfileHour] = []
    for i in range(lo, hi):
        points = _hour_points(series, elevation_m, levels, i)
        hours.append(ProfileHour(time=times[i], points=points, inversions=find_inversions(points)))
    return hours


def _hour_points(series, elevation_m, levels, i) -> list[ProfilePoint]:
    def at(key: str) -> float | None:
        values = series.get(key)
        return values[i] if values else None

    points: list[ProfilePoint] = []
    t2m = at("temperature_2m")
    if t2m is not None:
        points.append(ProfilePoint(pressure_hpa=None, height_agl_m=SURFACE_SENSOR_HEIGHT_M, temperature_c=t2m))
    surface_p = at("surface_pressure")
    if surface_p is None or elevation_m is None:
        # Without surface pressure and elevation we cannot tell which levels are underground.
        return points
    for level in sorted(levels, reverse=True):
        temp, gph = at(f"temperature_{level}hPa"), at(f"geopotential_height_{level}hPa")
        # Levels with pressure >= surface pressure are below ground: the model extrapolates them.
        if temp is None or gph is None or level >= surface_p:
            continue
        agl = gph - elevation_m
        if agl <= SURFACE_SENSOR_HEIGHT_M:
            continue
        points.append(ProfilePoint(pressure_hpa=float(level), height_agl_m=round(agl, 1), temperature_c=temp))
    return sorted(points, key=lambda p: p.height_agl_m)


def find_inversions(points: list[ProfilePoint]) -> list[Inversion]:
    """An inversion is a stretch where temperature rises with height between consecutive points."""
    found: list[Inversion] = []
    start = None
    for a, b in zip(points, points[1:]):
        if b.temperature_c > a.temperature_c:
            start = start or a
            end = b
        else:
            if start is not None:
                found.append(_make(start, end))
            start = None
    if start is not None:
        found.append(_make(start, end))
    return found


def _make(a: ProfilePoint, b: ProfilePoint) -> Inversion:
    return Inversion(
        base_agl_m=a.height_agl_m, top_agl_m=b.height_agl_m,
        strength_c=round(b.temperature_c - a.temperature_c, 1),
    )
