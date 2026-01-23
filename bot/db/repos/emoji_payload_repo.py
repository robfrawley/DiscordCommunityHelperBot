from __future__ import annotations

from datetime import datetime, timedelta

from bot.db.database import Database, database
from bot.utils.settings import settings
from bot.models.emoji_payload import EmojiPayload


class EmojiPayloadRepo:
    def __init__(self, database: Database):
        self.database = database

    async def init_schema(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS emoji_payload (
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
            CREATE INDEX IF NOT EXISTS idx_emoji_payload_lookup
            ON emoji_payload (message_id, guild_id, channel_id, user_id, emoji, timestamp DESC);
            """.strip(),
            auto_commit=False,
        )

        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_emoji_payload_timestamp
            ON emoji_payload (timestamp);
            """.strip(),
            auto_commit=False,
        )

        # Optional but recommended for time-window queries by user
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_emoji_payload_user_ts
            ON emoji_payload (user_id, timestamp DESC);
            """.strip(),
            auto_commit=False,
        )

        await self.database.commit()

    async def add(self, payload: EmojiPayload) -> None:
        await self.database.execute(
            """
            INSERT INTO emoji_payload (message_id, guild_id, channel_id, user_id, emoji, timestamp)
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

    async def get_and_delete(self, payload: EmojiPayload) -> EmojiPayload | None:
        result = await self.get(payload)

        if result:
            await self.delete(payload)

        return result

    async def get(self, payload: EmojiPayload) -> EmojiPayload | None:
        cursor = await self.database.execute(
            """
            SELECT message_id, guild_id, channel_id, user_id, emoji, timestamp
            FROM emoji_payload
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
            DELETE FROM emoji_payload
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

    async def prune(self, *, older_than_seconds: int) -> int:
        cutoff_ts: int = int(
            (datetime.now(settings.bot_time_zone) - timedelta(seconds=int(older_than_seconds))).timestamp()
        )

        cursor = await self.database.execute(
            """
            DELETE FROM emoji_payload
            WHERE timestamp < ?;
            """.strip(),
            (cutoff_ts,),
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)


emoji_payload_repo = EmojiPayloadRepo(database=database)
