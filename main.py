import disnake
from disnake.ext import commands

from bot.core.bot import Bot
from bot.utils.settings import settings
from bot.utils.logger import logger

intents = disnake.Intents.default()
intents.dm_messages = True
intents.members = True
intents.guild_reactions = True
intents.reactions = True
intents.guilds = True
intents.message_content = True

command_sync_flags = commands.CommandSyncFlags.default()
command_sync_flags.sync_commands_debug = settings.debug_mode

bot = Bot(
    intents=intents,
    test_guilds=[settings.bot_guild_id] if settings.debug_mode else None,
    reload=settings.debug_mode,
    command_sync_flags=command_sync_flags,
)


def main() -> None:
    try:
        logger.info("Bot is starting up...")
        bot.run(settings.discord_token)
    except KeyboardInterrupt:
        logger.info("Bot is shutting down...")
    finally:
        logger.info("Bot has exited...")


if __name__ == "__main__":
    main()
