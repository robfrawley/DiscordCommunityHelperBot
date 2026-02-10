from __future__ import annotations

import asyncio
from datetime import datetime

import disnake
from disnake.ext import commands

from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.utils.helpers import asset_embed

class ConfirmDumpView(disnake.ui.View):
    def __init__(self, author_id: int, timeout: float = 30.0):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.confirmed: bool | None = None

    async def interaction_check(self, inter: disnake.MessageInteraction) -> bool:
        if inter.author.id != self.author_id:
            await inter.response.send_message(
                "This confirmation isn’t for you.", ephemeral=True
            )
            return False
        return True

    @disnake.ui.button(label="Confirm", style=disnake.ButtonStyle.danger)
    async def confirm(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction,
    ):
        self.confirmed = True
        await inter.response.edit_message(
            content="✅ Asset dump confirmed. Starting…",
            view=None,
        )
        self.stop()

    @disnake.ui.button(label="Cancel", style=disnake.ButtonStyle.secondary)
    async def cancel(
        self,
        button: disnake.ui.Button,
        inter: disnake.MessageInteraction,
    ):
        self.confirmed = False
        await inter.response.edit_message(
            content="❌ Asset dump cancelled.",
            view=None,
        )
        self.stop()

class PeakyToolsExpressionListener(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.known_stickers: dict[int, set[int]] = {}
        self.known_emojis: dict[int, set[int]] = {}

    def _get_log_channel_id(self) -> int | None:
        return settings.peaky_tools_expression_channel_id

    async def _get_log_channel(self, guild: disnake.Guild) -> disnake.abc.Messageable | None:
        chan_id = self._get_log_channel_id()
        if not chan_id:
            return None

        chan = guild.get_channel(chan_id)
        if chan is None:
            try:
                chan = await self.bot.fetch_channel(chan_id)
            except disnake.HTTPException:
                return None

        if isinstance(chan, disnake.abc.Messageable):
            return chan

        return None

    async def _seed_stickers(self, guild: disnake.Guild) -> None:
        if guild.id in self.known_stickers:
            return
        stickers = await guild.fetch_stickers()
        self.known_stickers[guild.id] = {s.id for s in stickers}

    async def _seed_emojis(self, guild: disnake.Guild) -> None:
        if guild.id in self.known_emojis:
            return
        emojis = await guild.fetch_emojis()
        self.known_emojis[guild.id] = {e.id for e in emojis}

    async def _fetch_audit_entries(
        self,
        guild: disnake.Guild,
        *,
        action: disnake.AuditLogAction,
        delay_seconds: float = 2.0,
        limit: int = 15,
    ) -> list[disnake.AuditLogEntry]:
        # pause for audit log to catch up
        await asyncio.sleep(delay_seconds)

        entries: list[disnake.AuditLogEntry] = []
        try:
            async for entry in guild.audit_logs(action=action, limit=limit):
                entries.append(entry)
        except disnake.Forbidden:
            logger.warning(f"[PeakyAssetLogger] Missing View Audit Log in guild {guild.id}")
        except disnake.HTTPException as e:
            logger.warning(f"[PeakyAssetLogger] audit_logs fetch failed in guild {guild.id}: {e}")
        return entries

    def _match_uploader_for_sticker(
        self,
        sticker: disnake.GuildSticker,
        audit_entries: list[disnake.AuditLogEntry],
    ) -> tuple[disnake.abc.User | None, str | None]:
        for entry in audit_entries:
            if isinstance(entry.target, disnake.GuildSticker) and entry.target.id == sticker.id:
                u = entry.user
                if isinstance(u, disnake.abc.User):
                    return u, entry.reason
                return None, entry.reason
        return None, None


    def _match_uploader_for_emoji(
        self,
        emoji: disnake.Emoji,
        audit_entries: list[disnake.AuditLogEntry],
    ) -> tuple[disnake.abc.User | None, str | None]:
        for entry in audit_entries:
            if isinstance(entry.target, disnake.Emoji) and entry.target.id == emoji.id:
                u = entry.user
                if isinstance(u, disnake.abc.User):
                    return u, entry.reason
                return None, entry.reason
        return None, None

    def _asset_created_at(self, asset: object) -> datetime:
        asset_id = getattr(asset, "id", None)
        if isinstance(asset_id, int):
            return disnake.utils.snowflake_time(asset_id)

        return disnake.utils.utcnow()

    async def _post_asset_log(
        self,
        *,
        guild: disnake.Guild,
        embed: disnake.Embed,
        uploader: disnake.abc.User | None,
    ) -> None:
        channel = await self._get_log_channel(guild)
        if channel is None:
            return

        try:
            await channel.send(content=uploader.mention if uploader else None, embed=embed)
        except disnake.HTTPException as e:
            logger.warning(f"[PeakyAssetLogger] Failed to send log message in guild \"{guild.id}\": {e}")

    @commands.Cog.listener()
    async def on_guild_stickers_update(
        self,
        guild: disnake.Guild,
        before: list[disnake.GuildSticker],
        after: list[disnake.GuildSticker],
    ) -> None:
        return

        await self._seed_stickers(guild)

        current = await guild.fetch_stickers()
        current_ids = {s.id for s in current}
        old_ids = self.known_stickers.get(guild.id, set())

        logger.debug(f"[PeakyAssetLogger:on_guild_stickers_update] Current stickers  -> \"{current_ids if current_ids else '(none)'}\"")
        logger.debug(f"[PeakyAssetLogger:on_guild_stickers_update] Known stickers    -> \"{old_ids if old_ids else '(none)'}\"")

        added_ids = current_ids - old_ids

        logger.debug(f"[PeakyAssetLogger:on_guild_stickers_update] Added sticker IDs -> \"{added_ids if added_ids else '(none)'}\"")

        if not added_ids:
            self.known_stickers[guild.id] = current_ids
            return

        added = [s for s in current if s.id in added_ids]

        audit = await self._fetch_audit_entries(guild, action=disnake.AuditLogAction.sticker_create)

        for sticker in added:
            uploader, reason = self._match_uploader_for_sticker(sticker, audit)

            preview_url = getattr(sticker, "url", None)
            embed = asset_embed(
                guild=guild,
                kind="Sticker",
                name=sticker.name,
                asset_id=sticker.id,
                preview_url=str(preview_url) if preview_url else None,
                uploader=uploader,
                reason=reason,
                created_at=self._asset_created_at(sticker),
            )
            await self._post_asset_log(guild=guild, embed=embed, uploader=uploader)
            logger.info(f"[PeakyAssetLogger:on_guild_stickers_update] Logged new STICKER \"{sticker.name}\" ({sticker.id}) in guild \"{guild.id}\" from uploader \"{uploader}\"")

        self.known_stickers[guild.id] = current_ids

    @commands.Cog.listener()
    async def on_guild_emojis_update(
        self,
        guild: disnake.Guild,
        before: list[disnake.Emoji],
        after: list[disnake.Emoji],
    ) -> None:
        await self._seed_emojis(guild)

        current = await guild.fetch_emojis()
        current_ids = {e.id for e in current}
        old_ids = self.known_emojis.get(guild.id, set())

        added_ids = current_ids - old_ids
        if not added_ids:
            self.known_emojis[guild.id] = current_ids
            return

        self.known_emojis[guild.id] = current_ids

        added = [e for e in current if e.id in added_ids]
        audit = await self._fetch_audit_entries(guild, action=disnake.AuditLogAction.emoji_create)

        for emoji in added:
            uploader, reason = self._match_uploader_for_emoji(emoji, audit)
            embed = asset_embed(
                guild=guild,
                kind="Emoji",
                name=emoji.name,
                asset_id=emoji.id,
                preview_url=str(emoji.url) if getattr(emoji, "url", None) else None,
                uploader=uploader,
                reason=reason,
                created_at=self._asset_created_at(emoji),
            )
            await self._post_asset_log(guild=guild, embed=embed, uploader=uploader)
            logger.info(f"[PeakyAssetLogger:on_guild_emojis_update] Logged new EMOJI \"{emoji.name}\" ({emoji.id}) in guild \"{guild.id}\" from uploader \"{uploader}\"")

    @commands.slash_command(
        name="peaky_assets_dump",
        description="Post all current emojis and stickers to the configured asset log channel (one message per item).",
    )
    async def peaky_assets_dump(self, inter: disnake.ApplicationCommandInteraction) -> None:
        guild = inter.guild
        if guild is None:
            await inter.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        chan_id = self._get_log_channel_id()
        if not chan_id:
            await inter.response.send_message(
                "Asset log channel is not configured (settings.asset_log_channel_id).",
                ephemeral=True,
            )
            return

        channel = await self._get_log_channel(guild)
        if channel is None:
            await inter.response.send_message(
                f"Couldn't resolve the asset log channel ({chan_id}) or it isn't messageable.",
                ephemeral=True,
            )
            return

        view = ConfirmDumpView(author_id=inter.author.id)

        await inter.response.send_message(
            (
                f"⚠️ This will post **every emoji and sticker** "
                f"to <#{chan_id}>.\n\n"
                f"Are you sure you want to continue?"
            ),
            ephemeral=True,
            view=view,
        )

        await view.wait()

        if view.confirmed is not True:
            return

        # Authoritative lists
        emojis = await guild.fetch_emojis()
        stickers = await guild.fetch_stickers()

        # warm known sets so future adds are detected cleanly
        self.known_emojis[guild.id] = {e.id for e in emojis}
        self.known_stickers[guild.id] = {s.id for s in stickers}

        # we try to resolve uploader for existing assets (for old assets, audit logs may not include them)
        emoji_audit = await self._fetch_audit_entries_paginated(
            guild,
            action=disnake.AuditLogAction.emoji_create,
            delay_seconds=0.5,
            max_entries=500,
        )
        sticker_audit = await self._fetch_audit_entries_paginated(
            guild,
            action=disnake.AuditLogAction.sticker_create,
            delay_seconds=0.5,
            max_entries=500,
        )

        # Build a single timeline: (created_at, kind, obj)
        timeline: list[tuple[datetime, str, disnake.Emoji | disnake.GuildSticker]] = []

        for e in emojis:
            timeline.append((self._asset_created_at(e), "Emoji", e))

        for s in stickers:
            timeline.append((self._asset_created_at(s), "Sticker", s))

        # Sort by added date (oldest -> newest).
        timeline.sort(key=lambda t: t[0])

        logger.info(f"[PeakyAssetLogger:peaky_assets_dump] Dumping {len(timeline)} assets in guild \"{guild.id}\" to channel \"{chan_id}\".")

        # Post in date order, interleaving emojis + stickers
        for created_at, kind, obj in timeline:
            if kind == "Emoji":
                e: disnake.Emoji = obj  # type: ignore[assignment]
                uploader, reason = self._match_uploader_for_emoji(e, emoji_audit)
                embed = asset_embed(
                    guild=guild,
                    kind="Emoji",
                    name=e.name,
                    asset_id=e.id,
                    preview_url=str(e.url) if getattr(e, "url", None) else None,
                    uploader=uploader,
                    reason=reason,
                    created_at=created_at,
                )
            else:
                s: disnake.GuildSticker = obj  # type: ignore[assignment]
                uploader, reason = self._match_uploader_for_sticker(s, sticker_audit)
                preview_url = getattr(s, "url", None)
                embed = asset_embed(
                    guild=guild,
                    kind="Sticker",
                    name=s.name,
                    asset_id=s.id,
                    preview_url=str(preview_url) if preview_url else None,
                    uploader=uploader,
                    reason=reason,
                    created_at=created_at,
                )
            logger.info(f"[PeakyAssetLogger:peaky_assets_dump] Logged new {kind.upper()} \"{obj.name}\" ({obj.id}) in guild \"{guild.id}\" from uploader \"{uploader}\"")

            await self._post_asset_log(guild=guild, embed=embed, uploader=uploader)
            await asyncio.sleep(0.2)  # gentle pacing


    async def _fetch_audit_entries_paginated(
        self,
        guild: disnake.Guild,
        *,
        action: disnake.AuditLogAction,
        delay_seconds: float = 0.5,
        max_entries: int = 500,   # safety cap
    ) -> list[disnake.AuditLogEntry]:
        await asyncio.sleep(delay_seconds)

        entries: list[disnake.AuditLogEntry] = []
        try:
            async for entry in guild.audit_logs(
                action=action,
                limit=max_entries,
            ):
                entries.append(entry)
        except disnake.Forbidden:
            logger.warning(f"[PeakyAssetLogger:_fetch_audit_entries_paginated] Missing View Audit Log in guild {guild.id}")
        except disnake.HTTPException as e:
            logger.warning(f"[PeakyAssetLogger:_fetch_audit_entries_paginated] audit_logs fetch failed in guild {guild.id}: {e}")

        return entries
