from datetime import datetime

from bot.db.database import Database, database
from bot.models.configuration_record import ConfigurationRecord
from bot.utils.settings import settings


class ConfigurationRepo:
    def __init__(self, database: Database):
        self.database = database

    async def init_schema(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS configuration (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );
            """.strip(),
            auto_commit=False,
        )
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_configuration_updated_at
            ON configuration (updated_at DESC);
            """.strip(),
            auto_commit=False,
        )
        await self.database.commit()

    async def set(self, record: ConfigurationRecord) -> None:
        await self.database.execute(
            """
            INSERT INTO configuration (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at;
            """.strip(),
            (
                record.key,
                record.value,
                int(record.updated_at.timestamp()),
            ),
            auto_commit=True,
        )

    async def get(self, key: str) -> ConfigurationRecord | None:
        cursor = await self.database.execute(
            """
            SELECT key, value, updated_at
            FROM configuration
            WHERE key = ?;
            """.strip(),
            (str(key),),
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return ConfigurationRecord(
            key=row[0],
            value=row[1],
            updated_at=datetime.fromtimestamp(row[2], tz=settings.bot_time_zone),
        )

    async def delete(self, key: str) -> None:
        await self.database.execute(
            "DELETE FROM configuration WHERE key = ?;",
            (str(key),),
            auto_commit=True,
        )

    async def list(self, *, limit: int = 100, offset: int = 0) -> list[ConfigurationRecord]:
        cursor = await self.database.execute(
            """
            SELECT key, value, updated_at
            FROM configuration
            ORDER BY updated_at DESC, key ASC
            LIMIT ? OFFSET ?;
            """.strip(),
            (int(limit), int(offset)),
        )
        rows = await cursor.fetchall()
        return [
            ConfigurationRecord(
                key=row[0],
                value=row[1],
                updated_at=datetime.fromtimestamp(row[2], tz=settings.bot_time_zone),
            )
            for row in rows
        ]


configuration_repo = ConfigurationRepo(database=database)
