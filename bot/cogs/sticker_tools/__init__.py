from disnake.ext import commands
from bot.cogs.sticker_tools.sticker_tools import StickerTools


def setup(bot: commands.Bot) -> None:
    bot.add_cog(StickerTools(bot))
