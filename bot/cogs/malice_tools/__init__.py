from disnake.ext import commands
from bot.cogs.malice_tools.malice_tools_reaction_listener import MaliceToolsReactionListener


def setup(bot: commands.Bot) -> None:
    bot.add_cog(MaliceToolsReactionListener(bot))
