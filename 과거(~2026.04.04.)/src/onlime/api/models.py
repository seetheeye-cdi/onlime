from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class WorkerStatusResponse(BaseModel):
    id: str
    name: str
    status: str  # idle | running | error | syncing
    last_sync: str | None = None
    error_message: str | None = None
    is_available: bool = False


class SyncRequest(BaseModel):
    connectors: list[str] | None = None


class SyncEventOut(BaseModel):
    action: str
    detail: str
    timestamp: str


class SyncResult(BaseModel):
    success: bool
    message: str
    events: list[SyncEventOut] = []


class NoteResponse(BaseModel):
    path: str
    title: str
    modified: str
    type: str  # meeting | daily | standalone | inbox


class CalendarEventResponse(BaseModel):
    id: str
    summary: str
    start: str
    end: str
    location: str | None = None
    attendees: list[str] = []


class RecordingResponse(BaseModel):
    id: str
    title: str
    duration_minutes: float
    created_at: str
    has_transcript: bool


class ChatRequest(BaseModel):
    message: str
    context: str | None = None


class ChatResponse(BaseModel):
    reply: str
    thinking: str | None = None


class NotificationPayload(BaseModel):
    package: str = Field(..., max_length=256)
    title: str = Field(..., max_length=1000)
    text: str = Field(..., max_length=10_000)
    timestamp: int = Field(..., ge=0, le=32_503_680_000_000)  # unix ms, up to year 3000
    extras: dict[str, str] = Field(default_factory=dict)

    @field_validator("extras")
    @classmethod
    def validate_extras(cls, v: dict[str, str]) -> dict[str, str]:
        if len(v) > 20:
            raise ValueError("extras must contain at most 20 keys")
        for key, val in v.items():
            if len(key) > 256:
                raise ValueError(f"extras key too long ({len(key)} > 256)")
            if len(val) > 5000:
                raise ValueError(f"extras value too long for key {key!r} ({len(val)} > 5000)")
        return v


class IngestRequest(BaseModel):
    device_id: str = Field(..., min_length=1, max_length=128, pattern=r"^[a-zA-Z0-9_\-\.]+$")
    notifications: list[NotificationPayload] = Field(..., max_length=500)


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    message: str
