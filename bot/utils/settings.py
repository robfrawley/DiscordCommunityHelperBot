import json
from zoneinfo import ZoneInfo
from pathlib import Path

from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot import ENV_FILE_PATH
from bot.models.role_identifier import RoleIdentifier


class SettingsManager(BaseSettings):
    discord_token: str = Field()
    sqlite_db_path: str = Field()
    debug_mode: bool = Field(default=False)
    bot_time_zone: ZoneInfo = Field(default=ZoneInfo("UTC"))
    enabled_roles: list[RoleIdentifier] = Field(default_factory=list)
    private_message_title: str = Field(default="Private Message from {sender_guild_name}")
    private_message_footer: str = Field(default="Sent by {sender_username} in {sender_guild_name}")

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("sqlite_db_path", mode="before")
    @classmethod
    def make_sqlite_db_path_absolute(cls, v: str) -> str:
        if not v:
            raise ValueError("sqlite_db_path cannot be empty")

        return str(Path(v).expanduser().resolve())

    @field_validator("bot_time_zone", mode="before")
    @classmethod
    def normalize_bot_time_zone(cls, v):
        return ZoneInfo(v) if isinstance(v, str) else v

    @field_validator("enabled_roles", mode="before")
    @classmethod
    def parse_enabled_roles_json(cls, v):
        # Allow unset / empty values.
        if v is None or v == "":
            return []

        # The env value comes in as a JSON string most of the time.
        if isinstance(v, str):
            v = json.loads(v)

        # Be forgiving in case a single role id / RoleIdentifier is provided.
        if isinstance(v, RoleIdentifier):
            return [v]
        if isinstance(v, int):
            return [RoleIdentifier(id=v)]

        if not isinstance(v, (list, tuple, set)):
            raise TypeError(f"enabled_roles must be a JSON array (or list) of ints, got {type(v).__name__}")

        out: list[RoleIdentifier] = []
        for item in v:
            if isinstance(item, RoleIdentifier):
                out.append(item)
            elif isinstance(item, int):
                out.append(RoleIdentifier(id=item))
            elif isinstance(item, str) and item.isdigit():
                out.append(RoleIdentifier(id=int(item)))
            else:
                raise TypeError(
                    "enabled_roles items must be ints (or digit-strings) representing role IDs; "
                    f"got {item!r} ({type(item).__name__})"
                )

        return out


settings = SettingsManager() # type: ignore
