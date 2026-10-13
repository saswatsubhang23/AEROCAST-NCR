"""Local backend for the optional decision-support layer: the open `laya` package (Apache-2.0, Convai Innovations).

Laya runs on this machine (PyTorch, CPU by default). The model weights come from the Hugging Face Hub once and are cached; after that
nothing leaves the machine, so unlike the TypeSafe HTTP API no question text is sent anywhere. It answers the same typed questions
(`choice`, `noul`, `score`), so it plugs in behind `JevClient.ask` and every existing check (answer must match the question and name a
real option) applies unchanged. It stays shadow-only: it never influences an answer.

Loading takes minutes on first use, so it happens in a background thread; until it is ready calls fail fast with kind `loading`
and the shadow recorder logs them as failed observations. Torch is imported only here, only when this backend is enabled.
"""

import asyncio
import logging
import threading
import time
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.jev.client import ChoiceAnswer, JevClient, JevError, SystemOneResponse

logger = logging.getLogger("app.jev")


class LayaClient(JevClient):
    def __init__(self, settings: Settings):
        super().__init__(settings)
        self._agent: Any = None
        self._load_error: str | None = None
        self._loading = False
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return self.mode == "shadow"

    @property
    def state(self) -> str:
        return "ready" if self._agent is not None else "failed" if self._load_error else "loading" if self._loading else "not_loaded"

    def _load(self) -> None:
        try:
            import laya  # noqa: PLC0415 - heavy import, only for this backend

            self._agent = laya.load(self._s.laya_model, device="cpu")
        except Exception as exc:  # noqa: BLE001
            self._load_error = type(exc).__name__
            logger.warning("Laya could not be loaded: %s", self._load_error)
        finally:
            self._loading = False

    def start_loading(self) -> None:
        with self._lock:
            if self._agent is None and not self._loading and not self._load_error:
                self._loading = True
                threading.Thread(target=self._load, name="laya-load", daemon=True).start()

    async def model_name(self) -> str:
        return self._s.laya_model

    async def ask(self, state: str | dict | list, questions: dict[str, dict]) -> SystemOneResponse:
        if self.mode == "off":
            from app.jev.client import JevDisabled

            raise JevDisabled()
        if not questions:
            raise ValueError("at least one question is required")
        self.start_loading()
        if self._load_error:
            raise JevError(f"Laya could not be loaded ({self._load_error}).", "unavailable")
        if self._agent is None:
            raise JevError("Laya is still loading its model weights.", "loading")
        self.stats["requests"] += 1
        started = time.perf_counter()
        try:
            raw = await asyncio.to_thread(self._agent.predict, state, questions)
            res = SystemOneResponse.model_validate({"model": raw.get("model") or self._s.laya_model, "answers": raw["answers"], "usage": raw["usage"]})
        except (ValidationError, KeyError, TypeError):
            self.stats["failures"] += 1
            raise JevError("Laya's answer does not match the expected format.", "bad_response") from None
        except Exception as exc:  # noqa: BLE001
            self.stats["failures"] += 1
            raise JevError(f"Laya failed ({type(exc).__name__}).", "error") from None
        for name, q in questions.items():
            a = res.answers.get(name)
            if a is None or a.type != q["type"]:
                self.stats["failures"] += 1
                raise JevError(f"Laya's answer for '{name}' is missing or of the wrong type.", "bad_response")
            if isinstance(a, ChoiceAnswer) and a.choice not in q["criteria"]:
                self.stats["failures"] += 1
                raise JevError(f"Laya chose '{a.choice}', which is not one of the offered options.", "bad_response")
        self.last_latency_ms = round((time.perf_counter() - started) * 1000)
        return res
