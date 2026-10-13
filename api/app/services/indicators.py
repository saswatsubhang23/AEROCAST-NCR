"""Simple descriptive indicators derived arithmetically from weather-model values.

These are NOT measurements and NOT classifications. They apply no thresholds and attach no risk labels; each is a
plain quantity with a stated definition. A missing input yields a missing output, never a guess.
"""

RAIN_THRESHOLD_MM = 0.1


def ventilation_index(blh_m: list[float | None], wind_kmh: list[float | None]) -> list[float | None]:
    """Boundary-layer height (m) x 10 m wind speed (m/s) = m²/s.

    The surface wind is only a proxy for the mean wind through the mixed layer, so this is a rough guide to how
    strongly the air near the ground is being mixed and carried away, not a transport calculation.
    """
    return [
        None if h is None or w is None else round(h * (w / 3.6), 1)
        for h, w in zip(blh_m, wind_kmh)
    ]


def hours_since_rain(precip_mm: list[float | None]) -> list[int | None]:
    """Hours since the last hour with at least 0.1 mm, counted within the window only.

    None means unknown: either no rain has been seen yet in the window (it may have rained before it started), or
    an hour with missing precipitation lies between the last rain and now, so a dry spell cannot be confirmed.
    """
    out: list[int | None] = []
    last_rain: int | None = None
    uncertain = False
    for i, p in enumerate(precip_mm):
        if p is None:
            uncertain = True
        elif p >= RAIN_THRESHOLD_MM:
            last_rain, uncertain = i, False
        out.append(None if (last_rain is None or uncertain) else i - last_rain)
    return out
