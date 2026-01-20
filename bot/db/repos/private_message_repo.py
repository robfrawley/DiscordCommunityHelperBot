from datetime import datetime

from bot.db.database import Database, database
from bot.models.private_message_record import PrivateMessageRecord
from bot.utils.settings import settings


class PrivateMessageRepo:
    def __init__(self, database: Database):
        self.database = database

    async def init_schema(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS private_message (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                to_user_id INTEGER NOT NULL,
                from_user_id INTEGER NOT NULL,
                message TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            """.strip(),
            auto_commit=False,
        )
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pm_to_created
            ON private_message (to_user_id, created_at DESC);
            """.strip(),
            auto_commit=False,
        )
        await self.database.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pm_from_created
            ON private_message (from_user_id, created_at DESC);
            """.strip(),
            auto_commit=False,
        )
        await self.database.commit()

    async def add(self, record: PrivateMessageRecord) -> None:
        await self.database.execute(
            """
            INSERT INTO private_message (to_user_id, from_user_id, message, created_at)
            VALUES (?, ?, ?, ?);
            """.strip(),
            (
                record.to_user_id,
                record.from_user_id,
                record.message,
                int(record.created_at.timestamp()),
            ),
            auto_commit=True,
        )

    async def get_for_user_to(
        self,
        to_user_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> list[PrivateMessageRecord]:
        cursor = await self.database.execute(
            """
            SELECT id, to_user_id, from_user_id, message, created_at
            FROM private_message
            WHERE to_user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?;
            """.strip(),
            (int(to_user_id), int(limit), int(offset)),
        )
        rows = await cursor.fetchall()
        return [
            PrivateMessageRecord(
                id=row[0],
                to_user_id=row[1],
                from_user_id=row[2],
                message=row[3],
                created_at=datetime.fromtimestamp(row[4], tz=settings.bot_time_zone),
            )
            for row in rows
        ]

    async def get_for_user_from(
        self,
        from_user_id: int,
        *,
        limit: int = 25,
        offset: int = 0,
    ) -> list[PrivateMessageRecord]:
        cursor = await self.database.execute(
            """
            SELECT id, to_user_id, from_user_id, message, created_at
            FROM private_message
            WHERE from_user_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT ? OFFSET ?;
            """.strip(),
            (int(from_user_id), int(limit), int(offset)),
        )
        rows = await cursor.fetchall()
        return [
            PrivateMessageRecord(
                id=row[0],
                to_user_id=row[1],
                from_user_id=row[2],
                message=row[3],
                created_at=datetime.fromtimestamp(row[4], tz=settings.bot_time_zone),
            )
            for row in rows
        ]

    async def get_latest(
        self,
        *,
        to_user_id: int | None = None,
        from_user_id: int | None = None,
        limit: int = 25,
        offset: int = 0,
    ) -> list[PrivateMessageRecord]:
        where_clauses: list[str] = []
        params: list[int] = []

        if to_user_id is not None:
            where_clauses.append("to_user_id = ?")
            params.append(int(to_user_id))

        if from_user_id is not None:
            where_clauses.append("from_user_id = ?")
            params.append(int(from_user_id))

        where_sql = ""
        if where_clauses:
            where_sql = "WHERE " + " AND ".join(where_clauses)

        sql: str = (
            f"""
                SELECT id, to_user_id, from_user_id, message, created_at
                FROM private_message
                {where_sql}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?;
            """.strip()
        )

        cursor = await self.database.execute(
            sql,
            (*params, int(limit), int(offset)),
        )
        rows = await cursor.fetchall()
        return [
            PrivateMessageRecord(
                id=row[0],
                to_user_id=row[1],
                from_user_id=row[2],
                message=row[3],
                created_at=datetime.fromtimestamp(row[4], tz=settings.bot_time_zone),
            )
            for row in rows
        ]


private_message_repo = PrivateMessageRepo(database=database)
