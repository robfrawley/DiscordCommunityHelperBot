from __future__ import annotations

from datetime import datetime, timedelta

from bot.db.database import Database, database
from bot.utils.settings import settings
from bot.models.emoji_payload import EmojiPayload


class EmojiAbuserRepo:
    def __init__(self, database: Database):
        self.database = database

    async def init_schema(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS emoji_abuser (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER NOT NULL,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                emoji TEXT,
                timestamp INTEGER NOT NULL
            );
            """.strip(),
            auto_commit=False,
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_emoji_abuser_lookup
            ON emoji_abuser (message_id, guild_id, channel_id, user_id, emoji, timestamp DESC);
            """.strip(),
            auto_commit=False,
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_emoji_abuser_timestamp
            ON emoji_abuser (timestamp);
            """.strip(),
            auto_commit=False,
        )

        # Optional but recommended for time-window queries by user
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_emoji_abuser_user_ts
            ON emoji_abuser (user_id, timestamp DESC);
            """.strip(),
            auto_commit=False,
        )

        await self.database.commit()

    async def add(self, payload: EmojiPayload) -> None:
        await self.database.execute(
            """
            INSERT INTO emoji_abuser (message_id, guild_id, channel_id, user_id, emoji, timestamp)
            VALUES (?, ?, ?, ?, ?, ?);
            """.strip(),
            (
                int(payload.message_id),
                int(payload.guild_id),
                int(payload.channel_id),
                int(payload.user_id),
                payload.emoji,
                int(payload.timestamp.timestamp()),
            ),
            auto_commit=True,
        )

    async def get_abusers_within(
        self,
        *,
        within_seconds: int,
        max_count: int,
    ) -> list[EmojiPayload]:
        cutoff_ts: int = int(
            (datetime.now(settings.bot_time_zone) - timedelta(seconds=int(within_seconds))).timestamp()
        )

        cursor1 = await self.database.execute(
            """
            SELECT user_id
            FROM emoji_abuser
            WHERE timestamp >= ?
            GROUP BY user_id
            HAVING COUNT(*) > ?;
            """.strip(),
            (cutoff_ts, int(max_count)),
        )

        offenders_rows = await cursor1.fetchall()
        offender_ids = [int(r[0]) for r in offenders_rows]

        if not offender_ids:
            return []

        placeholders = ", ".join(["?"] * len(offender_ids))
        params: tuple[int, ...] = (cutoff_ts, *offender_ids)

        cursor2 = await self.database.execute(
            f"""
            SELECT message_id, guild_id, channel_id, user_id, emoji, timestamp
            FROM emoji_abuser
            WHERE timestamp >= ?
              AND user_id IN ({placeholders})
            ORDER BY user_id ASC, timestamp DESC, id DESC;
            """.strip(),
            params,
        )

        rows = await cursor2.fetchall()

        return [
            EmojiPayload(
                message_id=int(row[0]),
                guild_id=int(row[1]),
                channel_id=int(row[2]),
                user_id=int(row[3]),
                emoji=row[4],
                timestamp=datetime.fromtimestamp(int(row[5]), tz=settings.bot_time_zone),
            )
            for row in rows
        ]

    async def get_recent_for_user(
        self,
        *,
        user_id: int,
        within_seconds: int,
    ) -> list[EmojiPayload]:
        cutoff_ts: int = int(
            (datetime.now(settings.bot_time_zone) - timedelta(seconds=int(within_seconds))).timestamp()
        )

        cursor = await self.database.execute(
            """
            SELECT message_id, guild_id, channel_id, user_id, emoji, timestamp
            FROM emoji_abuser
            WHERE user_id = ?
              AND timestamp >= ?
            ORDER BY timestamp DESC, id DESC;
            """.strip(),
            (
                int(user_id),
                cutoff_ts,
            ),
        )

        rows = await cursor.fetchall()

        return [
            EmojiPayload(
                message_id=int(row[0]),
                guild_id=int(row[1]),
                channel_id=int(row[2]),
                user_id=int(row[3]),
                emoji=row[4],
                timestamp=datetime.fromtimestamp(int(row[5]), tz=settings.bot_time_zone),
            )
            for row in rows
        ]

    async def get(self, payload: EmojiPayload) -> EmojiPayload | None:
        cursor = await self.database.execute(
            """
            SELECT message_id, guild_id, channel_id, user_id, emoji, timestamp
            FROM emoji_abuser
            WHERE message_id = ? AND guild_id = ? AND channel_id = ? AND user_id = ?
              AND (
                (emoji IS NULL AND ? IS NULL)
                OR (emoji = ?)
              )
            ORDER BY timestamp DESC, id DESC
            LIMIT 1;
            """.strip(),
            (
                int(payload.message_id),
                int(payload.guild_id),
                int(payload.channel_id),
                int(payload.user_id),
                payload.emoji,
                payload.emoji,
            ),
        )

        row = await cursor.fetchone()

        return (
            EmojiPayload(
                message_id=int(row[0]),
                guild_id=int(row[1]),
                channel_id=int(row[2]),
                user_id=int(row[3]),
                emoji=row[4],
                timestamp=datetime.fromtimestamp(int(row[5]), tz=settings.bot_time_zone),
            )
            if row
            else None
        )

    async def delete(self, payload: EmojiPayload) -> int:
        cursor = await self.database.execute(
            """
            DELETE FROM emoji_abuser
            WHERE message_id = ? AND guild_id = ? AND channel_id = ? AND user_id = ?
              AND (
                (emoji IS NULL AND ? IS NULL)
                OR (emoji = ?)
              );
            """.strip(),
            (
                int(payload.message_id),
                int(payload.guild_id),
                int(payload.channel_id),
                int(payload.user_id),
                payload.emoji,
                payload.emoji,
            ),
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)

    async def delete_user_records(self, *, user_id: int) -> int:
        cursor = await self.database.execute(
            """
            DELETE FROM emoji_abuser
            WHERE user_id = ?;
            """.strip(),
            (int(user_id),),
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)

    async def prune(self, *, older_than_seconds: int) -> int:
        cutoff_ts: int = int(
            (datetime.now(settings.bot_time_zone) - timedelta(seconds=int(older_than_seconds))).timestamp()
        )

        cursor = await self.database.execute(
            """
            DELETE FROM emoji_abuser
            WHERE timestamp < ?;
            """.strip(),
            (cutoff_ts,),
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)


emoji_abuser_repo = EmojiAbuserRepo(database=database)
