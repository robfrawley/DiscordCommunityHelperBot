from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ExpressionItemType(Enum):
    STICKER = "STICKER"
    EMOJI = "EMOJI"


@dataclass(slots=True)
class ExpressionItem:
    id: int | None
    name: str
    type: ExpressionItemType
    uploader_id: int | None
    message_id: int | None
    created_at: int
    link: str | None
