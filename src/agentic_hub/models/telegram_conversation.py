from datetime import datetime, timezone

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TelegramConversationMessage(BaseModel):
    role: str
    content: str
    created_at: datetime = Field(default_factory=utc_now)


class TelegramConversationSession(BaseModel):
    session_id: str
    worker_id: str
    channel_type: str = Field(description="managed_bot, vanta_hybrid")
    chat_id: int
    user_id: int | None = None
    active: bool = True
    messages: list[TelegramConversationMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
