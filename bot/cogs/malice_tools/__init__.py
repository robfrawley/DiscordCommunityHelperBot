from bot.core.bot import Bot
from bot.cogs.malice_tools.malice_tools import MaliceTools


async def setup(bot: Bot) -> None:
    await bot.add_cog(MaliceTools(bot))
