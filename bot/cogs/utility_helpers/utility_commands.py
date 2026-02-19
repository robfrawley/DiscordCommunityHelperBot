from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from collections import Counter
from enum import Enum

import disnake
from disnake.ext import commands

from bot.utils.logger import logger
from bot.utils.settings import settings
from bot.utils.helpers import check_command_role_permission, chunk_text
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


def _parse_roles(inter: disnake.ApplicationCommandInteraction, value: str) -> list[disnake.Role]:
    """
    Parse roles from mentions/IDs/names in a single string.
    """
    guild = inter.guild
    if guild is None:
        raise ValueError("This command can only be used in a server.")

    roles: list[disnake.Role] = []

    # First try IDs/mentions
    ids = _extract_ids(value)
    for rid in ids:
        r = guild.get_role(rid)
        if r:
            roles.append(r)

    # If no IDs matched, fall back to exact name matching (comma/newline separated)
    if not roles:
        parts = [p.strip() for p in re.split(r"[,\n]+", value) if p.strip()]
        name_map = {r.name.lower(): r for r in guild.roles}
        for p in parts:
            r = name_map.get(p.lower())
            if r:
                roles.append(r)

    # De-dupe
    seen: set[int] = set()
    deduped: list[disnake.Role] = []
    for r in roles:
        if r.id not in seen:
            seen.add(r.id)
            deduped.append(r)

    if not deduped:
        raise ValueError("Couldn't find any roles from that input. Use role mentions, IDs, or exact role names.")

    return deduped


def _parse_members(inter: disnake.ApplicationCommandInteraction, value: str) -> list[disnake.Member]:
    """
    Parse members from mentions/IDs/usernames/display names in a single string.
    """
    guild = inter.guild
    if guild is None:
        raise ValueError("This command can only be used in a server.")

    members: list[disnake.Member] = []

    ids = _extract_ids(value)
    for uid in ids:
        m = guild.get_member(uid)
        if m:
            members.append(m)

    if not members:
        parts = [p.strip() for p in re.split(r"[,\n]+", value) if p.strip()]
        for p in parts:
            p_low = p.lower()
            m = disnake.utils.find(
                lambda mm: (mm.name.lower() == p_low) or (mm.display_name.lower() == p_low),
                guild.members,
            )
            if m:
                members.append(m)

    # De-dupe
    seen: set[int] = set()
    deduped: list[disnake.Member] = []
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


class AdaultRoleAction(Enum):
    ADD = "add"
    REMOVE = "remove"


