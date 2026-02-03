from bot.core.bot import Bot
from bot.cogs.sticker_tools.sticker_tools import StickerTools


async def setup(bot: Bot) -> None:
    await bot.add_cog(StickerTools(bot))
