from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands


class StickerTools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

        self.ctx_get_sticker_ids = app_commands.ContextMenu(
            name="Get Sticker IDs",
            callback=self.get_sticker_ids,
        )
        self.bot.tree.add_command(self.ctx_get_sticker_ids)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command(self.ctx_get_sticker_ids.name, type=self.ctx_get_sticker_ids.type)

    async def get_sticker_ids(
        self,
        interaction: discord.Interaction,
        message: discord.Message,
    ) -> None:
        stickers = getattr(message, "stickers", None) or []

        if not stickers:
            await interaction.response.send_message(
                "No stickers found on that message.",
                ephemeral=True,
            )
            return

        lines = []
        for s in stickers:
            lines.append(f"- **{s.name}** → `{s.id}`")

        msg_link = message.jump_url

        out = "Sticker(s) on that message:\n" + "\n".join(lines)
        await interaction.response.send_message(out + "\n" + msg_link, ephemeral=True)
