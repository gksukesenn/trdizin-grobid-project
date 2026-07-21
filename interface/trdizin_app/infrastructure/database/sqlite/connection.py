import sqlite3
from pathlib import Path
from typing import Any, Iterable

from trdizin_app.application.exceptions import (
    DatabaseUnavailableError,
)
from trdizin_app.infrastructure.config.settings import (
    Settings,
)


def convert_placeholders(query: str) -> str:
    """
    Mevcut MySQL sorgularındaki %s parametrelerini
    SQLite'ın kullandığı ? parametrelerine dönüştürür.
    """
    return query.replace("%s", "?")


class SQLiteCursorAdapter:
    def __init__(
        self,
        cursor: sqlite3.Cursor,
        dictionary: bool = False,
    ) -> None:
        self._cursor = cursor
        self._dictionary = dictionary

    def execute(
        self,
        query: str,
        parameters: Iterable[Any] | None = None,
    ) -> "SQLiteCursorAdapter":
        converted_query = convert_placeholders(query)

        if parameters is None:
            self._cursor.execute(converted_query)
        else:
            self._cursor.execute(
                converted_query,
                tuple(parameters),
            )

        return self

    def executemany(
        self,
        query: str,
        parameter_rows: Iterable[Iterable[Any]],
    ) -> "SQLiteCursorAdapter":
        self._cursor.executemany(
            convert_placeholders(query),
            [
                tuple(row)
                for row in parameter_rows
            ],
        )

        return self

    def _convert_row(
        self,
        row: sqlite3.Row | tuple[Any, ...] | None,
    ) -> dict[str, Any] | tuple[Any, ...] | None:
        if row is None:
            return None

        if self._dictionary:
            return dict(row)

        return tuple(row)

    def fetchone(
        self,
    ) -> dict[str, Any] | tuple[Any, ...] | None:
        return self._convert_row(
            self._cursor.fetchone()
        )

    def fetchall(
        self,
    ) -> list[dict[str, Any] | tuple[Any, ...]]:
        return [
            self._convert_row(row)
            for row in self._cursor.fetchall()
        ]

    def fetchmany(
        self,
        size: int | None = None,
    ) -> list[dict[str, Any] | tuple[Any, ...]]:
        rows = (
            self._cursor.fetchmany(size)
            if size is not None
            else self._cursor.fetchmany()
        )

        return [
            self._convert_row(row)
            for row in rows
        ]

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    @property
    def lastrowid(self) -> int | None:
        return self._cursor.lastrowid

    @property
    def description(self):
        return self._cursor.description

    def close(self) -> None:
        self._cursor.close()


class SQLiteConnectionAdapter:
    def __init__(
        self,
        connection: sqlite3.Connection,
    ) -> None:
        self._connection = connection

    def cursor(
        self,
        dictionary: bool = False,
        **_kwargs: Any,
    ) -> SQLiteCursorAdapter:
        return SQLiteCursorAdapter(
            self._connection.cursor(),
            dictionary=dictionary,
        )

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()

    def is_connected(self) -> bool:
        return True


def create_sqlite_connection(
    settings: Settings,
) -> SQLiteConnectionAdapter:
    sqlite_path: Path = settings.sqlite_path

    if not sqlite_path.exists():
        raise DatabaseUnavailableError(
            "SQLite veritabanı bulunamadı: "
            f"{sqlite_path}"
        )

    try:
        connection = sqlite3.connect(
            f"file:{sqlite_path}?mode=ro",
            uri=True,
            timeout=30,
            check_same_thread=False,
        )

        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA foreign_keys = ON")

        return SQLiteConnectionAdapter(connection)

    except sqlite3.Error as error:
        raise DatabaseUnavailableError(
            "SQLite bağlantısı kurulamadı: "
            f"{error}"
        ) from error
