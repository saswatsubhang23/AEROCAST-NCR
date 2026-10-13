"""Region labels for coverage reports. A region is the nearest of the five NCR city centres the app already knows
(`core/places.py`), if within ZONE_RADIUS_KM; otherwise "Other NCR". This is a reporting convenience, not an
administrative boundary."""

from app.core.places import PLACES, distance_km

ZONE_RADIUS_KM = 30.0
OTHER = "Other NCR"


def zone_of(lat: float, lon: float) -> str:
    best_name, best = OTHER, ZONE_RADIUS_KM
    for name, clat, clon in PLACES.values():
        d = distance_km(lat, lon, clat, clon)
        if d <= best:
            best_name, best = name, d
    return best_name


def agency_of(owner: str | None) -> str:
    o = (owner or "").lower()
    for key, label in (("delhi", "Delhi (DPCC)"), ("uttar pradesh", "Uttar Pradesh (UPPCB)"), ("haryana", "Haryana (HSPCB)"),
                       ("rajasthan", "Rajasthan (RSPCB)"), ("central pollution", "CPCB"), ("india meteorological", "IMD")):
        if key in o:
            return label
    return "Other/unknown"
