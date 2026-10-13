"""Knowledge-base interface used by the assistant's search tool.

`app.kb.service.KnowledgeBaseService` implements it over Chroma. `NullKnowledgeBase` stands in when nothing is
configured. Passage text is untrusted: it came from an uploaded document.
"""

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class KbPassage:
    document: str
    publisher: str
    licence: str
    text: str
    location: str  # human-readable position: "p. 3", "pp. 3-4" or "section 'Methods'"
    url: str | None = None
    category: str = ""  # official_guidance | scientific_publication | project_documentation
    category_label: str = ""
    score: float = 0.0  # cosine similarity of the passage to the query
    document_id: str | None = None


@dataclass
class KbResult:
    # ok | no_relevant_passages | empty | document_not_found | unavailable
    status: str
    reason: str | None = None
    passages: list[KbPassage] = field(default_factory=list)
    best_score: float | None = None
    available_documents: list[str] = field(default_factory=list)


class KnowledgeBase(Protocol):
    @property
    def ready(self) -> bool: ...

    @property
    def note(self) -> str: ...

    async def search(self, query: str, top_k: int, document: str | None = None) -> KbResult: ...


class NullKnowledgeBase:
    ready = False
    note = "The knowledge base has no indexed documents yet, so it cannot be searched."

    async def search(self, query: str, top_k: int, document: str | None = None) -> KbResult:
        return KbResult(status="empty", reason=self.note)
