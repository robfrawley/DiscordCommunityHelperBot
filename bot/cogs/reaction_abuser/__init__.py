from bot.core.bot import Bot
from bot.cogs.reaction_abuser.reaction_abuser_commands import ReactionAbuserCommands
from bot.cogs.reaction_abuser.reaction_abuser_listener import ReactionAbuserListener


async def setup(bot: Bot) -> None:
    await bot.add_cog(ReactionAbuserCommands(bot))
    await bot.add_cog(ReactionAbuserListener(bot))
