from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

LocationId = Literal["delhi", "gurugram", "noida", "ghaziabad", "faridabad"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class ChatRequest(BaseModel):
    # The server trims history further according to its configured limits.
    messages: list[ChatMessage] = Field(min_length=1, max_length=40)
    # The location currently selected in the UI, used as context when the question does not name one.
    location_id: LocationId | None = None


class SourceRef(BaseModel):
    """Where a piece of retrieved data came from. Cited in answers as [id]."""

    id: str
    kind: Literal["weather_observation", "weather_forecast", "air_quality", "knowledge_base", "report", "pollution_forecast"]
    title: str
    provider: str
    url: str | None
    retrieved_at: datetime
    period_start: datetime | None = None
    period_end: datetime | None = None
    note: str | None = None
    # Knowledge-base citations: what kind of document it is, where in it, and the passage that was retrieved.
    category: str | None = None
    reference: str | None = None
    excerpt: str | None = None
    document_id: str | None = None


class AssistantStatus(BaseModel):
    available: bool
    model: str
    code: str | None
    message: str | None
    tools_supported: bool
    thinking_enabled: bool
    context_length: int | None
    knowledge_base: Literal["unavailable", "ready"]
    knowledge_base_note: str
    pollution_forecast: Literal["available", "unavailable"]
    pollution_forecast_note: str
