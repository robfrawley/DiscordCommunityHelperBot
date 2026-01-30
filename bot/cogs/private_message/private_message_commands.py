from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from bot.db.repos.private_message_repo import private_message_repo
from bot.models.private_message_record import PrivateMessageRecord
from bot.views.private_message_list_paginator import PrivateMessageListPaginator
from bot.utils.helpers import build_dm_embed, flatten_newlines_and_strip_str, log_dm_embed, check_command_role_permission
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
        if not await check_command_role_permission(interaction, settings.command_enabled_roles):
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
        if not await check_command_role_permission(interaction, settings.command_enabled_roles):
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
