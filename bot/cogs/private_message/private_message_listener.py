from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from bot.db.repos.private_message_repo import private_message_repo
from bot.models.private_message_record import PrivateMessageRecord
from bot.utils.helpers import build_dm_embed, log_dm_embed
from bot.utils.helpers import build_dm_embed
from bot.utils.settings import settings
from bot.utils.logger import logger


class PrivateMessageListener(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        if message.guild is not None:
            return

        if not self.bot.user:
            return

        if not settings.allow_responses:
            await message.channel.send("Sorry, responses are currently disabled.")
            return

        record = PrivateMessageRecord(
            id=0,
            from_user_id=message.author.id,
            to_user_id=self.bot.user.id,
            message=message.content or "",
            created_at=datetime.now(tz=ZoneInfo("UTC")),
        )

        embed = await build_dm_embed(
            guild=None,
            from_user=message.author,
            record=record,
            settings=settings,
        )

        await log_dm_embed(
            bot=self.bot,
            embed=embed,
            record=record,
            logger=logger,
            settings=settings,
        )

        await private_message_repo.add(record)

        logger.info(
            f"Logged inbound DM from {message.author.id} to bot {self.bot.user.id}: "
            f"{(message.content or '').strip()[:200]!r}"
        )
