from __future__ import annotations

import disnake
from disnake.ext import commands

from bot.utils.logger import logger


class MaliceToolsReactionListener(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.target_user_id = int(502928871432257536)
        self.reactor_user_id = int(1371651018882023425)
        self.blocked_emojis = ["🧓", "👴", "👵", "🧑‍🦳", "🫃", "🫄", "🤰"]

    def _emoji_equals(self, emoji: disnake.PartialEmoji, blocked_emoji) -> bool:
        # Unicode emoji
        if isinstance(blocked_emoji, str):
            return emoji.id is None and emoji.name == blocked_emoji

        # Custom emoji by ID
        return emoji.id == int(blocked_emoji)

    def _emoji_matches(self, emoji: disnake.PartialEmoji) -> bool:
        return any(self._emoji_equals(emoji, blocked) for blocked in self.blocked_emojis)

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_raw_reaction_add(self, payload: disnake.RawReactionActionEvent) -> None:
        # Ignore the bot itself
        if self.bot.user and payload.user_id == self.bot.user.id:
            return

        # Only the specific reactor user
        #if payload.user_id != self.reactor_user_id:
        #    return

        # Only the specific emoji (uncomment if you want to enforce)
        if not self._emoji_matches(payload.emoji):
            return

        # Fetch channel
        channel = self.bot.get_channel(payload.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(payload.channel_id)
            except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                return

        if not isinstance(
            channel,
            (disnake.TextChannel, disnake.Thread, disnake.DMChannel, disnake.GroupChannel),
        ):
            return

        # Fetch message
        try:
            message = await channel.fetch_message(payload.message_id)
        except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
            return

        # Only when reacting to the target user's message
        #if message.author.id != self.target_user_id:
        #    return

        # Remove reaction from that user
        try:
            user = None
            if message.guild is not None:
                user = message.guild.get_member(payload.user_id)
            if user is None:
                user = await self.bot.fetch_user(payload.user_id)

            await message.remove_reaction(payload.emoji, user)
            logger.debug(
                f"Removed reaction: {payload.emoji} by user {payload.user_id} on message {payload.message_id}"
            )
        except (disnake.Forbidden, disnake.HTTPException):
            pass
