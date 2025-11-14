import asyncio
import sqlite3
from typing import Any, Iterable, Optional

Row = sqlite3.Row
IntegrityError = sqlite3.IntegrityError


class Cursor:
    def __init__(self, cursor: sqlite3.Cursor):
        self._cursor = cursor

    async def fetchone(self) -> Optional[sqlite3.Row]:
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self) -> list[sqlite3.Row]:
        return await asyncio.to_thread(self._cursor.fetchall)


class Connection:
    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    async def execute(self, sql: str, parameters: Iterable[Any] | None = None) -> Cursor:
        if parameters is None:
            parameters = ()
        cursor = await asyncio.to_thread(self._conn.execute, sql, tuple(parameters))
        return Cursor(cursor)

    async def executescript(self, script: str) -> None:
        await asyncio.to_thread(self._conn.executescript, script)

    async def commit(self) -> None:
        await asyncio.to_thread(self._conn.commit)

    async def close(self) -> None:
        await asyncio.to_thread(self._conn.close)

    @property
    def row_factory(self) -> Any:
        return self._conn.row_factory

    @row_factory.setter
    def row_factory(self, factory: Any) -> None:
        self._conn.row_factory = factory


async def connect(path: str, **kwargs: Any) -> Connection:
    kwargs.setdefault("check_same_thread", False)
    conn = await asyncio.to_thread(sqlite3.connect, path, **kwargs)
    return Connection(conn)
