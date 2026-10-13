"""Labelled evaluation of routing decisions: deterministic router versus Jev, against hand-written labels.

The examples below are *questions to the assistant*, written and labelled by the developer for this evaluation. They contain no
environmental measurements and no personal data. Labels are one person's judgement, so scores measure agreement with that
judgement, not an objective truth. The harness reports accuracy, per-category precision/recall, failure and fallback rates and
latency. Jev's own confidence values are reported but are not assumed to be calibrated.

Running it against Jev needs TYPESAFE_API_KEY:  python -m app.jev
"""

import asyncio
import json
import sys
import time
from collections.abc import Awaitable, Callable

from app.jev.client import JevError
from app.jev.routing import CATEGORIES, deterministic_route

EXAMPLES: list[tuple[str, str]] = [
    ("What is the PM2.5 in Delhi right now?", "observation_question"), ("Show me the latest air quality at Anand Vihar", "observation_question"),
    ("How windy was it in Noida yesterday?", "observation_question"), ("Compare the AQI of Gurugram and Faridabad", "observation_question"),
    ("What was the temperature this morning?", "observation_question"), ("Which station has the highest PM10 today?", "observation_question"),
    ("Will the air be worse tomorrow in Delhi?", "forecast_request"), ("What will PM2.5 be over the next 24 hours?", "forecast_request"),
    ("Is it going to rain next week?", "forecast_request"), ("Forecast the air quality for Ghaziabad tonight", "forecast_request"),
    ("Will pollution rise next hour?", "forecast_request"), ("What does the weather forecast say for Saturday?", "forecast_request"),
    ("Why does PM2.5 rise on calm nights?", "weather_pollution_relationship"), ("How does the boundary layer height affect pollution?", "weather_pollution_relationship"),
    ("Does humidity influence particulate levels?", "weather_pollution_relationship"), ("What is the relationship between wind speed and PM10?", "weather_pollution_relationship"),
    ("Why is the air stagnant in winter?", "weather_pollution_relationship"), ("Does rain wash pollutants out of the air?", "weather_pollution_relationship"),
    ("What does the WHO guideline say about PM2.5?", "document_question"), ("According to the uploaded study, what were the findings?", "document_question"),
    ("What is the NAAQS limit for PM10?", "document_question"), ("Summarise the guideline document I uploaded", "document_question"),
    ("Which paper discusses crop-residue burning?", "document_question"), ("What does the literature say about ozone and monsoon?", "document_question"),
    ("Generate a report for Delhi for the last 24 hours", "report_request"), ("Create an incident report for Noida", "report_request"),
    ("I need a PDF report on PM2.5 in Faridabad", "report_request"), ("Make a summary document of this week's air quality", "report_request"),
    ("Build a report comparing two stations", "report_request"), ("Export the air-quality report", "report_request"),
    ("Is the air safe for children to play outside?", "health_exposure_question"), ("What are the health effects of long PM2.5 exposure?", "health_exposure_question"),
    ("Should people with asthma avoid going out?", "health_exposure_question"), ("Do masks help against particulate exposure?", "health_exposure_question"),
    ("How does pollution affect the elderly?", "health_exposure_question"), ("What is my exposure to PM2.5 on my commute?", "health_exposure_question"),
    ("Hello, who are you?", "other"), ("Tell me a joke", "other"), ("What is the capital of France?", "other"),
    ("Thanks, that is all", "other"), ("Can you write a poem about rivers?", "other"), ("How do I reset my password?", "other"),
]


def metrics(labels: list[str], preds: list[str | None]) -> dict:
    answered = [(l, p) for l, p in zip(labels, preds) if p is not None]
    per = {}
    for c in CATEGORIES:
        tp = sum(1 for l, p in answered if l == c and p == c)
        fp = sum(1 for l, p in answered if l != c and p == c)
        fn = sum(1 for l, p in answered if l == c and p != c)
        per[c] = {"support": sum(1 for l, _ in answered if l == c), "precision": None if tp + fp == 0 else tp / (tp + fp), "recall": None if tp + fn == 0 else tp / (tp + fn)}
    return {"n": len(labels), "answered": len(answered), "failed": len(labels) - len(answered),
            "accuracy_on_answered": None if not answered else sum(1 for l, p in answered if l == p) / len(answered), "per_category": per}


async def evaluate(decide: Callable[[str], Awaitable[tuple[str, float]]], examples: list[tuple[str, str]] = EXAMPLES, concurrency: int = 2) -> dict:
    labels = [l for _, l in examples]
    det = [deterministic_route(q) for q, _ in examples]
    jev: list[str | None] = [None] * len(examples)
    conf: list[float | None] = [None] * len(examples)
    lat: list[int] = []
    errors: dict[str, int] = {}
    sem = asyncio.Semaphore(concurrency)

    async def one(i: int, q: str):
        async with sem:
            t = time.perf_counter()
            try:
                jev[i], conf[i] = await decide(q)
                lat.append(round((time.perf_counter() - t) * 1000))
            except JevError as exc:
                errors[exc.kind] = errors.get(exc.kind, 0) + 1

    await asyncio.gather(*[one(i, q) for i, (q, _) in enumerate(examples)])
    both = [(d, j) for d, j in zip(det, jev) if j is not None]
    lat.sort()
    right = [c for c, l, j in zip(conf, labels, jev) if j is not None and j == l and c is not None]
    wrong = [c for c, l, j in zip(conf, labels, jev) if j is not None and j != l and c is not None]
    return {
        "examples": len(examples), "labels_note": "labelled by the developer; agreement with one person's judgement, not ground truth",
        "deterministic": metrics(labels, det), "jev": metrics(labels, jev),
        "agreement_between_them": None if not both else sum(1 for d, j in both if d == j) / len(both),
        "fallback_rate": sum(1 for j in jev if j is None) / len(jev), "errors": errors,
        "latency_ms": None if not lat else {"median": lat[len(lat) // 2], "max": lat[-1]},
        "confidence_when_right_mean": None if not right else sum(right) / len(right), "confidence_when_wrong_mean": None if not wrong else sum(wrong) / len(wrong),
        "calibration_note": "Jev's confidence is not assumed calibrated; compare the two means above before relying on it.",
    }


def main() -> int:
    from app.core.config import get_settings
    from app.jev.shadow import ShadowService

    s = get_settings()
    if s.jev_backend.strip().lower() == "typesafe" and not s.typesafe_api_key.get_secret_value():
        print("TYPESAFE_API_KEY is not set; only the deterministic router can be scored.")
        print(json.dumps({"deterministic": metrics([l for _, l in EXAMPLES], [deterministic_route(q) for q, _ in EXAMPLES])}, indent=1))
        return 1
    svc = ShadowService(type(s)(**{**s.model_dump(), "jev_mode": "shadow"}))
    if hasattr(svc.client, "start_loading"):  # local backend: wait for the weights (minutes on first use)
        import time

        svc.client.start_loading()
        while svc.client.state == "loading":
            time.sleep(2)
        if svc.client.state != "ready":
            print("Laya could not be loaded.")
            return 1
    print(json.dumps(asyncio.run(evaluate(svc.decide)), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
