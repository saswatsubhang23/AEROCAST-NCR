"""Alert rules, stored in a small local SQLite file (standard library). All queries are parameterised."""

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.alerts.models import MAX_RULES

SCHEMA = """
create table if not exists alert_rules (
    id integer primary key autoincrement,
    name text not null,
    location_id text not null,
    pollutant text not null,
    operator text not null,
    threshold real not null,
    unit text not null,
    enabled integer not null default 1,
    created_at text not null
)
"""


class TooManyRules(Exception):
    pass


class AlertRuleStore:
    def __init__(self, path: Path | str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute(SCHEMA)
            self._db.commit()

    def list(self) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._db.execute("select * from alert_rules order by id").fetchall()]

    def get(self, rule_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("select * from alert_rules where id = ?", (rule_id,)).fetchone()
        return dict(row) if row else None

    def add(self, name: str, location_id: str, pollutant: str, operator: str, threshold: float, unit: str) -> dict:
        with self._lock:
            if self._db.execute("select count(*) from alert_rules").fetchone()[0] >= MAX_RULES:
                raise TooManyRules()
            cur = self._db.execute(
                "insert into alert_rules (name, location_id, pollutant, operator, threshold, unit, enabled, created_at) "
                "values (?, ?, ?, ?, ?, ?, 1, ?)",
                (name, location_id, pollutant, operator, threshold, unit, datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")),
            )
            self._db.commit()
            return self.get(cur.lastrowid)  # type: ignore[arg-type,return-value]

    def set_enabled(self, rule_id: int, enabled: bool) -> dict | None:
        with self._lock:
            self._db.execute("update alert_rules set enabled = ? where id = ?", (int(enabled), rule_id))
            self._db.commit()
        return self.get(rule_id)

    def delete(self, rule_id: int) -> bool:
        with self._lock:
            cur = self._db.execute("delete from alert_rules where id = ?", (rule_id,))
            self._db.commit()
            return cur.rowcount > 0

    def close(self) -> None:
        with self._lock:
            self._db.close()
