from datetime import datetime
from collections import Counter

import disnake
from disnake.ext import commands, tasks

from disnake.ext import commands
from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.models.emoji_payload import EmojiPayload
from bot.db.repos.emoji_payload_repo import emoji_payload_repo
from bot.db.repos.emoji_abuser_repo import emoji_abuser_repo
from bot.utils.helpers import (
    extract_reaction_payload_info,
    get_log_channel,
    encode_emoji_as_renderable,
)


class ReactionAbuserListener(commands.Cog):
    """
    Dedicated to Peaky.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.every_minute_task.start()
        self.every_sixty_minutes_task.start()

    def cog_unload(self) -> None:
        self.every_minute_task.cancel()
        self.every_sixty_minutes_task.cancel()

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: disnake.RawReactionActionEvent) -> None:
        if not self._is_actionable_reaction(payload):
            return

        emoji_add_payload: EmojiPayload = extract_reaction_payload_info(payload)
        #logger.debug(f"Reaction added: {emoji_add_payload}")
        await emoji_payload_repo.add(emoji_add_payload)

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: disnake.RawReactionActionEvent) -> None:
        if not self._is_actionable_reaction(payload):
            return

        emoji_del_payload: EmojiPayload = extract_reaction_payload_info(payload)
        #logger.debug(f"Reaction removed: {emoji_del_payload}")

        emoji_add_payload: EmojiPayload | None = await emoji_payload_repo.get_and_delete(emoji_del_payload)
        if emoji_add_payload is None:
            logger.debug("No matching reaction add payload found; skipping removal processing.")
            return

        time_diff = (emoji_del_payload.timestamp - emoji_add_payload.timestamp).total_seconds()
        logger.debug(f"Time difference between add and remove: {time_diff} seconds")

        if time_diff <= settings.reaction_abuser_reacted_time_window_seconds:
            logger.notice(
                f"Detected reaction abuser: User {emoji_del_payload.user_id} "
                f"on Message {emoji_del_payload.message_id} "
                f"with Emoji '{emoji_del_payload.emoji}' "
                f"within {time_diff:.2f} seconds."
            )
            await emoji_abuser_repo.add(emoji_del_payload)
        else:
            #logger.debug("Reaction removal outside of abuser time window; no action taken.")
            pass

    @tasks.loop(minutes=60)
    async def every_sixty_minutes_task(self) -> None:
        pruned_count = await emoji_abuser_repo.prune(
            older_than_seconds=int(settings.reaction_abuser_warning_time_window_seconds * 2)
        )
        if pruned_count > 0:
            logger.debug(
                f"Pruned {pruned_count} old reaction abuser records older than "
                f"{int(settings.reaction_abuser_warning_time_window_seconds * 2 // 3600)} hours."
            )

    @every_sixty_minutes_task.before_loop
    async def before_every_sixty_minutes_task(self) -> None:
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=1)
    async def every_minute_task(self) -> None:
        abusers: list[EmojiPayload] = await emoji_abuser_repo.get_abusers_within(
            within_seconds=int(settings.reaction_abuser_warning_time_window_seconds),
            count_minimums=settings.reaction_abuser_warning_max_allowed_removal,
        )

        if abusers:
            logger.debug(f"Found {len(abusers)} reaction abuser records in the time window: {abusers}")
        else:
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

        log_channel: disnake.TextChannel | None = get_log_channel(self.bot)
        if log_channel is None:
            return

        abuse_count_by_user_ids: Counter[int] = Counter(p.user_id for p in abusers)
        abuse_warns_by_user_ids: dict[int, int] = {
            user_id: count
            for user_id, count in abuse_count_by_user_ids.items()
            if count > settings.reaction_abuser_warning_max_allowed_removal
        }

        for user_id, count in abuse_warns_by_user_ids.items():
            logger.info(
                f"User {user_id} has {count} reaction removals in the warning window; sending log message."
            )

            matched_payloads: list[EmojiPayload] = [mp for mp in match_abusers if mp.user_id == user_id]
            matched_messages = "\n".join(
                f"• [`{mp.message_id}`](https://discord.com/channels/{mp.guild_id}/{mp.channel_id}/{mp.message_id}) -> "
                f"{encode_emoji_as_renderable(self.bot, mp)}"
                for mp in matched_payloads
            )

            embed = disnake.Embed(
                title="Reaction Abuser Detected",
                description=(
                    f"User <@{user_id}> with ID `{user_id}` has added and immediately removed reactions "
                    f"**{count}** times within "
                    f"**{int(settings.reaction_abuser_warning_time_window_seconds // 60)}** minutes.\n\n"
                    f"Messages and emojis involved:\n{matched_messages}"
                ),
                color=disnake.Color.red(),
                timestamp=datetime.now(settings.bot_time_zone),
            )

            await log_channel.send(
                content=(
                    f"<@&{settings.reaction_abuser_warning_ping_role_id}>"
                    if settings.reaction_abuser_warning_ping_role_id
                    else None
                ),
                embed=embed,
            )

            deleted: int = await emoji_abuser_repo.delete_user_records(user_id=user_id)
            logger.debug(
                f"Deleted {deleted} reaction abuser records for user {user_id} after logging the warning."
            )

    @every_minute_task.before_loop
    async def before_every_minute_task(self) -> None:
        await self.bot.wait_until_ready()

    def _is_actionable_reaction(self, payload: disnake.RawReactionActionEvent) -> bool:
        # Ignore the bot's own reactions
        bot_id = self.bot.user.id if self.bot.user else None
        if bot_id is not None and payload.user_id == bot_id:
            return False
        return True
