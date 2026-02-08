from disnake.ext import commands
from bot.cogs.utility_helpers.utility_commands import UtilityCommands


def setup(bot: commands.Bot) -> None:
    bot.add_cog(UtilityCommands(bot))
