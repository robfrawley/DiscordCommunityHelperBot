from discord.ext import commands

from bot.utils.settings import settings
from bot.utils.logger import logger
from bot.db.database import database
from bot.db.repos.private_message_repo import private_message_repo
from bot.db.repos.emoji_payload_repo import emoji_payload_repo
from bot.db.repos.emoji_abuser_repo import emoji_abuser_repo


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
        if not settings.bot_enabled_cogs:
            logger.error(
                'No extensions to load! Enable one in your .env file.')

        for ext in settings.bot_enabled_cogs:
            try:
                await self.load_extension(ext)
                logger.debug(f'- "{ext}" (success)')
            except Exception as e:
                logger.warning(f'- "{ext}" (failure: {e})')

        logger.info('Syncing commands...')
        if settings.debug_mode:
            guild = await self.fetch_guild(
                settings.bot_guild_id
            )
            self.tree.copy_global_to(guild=guild)

        logger.log_commands(
            await self.tree.sync(guild=guild or None)
        )

    async def on_ready(self) -> None:
        logger.debug('Running on-ready hook...')

        if not self.user:
            raise Exception("Bot user information is None.")

        logger.info(
            f'User "{self.user.name}" with ID "{self.user.id}" is logged in and ready.'
        )

    async def close(self) -> None:
        logger.debug('Closing Discord connection...')
        await super().close()

        try:
            logger.debug('Closing database connection...')
            await database.close()
        except Exception as e:
            logger.warning(f'Error closing database connection: {e}')
