from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord import app_commands
from discord.ext import commands

from bot.db.repos.private_message_repo import private_message_repo
from bot.models.private_message_record import PrivateMessageRecord
from bot.utils.logger import logger
from bot.utils.settings import settings


class PrivateMessageCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="dm_send",
        description="Send a DM to a user and log the message."
    )
    @app_commands.describe(
        user="The user to DM",
        message="The message to send"
    )
    async def dm_send(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        message: str,
    ) -> None:
        if not await self._has_role_permission(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        record = PrivateMessageRecord(
            id=0,
            from_user_id=interaction.user.id,
            to_user_id=user.id,
            message=message,
            created_at=datetime.now(tz=ZoneInfo("UTC")),
        )

        guild = interaction.guild.name if interaction.guild else "Server"
        embed = discord.Embed(
            title=settings.private_message_title.format(sender_guild_name=guild) if (
                settings.private_message_title
             ) else "Private Message",
            description=record.message,
            color=discord.Color.blurple(),
            timestamp=record.created_at,
        )
        embed.set_footer(
            text=settings.private_message_footer.format(
                sender_username=interaction.user.name,
                sender_guild_name=guild,
            ),
            icon_url=interaction.user.display_avatar.url,
        )

        if interaction.guild and interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)

        try:
            await user.send(embed=embed)
            logger.info(f'Sent DM to user {user.id} from {interaction.user.id}: "{self._flatten_newlines_and_strip(record.message)}"')
        except discord.Forbidden:
            await interaction.followup.send(
                "I can't send a DM to that user (DMs disabled or blocked).",
                ephemeral=True,
            )
            return
        except discord.HTTPException as exc:
            logger.error(f"Failed to send DM: {exc}")
            await interaction.followup.send(
                "Failed to send the DM due to an unexpected error.",
                ephemeral=True,
            )
            return

        await private_message_repo.add(record)
        await interaction.followup.send(
            f"DM successfully sent to **{user}**.",
            ephemeral=True,
        )

    @app_commands.command(
        name="dm_list",
        description="List the latest logged DMs."
    )
    @app_commands.describe(
        to_user="Filter by receiving user",
        from_user="Filter by sending user",
        limit="Max number of results (default 10, max 25)",
        offset="Number of results to skip (default 0)",
    )
    async def dm_list(
        self,
        interaction: discord.Interaction,
        to_user: discord.User | None = None,
        from_user: discord.User | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> None:
        if not await self._has_role_permission(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        limit = max(1, min(int(limit), 25))
        offset = max(0, int(offset))

        records = await private_message_repo.get_latest(
            to_user_id=to_user.id if to_user else None,
            from_user_id=from_user.id if from_user else None,
            limit=limit,
            offset=offset,
        )

        if not records:
            await interaction.followup.send(
                "No matching messages found.",
                ephemeral=True,
            )
            return

        if to_user and from_user:
            title = (
                f"Logged DMs sent by {from_user} to {to_user} "
                f"(latest first)"
            )
        elif to_user:
            title = (
                f"Logged DMs received by {to_user} "
                f"(latest first)"
            )
        elif from_user:
            title = (
                f"Logged DMs sent by {from_user} "
                f"(latest first)"
            )
        else:
            title = "Latest logged DMs"

        embed = discord.Embed(
            title=title,
            color=discord.Color.blurple(),
        )

        lines: list[str] = []
        for r in records:
            ts = int(r.created_at.timestamp())
            msg = self._flatten_newlines_and_strip(r.message)
            if len(msg) > 120:
                msg = msg[:117] + "..."

            lines.append(
                f"• <t:{ts}:f> "
                f"**<@{r.from_user_id}> → <@{r.to_user_id}>**: {msg}"
            )

        embed.description = "\n".join(lines)
        embed.set_footer(
            text=f"Showing {len(records)} message(s) • offset={offset} • limit={limit}"
        )

        await interaction.followup.send(embed=embed, ephemeral=True)

    def _flatten_newlines_and_strip(self, text: str) -> str:
        return " ".join(line.strip() for line in text.splitlines() if line.strip())

    async def _has_role_permission(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if not settings.enabled_roles:
            logger.warning(
                "No roles are configured to use private message commands."
            )
            await interaction.response.send_message(
                "No roles are configured to use this command.",
                ephemeral=True,
            )
            return False

        if interaction.guild is None:
            logger.debug(
                "Private message command used outside of a guild."
            )
            await interaction.response.send_message(
                "This command can only be used in a server.",
                ephemeral=True,
            )
            return False

        member = interaction.guild.get_member(interaction.user.id)
        if member is None:
            logger.warning(
                f"Unable to resolve server member for user {interaction.user.id}."
            )
            await interaction.response.send_message(
                "Unable to resolve your server roles.",
                ephemeral=True,
            )
            return False

        if not any(
            role.id in settings.enabled_roles for role in member.roles
        ):
            logger.warning(
                f"User {interaction.user.id} lacks required roles "
                "to use private message commands."
            )
            await interaction.response.send_message(
                "You do not have permission to use this command.",
                ephemeral=True,
            )
            return False

        return True
