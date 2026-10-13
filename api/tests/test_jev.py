"""Jev client, shadow mode and evaluation harness. All network traffic is a mock transport; no test calls the real service."""

import asyncio
import json
import logging

import httpx
import pytest

from app.core.config import Settings, get_settings
from app.jev import evaluate as ev
from app.jev.client import JevClient, JevDisabled, JevError, choice_question, noul_question
from app.jev.routing import CATEGORIES, deterministic_route
from app.jev.shadow import ShadowRecorder, ShadowService

KEY = "sk-test-super-secret-key"


def settings(**over) -> Settings:
    return Settings(**{**get_settings().model_dump(), "jev_mode": "shadow", "typesafe_api_key": KEY, "jev_max_attempts": 2, **over})


class Fake:
    """A TypeSafe-shaped server: GET /v1/models and POST /v1/systemone."""

    def __init__(self, answer=None, status=200, models=("jev-latest",), fail_times=0, retry_after="0"):
        self.calls: list[httpx.Request] = []
        self.answer, self.status, self.models, self.fail_times, self.retry_after = answer, status, models, fail_times, retry_after

    def __call__(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        if req.headers.get("authorization") != f"Bearer {KEY}":
            return httpx.Response(403, json={"detail": {"error_type": "authentication_error"}})
        if len(self.calls) <= self.fail_times:
            return httpx.Response(self.status, headers={"retry-after": self.retry_after})
        if req.method == "GET" and req.url.path == "/v1/models":
            return httpx.Response(200, json={"models": [{"name": m, "description": "d", "release_date": "2026-09-15"} for m in self.models]})
        if req.method == "POST" and req.url.path == "/v1/systemone":
            body = json.loads(req.content)
            answers = self.answer(body) if callable(self.answer) else self.answer
            return httpx.Response(200, json={"model": body["model"], "answers": answers, "usage": {"input_tokens": 10, "output_tokens": 2}})
        return httpx.Response(404)

    def client(self, **over) -> JevClient:
        return JevClient(settings(**over), transport=httpx.MockTransport(self))

    def posts(self):
        return [c for c in self.calls if c.method == "POST"]


def route_answer(choice="observation_question", confidence=0.9):
    return lambda body: {"route": {"type": "choice", "choice": choice, "confidence": confidence, "probabilities": {choice: confidence}}}


# ---------------------------------------------------------------------------------------------- client
async def test_kill_switch_means_no_network_at_all():
    fake = Fake(route_answer())
    c = fake.client(jev_mode="off")
    with pytest.raises(JevDisabled):
        await c.ask("hi", {"route": noul_question("x")})
    with pytest.raises(JevDisabled):
        await c.models()
    assert fake.calls == [] and c.enabled is False


async def test_without_a_key_nothing_is_sent():
    fake = Fake(route_answer())
    c = fake.client(typesafe_api_key="")
    with pytest.raises(JevError) as e:
        await c.ask("hi", {"route": noul_question("x")})
    assert e.value.kind == "not_configured" and fake.calls == []


async def test_requests_follow_the_documented_shape_and_use_bearer_auth():
    fake = Fake(route_answer())
    c = fake.client()
    q = {"route": choice_question("Which?", {"observation_question": "a", "other": "b"})}
    res = await c.ask("What is PM2.5 now?", q)
    assert [r.method + " " + r.url.path for r in fake.calls] == ["GET /v1/models", "POST /v1/systemone"]  # the model name is discovered, not guessed
    body = json.loads(fake.posts()[0].content)
    assert body == {"state": "What is PM2.5 now?", "model": "jev-latest", "questions": q}
    assert res.model == "jev-latest" and res.answers["route"].choice == "observation_question" and res.usage.input_tokens == 10


async def test_a_configured_model_skips_discovery():
    fake = Fake(route_answer())
    await fake.client(jev_model="my-alias").ask("q", {"route": choice_question("?", {"observation_question": "x"})})
    assert [c.method for c in fake.calls] == ["POST"] and json.loads(fake.calls[0].content)["model"] == "my-alias"


async def test_the_key_never_appears_in_logs_or_errors(caplog):
    caplog.set_level(logging.DEBUG)
    fake = Fake(route_answer(), status=500, fail_times=5)
    with pytest.raises(JevError) as e:
        await fake.client(jev_model="m").ask("q", {"route": choice_question("?", {"observation_question": "x"})})
    assert KEY not in caplog.text and KEY not in e.value.message and KEY not in repr(e.value)


@pytest.mark.parametrize("answers", [
    {"route": {"type": "choice", "choice": "made_up_option", "confidence": 0.9, "probabilities": {"made_up_option": 0.9}}},  # not offered
    {"route": {"type": "noul", "noul": 0.5}},  # wrong type for the question
    {"other": {"type": "noul", "noul": 0.5}},  # the asked question is missing
    {"route": {"type": "choice", "choice": "observation_question", "confidence": 1.4, "probabilities": {"observation_question": 1.0}}},  # out of range
    {"route": {"type": "choice", "choice": "observation_question", "confidence": 0.9}},  # missing probabilities
])
async def test_answers_that_do_not_match_the_question_are_rejected_not_repaired(answers):
    fake = Fake(answers)
    with pytest.raises(JevError) as e:
        await fake.client(jev_model="m").ask("q", {"route": choice_question("?", {"observation_question": "x"})})
    assert e.value.kind == "bad_response"


async def test_unknown_fields_in_a_valid_answer_are_ignored():
    fake = Fake(lambda b: {"route": {"type": "choice", "choice": "other", "confidence": 0.5, "probabilities": {"other": 1.0}, "extra": "ignored"}})
    res = await fake.client(jev_model="m").ask("q", {"route": choice_question("?", {"other": "x"})})
    assert res.answers["route"].choice == "other"


async def test_a_rejected_key_is_not_retried():
    fake = Fake(route_answer())
    c = JevClient(settings(typesafe_api_key="wrong", jev_model="m"), transport=httpx.MockTransport(fake))
    with pytest.raises(JevError) as e:
        await c.ask("q", {"route": choice_question("?", {"other": "x"})})
    assert e.value.kind == "auth" and len(fake.calls) == 1


async def test_rate_limits_are_retried_once_within_bounds_then_succeed():
    fake = Fake(route_answer(), status=429, fail_times=1, retry_after="0")
    c = fake.client(jev_model="m")
    res = await c.ask("q", {"route": choice_question("?", {"observation_question": "x"})})
    assert res.answers["route"].choice == "observation_question" and c.stats["rate_limited"] == 1 and len(fake.calls) == 2


async def test_server_errors_are_bounded_and_reported():
    fake = Fake(route_answer(), status=503, fail_times=10)
    c = fake.client(jev_model="m", jev_max_attempts=2)
    with pytest.raises(JevError) as e:
        await c.ask("q", {"route": choice_question("?", {"other": "x"})})
    assert e.value.kind == "server_error" and len(fake.calls) == 2 and c.stats["failures"] == 1


async def test_a_bad_request_response_is_not_retried():
    fake = Fake(route_answer(), status=422, fail_times=10)
    with pytest.raises(JevError) as e:
        await fake.client(jev_model="m").ask("q", {"route": choice_question("?", {"other": "x"})})
    assert e.value.kind == "bad_request" and len(fake.calls) == 1


async def test_timeouts_and_unreachable_hosts_become_typed_errors():
    def boom(req):
        raise httpx.ConnectTimeout("slow")

    c = JevClient(settings(jev_model="m"), transport=httpx.MockTransport(boom))
    with pytest.raises(JevError) as e:
        await c.ask("q", {"route": choice_question("?", {"other": "x"})})
    assert e.value.kind == "timeout"
    c2 = JevClient(settings(jev_model="m"), transport=httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("down"))))
    with pytest.raises(JevError) as e2:
        await c2.ask("q", {"route": choice_question("?", {"other": "x"})})
    assert e2.value.kind == "unreachable"


