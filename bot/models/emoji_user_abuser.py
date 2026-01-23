from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class EmojiUserAbuser:
    message_id: int
    user_id: int
    timestamp: datetime
