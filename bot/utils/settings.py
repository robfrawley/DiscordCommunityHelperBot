import json
from zoneinfo import ZoneInfo
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from bot import ENV_FILE_PATH, COGS_DIR_PATH
from bot.models.role_identifier import RoleIdentifier


class SettingsManager(BaseSettings):
    discord_token: str = Field()
    sqlite_db_path: str = Field()
    debug_mode: bool = Field(default=False)
    bot_guild_id: int = Field()
    bot_time_zone: ZoneInfo = Field(default=ZoneInfo("UTC"))
    bot_defined_cogs: list[str] = sorted([
        f"bot.cogs.{p.name}"
        for p in Path(COGS_DIR_PATH).iterdir()
        if p.is_dir() and (p / "__init__.py").exists()
    ])
    bot_enabled_cogs: list[str] = Field(default_factory=list)
    command_enabled_roles: list[RoleIdentifier] = Field(default_factory=list)
    command_enabled_elevated_roles: list[RoleIdentifier] = Field(default_factory=list)
    private_message_title: str = Field(default="Private Message from {sender_guild_name}")
    private_message_footer: str = Field(default="Sent by {sender_username} in {sender_guild_name}")
    private_message_log_channel_id: int | None = Field(default=None)
    allow_responses: bool = Field(default=False)
    reaction_abuser_log_channel_id: int | None = Field(default=None)
    reaction_abuser_reacted_time_window_seconds: float = Field(default=2.5)
    reaction_abuser_warning_time_window_seconds: float = Field(default=3600.0)
    reaction_abuser_warning_max_allowed_removal: int = Field(default=3)
    reaction_abuser_warning_ping_role_id: int | None = Field(default=None)

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    @field_validator("bot_enabled_cogs")
    @classmethod
    def enabled_cogs_must_exist(cls, enabled: list[str], info):
        defined: set[str] = set(info.data.get("bot_defined_cogs", []))
        invalid: set[str] = set([c for c in enabled if c not in defined])

        if invalid:
            raise ValueError(
                f"Unknown cogs in bot_enabled_cogs: {', '.join(sorted(invalid))}. "
                f"Available cogs: {', '.join(sorted(defined))}"
            )

        return sorted(enabled)

    @field_validator(
        "private_message_log_channel_id",
        "reaction_abuser_warning_ping_role_id",
        "reaction_abuser_log_channel_id",
        mode="before",
    )
    @classmethod
    def empty_str_to_none(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.strip() == "":
            return None
        return v

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

    @field_validator(
        "command_enabled_roles",
        "command_enabled_elevated_roles",
        mode="before"
    )
    @classmethod
    def parse_command_enabled_roles_json(cls, v):
        if v is None or v == "":
            return []

        if isinstance(v, str):
            v = json.loads(v)

        if isinstance(v, RoleIdentifier):
            return [v]
        if isinstance(v, int):
            return [RoleIdentifier(id=v)]

        if not isinstance(v, (list, tuple, set)):
            raise TypeError(f"command_enabled_roles must be a JSON array (or list) of ints, got {type(v).__name__}")

        out: list[RoleIdentifier] = []
        for item in v:
            if isinstance(item, RoleIdentifier):
                out.append(item)
            elif isinstance(item, int):
                out.append(RoleIdentifier(id=item))
            elif isinstance(item, str) and item.isdigit():
                out.append(RoleIdentifier(id=int(item)))
            elif isinstance(item, dict) and "id" in item:
                raw_id = item["id"]
                if isinstance(raw_id, int):
                    out.append(RoleIdentifier(id=raw_id))
                elif isinstance(raw_id, str) and raw_id.isdigit():
                    out.append(RoleIdentifier(id=int(raw_id)))
                else:
                    raise TypeError(
                        "command_enabled_roles dict items must have an int (or digit-string) 'id'; "
                        f"got id={raw_id!r} ({type(raw_id).__name__})"
                    )
            else:
                raise TypeError(
                    "command_enabled_roles items must be ints (or digit-strings) representing role IDs; "
                    f"got {item!r} ({type(item).__name__})"
                )

        return out


settings = SettingsManager() # type: ignore