async def test_an_account_with_no_models_is_an_error_not_a_guess():
    fake = Fake(route_answer(), models=())
    with pytest.raises(JevError) as e:
        await fake.client().ask("q", {"route": choice_question("?", {"other": "x"})})
    assert e.value.kind == "no_models"


# ---------------------------------------------------------------------------------------------- shadow mode
def service(fake: Fake, tmp_path, **over) -> ShadowService:
    s = settings(data_dir=str(tmp_path), jev_model="m", **over)
    return ShadowService(s, JevClient(s, transport=httpx.MockTransport(fake)), ShadowRecorder(tmp_path / "shadow.sqlite"))


async def test_shadow_records_both_decisions_and_the_agreement(tmp_path):
    svc = service(Fake(route_answer("observation_question", 0.8)), tmp_path)
    await svc.observe("What is the latest PM2.5 in Delhi?")
    await svc.observe("Will it rain tomorrow?")  # deterministic: forecast_request; Jev (fake) says observation_question
    s = svc.recorder.summary()
    assert s["records"] == 2 and s["answered"] == 2 and s["agreement_with_deterministic"] == 0.5 and s["failure_rate"] == 0
    assert s["confusion_deterministic_to_jev"]["forecast_request"]["observation_question"] == 1 and "not accuracy" in s["note"]


