from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from bot.db.repos.emoji_abuser_repo import emoji_abuser_repo
from bot.models.emoji_payload import EmojiPayload
from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.views.private_message_list_paginator import PrivateMessageListPaginator
from bot.utils.helpers import (
    check_command_role_permission,
    get_log_channel,
    encode_emoji_as_renderable,
)


class ReactionAbuserCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="react_abuse_list",
        description="List users who have abused reactions but have not yet been warned.",
    )
    @app_commands.describe(
        within_minutes="Time window in minutes to check for reaction abuse",
        count_minimums="Minimum number of reaction removals to consider as abuse",
    )
    async def react_abuse_list(
        self,
        interaction: discord.Interaction,
        *,
        within_minutes: int = int(settings.reaction_abuser_warning_time_window_seconds // 60),
        count_minimums: int = int(settings.reaction_abuser_warning_max_allowed_removal),
    ) -> None:
        if not await check_command_role_permission(interaction, settings.command_enabled_roles):
            return

        await interaction.response.defer(ephemeral=True)

        logger.debug("Checking reaction abusers (via command)...")

        within_seconds: int = within_minutes * 60
        abusers: list[EmojiPayload] = await emoji_abuser_repo.get_abusers_within(
            within_seconds=within_seconds,
            count_minimums=count_minimums,
        )

        logger.debug(f"Found {len(abusers)} reaction abuser records in the time window {within_seconds // 60} minutes: {abusers}")

        if not abusers:
            logger.debug("No reaction abusers detected...")
            await interaction.followup.send(
                "No reaction abusers detected in the specified time window.",
                ephemeral=True,
            )
            return

        found_abusers: set[tuple[int, int, int, int, str | None]] = set()
        match_abusers: list[EmojiPayload] = []

        for payload in abusers:
            key = (payload.message_id, payload.user_id, payload.channel_id, payload.guild_id, payload.emoji)
            if key not in found_abusers:
                found_abusers.add(key)
                match_abusers.append(payload)

        logger.info(
            f"Detected {len(match_abusers)} unique reaction abusers "
            f"in the last {within_seconds} seconds."
        )

        abuse_count_by_user_ids: Counter[int] = Counter(p.user_id for p in abusers)
        abuse_warns_by_user_ids: dict[int, int] = {
            user_id: count
            for user_id, count in abuse_count_by_user_ids.items()
            if count > count_minimums
        }

        matched_messages: list[str] = []

        for p in abuse_warns_by_user_ids.items():
            logger.info(
                f"User {p[0]} has {p[1]} reaction removals in the warning window."
            )

            matched_payloads: list[EmojiPayload] = [mp for mp in match_abusers if mp.user_id == p[0]]
            matched_messages.append("\n".join(
                f"• <@{mp.user_id}> [`{mp.message_id}`](https://discord.com/channels/{mp.guild_id}/{mp.channel_id}/{mp.message_id}) -> "
                f"{encode_emoji_as_renderable(self.bot, mp)}"
                for mp in matched_payloads
            ))

        embed = discord.Embed(
            title="Reaction Abuser Detected",
            description=(
                f"{'\n'.join(matched_messages)}"
            ),
            color=discord.Color.red(),
            timestamp=datetime.now(settings.bot_time_zone),
        )

        await interaction.followup.send(
            embed=embed,
            ephemeral=True,
        )
