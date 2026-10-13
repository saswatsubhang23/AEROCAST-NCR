"""Small, pure calculations over hourly series. Only observed values are used; a gap is never filled."""

from datetime import datetime

from app.reports.models import Rise, SeriesStats, Trend

RISE_SPAN_HOURS = 6
MIN_HOURS_PER_THIRD = 4


def stats(times: list[datetime], values: list[float | None], unit: str | None) -> SeriesStats:
    obs = [(t, v) for t, v in zip(times, values) if v is not None]
    n, total = len(obs), len(values)
    if not obs:
        return SeriesStats(unit=unit, latest=None, latest_time=None, min=None, min_time=None, max=None, max_time=None,
                           mean=None, observed_hours=0, missing_hours=total)
    lo, hi = min(obs, key=lambda x: x[1]), max(obs, key=lambda x: x[1])
    return SeriesStats(
        unit=unit, latest=obs[-1][1], latest_time=obs[-1][0], min=lo[1], min_time=lo[0], max=hi[1], max_time=hi[0],
        mean=sum(v for _, v in obs) / n, observed_hours=n, missing_hours=total - n,
    )


def largest_rise(times: list[datetime], values: list[float | None], span: int = RISE_SPAN_HOURS) -> Rise | None:
    """Largest increase from the lowest observed value in the preceding `span` hours to an observed value."""
    best: Rise | None = None
    for i, v in enumerate(values):
        if v is None:
            continue
        prior = [(values[j], j) for j in range(max(0, i - span), i) if values[j] is not None]
        if not prior:
            continue
        base_v, base_j = min(prior)
        rise = v - base_v
        if rise > 0 and (best is None or rise > best.rise):
            best = Rise(rise=rise, pct=None if base_v == 0 else rise / base_v * 100, from_value=base_v, from_time=times[base_j],
                        to_value=v, to_time=times[i], span_hours=span)
    return best


def trend(values: list[float | None]) -> Trend | None:
    """Mean of the first third of the period against the mean of the last third, using observed hours only. Needs
    enough observations in both thirds, otherwise there is no trend to report."""
    n = len(values)
    if n < 12:
        return None
    third = n // 3
    first = [v for v in values[:third] if v is not None]
    last = [v for v in values[n - third:] if v is not None]
    if len(first) < MIN_HOURS_PER_THIRD or len(last) < MIN_HOURS_PER_THIRD:
        return None
    a, b = sum(first) / len(first), sum(last) / len(last)
    return Trend(first_mean=a, last_mean=b, change=b - a, change_pct=None if a == 0 else (b - a) / a * 100,
                 basis=f"mean of the first {third} h versus the last {third} h of the period (observed hours only)")


def mean_between(times: list[datetime], values: list[float | None], start: datetime | None = None, end: datetime | None = None) -> float | None:
    xs = [v for t, v in zip(times, values) if v is not None and (start is None or t >= start) and (end is None or t <= end)]
    return sum(xs) / len(xs) if xs else None
