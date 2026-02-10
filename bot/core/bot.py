from disnake.ext import commands

from bot.utils.settings import settings
from bot.utils.logger import logger
from bot.db.database import database
from bot.db.repos.private_message_repo import private_message_repo
from bot.db.repos.emoji_payload_repo import emoji_payload_repo
from bot.db.repos.emoji_abuser_repo import emoji_abuser_repo
from bot.db.repos.expression_item_repo import expression_item_repo


class Bot(commands.InteractionBot):
    def __init__(self, *args, **kwargs):
        kwargs.pop("help_command", None)
        kwargs.pop("command_prefix", None)
        super().__init__(*args, **kwargs)

        self._did_startup = False

    async def on_connect(self) -> None:
        if self._did_startup:
            return

        self._did_startup = True

        logger.debug("[Bot:on_connect] Running startup (on_connect)...")

        logger.log_settings(settings)

        logger.info("[Bot:on_connect] Setting up database...")
        await database.connect()
        await emoji_payload_repo.init_schema()
        await emoji_abuser_repo.init_schema()
        await private_message_repo.init_schema()
        await expression_item_repo.init_schema()

        logger.info("[Bot:on_connect] Loading extensions...")
        if not settings.bot_enabled_cogs:
            logger.error("[Bot:on_connect] No extensions to load! Enable one in your .env file.")
        for ext in settings.bot_enabled_cogs:
            try:
                self.load_extension(ext)
                logger.debug(f'-> "{ext}" (success)')
            except Exception as e:
                logger.warning(f'-> "{ext}" (failure: {e})')

        logger.log_commands(self.application_commands)

    async def on_ready(self) -> None:
        if not self.user:
            raise RuntimeError("Bot user information is None.")

        logger.info(f'[Bot:on_ready] Bot user "{self.user.name}" with ID "{self.user.id}" is logged in and ready.')

    async def close(self) -> None:
        logger.debug("[Bot:close] Closing Discord connection...")
        await super().close()

        try:
            logger.debug("[Bot:close] Closing database connection...")
            await database.close()
        except Exception as e:
            logger.warning(f"[Bot:close] Error closing database connection: {e}")
