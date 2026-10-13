from dataclasses import dataclass, field

# What a document is. The label is shown next to every citation so users can tell guidance from research from
# project notes, and none of these is ever confused with the assistant's own interpretation.
CATEGORIES: dict[str, str] = {
    "official_guidance": "Official guidance",
    "scientific_publication": "Scientific publication",
    "project_documentation": "Project documentation",
    "dataset": "Dataset (table)",
}

STATUSES = ("indexing", "ready", "failed")


class KbError(Exception):
    """A problem with a document or the knowledge base, with a stable code and an HTTP status for the API."""

    def __init__(self, code: str, message: str, status: int = 422):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


@dataclass
class PageText:
    number: int | None  # 1-based page number when the format has pages (PDF); None for plain text
    text: str
    section: str | None = None  # a label for this block when it has no page (CSV: "rows 1-14")


@dataclass
class Table:
    """The parsed cells of a CSV, kept so the file can also be loaded as a real, queryable table."""
    header: list[str]
    rows: list[list[str]]
    warnings: list[str] = field(default_factory=list)


@dataclass
class Extracted:
    kind: str  # "pdf" | "txt" | "md" | "csv"
    pages: list[PageText]
    page_count: int | None
    warnings: list[str] = field(default_factory=list)
    table: Table | None = None


@dataclass
class Chunk:
    index: int
    text: str
    page_start: int | None
    page_end: int | None
    section: str | None