class UtilityCommands(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def adult_add_or_remove_role(
        self,
        inter: disnake.ApplicationCommandInteraction,
        to_members: str = commands.Param(
            default=None,
            description="Members to apply the role to (mentions/IDs/names).",
        ),
        action: AdaultRoleAction = commands.Param(
            default=AdaultRoleAction.REMOVE,
            description="Action to perform (add/remove).",
        ),
    ) -> None:
        if not await check_command_role_permission(inter, settings.command_enabled_adult_roles):
            return

        if not inter.guild:
            await inter.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True, with_message=True)
        logger.debug(f'Initiating /adult{"verify" if action == AdaultRoleAction.ADD else "unverify"} command by user {inter.user} ({inter.user.id}) in guild {guild.name} ({guild.id}) with input: {to_members!r}')
        try:
            apply_roles_list = _parse_roles(inter, " " + " ".join(r.mention() for r in settings.adult_role_ids))
            to_members_list = _parse_members(inter, to_members) if to_members else None
            roles_str = ", ".join(r.mention() for r in settings.adult_role_ids)
            members_str = ", ".join(m.mention for m in to_members_list) if to_members_list else ""
        except ValueError as e:
            await inter.followup.send(str(e), ephemeral=True)
            return

        if self.bot.user is None:
            await inter.followup.send("Bot user information is not available.", ephemeral=True)
            return

        me = guild.me or guild.get_member(self.bot.user.id)  # type: ignore[union-attr]
        if me is None:
            await inter.followup.send("Couldn't resolve the bot member in this guild.", ephemeral=True)
            return

        if not me.guild_permissions.manage_roles:
            await inter.followup.send("I need **Manage Roles** permission to do that.", ephemeral=True)
            return

        if to_members_list is None:
            await inter.followup.send("No members specified. Please specify members to apply the role to.", ephemeral=True)
            return

        preview_embed = disnake.Embed(
            title=f"Confirm role {'assignment' if action == AdaultRoleAction.ADD else 'removal'}",
            description="Click **confirm** to apply the roles as specified below.\n\n",
        )
        preview_embed.add_field(name=f"{'Add' if action == AdaultRoleAction.ADD else 'Remove'} Roles", value=roles_str, inline=False)
        preview_embed.add_field(name="To Users", value=members_str, inline=False)

        view = ConfirmApplyRolesView(requester_id=inter.user.id, timeout=60.0)
        confirm_msg = await inter.followup.send(embed=preview_embed, view=view, ephemeral=True, wait=True)

        await view.wait()

        if view.confirmed is None:
            try:
                await confirm_msg.edit(content="⌛ Timed out. No roles were changed.", embed=None, view=None)
            except Exception:
                pass
            return

        if view.confirmed is False:
            return

        now = datetime.now(timezone.utc)
        reason = f"/adultverify by {inter.user} ({inter.user.id}) at {now.isoformat()}"

        failures: Counter[str] = Counter()
        attempted = 0
        updated = 0
        skipped_already_had_all = 0
        skipped_excluded_role = 0

        for member in to_members_list:
            if all(r in member.roles for r in apply_roles_list) and action == AdaultRoleAction.ADD:
                logger.debug(
                    f'Skipping member {member.name} with ID "{member.id}" (already has all requested roles)...'
                )
                skipped_already_had_all += 1
                continue

            attempted += 1
            try:
                if action == AdaultRoleAction.ADD:
                    await member.add_roles(*apply_roles_list, reason=reason)
                else:
                    await member.remove_roles(*apply_roles_list, reason=reason)
                updated += 1
                logger.info(f'Applied roles to member {member.name} with ID "{member.id}".')
            except disnake.Forbidden:
                failures["forbidden"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: Forbidden")
            except disnake.HTTPException:
                failures["http_exception"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: HTTPException")
            except Exception:
                failures["unknown"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: General exception")

        result = ApplyRolesResult(
            total_targets=len(to_members_list),
            attempted=attempted,
            updated=updated,
            skipped_already_had_all=skipped_already_had_all,
            skipped_excluded_role=skipped_excluded_role,
            failures=failures,
        )

        failure_bits: list[str] = [f"{k}: {v}" for k, v in result.failures.most_common()] if result.failures else []
        failures_str = " | ".join(failure_bits) if failure_bits else "None"

        embed = disnake.Embed(
            title=f"Role {'application' if action == AdaultRoleAction.ADD else 'removal'} complete",
            description=f"Applied: {roles_str}",
            timestamp=now,
        )
        embed.add_field(name=f"{'Applied' if action == AdaultRoleAction.ADD else 'Removed'} roles", value=roles_str, inline=False)
        embed.add_field(name="Targets", value=str(result.total_targets), inline=True)
        embed.add_field(name="Attempted", value=str(result.attempted), inline=True)
        embed.add_field(name="Updated", value=str(result.updated), inline=True)
        embed.add_field(name="Skipped (Already Had)", value=str(result.skipped_already_had_all), inline=True)
        embed.add_field(name="Skipped (Excluded Role)", value=str(result.skipped_excluded_role), inline=True)
        embed.add_field(name="Failures", value=failures_str, inline=False)

        await inter.followup.send(embed=embed, ephemeral=True)

        logger.debug_dataset(
            "util_apply_roles completed",
            {
                "guild_id": guild.id,
                "actor_id": inter.user.id,
                "roles": [r.id for r in apply_roles_list],
                "target_count": result.total_targets,
                "attempted": result.attempted,
                "updated": result.updated,
                "skipped_already_had_all": result.skipped_already_had_all,
                "skipped_excluded_role": result.skipped_excluded_role,
                "failures": dict(result.failures),
            },
        )

    @commands.slash_command(
        name="adult_verify",
        description="Verify adult users and assign them a configurable role.",
    )
    async def adult_verify(
        self,
        inter: disnake.ApplicationCommandInteraction,
        to_members: str = commands.Param(
            default=None,
            description="Members to apply the role to (mentions/IDs/names).",
        ),
    ) -> None:
        await self.adult_add_or_remove_role(inter, to_members=to_members, action=AdaultRoleAction.ADD)

    @commands.slash_command(
        name="adult_unverify",
        description="Unverify adult users and remove their configurable role.",
    )
    async def adult_unverify(
        self,
        inter: disnake.ApplicationCommandInteraction,
        to_members: str = commands.Param(
            default=None,
            description="Members to apply the role to (mentions/IDs/names).",
        ),
    ) -> None:
        await self.adult_add_or_remove_role(inter, to_members=to_members, action=AdaultRoleAction.REMOVE)


    @commands.slash_command(
        name="util_get_all_matching_users",
        description="Get all users with specific roles. Input can be role mentions, IDs, or exact names.",
    )
    async def util_get_all_matching_users(
        self,
        inter: disnake.ApplicationCommandInteraction,
        searched_roles: str = commands.Param(
            description="Roles a user MUST have (mentions, IDs, or exact names). Example: @RoleA @RoleB"
        ),
        excluded_roles: str | None = commands.Param(
            default=None,
            description="Skip members who have ANY of these roles (mentions, IDs, or exact names). Optional.",
        ),
        exclude_bots: bool = commands.Param(
            default=True,
            description="Exclude bot accounts from the results.",
        ),
    ) -> None:
        if not await check_command_role_permission(inter, settings.command_enabled_elevated_roles):
            return

        if not inter.guild:
            await inter.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        guild = inter.guild

        try:
            searched_roles_list = _parse_roles(inter, searched_roles)
            excluded_roles_list = _parse_roles(inter, excluded_roles) if excluded_roles else []
        except ValueError as e:
            await inter.response.send_message(str(e), ephemeral=True)
            return

        searched_role_ids = {r.id for r in searched_roles_list}
        excluded_role_ids = {r.id for r in excluded_roles_list}

        matched: list[disnake.Member] = []
        members = list(guild.members)
        if not members:
            async for m in guild.fetch_members(limit=None):
                members.append(m)

        for member in members:
            if exclude_bots and member.bot:
                logger.debug(f'Skipping bot member {member} ({member.id})...')
                continue

            member_role_ids = {r.id for r in member.roles}

            if not searched_role_ids.issubset(member_role_ids):
                logger.debug(f'Skipping member {member} ({member.id}) due to missing required role...')
                continue

            if excluded_role_ids & member_role_ids:
                logger.debug(f'Skipping member {member} ({member.id}) due to excluded role...')
                continue

            logger.debug(f'Member "{member}" ({member.id}) matches the role criteria.')
            matched.append(member)

        role_mentions = ", ".join(r.mention for r in searched_roles_list)
        lines = [f"{m.mention} — {m} (`{m.id}`)" for m in matched] or ["(none)"]

        header = f"**Required roles:** {role_mentions}\n**Matched users:** {len(matched)}\n"
        if excluded_roles_list:
            ex_mentions = ", ".join(r.mention for r in excluded_roles_list)
            header += f"**Excluded roles:** {ex_mentions}\n"
        header += "\n"

        full_text = header + "\n".join(lines)
        chunks = chunk_text(full_text, limit=2000)

        await inter.response.send_message(
            chunks[0],
            allowed_mentions=disnake.AllowedMentions.none(),
        )

        for chunk in chunks[1:]:
            await inter.followup.send(chunk, allowed_mentions=disnake.AllowedMentions.none())

    @commands.slash_command(
        name="util_apply_roles",
        description="Apply one or more roles to select or all users in the server.",
    )
    async def util_apply_roles(
        self,
        inter: disnake.ApplicationCommandInteraction,
        apply_roles: str = commands.Param(
            description="Roles to apply (mentions, IDs, or exact names). Example: @RoleA @RoleB"
        ),
        to_members: str | None = commands.Param(
            default=None,
            description="Members to apply the roles to (mentions/IDs/names). Leave empty to apply to all members.",
        ),
        excluded_roles: str | None = commands.Param(
            default=None,
            description="Skip members who have ANY of these roles (mentions, IDs, or exact names). Optional.",
        ),
        exclude_bots: bool = commands.Param(
            default=True,
            description="Exclude bot accounts from the operation.",
        ),
    ) -> None:
        if not await check_command_role_permission(inter, settings.command_enabled_elevated_roles):
            return

        guild = inter.guild
        if guild is None:
            await inter.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        await inter.response.defer(ephemeral=True, with_message=True)

        try:
            apply_roles_list = _parse_roles(inter, apply_roles)
            excluded_roles_list = _parse_roles(inter, excluded_roles) if excluded_roles else []
            to_members_list = _parse_members(inter, to_members) if to_members else None
        except ValueError as e:
            await inter.followup.send(str(e), ephemeral=True)
            return

        if self.bot.user is None:
            await inter.followup.send("Bot user information is not available.", ephemeral=True)
            return

        me = guild.me or guild.get_member(self.bot.user.id)  # type: ignore[union-attr]
        if me is None:
            await inter.followup.send("Couldn't resolve the bot member in this guild.", ephemeral=True)
            return

        if not me.guild_permissions.manage_roles:
            await inter.followup.send("I need **Manage Roles** permission to do that.", ephemeral=True)
            return

        blocked_roles = [r for r in apply_roles_list if r >= me.top_role]  # type: ignore[operator]
        if blocked_roles:
            await inter.followup.send(
                "I can't apply these roles due to role hierarchy (they're >= my top role): "
                + ", ".join(r.mention for r in blocked_roles),
                ephemeral=True,
            )
            return

        # Determine target members
        targets: list[disnake.Member]
        if to_members_list is None:
            targets = list(guild.members)
            if not targets:
                try:
                    async for m in guild.fetch_members(limit=None):
                        targets.append(m)
                except disnake.Forbidden:
                    await inter.followup.send(
                        "I can't enumerate all members (missing permissions/intents). "
                        "Try specifying members explicitly.",
                        ephemeral=True,
                    )
                    return
        else:
            targets = list(to_members_list)

        excluded_role_ids: set[int] = {r.id for r in excluded_roles_list}

        roles_str = ", ".join(r.mention for r in apply_roles_list)
        excluded_str = ", ".join(r.mention for r in excluded_roles_list) if excluded_roles_list else "None"
        scope_str = "All members in server" if to_members_list is None else f"{len(targets)} specified member(s)"

        preview_embed = disnake.Embed(
            title="Confirm role assignment",
            description="Click **confirm** to apply the roles as specified below.\n\n",
        )
        preview_embed.add_field(name="Apply Roles", value=roles_str, inline=False)
        preview_embed.add_field(name="Target Roles", value=scope_str, inline=False)
        preview_embed.add_field(name="Excluded Roles", value=excluded_str, inline=False)
        preview_embed.add_field(name="Include Bots", value="NO" if exclude_bots else "YES", inline=False)

        view = ConfirmApplyRolesView(requester_id=inter.user.id, timeout=60.0)
        confirm_msg = await inter.followup.send(embed=preview_embed, view=view, ephemeral=True, wait=True)

        await view.wait()

        if view.confirmed is None:
            try:
                await confirm_msg.edit(content="⌛ Timed out. No roles were changed.", embed=None, view=None)
            except Exception:
                pass
            return

        if view.confirmed is False:
            return

        now = datetime.now(timezone.utc)
        reason = f"/util_apply_roles by {inter.user} ({inter.user.id}) at {now.isoformat()}"

        failures: Counter[str] = Counter()
        attempted = 0
        updated = 0
        skipped_already_had_all = 0
        skipped_excluded_role = 0

        for member in targets:
            if member.bot and exclude_bots:
                logger.debug(f'Skipping bot member {member.name} with ID "{member.id}"...')
                continue

            if excluded_role_ids:
                member_role_ids = {r.id for r in member.roles}
                if member_role_ids & excluded_role_ids:
                    logger.debug(f'Skipping member {member.name} with ID "{member.id}" (has excluded role)...')
                    skipped_excluded_role += 1
                    continue

            if all(r in member.roles for r in apply_roles_list):
                logger.debug(
                    f'Skipping member {member.name} with ID "{member.id}" (already has all requested roles)...'
                )
                skipped_already_had_all += 1
                continue

            attempted += 1
            try:
                await member.add_roles(*apply_roles_list, reason=reason)
                updated += 1
                logger.info(f'Applied roles to member {member.name} with ID "{member.id}".')
            except disnake.Forbidden:
                failures["forbidden"] += 1
                logger.error(f"Error applying roles to {member.id} in guild {guild.id}: Forbidden")
            except disnake.HTTPException:
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

        failure_bits: list[str] = [f"{k}: {v}" for k, v in result.failures.most_common()] if result.failures else []
        failures_str = " | ".join(failure_bits) if failure_bits else "None"

        embed = disnake.Embed(
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

        await inter.followup.send(embed=embed, ephemeral=True)

        logger.debug_dataset(
            "util_apply_roles completed",
            {
                "guild_id": guild.id,
                "actor_id": inter.user.id,
                "roles": [r.id for r in apply_roles_list],
                "excluded_roles": [r.id for r in excluded_roles_list],
                "target_count": result.total_targets,
                "attempted": result.attempted,
                "updated": result.updated,
                "skipped_already_had_all": result.skipped_already_had_all,
                "skipped_excluded_role": result.skipped_excluded_role,
                "failures": dict(result.failures),
            },
        )
