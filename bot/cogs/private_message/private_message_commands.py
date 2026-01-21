from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from bot.db.repos.private_message_repo import private_message_repo
from bot.models.private_message_record import PrivateMessageRecord
from bot.db.repos.configuration_repo import configuration_repo
from bot.models.configuration_record import ConfigurationRecord
from bot.views.private_message_list_paginator import PrivateMessageListPaginator
from bot.utils.helpers import build_dm_embed, flatten_newlines_and_strip_str, get_channel, log_dm_embed
from bot.utils.logger import logger
from bot.utils.settings import settings, SettingsManager


class PrivateMessageCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="dm_send",
        description="Send a DM to a user and log the message."
    )
    @app_commands.describe(
        user="The user to DM",
        message="The message to send"
    )
    async def dm_send(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        message: str,
    ) -> None:
        if not await self._has_role_permission(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        record = PrivateMessageRecord(
            id=0,
            from_user_id=interaction.user.id,
            to_user_id=user.id,
            message=message,
            created_at=datetime.now(tz=ZoneInfo("UTC")),
        )

        embed = await build_dm_embed(
            guild=interaction.guild,
            record=record,
            from_user=interaction.user,
            settings=settings,
        )

        try:
            await user.send(embed=embed)
            logger.info(
                f'Sent DM to user {user.id} from {interaction.user.id}: '
                f'"{flatten_newlines_and_strip_str(record.message)}"'
            )
            await log_dm_embed(
                bot=self.bot,
                embed=embed,
                record=record,
                settings=settings,
                logger=logger,
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "Can't send a DM to that user (DMs disabled or blocked).",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            logger.error(f"Failed to send DM: {exc}")
            await interaction.followup.send(
                "Failed to send the DM due to an unexpected error.",
                ephemeral=True,
            )
            return

        await private_message_repo.add(record)
        await interaction.followup.send(
            f"DM successfully sent to **{user}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="dm_list",
        description="List the latest logged DMs."
    )
    @app_commands.describe(
        to_user="Filter by receiving user",
        from_user="Filter by sending user",
        limit="Max number of results (default 10, max 25)",
        offset="Number of results to skip (default 0)",
    )
    async def dm_list(
        self,
        interaction: discord.Interaction,
        to_user: discord.User | None = None,
        from_user: discord.User | None = None,
        limit: int = 4,
        offset: int = 0,
    ) -> None:
        if not await self._has_role_permission(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        limit = max(1, min(int(limit), 25))
        offset = max(0, int(offset))

        records = await private_message_repo.get_latest(
            to_user_id=to_user.id if to_user else None,
            from_user_id=from_user.id if from_user else None,
            limit=limit,
            offset=offset,
        )

        to_user_id = to_user.id if to_user else None
        from_user_id = from_user.id if from_user else None

        to_user_label = (to_user.display_name if to_user else None)
        from_user_label = (from_user.display_name if from_user else None)

        embed = self._build_dm_list_embed(
            records=records,
            to_user_id=to_user_id,
            from_user_id=from_user_id,
            to_user_label=to_user_label,
            from_user_label=from_user_label,
            limit=limit,
            offset=offset,
        )

        view = PrivateMessageListPaginator(
            cog=self,
            user_id=interaction.user.id,
            to_user_id=to_user_id,
            from_user_id=from_user_id,
            to_user_label=to_user_label,
            from_user_label=from_user_label,
            limit=limit,
            offset=offset,
        )

        view.prev_button.disabled = (offset <= 0)
        view.next_button.disabled = (len(records) < limit)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    async def _has_role_permission(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if not settings.enabled_roles:
            logger.warning(
                "No roles are configured to use private message commands."
            )
            await interaction.response.send_message(
                "No roles are configured to use this command.",
                ephemeral=True,
            )
            return False

        if interaction.guild is None:
            logger.debug(
                "Private message command used outside of a guild."
            )
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return False

        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            logger.warning(
                f"Unable to resolve server member for user {interaction.user.id}."
            )
            await interaction.response.send_message(
                "Unable to resolve your server roles.",
                ephemeral=True,
            )
            return False

        if not any(
            role.id in settings.enabled_roles for role in member.roles
        ):
            logger.warning(
                f"User {interaction.user.id} lacks required roles "
                "to use private message commands."
            )
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return False

        return True

    def _build_dm_list_embed(
        self,
        *,
        records: list[PrivateMessageRecord],
        to_user_id: int | None,
        from_user_id: int | None,
        to_user_label: str | None,
        from_user_label: str | None,
        limit: int,
        offset: int,
    ) -> discord.Embed:
        if to_user_id and not to_user_label:
            to_user_label = f"User {to_user_id}"
        if from_user_id and not from_user_label:
            from_user_label = f"User {from_user_id}"

        if to_user_id and from_user_id:
            title = f"Logged DMs: {from_user_label} → {to_user_label}"
        elif to_user_id:
            title = f"Logged DMs received by {to_user_label}"
        elif from_user_id:
            title = f"Logged DMs sent by {from_user_label}"
        else:
            title = "Latest logged DMs"

        embed = discord.Embed(title=f"{title} (latest first)", color=discord.Color.blurple())

        header_bits: list[str] = []
        if from_user_id:
            header_bits.append(f"From: <@{from_user_id}>")
        if to_user_id:
            header_bits.append(f"To: <@{to_user_id}>")

        header = "**" + "\n".join(header_bits) + "**\n\n" if header_bits else ""

        if not records:
            embed.description = "No matching messages found."
            embed.set_footer(text=f"offset={offset} • limit={limit}")
            return embed

        lines: list[str] = []
        for r in records:
            ts = int(r.created_at.timestamp())
            msg = flatten_newlines_and_strip_str(r.message)
            #if len(msg) > 120:
            #    msg = msg[:117] + "..."
            lines.append(f"• <t:{ts}:f> **<@{r.from_user_id}> → <@{r.to_user_id}>**:\n  ```\n{msg}\n```")

        embed.description = header + "\n".join(lines)
        embed.set_footer(text=f"Showing {len(records)} message(s) • offset={offset} • limit={limit}")

        return embed

    @app_commands.command(
        name="dm_config",
        description="Set or view SettingsManager values stored in the configuration table.",
    )
    @app_commands.describe(
        key="SettingsManager field name (ex: enabled_roles, debug_mode)",
        value=(
            "Value to set (stored as text). Use JSON for lists/objects. "
            "Omit to view current value."
        ),
        delete="Delete the override from the database (reverts to env/default)",
    )
    async def dm_config(
        self,
        interaction: discord.Interaction,
        key: str,
        value: str | None = None,
        delete: bool = False,
    ) -> None:
        if not await self._has_role_permission(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        allowed_keys = set(SettingsManager.model_fields.keys())

        if key not in allowed_keys:
            await interaction.followup.send(
                "Unknown settings key. Valid keys:\n" + "\n".join(sorted(allowed_keys)),
                ephemeral=True,
            )
            return

        # View current value (and whether an override exists)
        if value is None and not delete:
            current_value = getattr(settings, key)
            override = await configuration_repo.get(key)

            embed = discord.Embed(
                title=f"Config: {key}",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Current (effective)", value=f"```\n{current_value!r}\n```", inline=False)
            if override:
                embed.add_field(name="DB override", value=f"```\n{override.value}\n```", inline=False)
                embed.set_footer(text=f"Updated: {override.updated_at.isoformat()}")
            else:
                embed.add_field(name="DB override", value="*(none; using env/default)*", inline=False)

            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        now = datetime.now(tz=settings.bot_time_zone)

        if delete:
            await configuration_repo.delete(key)
            await self._reload_settings_from_env_and_db()
            await interaction.followup.send(
                f"Deleted configuration override for `{key}` (reverted to env/default).",
                ephemeral=True,
            )
            return

        assert value is not None

        # Validate the change by re-validating the full settings model
        try: # reload env/defaults
            overrides = await configuration_repo.get_all_as_dict()
            overrides[key] = value

            base_env = SettingsManager() # type: ignore
            validated = SettingsManager.model_validate({**base_env.model_dump(), **overrides})
        except Exception as exc:
            await interaction.followup.send(
                f"Invalid value for `{key}`: `{exc}`",
                ephemeral=True,
            )
            return

        await configuration_repo.set(
            ConfigurationRecord(
                key=key,
                value=value,
                updated_at=now,
            )
        )

        # Apply the validated settings to the singleton instance so other imports see the update.
        for name in SettingsManager.model_fields.keys():
            setattr(settings, name, getattr(validated, name))

        await interaction.followup.send(
            f"Set `{key}` to `{value}`.",
            ephemeral=True,
        )

    @dm_config.autocomplete("key")
    async def dm_config_key_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        keys = sorted(SettingsManager.model_fields.keys())
        if current:
            cur = current.lower()
            keys = [k for k in keys if cur in k.lower()]
        return [app_commands.Choice(name=k, value=k) for k in keys[:25]]

    async def _reload_settings_from_env_and_db(self) -> None:
        """Reload env/default settings, apply DB overrides, and update the singleton in-place."""
        base_env = SettingsManager() # type: ignore
        overrides = await configuration_repo.get_all_as_dict()
        validated = SettingsManager.model_validate({**base_env.model_dump(), **overrides})

        for name in SettingsManager.model_fields.keys():
            setattr(settings, name, getattr(validated, name))
