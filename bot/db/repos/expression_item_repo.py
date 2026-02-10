# bot/db/repos/expression_item_repo.py
from __future__ import annotations

from bot.db.database import Database, database
from bot.models.expression_item import ExpressionItem, ExpressionItemType


class ExpressionItemRepo:
    def __init__(self, database: Database):
        self.database = database

    async def init_schema(self) -> None:
        await self.database.execute(
            """
            CREATE TABLE IF NOT EXISTS expression_item (
                id INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL,
                uploader_id INTEGER,
                message_id INTEGER,
                created_at INTEGER NOT NULL,
                link TEXT
            );
            """.strip(),
            auto_commit=True,
        )

    async def add(self, item: ExpressionItem) -> None:
        await self.database.execute(
            """
            INSERT INTO expression_item (id, name, type, uploader_id, message_id, created_at, link)
            VALUES (?, ?, ?, ?, ?, ?, ?);
            """.strip(),
            (
                item.id,
                item.name,
                item.type.value,
                item.uploader_id,
                item.message_id,
                item.created_at,
                item.link,
            ),
            auto_commit=True,
        )

    async def update(self, item: ExpressionItem) -> int:
        cursor = await self.database.execute(
            """
            UPDATE expression_item
            SET name = ?,
                type = ?,
                uploader_id = ?,
                message_id = ?,
                created_at = ?,
                link = ?
            WHERE id = ?;
            """.strip(),
            (
                item.name,
                item.type.value,
                item.uploader_id,
                item.message_id,
                item.created_at,
                item.link,
                item.id,
            ),
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)

    async def delete(self, item: ExpressionItem) -> int:
        cursor = await self.database.execute(
            """
            DELETE FROM expression_item
            WHERE id = ?;
            """.strip(),
            (item.id,),
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)

    async def get_all(self) -> list[ExpressionItem]:
        cursor = await self.database.execute(
            """
            SELECT id, name, type, uploader_id, message_id, created_at, link
            FROM expression_item
            ORDER BY created_at DESC, id DESC;
            """.strip()
        )

        rows = await cursor.fetchall()

        return [
            ExpressionItem(
                id=int(row[0]),
                name=row[1],
                type=ExpressionItemType(row[2]),
                uploader_id=int(row[3]) if row[3] else None,
                message_id=int(row[4]) if row[4] else None,
                created_at=int(row[5]),
                link=row[6],
            )
            for row in rows
        ]

    async def del_all(self) -> int:
        cursor = await self.database.execute(
            "DELETE FROM expression_item;",
            auto_commit=True,
        )

        return int(getattr(cursor, "rowcount", 0) or 0)



expression_item_repo = ExpressionItemRepo(database=database)
