from bot.core.bot import Bot
from bot.cogs.utility_helpers.utility_commands import UtilityCommands


async def setup(bot: Bot) -> None:
    await bot.add_cog(UtilityCommands(bot))
