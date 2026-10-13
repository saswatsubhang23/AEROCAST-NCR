"""A small synthetic history store for the ML tests: AR(1) PM2.5 with a daily cycle, plus weather, six stations, ending at the
current hour so request-time inference tests can ask for a forecast "now". Built through the real pipeline (raw -> clean ->
model_ready), so the tests exercise the same tables the real run uses."""

from datetime import datetime, timedelta, timezone

import numpy as np
from histfakes import add_raw, add_sensor, add_station, add_weather_raw, isoz

from app.history import clean, features
from app.history.store import HistoryStore

HOUR = timedelta(hours=1)


def make_history(path: str, hours: int = 1500, stations: int = 6, seed: int = 3, end: datetime | None = None,
                 test_shift: float = 0.0, shift_from_hour: int | None = None) -> tuple[HistoryStore, datetime]:
    """`test_shift` adds a constant to every PM2.5 value from `shift_from_hour` on (used to prove the test period does not
    influence any choice made before it)."""
    end = end or datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - (hours - 1) * HOUR
    rng = np.random.default_rng(seed)
    st = HistoryStore(path)
    labels = [start + i * HOUR for i in range(hours)]
    for s in range(stations):
        sid = 100 + s
        add_station(st, sid, lat=28.60 + 0.01 * s, lon=77.20 + 0.01 * s, name=f"Synthetic {sid}")
        add_sensor(st, 1000 + s, sid, "pm25", first="2020-01-01T00:00:00Z", last="2099-01-01T00:00:00Z")
        x = 60.0 + 8 * s
        wind = rng.uniform(2, 18, hours)
        for i, t in enumerate(labels):
            diurnal = 18 * np.sin(2 * np.pi * (t.hour + 5.5 - 8) / 24)
            x = 0.92 * x + 0.08 * (65 + 8 * s + diurnal - 1.2 * wind[i]) + rng.normal(0, 3)
            v = float(max(5.0, x)) + (test_shift if shift_from_hour is not None and i >= shift_from_hour else 0.0)
            end_ts = isoz(t + timedelta(minutes=30))
            add_raw(st, 1000 + s, sid, "pm25", end_ts, round(v, 1), fetched=isoz(end))
        add_weather_raw(st, sid, [isoz(t) for t in labels], fetched=isoz(end + timedelta(days=30)), wind_speed_10m=10.0)
        # distinct wind per hour so wind features carry information
        for i, t in enumerate(labels):
            st.execute("update raw_weather set wind_speed_10m=?, temperature_2m=? where point_id=? and time_utc=?",
                       (float(wind[i] * 3.6), 20.0 + 8 * np.sin(2 * np.pi * (t.hour - 8) / 24), f"st{sid}", isoz(t)))
    st.commit()
    clean.clean_air(st)
    clean.clean_weather(st)
    features.build_model_ready(st, ["pm25"], now=end)
    return st, end
