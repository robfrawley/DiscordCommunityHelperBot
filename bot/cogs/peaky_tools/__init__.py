from disnake.ext import commands
from bot.cogs.peaky_tools.peaky_tools_message_listener import PeakyToolsMessageListener
from bot.cogs.peaky_tools.peaky_tools_expression_listener import PeakyToolsExpressionListener


def setup(bot: commands.Bot) -> None:
    bot.add_cog(PeakyToolsMessageListener(bot))
    bot.add_cog(PeakyToolsExpressionListener(bot))
