from bot.core.bot import Bot
from bot.cogs.malice_tools.malice_tools_reaction_listener import MaliceToolsReactionListener


async def setup(bot: Bot) -> None:
    await bot.add_cog(MaliceToolsReactionListener(bot))
