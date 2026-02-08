from disnake.ext import commands
from bot.cogs.reaction_abuser.reaction_abuser_commands import ReactionAbuserCommands
from bot.cogs.reaction_abuser.reaction_abuser_listener import ReactionAbuserListener


def setup(bot: commands.Bot) -> None:
    bot.add_cog(ReactionAbuserCommands(bot))
    bot.add_cog(ReactionAbuserListener(bot))
