from datetime import datetime

from app.core.time import to_ist


def ist(dt: datetime) -> str:
    return to_ist(dt).strftime("%a %d %b %H:%M IST")


def r1(x: float | None, nd: int = 1) -> float | None:
    return None if x is None else round(x, nd)
