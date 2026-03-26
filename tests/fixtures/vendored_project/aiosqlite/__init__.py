"""Vendored copy of aiosqlite — in-tree for deployment simplicity."""
import sqlite3
import asyncio


async def connect(database: str):
    return Connection(database)


class Connection:
    def __init__(self, database: str) -> None:
        self._database = database
        self._conn = None

    async def __aenter__(self):
        self._conn = sqlite3.connect(self._database)
        return self

    async def __aexit__(self, *args):
        if self._conn:
            self._conn.close()

    async def execute(self, sql: str, params=None):
        cursor = self._conn.cursor()
        cursor.execute(sql, params or ())
        return cursor

    async def commit(self):
        self._conn.commit()
