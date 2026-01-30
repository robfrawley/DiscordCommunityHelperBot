from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import Counter

import discord
from discord import app_commands
from discord.ext import commands

from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.utils.helpers import check_command_role_permission
from bot.views.confirm_apply_roles_view import ConfirmApplyRolesView


_ROLE_MENTION_RE = re.compile(r"<@&(\d+)>")
_USER_MENTION_RE = re.compile(r"<@!?(\d+)>")


def _extract_ids(raw: str) -> list[int]:
    """
    Extracts any snowflake-like IDs from:
      - <@&123>, <@123>, <@!123>
      - plain 123
    """
    ids: list[int] = []
    for m in _ROLE_MENTION_RE.finditer(raw):
        ids.append(int(m.group(1)))
    for m in _USER_MENTION_RE.finditer(raw):
        ids.append(int(m.group(1)))

    # plain IDs too (avoid double-counting ones already included)
    for token in re.split(r"[\s,]+", raw.strip()):
        if token.isdigit():
            ids.append(int(token))

    # de-dupe preserving order
    seen: set[int] = set()
    out: list[int] = []
    for i in ids:
        if i not in seen:
            seen.add(i)
            out.append(i)
    return out


class RoleListTransformer(app_commands.Transformer):
    """
    Slash commands don't natively support list[discord.Role] parameters.
    This transformer lets users input: role mentions, IDs, or names.
    Examples:
      - @RoleA @RoleB
      - 123 456
      - "Role A, Role B"
    """

    async def transform(self, interaction: discord.Interaction, value: str) -> list[discord.Role]:
        guild = interaction.guild
        if guild is None:
            raise ValueError("This command can only be used in a server.")

        roles: list[discord.Role] = []

        # First try IDs/mentions
        ids = _extract_ids(value)
        for rid in ids:
            r = guild.get_role(rid)
            if r:
                roles.append(r)

        # If no IDs matched, fall back to name-based matching (comma-separated or newline)
        if not roles:
            parts = [p.strip() for p in re.split(r"[,\n]+", value) if p.strip()]
            name_map = {r.name.lower(): r for r in guild.roles}
            for p in parts:
                r = name_map.get(p.lower())
                if r:
                    roles.append(r)

        # De-dupe
        seen: set[int] = set()
        deduped: list[discord.Role] = []
        for r in roles:
            if r.id not in seen:
                seen.add(r.id)
                deduped.append(r)

        if not deduped:
            raise ValueError(
                "Couldn't find any roles from that input. Use role mentions, IDs, or exact role names."
            )

        return deduped


class MemberListTransformer(app_commands.Transformer):
    """
    Optional list of members (mentions/IDs/names).
    If omitted, we apply to all members in the guild.
    """

    async def transform(self, interaction: discord.Interaction, value: str) -> list[discord.Member]:
        guild = interaction.guild
        if guild is None:
            raise ValueError("This command can only be used in a server.")

        members: list[discord.Member] = []

        ids = _extract_ids(value)
        for uid in ids:
            m = guild.get_member(uid)
            if m:
                members.append(m)

        if not members:
            parts = [p.strip() for p in re.split(r"[,\n]+", value) if p.strip()]
            for p in parts:
                p_low = p.lower()
                m = discord.utils.find(
                    lambda mm: (mm.name.lower() == p_low) or (mm.display_name.lower() == p_low),
                    guild.members,
                )
                if m:
                    members.append(m)

        # De-dupe
        seen: set[int] = set()
        deduped: list[discord.Member] = []
        for m in members:
            if m.id not in seen:
                seen.add(m.id)
                deduped.append(m)

        if not deduped:
            raise ValueError(
                "Couldn't find any members from that input. Use user mentions, IDs, or exact usernames/nicknames."
            )

        return deduped


@dataclass(slots=True)
class ApplyRolesResult:
    total_targets: int
    attempted: int
    updated: int
    skipped_already_had_all: int
    skipped_excluded_role: int
    failures: Counter


