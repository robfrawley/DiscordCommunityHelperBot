from __future__ import annotations

import disnake
from disnake.ext import commands

from bot.services.peaky_response_service import PeakyResponseService
from bot.utils.settings import settings


class PeakyToolsMessageListener(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.peaky_mean_response_service = PeakyResponseService(bot, nice=False)
        self.peaky_nice_response_service = PeakyResponseService(bot, nice=True)


    def cog_unload(self) -> None:
        self.peaky_mean_response_service.shutdown()
        self.peaky_nice_response_service.shutdown()


    @commands.Cog.listener("on_message")
    async def on_message(self, msg: disnake.Message) -> None:
        if not settings.peaky_tools_enabled:
            return

        if msg.author.bot:
            return

        if msg.guild is None:
            return

        if settings.peaky_tools_mention_enabled and self.bot.user in msg.mentions:
            await self._handle_message(msg, True)
            return

        if not settings.peaky_tools_replies_enabled or not msg.reference or not msg.reference.message_id:
            return

        channel = self.bot.get_channel(msg.channel.id)
        if channel is None or not isinstance(channel, disnake.abc.Messageable):
            return

        await self._handle_message(msg)


    async def _handle_message(self, msg: disnake.Message, allow_no_ref: bool = False) -> None:
        if msg.author.id in set(settings.peaky_tools_nice_user_ids):
            await self.peaky_nice_response_service.handle(msg, allow_no_ref)
        else:
            await self.peaky_mean_response_service.handle(msg, allow_no_ref)
