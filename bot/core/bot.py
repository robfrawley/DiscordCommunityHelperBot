from collections.abc import Sequence
from discord import Message
from discord.ext import commands

from bot.utils.settings import settings
from bot.utils.logger import logger
from bot.db.database import database
from bot.db.repos.private_message_repo import private_message_repo
from bot.db.repos.emoji_payload_repo import emoji_payload_repo
from bot.db.repos.emoji_abuser_repo import emoji_abuser_repo


# List of bot extensions to load
BOT_LOAD_EXTENSIONS: list[str] = [
    "bot.cogs.private_message",
    "bot.cogs.reaction_abuser",
]


class Bot(commands.Bot):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("command_prefix", "__disabled__")
        super().__init__(*args, **kwargs)

    async def setup_hook(self) -> None:
        logger.debug('Running setup hook...')

        logger.log_settings(settings)

        logger.info('Setting up database...')
        await database.connect()
        await emoji_payload_repo.init_schema()
        await emoji_abuser_repo.init_schema()
        await private_message_repo.init_schema()

        logger.info('Loading extensions...')
        for ext in BOT_LOAD_EXTENSIONS:
            try:
                await self.load_extension(ext)
                logger.debug(f'- "{ext}" (success)')
            except Exception as e:
                logger.warning(f'- "{ext}" (failure: {e})')

        logger.info('Syncing commands...')
        logger.log_commands(await self.tree.sync())

    async def on_ready(self) -> None:
        logger.debug('Running on-ready hook...')

        if not self.user:
            raise Exception("Bot user information is None.")

        logger.info(f'User "{self.user.name}" with ID "{self.user.id}" is logged in and ready.')

    async def close(self) -> None:
        logger.debug('Closing Discord connection...')
        await super().close()

        try:
            logger.debug('Closing database connection...')
            await database.close()
        except Exception as e:
            logger.warning(f'Error closing database connection: {e}')
