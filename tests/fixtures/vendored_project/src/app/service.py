"""Application service — calls into a vendored aiosqlite copy."""
from aiosqlite import connect


class DataService:
    def __init__(self, db_path: str) -> None:
        self._db_path = db_path

    async def fetch_records(self, table: str) -> list:
        async with connect(self._db_path) as db:
            cursor = await db.execute(f"SELECT * FROM {table}")
            return await cursor.fetchall()

    async def insert_record(self, table: str, data: dict) -> None:
        async with connect(self._db_path) as db:
            keys = ", ".join(data.keys())
            vals = tuple(data.values())
            await db.execute(f"INSERT INTO {table} ({keys}) VALUES {vals}")
            await db.commit()
