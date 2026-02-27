from __future__ import annotations

import csv
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Set

import disnake
from disnake.ext import commands
from bot.utils.settings import settings
from bot.utils.logger import logger

from bot.utils.helpers import (
    check_command_role_permission,
)


MENTION_RE = re.compile(r"<@!?(\d{15,25})>")


def _parse_user_ids(raw: str) -> Set[int]:
    if not raw or not raw.strip():
        return set()

    ids: Set[int] = set()

    for m in MENTION_RE.finditer(raw):
        ids.add(int(m.group(1)))

    scrubbed = MENTION_RE.sub(" ", raw)
    for token in re.split(r"[,\s]+", scrubbed.strip()):
        if not token:
            continue
        if token.isdigit():
            ids.add(int(token))

    return ids


def _parse_dt(dt_str: Optional[str]) -> Optional[datetime]:
    """
    Parses a datetime string into an aware UTC datetime.

    Accepted examples:
      - 2026-02-27
      - 2026-02-27T13:45
      - 2026-02-27 13:45
      - 2026-02-27T13:45:12
      - 2026-02-27T13:45:12Z
      - 2026-02-27T13:45:12+00:00
    If no timezone is given, it assumes UTC.
    """
    if not dt_str:
        return None

    s = dt_str.strip()
    if not s:
        return None

    # Normalize a few common cases
    s = s.replace(" ", "T")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(
            "Invalid datetime. Use formats like: "
            "2026-02-27 or 2026-02-27T13:45 or 2026-02-27T13:45:12Z"
        )

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)

    return dt


def _dt_utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.isoformat()


async def _get_op_message(
    ch: disnake.abc.Messageable,
    msg: disnake.Message,
) -> Optional[disnake.Message]:
    ref = getattr(msg, "reference", None)
    if ref is not None and getattr(ref, "message_id", None):
        resolved = getattr(ref, "resolved", None)
        if isinstance(resolved, disnake.Message):
            return resolved

        try:
            fetched = await ch.fetch_message(ref.message_id)  # type: ignore[attr-defined]
            if isinstance(fetched, disnake.Message):
                return fetched
        except Exception:
            pass

    try:
        async for prior in ch.history(limit=1, before=msg, oldest_first=False):  # type: ignore[attr-defined]
            return prior
    except Exception:
        return None

    return None


@dataclass(frozen=True)
class LogRow:
    kind: str  # "op" or "response"
    message_id: int
    author_id: int
    dt_utc_iso: str
    contents: str


