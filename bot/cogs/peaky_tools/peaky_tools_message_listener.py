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
    async def on_message(self, message: disnake.Message) -> None:
        if message.author.id in set(settings.peaky_tools_nice_user_ids):
            await self.peaky_nice_response_service.handle(message)
        else:
            await self.peaky_mean_response_service.handle(message)
