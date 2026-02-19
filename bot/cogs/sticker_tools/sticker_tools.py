from __future__ import annotations

import re

import disnake
from disnake.ext import commands

CUSTOM_EMOJI_RE = re.compile(r"<(a?):([a-zA-Z0-9_]+):(\d+)>")

class StickerTools(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.message_command(name="Get Sticker IDs")
    async def get_sticker_ids(
        self,
        inter: disnake.MessageCommandInteraction,
    ) -> None:
        message: disnake.Message = inter.target

        stickers = getattr(message, "stickers", None) or []
        if not stickers:
            await inter.response.send_message(
                "No stickers found on that message.",
                ephemeral=True,
            )
            return

        lines: list[str] = []

        for s in stickers:
            # Determine extension based on sticker format
            if s.format == disnake.StickerFormatType.lottie:
                ext = "json"
            elif s.format == disnake.StickerFormatType.apng:
                ext = "png"
            else:
                ext = "png"

            cdn_url = f"https://cdn.discordapp.com/stickers/{s.id}.{ext}"

            lines.append(
                f"- **{s.name}** → `{s.id}`\n"
                f"  Format: `{s.format.name}`\n"
                f"  CDN: {cdn_url}"
            )

        msg_link = message.jump_url

        out = (
            "Sticker(s) on that message:\n\n"
            + "\n\n".join(lines)
            + f"\n\nMessage: {msg_link}"
        )

        await inter.response.send_message(out, ephemeral=True)

    @commands.message_command(name="Get Emoji IDs")
    async def get_emoji_ids(
        self,
        inter: disnake.MessageCommandInteraction,
    ) -> None:
        message: disnake.Message = inter.target

        matches = CUSTOM_EMOJI_RE.findall(message.content or "")
        if not matches:
            await inter.response.send_message(
                "No custom emojis found in that message.",
                ephemeral=True,
            )
            return

        lines: list[str] = []

        for animated_flag, name, emoji_id in matches:
            is_animated = bool(animated_flag)
            ext = "gif" if is_animated else "png"
            cdn_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}"

            lines.append(
                f"- **{name}** → `{emoji_id}`\n"
                f"  Animated: `{is_animated}`\n"
                f"  CDN: {cdn_url}"
            )

        msg_link = message.jump_url

        out = (
            "Custom emoji(s) in that message:\n\n"
            + "\n\n".join(lines)
            + f"\n\nMessage: {msg_link}"
        )

        await inter.response.send_message(out, ephemeral=True)