async def test_shadow_never_raises_and_records_failures(tmp_path):
    svc = service(Fake(route_answer(), status=503, fail_times=99), tmp_path)
    await svc.observe("anything")  # must not raise
    s = svc.recorder.summary()
    assert s["failed"] == 1 and s["failure_kinds"] == {"server_error": 1} and s["agreement_with_deterministic"] is None


async def test_shadow_is_inactive_when_off_or_without_a_key(tmp_path):
    assert service(Fake(route_answer()), tmp_path, jev_mode="off").active is False
    assert service(Fake(route_answer()), tmp_path, typesafe_api_key="").active is False
    assert service(Fake(route_answer()), tmp_path).active is True


async def test_only_the_question_text_is_sent_and_stored_truncated(tmp_path):
    fake = Fake(route_answer())
    svc = service(fake, tmp_path)
    q = "PM2.5 in Delhi? " + "x" * 400
    await svc.observe(q)
    body = json.loads(fake.posts()[0].content)
    assert body["state"] == q and set(body) == {"state", "model", "questions"} and list(body["questions"]) == ["route"]
    assert set(body["questions"]["route"]["criteria"]) == set(CATEGORIES)
    assert len(svc.recorder._db.execute("select question from shadow").fetchone()[0]) == 200


async def test_shadow_does_not_change_the_assistants_answer(tmp_path):
    from test_assistant import FakeOllama, ask, build, call, say  # reuse the assistant test harness

    rounds = lambda: FakeOllama([call(("get_weather_observations", {"location": "Delhi", "hours": 6})), say("Delhi is at ", "30.6 °C right now [W1].")])  # noqa: E731
    plain = await ask(build(rounds()), "What is the temperature in Delhi?")
    shadowed_orch = build(rounds())
    svc = service(Fake(route_answer()), tmp_path)
    shadowed_orch._shadow = svc
    shadowed = await ask(shadowed_orch, "What is the temperature in Delhi?")
    await asyncio.sleep(0.2)
    strip = lambda ev_: [{k: v for k, v in e.items() if k not in ("duration_ms", "finished_at")} for e in ev_]  # noqa: E731
    assert strip(plain) == strip(shadowed)
    assert svc.recorder.summary()["records"] == 1


# ---------------------------------------------------------------------------------------------- routing and evaluation
@pytest.mark.parametrize("q,expected", [
    ("What is the PM2.5 in Delhi right now?", "observation_question"), ("Will PM2.5 rise tomorrow?", "forecast_request"),
    ("Generate a report for Noida", "report_request"), ("What does the WHO guideline say?", "document_question"),
    ("Hello, who are you?", "other"), ("Is it safe for children to go out?", "health_exposure_question"),
])
def test_deterministic_router_examples(q, expected):
    assert deterministic_route(q) == expected


