"""Research metadata for a document: which pollutants and places it is about, and (for tables) what period it covers.

This is plain pattern matching on the text, not interpretation. A document that mentions "ozone" is tagged `o3`; that says
the word appears, not that the document is a good source on ozone. The counts are kept so the tag can be judged.
"""

from __future__ import annotations

import re

from app.core.places import ALIASES, PLACES

_POLLUTANTS = {
    "pm25": re.compile(r"pm\s?2\.?5|pm[₂]\.?[₅]|fine\s+particulate|particulate\s+matter\s*\(?pm\s?2", re.I),
    "pm10": re.compile(r"pm\s?10|pm[₁][₀]|coarse\s+particulate", re.I),
    "no2": re.compile(r"\bno\s?2\b|\bno[₂]|nitrogen\s+dioxide", re.I),
    "so2": re.compile(r"\bso\s?2\b|\bso[₂]|sulph?ur\s+dioxide", re.I),
    "o3": re.compile(r"\bo\s?3\b|\bo[₃]|\bozone\b", re.I),
    "co": re.compile(r"\bCO\b|carbon\s+monoxide"),
}
_TOPICS = {
    "stubble burning": re.compile(r"stubble|crop\s+residue|paddy\s+straw|biomass\s+burning", re.I),
    "fireworks": re.compile(r"firework|firecracker|diwali", re.I),
    "vehicles": re.compile(r"vehicular|vehicle|traffic|transport\s+sector", re.I),
    "industry": re.compile(r"industr|power\s+plant|thermal\s+power", re.I),
    "construction dust": re.compile(r"construction|road\s+dust|resuspen", re.I),
    "meteorology": re.compile(r"inversion|boundary\s+layer|mixing\s+height|wind\s+speed|ventilation", re.I),
    "health": re.compile(r"health|mortality|asthma|exposure", re.I),
    "standards": re.compile(r"naaqs|guideline|standard|permissible\s+limit", re.I),
}
_PLACE_WORDS = {name.lower(): key for key, (name, _, _) in PLACES.items()}
_PLACE_WORDS.update(ALIASES)
_PLACE_RX = re.compile(r"\b(" + "|".join(sorted((re.escape(w) for w in _PLACE_WORDS), key=len, reverse=True)) + r")\b", re.I)
_NCR = re.compile(r"\bNCR\b|national\s+capital\s+region", re.I)


def text_meta(text: str) -> dict:
    """Pollutants, places and topics mentioned in `text`, with how many times."""
    pollutants = {k: len(rx.findall(text)) for k, rx in _POLLUTANTS.items()}
    topics = {k: len(rx.findall(text)) for k, rx in _TOPICS.items()}
    places: dict[str, int] = {}
    for m in _PLACE_RX.finditer(text):
        key = _PLACE_WORDS[m.group(1).lower()]
        places[PLACES[key][0]] = places.get(PLACES[key][0], 0) + 1
    if _NCR.search(text):
        places["NCR"] = len(_NCR.findall(text))
    return {
        "pollutants": sorted((k for k, n in pollutants.items() if n), key=lambda k: -pollutants[k]),
        "pollutant_mentions": {k: n for k, n in pollutants.items() if n},
        "places": sorted(places, key=lambda k: -places[k]),
        "topics": sorted((k for k, n in topics.items() if n >= 2), key=lambda k: -topics[k]),
    }


def table_meta(profile: dict, text_sample: str) -> dict:
    """Metadata for a table: the text-derived tags plus what the columns and timestamps say."""
    meta = text_meta(text_sample)
    for key in profile.get("pollutant_columns", {}):
        if key not in meta["pollutants"]:
            meta["pollutants"].append(key)
    meta.update(
        kind="table", rows=profile["rows"], columns=[c["name"] for c in profile["columns"]], period_start=profile.get("time_start"),
        period_end=profile.get("time_end"), resolution=profile.get("resolution"),
    )
    return meta
