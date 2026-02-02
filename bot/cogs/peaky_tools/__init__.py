from bot.core.bot import Bot
from bot.cogs.peaky_tools.peaky_tools import PeakyTools


async def setup(bot: Bot) -> None:
    await bot.add_cog(PeakyTools(bot))
