from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class PrivateMessageRecord:
    id: int
    to_user_id: int
    from_user_id: int
    message: str
    created_at: datetime
