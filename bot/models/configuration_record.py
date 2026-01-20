from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True, frozen=True)
class ConfigurationRecord:
    key: str
    value: str
    updated_at: datetime
