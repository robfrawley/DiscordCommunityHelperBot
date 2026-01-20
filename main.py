import discord

from bot.core.bot import Bot
from bot.utils.settings import settings
from bot.utils.logger import logger

intents = discord.Intents.default()
intents.members = True

bot = Bot(
    command_prefix="i!",
    intents=intents,
    help_command=None,
)


def main() -> None:
    try:
        bot.run(settings.discord_token)
    except KeyboardInterrupt:
        logger.info('Bot is shutting down...')
    finally:
        logger.info('Bot has exited...')


if __name__ == "__main__":
    main()
