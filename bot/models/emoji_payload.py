from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class EmojiPayload:
    message_id: int
    channel_id: int
    guild_id: int
    user_id: int
    emoji: str | None
    timestamp: datetime
