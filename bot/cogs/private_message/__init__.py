from bot.core.bot import Bot
from bot.cogs.private_message.private_message_commands import PrivateMessageCommands


async def setup(bot: Bot) -> None:
    await bot.add_cog(PrivateMessageCommands(bot))
