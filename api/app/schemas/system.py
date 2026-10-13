from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DependencyState = Literal["ok", "degraded", "unavailable", "not_configured", "configured"]


class HealthResponse(BaseModel):
    """Liveness only: says the API process is serving requests, nothing about its dependencies."""

    status: Literal["ok"]
    version: str
    time: datetime


class DependencyStatus(BaseModel):
    key: str
    name: str
    required: bool
    state: DependencyState
    detail: str
    latency_ms: int | None = None


class AppInfo(BaseModel):
    name: str
    version: str
    environment: str


class SystemStatusResponse(BaseModel):
    # "ok" when every required dependency is ok, otherwise "degraded".
    status: Literal["ok", "degraded"]
    app: AppInfo
    generated_at: datetime
    generated_at_ist: datetime
    dependencies: list[DependencyStatus]