class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="util_apply_roles",
        description="Apply one or more roles to select or all users in the server.",
    )
    @app_commands.describe(
        apply_roles="Roles to apply (mentions, IDs, or exact names). Example: @RoleA @RoleB",
        to_members="Members to apply the roles to (mentions/IDs/names). Leave empty to apply to all members.",
        excluded_roles="Skip members who have ANY of these roles (mentions, IDs, or exact names). Optional.",
    )
    async def util_apply_roles(
        self,
        interaction: discord.Interaction,
        *,
        apply_roles: app_commands.Transform[list[discord.Role], RoleListTransformer],
        to_members: app_commands.Transform[list[discord.Member], MemberListTransformer] | None = None,
        excluded_roles: app_commands.Transform[list[discord.Role], RoleListTransformer] | None = None,
        exclude_bots: bool = True,
    ) -> None:
        if not await check_command_role_permission(interaction, settings.command_enabled_elevated_roles):
            return

        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)

        me = guild.me or guild.get_member(self.bot.user.id)  # type: ignore[union-attr]
        if me is None:
            await interaction.followup.send("Couldn't resolve the bot member in this guild.", ephemeral=True)
            return

        if not guild.me.guild_permissions.manage_roles:  # type: ignore[union-attr]
            await interaction.followup.send("I need **Manage Roles** permission to do that.", ephemeral=True)
            return

        # Role hierarchy checks (bot must be higher than target roles)
        blocked_roles = [r for r in apply_roles if r >= me.top_role]  # type: ignore[operator]
        if blocked_roles:
            await interaction.followup.send(
                "I can't apply these roles due to role hierarchy (they're >= my top role): "
                + ", ".join(r.mention for r in blocked_roles),
                ephemeral=True,
            )
            return

        # Determine target members
        targets: list[discord.Member]
        if to_members is None:
            targets = list(guild.members)
            if not targets:
                try:
                    async for m in guild.fetch_members(limit=None):
                        targets.append(m)
                except discord.Forbidden:
                    await interaction.followup.send(
                        "I can't enumerate all members (missing permissions/intents). "
                        "Try specifying members explicitly.",
                        ephemeral=True,
                    )
                    return
        else:
            targets = list(to_members)

        # Precompute exclusion set for fast membership checks
        excluded_role_ids: set[int] = set(r.id for r in (excluded_roles or []))

        roles_str = ", ".join(r.mention for r in apply_roles)
        excluded_str = ", ".join(r.mention for r in excluded_roles) if excluded_roles else "None"
        scope_str = "All members in server" if to_members is None else f"{len(targets)} specified member(s)"

        # Rough pre-flight summary (still not mutating anything)
        preview_embed = discord.Embed(
            title="Confirm role assignment",
            description=(
                "Click **confirm** to apply the roles as specified below.\n\n"
            ),
        )
        preview_embed.add_field(name="Apply Roles", value=roles_str, inline=False)
        preview_embed.add_field(name="Target Roles", value=scope_str, inline=False)
        preview_embed.add_field(name="Excluded Roles", value=excluded_str, inline=False)
        preview_embed.add_field(name="Include Bots", value="NO" if exclude_bots else "YES", inline=False)

        view = ConfirmApplyRolesView(requester_id=interaction.user.id, timeout=60.0)
        confirm_msg = await interaction.followup.send(embed=preview_embed, view=view, ephemeral=True, wait=True)

        # Wait for confirm/cancel/timeout
        await view.wait()

        if view.confirmed is None:
            # Timed out
            try:
                await confirm_msg.edit(content="⌛ Timed out. No roles were changed.", embed=None, view=None)
            except Exception:
                pass
            return

        if view.confirmed is False:
            # Cancelled (message already updated by the view)
            return

        # Proceed with role application
        now = datetime.now(timezone.utc)
        reason = f"/util_apply_roles by {interaction.user} ({interaction.user.id}) at {now.isoformat()}"

        failures: Counter[str] = Counter()
        attempted = 0
        updated = 0
        skipped_already_had_all = 0
        skipped_excluded_role = 0

        for member in targets:
            if member.bot and exclude_bots:
                logger.debug(f'Skipping bot member {member.name} with ID "{member.id}"...')
                continue

            # Skip if member has any excluded role
            if excluded_role_ids:
                member_role_ids = {r.id for r in member.roles}
                if member_role_ids & excluded_role_ids:
                    logger.debug(
                        f'Skipping member {member.name} with ID "{member.id}" (has excluded role)...'
                    )
                    skipped_excluded_role += 1
                    continue

            if all(r in member.roles for r in apply_roles):
                logger.debug(
                    f'Skipping member {member.name} with ID "{member.id}" (already has all requested roles)...'
                )
                skipped_already_had_all += 1
                continue

            attempted += 1
            try:
                await member.add_roles(*apply_roles, reason=reason)
                updated += 1
                logger.info(f'Applied roles to member {member.name} with ID "{member.id}".')
            except discord.Forbidden:
                failures["forbidden"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: Forbidden")
            except discord.HTTPException:
                failures["http_exception"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: HTTPException")
            except Exception:
                failures["unknown"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: General exception")

        result = ApplyRolesResult(
            total_targets=len(targets),
            attempted=attempted,
            updated=updated,
            skipped_already_had_all=skipped_already_had_all,
            skipped_excluded_role=skipped_excluded_role,
            failures=failures,
        )

        failure_bits: list[str] = []
        if result.failures:
            for k, v in result.failures.most_common():
                failure_bits.append(f"{k}: {v}")
        failures_str = " | ".join(failure_bits) if failure_bits else "None"

        embed = discord.Embed(
            title="Role application complete",
            description=f"Applied: {roles_str}",
            timestamp=now,
        )
        embed.add_field(name="Applied roles", value=roles_str, inline=False)
        embed.add_field(name="Excluded roles", value=excluded_str, inline=False)
        embed.add_field(name="Targets", value=str(result.total_targets), inline=True)
        embed.add_field(name="Attempted", value=str(result.attempted), inline=True)
        embed.add_field(name="Updated", value=str(result.updated), inline=True)
        embed.add_field(name="Skipped (Already Had)", value=str(result.skipped_already_had_all), inline=True)
        embed.add_field(name="Skipped (Excluded Role)", value=str(result.skipped_excluded_role), inline=True)
        embed.add_field(name="Failures", value=failures_str, inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

        logger.debug_dataset(
            "util_apply_roles completed",
            {
                "guild_id": guild.id,
                "actor_id": interaction.user.id,
                "roles": [r.id for r in apply_roles],
                "excluded_roles": [r.id for r in (excluded_roles or [])],
                "target_count": result.total_targets,
                "attempted": result.attempted,
                "updated": result.updated,
                "skipped_already_had_all": result.skipped_already_had_all,
                "skipped_excluded_role": result.skipped_excluded_role,
                "failures": dict(result.failures),
            },
        )