async def test_the_evaluation_harness_scores_both_routers_and_counts_fallbacks():
    labels = dict(ev.EXAMPLES)

    async def perfect(q):
        return labels[q], 0.95

    async def flaky(q):
        if len(q) % 3 == 0:
            raise JevError("down", "timeout")
        return "other", 0.4

    good = await ev.evaluate(perfect)
    assert good["jev"]["accuracy_on_answered"] == 1.0 and good["fallback_rate"] == 0 and good["deterministic"]["n"] == len(ev.EXAMPLES)
    assert good["deterministic"]["accuracy_on_answered"] > 0.8 and "not ground truth" in good["labels_note"]
    bad = await ev.evaluate(flaky)
    assert 0 < bad["fallback_rate"] < 1 and bad["errors"]["timeout"] > 0 and bad["jev"]["failed"] == bad["errors"]["timeout"]
    assert "not assumed calibrated" in bad["calibration_note"]


def test_every_category_has_labelled_examples_and_none_are_environmental_data():
    import re
    assert {l for _, l in ev.EXAMPLES} == set(CATEGORIES)
    assert not any(re.search(r"\d+(\.\d+)?\s*(µg|ug|ppb|ppm|°|mg|%)", q) for q, _ in ev.EXAMPLES)  # no measurement values in the examples


# ---------------------------------------------------------------------------------------------- API
def test_status_is_off_by_default_and_never_returns_the_key(client, monkeypatch):
    s = client.get("/api/jev/status").json()
    assert s["mode"] == "off" and s["enabled"] is False and s["influences_answers"] is False and "Switched off" in s["message"]
    monkeypatch.setenv("TYPESAFE_API_KEY", KEY)
    monkeypatch.setenv("JEV_MODE", "shadow")
    monkeypatch.setenv("JEV_BACKEND", "typesafe")
    get_settings.cache_clear()
    raw = client.get("/api/jev/status").text
    assert KEY not in raw and json.loads(raw)["api_key_configured"] is True and "Only the user's question text" in raw


def test_laya_is_the_default_backend_and_sends_nothing_off_the_machine(client, monkeypatch):
    monkeypatch.setenv("JEV_MODE", "shadow")
    get_settings.cache_clear()
    s = client.get("/api/jev/status").json()
    assert s["backend"] == "laya (local)" and s["base_url"] is None and "Nothing" in s["sent_to_service"] and s["influences_answers"] is False


class _FakeAgent:
    def predict(self, state, questions):
        return {"model": "laya-rl-agent", "usage": {"input_tokens": 3, "output_tokens": 0},
                "answers": {"route": {"type": "choice", "choice": "air", "confidence": 0.5, "probabilities": {"weather": 0.2, "air": 0.8}}}}


@pytest.mark.asyncio
async def test_laya_client_validates_answers_like_the_remote_client(monkeypatch):
    from app.jev.client import JevError
    from app.jev.laya_client import LayaClient

    monkeypatch.setenv("JEV_MODE", "shadow")
    get_settings.cache_clear()
    c = LayaClient(get_settings())
    c._agent = _FakeAgent()
    q = {"route": choice_question("which?", {"weather": "w", "air": "a"})}
    assert (await c.ask("PM2.5 in Delhi?", q)).answers["route"].choice == "air"
    with pytest.raises(JevError) as e:  # an option that was not offered is rejected, never passed on
        await c.ask("x", {"route": choice_question("which?", {"weather": "w", "other": "o"})})
    assert e.value.kind == "bad_response"
    c2 = LayaClient(get_settings())
    c2._load_error = "OSError"
    with pytest.raises(JevError) as e2:
        await c2.ask("x", q)
    assert e2.value.kind == "unavailable"


def test_shadow_summary_is_empty_without_records(client):
    s = client.get("/api/jev/shadow").json()
    assert s["records"] == 0 and s["agreement_with_deterministic"] is None
