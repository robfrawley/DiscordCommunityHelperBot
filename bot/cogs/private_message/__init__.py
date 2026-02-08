from disnake.ext import commands
from bot.cogs.private_message.private_message_commands import PrivateMessageCommands
from bot.cogs.private_message.private_message_listener import PrivateMessageListener


def setup(bot: commands.Bot) -> None:
    bot.add_cog(PrivateMessageCommands(bot))
    bot.add_cog(PrivateMessageListener(bot))
