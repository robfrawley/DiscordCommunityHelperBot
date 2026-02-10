from __future__ import annotations

from pprint import pprint
import re
from typing import Protocol

import disnake
from disnake.ext import commands, tasks

from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.models.expression_item import ExpressionItem, ExpressionItemType
from bot.db.repos.expression_item_repo import expression_item_repo
from bot.utils.helpers import resolve_expression, resolve_guild, asset_embed, resolve_user


class EmbedField(Protocol):
    name: str | None
    value: str | None
    inline: bool | None


class PeakyToolsExpressionCommands(commands.Cog):
    _EXTRACT_FIELD_ID: re.Pattern[str] = re.compile(r"(\d+)\.\w+$")
    _EXTRACT_FIELD_NAME: re.Pattern[str] = re.compile(r"`([^`]+)`")
    _EXTRACT_FIELD_UPLOADER: re.Pattern[str] = re.compile(r"<@(\d+)>")
    _EXTRACT_FIELD_CREATED: re.Pattern[str] = re.compile(r"<t:(\d+):")
    _EXTRACT_FIELD_LINK: re.Pattern[str] = re.compile(r"(.*)")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.cleanup_task.start()

    def cog_unload(self):
        self.cleanup_task.cancel()

    @tasks.loop(minutes=settings.peaky_tools_expression_sync_interval_minutes)
    async def cleanup_task(self):
        guild = await resolve_guild(self.bot, settings.bot_guild_id)

        if guild is None:
            logger.error(f"Guild not found or inaccessible ({settings.bot_guild_id}); cannot perform cleanup.")
            return

        item_count = await self._rescan_and_resync(guild)

        logger.debug(f"Rescan complete. Total items: {item_count}")

    @cleanup_task.before_loop
    async def before_cleanup(self):
        await self.bot.wait_until_ready()

    @commands.slash_command(
        name="peaky_assets_rescan_and_sync",
        description="Resets the known stickers database and rescans it.",
    )
    async def peaky_assets_rescan_and_sync(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer(ephemeral=True)

        if inter.guild is None:
            await inter.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        item_count = await self._rescan_and_resync(inter.guild)

        await inter.edit_original_response(f"Rescan complete. Total items added: {item_count}")

    async def _rescan_and_resync(self, guild: disnake.Guild) -> int | None:
        channel = await self._get_log_channel(guild)

        if channel is None:
            logger.error("Log channel not found or inaccessible.")
            return None

        deleted_count = await expression_item_repo.del_all()
        logger.info(f"Deleted {deleted_count} existing expression items.")

        found_channel_expressions = await self._scan_channel_expressions(channel)
        logger.info(f"Found {len(found_channel_expressions)} expression items in the log channel")

        for expression_item in found_channel_expressions:
            logger.debug(f"Adding expression item: {expression_item}")
            await expression_item_repo.add(expression_item)

        logger.info("Rescan complete.")

        all_items = await expression_item_repo.get_all()

        for item in all_items:
            expression = await resolve_expression(guild=guild, item=item)
            #logger.debug(f" - Expression Item: {item}")
            #pprint(expression)

            if expression is None:
                logger.warning(f" -> Could not resolve expression for item ID {item.id}, removing from database and from log (message ID {item.message_id}).")
                await expression_item_repo.delete(item)
                await self._remove_log_message_from_expression(channel, item)
            else:
                if expression.name != item.name:
                    logger.warning(f" -> Name mismatch for item ID {item.id}: expected '{item.name}', got '{expression.name}'. Updating database record.")
                    updated_item = ExpressionItem(
                        id=item.id,
                        name=expression.name,
                        type=item.type,
                        uploader_id=item.uploader_id,
                        message_id=item.message_id,
                        created_at=item.created_at,
                        link=item.link,
                    )
                    await expression_item_repo.update(updated_item)
                    await self._update_asset_log(
                        guild=guild,
                        message_id=item.message_id,
                        embed=asset_embed(
                            guild=guild,
                            kind="Sticker" if item.type == ExpressionItemType.STICKER else "Emoji",
                            name=expression.name,
                            asset_id=item.id or 0,
                            preview_url=expression.url or None,
                            uploader=await resolve_user(self.bot, item.uploader_id) if item.uploader_id else None,
                            created_at=item.created_at,
                            reason=None,
                        ),
                        uploader=await resolve_user(self.bot, item.uploader_id) if item.uploader_id else None,
                    )

        return len(all_items)

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

    async def _update_asset_log(
        self,
        *,
        guild: disnake.Guild,
        message_id: int | None,
        embed: disnake.Embed,
        uploader: disnake.abc.User | None,
    ) -> None:
        channel = await self._get_log_channel(guild)

        if channel is None:
            return

        if message_id is None:
            return

        try:
            message: disnake.Message = await channel.fetch_message(message_id)  # type: ignore
            await message.edit(content=uploader.mention if uploader else None, embed=embed)
        except disnake.HTTPException as e:
            logger.warning(f"Failed to edit message \"{message_id}\" with embed: {embed}")

    async def _scan_channel_expressions(self, channel: disnake.abc.Messageable) -> list[ExpressionItem]:
        expressions_list: list[ExpressionItem] = []

        async for message in channel.history(limit=None, oldest_first=True):
            if not message.embeds:
                logger.warning(f"Skipping message {message.id} with no embeds.")
                continue

            embed: disnake.Embed = message.embeds[0]

            field_name: str | None = self._extract_field_name(
                next(
                    (f for f in embed.fields if f.name == "Name:"),
                    None,
                )
            )

            field_uploader: int | None = self._extract_field_uploader(
                next(
                    (f for f in embed.fields if f.name == "Uploader:"),
                    None,
                )
            )

            field_created: int | None = self._extract_field_created(
                next(
                    (f for f in embed.fields if f.name == "Created:"),
                    None,
                ),
            )

            field_link: str | None = self._extract_field_link(
                next(
                    (f for f in embed.fields if f.name == "Link:"),
                    None,
                )
            )

            field_id: int | None = self._extract_field_id(
                next(
                    (f for f in embed.fields if f.name == "Link:"),
                    None,
                )
            )

            if field_id is None:
                logger.debug(f"Skipping message {message.id} due to missing ID field.")
                await self._remove_log_message_from_id(channel, message.id)
                continue

            if field_name is None:
                logger.debug(f"Skipping message {message.id} due to missing name field.")
                await self._remove_log_message_from_id(channel, message.id)
                continue

            if field_created is None:
                logger.debug(f"Skipping message {message.id} due to missing created field.")
                await self._remove_log_message_from_id(channel, message.id)
                continue

            if field_link is None:
                logger.debug(f"Skipping message {message.id} due to missing link field.")
                await self._remove_log_message_from_id(channel, message.id)
                continue

            if any(item.id == field_id for item in expressions_list):
                logger.debug(f"Skipping message {message.id} due to duplicate ID {field_id}.")
                await self._remove_log_message_from_id(channel, message.id)
                continue

            expression: ExpressionItem = ExpressionItem(
                id=field_id,
                name=field_name,
                type=ExpressionItemType.STICKER if embed.title and "STICKER" in embed.title else ExpressionItemType.EMOJI,
                uploader_id=field_uploader,
                message_id=message.id,
                created_at=field_created,
                link=field_link,
            )

            logger.debug(f"Found message {message.id} with expression item: {expression}")
            expressions_list.append(expression)

        return expressions_list

    async def _remove_log_message_from_expression(self, channel: disnake.abc.Messageable, item: ExpressionItem) -> None:
        try:
            msg = await channel.fetch_message(item.message_id)  # type: ignore
            await msg.delete()
            logger.debug(f"Deleted log message {item.message_id} for item ID {item.id}.")
        except disnake.NotFound:
            logger.warning(f"Could not find log message {item.message_id} to delete for item ID {item.id}.")

    async def _remove_log_message_from_id(self, channel: disnake.abc.Messageable, message_id: int | None) -> None:
        try:
            msg = await channel.fetch_message(message_id)  # type: ignore
            await msg.delete()
            logger.debug(f"Deleted log message {message_id}.")
        except disnake.NotFound:
            logger.warning(f"Could not find log message {message_id} to delete.")

    def _extract_field_id(self, embed_field: EmbedField | None) -> int | None:
        value = self._extract_field_data(embed_field, self._EXTRACT_FIELD_ID)
        return int(value) if value is not None else None

    def _extract_field_name(self, embed_field: EmbedField | None) -> str | None:
        return self._extract_field_data(embed_field, self._EXTRACT_FIELD_NAME)

    def _extract_field_uploader(self, embed_field: EmbedField | None) -> int | None:
        value = self._extract_field_data(embed_field, self._EXTRACT_FIELD_UPLOADER)
        return int(value) if value is not None else None

    def _extract_field_created(self, embed_field: EmbedField | None) -> int | None:
        value = self._extract_field_data(embed_field, self._EXTRACT_FIELD_CREATED)
        return int(value) if value is not None else None

    def _extract_field_link(self, embed_field: EmbedField | None) -> str | None:
        return self._extract_field_data(embed_field, self._EXTRACT_FIELD_LINK)

    def _extract_field_data(self, embed_field: EmbedField | None, pattern: re.Pattern[str]) -> str | None:
        if embed_field is None:
            return None

        match = re.search(pattern, embed_field.value or "")

        return match.group(1) if match else None
