from disnake.ext import commands
from bot.cogs.peaky_tools.peaky_tools_message_listener import PeakyToolsMessageListener
from bot.cogs.peaky_tools.peaky_tools_expression_listener import PeakyToolsExpressionListener
from bot.cogs.peaky_tools.peaky_tools_expression_commands import PeakyToolsExpressionCommands


def setup(bot: commands.Bot) -> None:
    bot.add_cog(PeakyToolsMessageListener(bot))
    bot.add_cog(PeakyToolsExpressionListener(bot))
    bot.add_cog(PeakyToolsExpressionCommands(bot))
