from bot.core.bot import Bot
from bot.cogs.peaky_tools.peaky_tools_message_listener import PeakyToolsMessageListener


async def setup(bot: Bot) -> None:
    await bot.add_cog(PeakyToolsMessageListener(bot))
