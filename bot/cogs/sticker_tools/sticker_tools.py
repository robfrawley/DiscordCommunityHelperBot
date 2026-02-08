from __future__ import annotations

import disnake
from disnake.ext import commands


class StickerTools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.message_command(name="Get Sticker IDs")
    async def get_sticker_ids(
        self,
        inter: disnake.MessageCommandInteraction,
    ) -> None:
        # The message that was right-clicked
        message: disnake.Message = inter.target

        stickers = getattr(message, "stickers", None) or []
        if not stickers:
            await inter.response.send_message(
                "No stickers found on that message.",
                ephemeral=True,
            )
            return

        lines: list[str] = [f"- **{s.name}** → `{s.id}`" for s in stickers]
        msg_link = message.jump_url

        out = (
            "Sticker(s) on that message:\n"
            + "\n".join(lines)
            + f"\n\nMessage: {msg_link}"
        )

        await inter.response.send_message(out, ephemeral=True)
