"""Shadow mode: ask Jev the routing question beside the deterministic router, record both, and never let Jev influence an answer.

What leaves the machine: only the user's question text (already length-limited by the chat API), as the `state` of one
`choice` question whose options are the fixed category descriptions in routing.py. No measurements, retrieved text, identities
or conversation history are sent. Records are kept locally in SQLite (`DATA_DIR/jev_shadow.sqlite`); the question is stored truncated.
"""

import asyncio
import logging
import sqlite3
import threading
import time
from pathlib import Path

from app.core.config import Settings
from app.jev.client import ChoiceAnswer, JevClient, JevError, choice_question
from app.jev.routing import CATEGORIES, deterministic_route

logger = logging.getLogger("app.jev")
INSTRUCTIONS = "Which kind of request is this message to an environmental-monitoring assistant?"

SCHEMA = """
create table if not exists shadow (
  id integer primary key autoincrement, ts text not null, question text, deterministic text not null, jev text, confidence real,
  agree integer, latency_ms integer, status text not null, error_kind text
);
"""


class ShadowRecorder:
    def __init__(self, path: str | Path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    def add(self, question: str, deterministic: str, jev: str | None, confidence: float | None, latency_ms: int | None, status: str, error_kind: str | None):
        with self._lock:
            self._db.execute("insert into shadow (ts, question, deterministic, jev, confidence, agree, latency_ms, status, error_kind) values (datetime('now'),?,?,?,?,?,?,?,?)",
                             (question[:200], deterministic, jev, confidence, None if jev is None else int(jev == deterministic), latency_ms, status, error_kind))
            self._db.commit()

    def summary(self) -> dict:
        with self._lock:
            rows = [dict(r) for r in self._db.execute("select * from shadow").fetchall()]
        ok = [r for r in rows if r["status"] == "ok"]
        agree = [r for r in ok if r["agree"] == 1]
        lat = sorted(r["latency_ms"] for r in ok if r["latency_ms"] is not None)
        confusion: dict[str, dict[str, int]] = {}
        for r in ok:
            confusion.setdefault(r["deterministic"], {}).setdefault(r["jev"], 0)
            confusion[r["deterministic"]][r["jev"]] += 1
        return {
            "records": len(rows), "answered": len(ok), "failed": len(rows) - len(ok),
            "failure_rate": None if not rows else (len(rows) - len(ok)) / len(rows),
            "agreement_with_deterministic": None if not ok else len(agree) / len(ok),
            "latency_ms": None if not lat else {"median": lat[len(lat) // 2], "max": lat[-1]},
            "failure_kinds": {k: sum(1 for r in rows if r["error_kind"] == k) for k in {r["error_kind"] for r in rows if r["error_kind"]}},
            "confusion_deterministic_to_jev": confusion,
            "note": "Agreement with the deterministic router is not accuracy: neither is ground truth. Use the labelled evaluation for that. Jev's confidence values are not assumed to be calibrated.",
        }


def make_client(settings: Settings) -> JevClient:
    if settings.jev_backend.strip().lower() == "typesafe":
        return JevClient(settings)
    from app.jev.laya_client import LayaClient

    return LayaClient(settings)


class ShadowService:
    def __init__(self, settings: Settings, client: JevClient | None = None, recorder: ShadowRecorder | None = None):
        self.client = client or make_client(settings)
        self.recorder = recorder or ShadowRecorder(Path(settings.data_dir) / "jev_shadow.sqlite")
        self._s = settings

    @property
    def active(self) -> bool:
        return self.client.enabled

    async def decide(self, question: str) -> tuple[str, float]:
        res = await self.client.ask(question, {"route": choice_question(INSTRUCTIONS, CATEGORIES)})
        a = res.answers["route"]
        assert isinstance(a, ChoiceAnswer)
        return a.choice, a.confidence

    async def observe(self, question: str) -> None:
        """Fire-and-forget: never raises, never delays or alters the answer."""
        det = deterministic_route(question)
        started = time.perf_counter()
        try:
            choice, conf = await asyncio.wait_for(self.decide(question), timeout=self._s.jev_timeout_s * max(1, self._s.jev_max_attempts) + 2)
            self.recorder.add(question, det, choice, conf, round((time.perf_counter() - started) * 1000), "ok", None)
        except JevError as exc:
            self.recorder.add(question, det, None, None, round((time.perf_counter() - started) * 1000), "failed", exc.kind)
        except Exception as exc:  # noqa: BLE001 - shadow mode must never affect the product
            logger.warning("Jev shadow observation failed: %s", type(exc).__name__)
            self.recorder.add(question, det, None, None, None, "failed", "internal")