class PeakyToolsMessageLoggerCommands(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.slash_command(
        name="log_user_messages",
        description="Scan all channels and export messages from given users to CSV.",
    )
    @commands.default_member_permissions(administrator=True)
    async def log_user_messages(
        self,
        inter: disnake.ApplicationCommandInteraction,
        users: str = commands.Param(
            description="User mentions and/or IDs (e.g. @User, 123, <@!456>). Separate with spaces/commas."
        ),
        after: Optional[str] = commands.Param(
            default=None,
            description="Optional start datetime (UTC). e.g. 2026-02-01 or 2026-02-01T12:00Z",
        ),
        before: Optional[str] = commands.Param(
            default=None,
            description="Optional end datetime (UTC). e.g. 2026-03-01 or 2026-03-01T12:00Z",
        ),
        limit_per_channel: int = commands.Param(
            default=10000000,
            description="Max messages to scan per channel (newest->oldest via history).",
        ),
        include_threads: bool = commands.Param(
            default=True,
            description="Also scan active threads (where accessible).",
        ),
    ) -> None:
        if not await check_command_role_permission(inter, settings.command_enabled_roles):
            return

        await inter.response.defer(ephemeral=True)

        guild = inter.guild
        if guild is None:
            await inter.edit_original_message("This command must be used in a server.")
            return

        target_user_ids = _parse_user_ids(users)
        if not target_user_ids:
            await inter.edit_original_message(
                "No valid users found. Provide mentions and/or numeric IDs."
            )
            return

        try:
            after_dt = _parse_dt(after)
            before_dt = _parse_dt(before)
        except ValueError as e:
            await inter.edit_original_message(str(e))
            return

        if after_dt and before_dt and after_dt > before_dt:
            await inter.edit_original_message("`after` must be earlier than `before`.")
            return

        me = guild.me
        if me is None:
            await inter.edit_original_message("Could not resolve the bot member in this guild.")
            return

        channels: list[disnake.abc.Messageable] = list(guild.text_channels)

        if include_threads:
            try:
                channels.extend(list(getattr(guild, "threads", []) or []))
            except Exception:
                pass

        scanned_channels = 0
        total_found = 0
        total_scanned_msgs = 0
        total_op_rows = 0

        ts = int(datetime.now(tz=timezone.utc).timestamp())
        out_path = f"user_messages_{guild.id}_{ts}.csv"

        def _norm_contents(s: str) -> str:
            # Replace CRLF, CR, LF with single spaces and collapse excess whitespace
            return " ".join((s or "").replace("\r\n", " ")
                                        .replace("\r", " ")
                                        .replace("\n", " ")
                                        .split())

        try:
            with open(out_path, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                # Include kind column
                writer.writerow(["kind", "message_id", "author_id", "datetime", "contents"])

                for ch in channels:
                    logger.debug(f"Scanning channel {ch.id} ({getattr(ch, 'name', 'DM/Thread')})...")

                    try:
                        perms = ch.permissions_for(me)  # type: ignore[attr-defined]
                        if not (perms.read_messages and perms.read_message_history):
                            continue
                    except Exception:
                        pass

                    scanned_channels += 1

                    try:
                        async for msg in ch.history(limit=limit_per_channel, oldest_first=False):  # type: ignore[attr-defined]
                            total_scanned_msgs += 1

                            if total_scanned_msgs % 1000 == 0:
                                logger.debug(f"Scanned {total_scanned_msgs} messages so far...")

                            msg_dt: datetime = msg.created_at
                            if msg_dt.tzinfo is None:
                                msg_dt = msg_dt.replace(tzinfo=timezone.utc)
                            else:
                                msg_dt = msg_dt.astimezone(timezone.utc)

                            if before_dt and msg_dt > before_dt:
                                continue

                            if after_dt and msg_dt < after_dt:
                                # We are scanning newest->oldest; once older than after_dt, stop for this channel.
                                break

                            if not msg.author or msg.author.id not in target_user_ids:
                                continue

                            # Matched user message ("response")
                            total_found += 1

                            # Resolve OP (reply target or preceding message)
                            op_msg = await _get_op_message(ch, msg)

                            rows: list[LogRow] = []

                            if op_msg is not None and op_msg.author is not None:
                                rows.append(
                                    LogRow(
                                        kind="op",
                                        message_id=op_msg.id,
                                        author_id=op_msg.author.id,
                                        dt_utc_iso=_dt_utc_iso(op_msg.created_at),
                                        contents=_norm_contents(op_msg.content),
                                    )
                                )
                                total_op_rows += 1

                            rows.append(
                                LogRow(
                                    kind="response",
                                    message_id=msg.id,
                                    author_id=msg.author.id,
                                    dt_utc_iso=_dt_utc_iso(msg.created_at),
                                    contents=_norm_contents(msg.content),
                                )
                            )

                            for r in rows:
                                writer.writerow([r.kind, r.message_id, r.author_id, r.dt_utc_iso, r.contents])

                    except disnake.Forbidden:
                        continue
                    except disnake.HTTPException:
                        continue
                    except Exception:
                        continue

        except Exception as e:
            await inter.edit_original_message(f"Failed to export CSV: {e}")
            try:
                if os.path.exists(out_path):
                    os.remove(out_path)
            except Exception:
                pass
            return

        await inter.followup.send(
            content=(
                f"CSV export complete.\n"
                f"Users: {', '.join(map(str, sorted(target_user_ids)))}\n"
                f"Time range (UTC): "
                f"{after_dt.isoformat() if after_dt else '—'} → {before_dt.isoformat() if before_dt else '—'}\n"
                f"Channels scanned: {scanned_channels}\n"
                f"Messages scanned: {total_scanned_msgs}\n"
                f"Responses written: {total_found}\n"
                f"OP rows written: {total_op_rows}"
            ),
            file=disnake.File(out_path),
            ephemeral=True,
        )

        try:
            os.remove(out_path)
        except Exception:
            pass
