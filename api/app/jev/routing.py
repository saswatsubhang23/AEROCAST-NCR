"""The assistant-request routing decision that Jev may shadow, and the deterministic baseline it is compared with.

The deterministic router is the product's current behaviour (keyword rules, plus the forecast-intent detector already used by the
assistant). Jev never replaces it: in shadow mode both decisions are recorded and only the deterministic one is used.
"""

import re

from app.assistant.guards import asks_for_pollution_forecast

CATEGORIES: dict[str, str] = {
    "observation_question": "Asks what the measured air quality or weather is or was (current, latest, past, a station, a comparison of places).",
    "forecast_request": "Asks what air quality or weather will be in the future.",
    "weather_pollution_relationship": "Asks how weather (wind, humidity, rain, boundary layer, temperature) relates to pollution levels.",
    "document_question": "Asks what a guideline, standard, study or uploaded document says.",
    "report_request": "Asks for a report or summary document to be generated.",
    "health_exposure_question": "Asks about health effects or exposure to pollution in general terms.",
    "other": "Anything else, including greetings or questions outside weather and air quality.",
}

_RULES: list[tuple[str, re.Pattern]] = [
    ("report_request", re.compile(r"\b(report|incident report|summary document|export)\b", re.I)),
    ("health_exposure_question", re.compile(r"\b(health|asthma|exposure|lung|breath|symptom|safe to|mask|children|elderly)\b", re.I)),
    ("document_question", re.compile(r"\b(guideline|standard|naaqs|(?-i:WHO)\b|study|paper|document|uploaded|according to|literature)\b", re.I)),
    ("weather_pollution_relationship", re.compile(r"\b(why|relationship|correlat|affect|influence|cause|due to|boundary layer|inversion|stagnant)\b", re.I)),
    ("observation_question", re.compile(r"\b(pm\s?2\.?5|pm\s?10|no2|so2|ozone|o3|co\b|aqi|air quality|temperature|humidity|wind|rain|weather|latest|current|now|today|yesterday)\b", re.I)),
]


def deterministic_route(question: str) -> str:
    if asks_for_pollution_forecast(question) or re.search(r"\b(tomorrow|next (hour|day|week)|forecast|will (it|the))\b", question, re.I):
        return "forecast_request"
    for name, rx in _RULES:
        if rx.search(question):
            return name
    return "other"
