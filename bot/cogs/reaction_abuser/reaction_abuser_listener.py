from datetime import datetime
from collections import Counter
import re

import discord
from discord.ext import commands, tasks

from bot.core.bot import Bot
from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.models.emoji_payload import EmojiPayload
from bot.db.repos.emoji_payload_repo import emoji_payload_repo
from bot.db.repos.emoji_abuser_repo import emoji_abuser_repo


class ReactionAbuserListener(commands.Cog):
    _EMOJI_CUSTOMS_RE = re.compile(r"^([A-Za-z0-9_]+)-(\d+)$")

    def __init__(self, bot: Bot) -> None:
        self.bot = bot
        self.every_minute_task.start()
        self.every_sixty_minutes_task.start()

    def cog_unload(self):
        self.every_minute_task.cancel()
        self.every_sixty_minutes_task.cancel()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if not self._is_actionable_reaction(payload):
            return

        emoji_add_payload: EmojiPayload = self._extract_payload_info(payload)
        logger.debug(f"Reaction added: {emoji_add_payload}")
        await emoji_payload_repo.add(emoji_add_payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if not self._is_actionable_reaction(payload):
            return

        emoji_del_payload: EmojiPayload = self._extract_payload_info(payload)
        logger.debug(f"Reaction removed: {emoji_del_payload}")
        emoji_add_payload: EmojiPayload | None = await emoji_payload_repo.get_and_delete(emoji_del_payload)

        if emoji_add_payload is None:
            logger.debug("No matching reaction add payload found; skipping removal processing.")
            return

        time_diff = (emoji_del_payload.timestamp - emoji_add_payload.timestamp).total_seconds()
        logger.debug(f"Time difference between add and remove: {time_diff} seconds")

        if time_diff <= settings.reaction_abuser_reacted_time_window_seconds:
            logger.info(
                f"Detected reaction abuser: User {emoji_del_payload.user_id} "
                f"on Message {emoji_del_payload.message_id} "
                f"with Emoji '{emoji_del_payload.emoji}' "
                f"within {time_diff:.2f} seconds."
            )
            await emoji_abuser_repo.add(emoji_del_payload)
        else:
            logger.debug("Reaction removal outside of abuser time window; no action taken.")

    @tasks.loop(minutes=1)
    async def every_minute_task(self):
        logger.debug("Running reaction abuser detection task (every minute)...")

        abusers: list[EmojiPayload] = await emoji_abuser_repo.get_abusers_within(
            within_seconds=int(settings.reaction_abuser_warning_time_window_seconds),
            max_count=settings.reaction_abuser_warning_max_allowed_removal,
        )

        logger.debug(f"Found {len(abusers)} reaction abuser records in the time window: {abusers}")

        if not abusers:
            logger.debug("No reaction abusers detected...")
            return

        found_abusers: set[tuple[int, int, int, int, str | None]] = set()
        match_abusers: list[EmojiPayload] = []

        for payload in abusers:
            key = (payload.message_id, payload.user_id, payload.channel_id, payload.guild_id, payload.emoji)
            if key not in found_abusers:
                found_abusers.add(key)
                match_abusers.append(payload)

        logger.info(
            f"Detected {len(match_abusers)} unique reaction abusers "
            f"in the last {settings.reaction_abuser_warning_time_window_seconds} seconds."
        )

        log_channel: discord.TextChannel | None = self._get_log_channel()
        if log_channel is None:
            return

        abuse_count_by_user_ids: Counter[int] = Counter(p.user_id for p in abusers)
        abuse_warns_by_user_ids: dict[int, int] = {
            user_id: count
            for user_id, count in abuse_count_by_user_ids.items()
            if count > settings.reaction_abuser_warning_max_allowed_removal
        }

        for p in abuse_warns_by_user_ids.items():
            logger.info(
                f"User {p[0]} has {p[1]} reaction removals in the warning window; "
                f"sending log message."
            )

            matched_payloads: list[EmojiPayload] = [mp for mp in match_abusers if mp.user_id == p[0]]
            matched_messages = matched_messages = "\n".join(
                f"• [`{mp.message_id}`](https://discord.com/channels/{mp.guild_id}/{mp.channel_id}/{mp.message_id}) -> "
                f"{self._encode_emoji_as_renderable(mp)}"
                for mp in matched_payloads
            )

            embed = discord.Embed(
                title="Reaction Abuser Detected",
                description=(
                    f"User <@{p[0]}> with ID `{p[0]}` has added and immediately removed reactions **{p[1]}** times within "
                    f"**{int(settings.reaction_abuser_warning_time_window_seconds // 60)}** minutes.\n\n"
                    f"Messages and emojis involved:\n{matched_messages}"
                ),
                color=discord.Color.red(),
                timestamp=datetime.now(settings.bot_time_zone),
            )

            await log_channel.send(
                content=(f"<@&{settings.reaction_abuser_warning_ping_role_id}>" if settings.reaction_abuser_warning_ping_role_id else None),
                embed=embed
            )

            deleted: int = await emoji_abuser_repo.delete_user_records(user_id=p[0])

            logger.debug(
                f"Deleted {deleted} reaction abuser records for user {p[0]} "
                "after logging the warning."
            )

    def _emoji_cdn_url(self, emoji_id: str, *, animated: bool) -> str:
        ext = "gif" if animated else "png"
        return f"https://cdn.discordapp.com/emojis/{emoji_id}.{ext}?v=1"

    def _encode_emoji_as_renderable(self, payload: EmojiPayload) -> str:
        if not payload.emoji:
            return ""

        # Unicode escape text like "\\u2764\\ufe0f" or "\\U0001f525"
        if payload.emoji.startswith("\\"):
            try:
                return payload.emoji.encode("ascii").decode("unicode_escape")
            except Exception as e:
                logger.warning(f"Failed to decode unicode emoji '{payload.emoji}': {e}")
                return ""

        m = self._EMOJI_CUSTOMS_RE.fullmatch(payload.emoji)
        if not m:
            return payload.emoji  # if you ever store real unicode directly

        emoji_name, emoji_id = m.group(1), m.group(2)

        guild = self.bot.get_guild(payload.guild_id)
        emoji_obj = guild and discord.utils.get(guild.emojis, id=int(emoji_id))

        if emoji_obj:
            return f"<{'a' if emoji_obj.animated else ''}:{emoji_name}:{emoji_id}>"

        # Can't render as emoji -> provide a clickable image link
        url = self._emoji_cdn_url(emoji_id, animated=False)
        return f"[`:{emoji_name}:`]({url})"

    @every_minute_task.before_loop
    async def before_every_minute_task(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=60)
    async def every_sixty_minutes_task(self):
        logger.debug("Running reaction abuser cleanup task (every 60 minutes)...")
        pruned_count = await emoji_abuser_repo.prune(
            older_than_seconds=int(settings.reaction_abuser_warning_time_window_seconds * 2)
        )
        logger.info(f"Pruned {pruned_count} old reaction abuser records older than {int(settings.reaction_abuser_warning_time_window_seconds * 2 // 3600)} hours.")

    @every_sixty_minutes_task.before_loop
    async def before_every_sixty_minutes_task(self):
        await self.bot.wait_until_ready()

    def _extract_payload_info(self, payload: discord.RawReactionActionEvent) -> EmojiPayload:
        parts: list[str | int | None] = [
            self._get_emoji_as_readable_utf8_str(payload),
            payload.emoji.id,
        ]

        return EmojiPayload(
            message_id=payload.message_id,
            channel_id=payload.channel_id,
            user_id=payload.user_id,
            guild_id=payload.guild_id if payload.guild_id is not None else 0,
            emoji="-".join(str(x) for x in parts if x is not None),
            timestamp=datetime.now(settings.bot_time_zone),
        )

    def _get_log_channel(self) -> discord.TextChannel | None:
        if settings.reaction_abuser_log_channel_id is None:
            logger.warning("Reaction abuser log channel ID is not configured.")
            return None

        channel = self.bot.get_channel(settings.reaction_abuser_log_channel_id)
        if channel is None or not isinstance(channel, discord.TextChannel):
            logger.warning(
                f"Unable to resolve reaction abuser log channel with ID "
                f"{settings.reaction_abuser_log_channel_id}."
            )
            return None

        return channel

    def _get_emoji_as_readable_utf8_str(self, payload: discord.RawReactionActionEvent) -> str | None:
        if payload.emoji.name:
            return payload.emoji.name.encode("unicode_escape").decode("ascii")

        return None

    def _is_actionable_reaction(self, payload: discord.RawReactionActionEvent) -> bool:
        if payload.user_id == (self.bot.user.id if self.bot.user else None):
            return False

        return True
