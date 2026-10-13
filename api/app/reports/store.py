"""Generated reports are kept in memory for a while so the page, the PDF and the Markdown download all show the same report.
They are not persisted: after a restart or the expiry time a report must be generated again."""

import threading
import time
from collections import OrderedDict

from app.reports.models import LlmSummary, Report


class ReportStore:
    def __init__(self, max_items: int = 25, ttl_s: int = 2 * 3600, clock=time.monotonic):
        self._items: OrderedDict[str, tuple[float, Report]] = OrderedDict()
        self._max, self._ttl, self._clock = max_items, ttl_s, clock
        self._lock = threading.Lock()

    def _expire(self) -> None:
        now = self._clock()
        for k in [k for k, (t, _) in self._items.items() if now - t > self._ttl]:
            del self._items[k]

    def put(self, report: Report) -> None:
        with self._lock:
            self._expire()
            self._items[report.id] = (self._clock(), report)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def get(self, report_id: str) -> Report | None:
        with self._lock:
            self._expire()
            hit = self._items.get(report_id)
            return hit[1] if hit else None

    def set_summary(self, report_id: str, summary: LlmSummary) -> Report | None:
        with self._lock:
            hit = self._items.get(report_id)
            if hit is None:
                return None
            hit[1].llm_summary = summary
            return hit[1]
