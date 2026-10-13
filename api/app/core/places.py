"""The Delhi-NCR cities the application knows about: name and reference centre coordinates (fixed geography)."""

import math

PLACES: dict[str, tuple[str, float, float]] = {
    "delhi": ("Delhi", 28.6139, 77.209),
    "gurugram": ("Gurugram", 28.4595, 77.0266),
    "noida": ("Noida", 28.5355, 77.391),
    "ghaziabad": ("Ghaziabad", 28.6692, 77.4538),
    "faridabad": ("Faridabad", 28.4089, 77.3178),
}
ALIASES = {"new delhi": "delhi", "gurgaon": "gurugram", "greater noida": "noida"}
STATION_RADIUS_KM = 20.0
POLLUTANT_LABELS = {"pm25": "PM2.5", "pm10": "PM10", "no2": "NO₂", "so2": "SO₂", "co": "CO", "o3": "O₃"}


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))
