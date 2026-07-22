import hashlib
import os
from pathlib import Path

import mysql.connector


MIGRATIONS = Path(__file__).parent / "migrations"


def connection():
    return mysql.connector.connect(
        host=os.environ["MYSQL_HOST"],
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.environ["MYSQL_DATABASE"],
        user=os.environ["MYSQL_USER"],
        password=os.environ["MYSQL_PASSWORD"],
    )


def statements(sql: str):
    for value in sql.split(";"):
        value = value.strip()
        if value:
            yield value


def run() -> None:
    db = connection()
    cursor = db.cursor()
    try:
        cursor.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
            version VARCHAR(32) PRIMARY KEY, name VARCHAR(255) NOT NULL,
            checksum CHAR(64) NOT NULL,
            applied_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6))"""
        )
        db.commit()
        for path in sorted(MIGRATIONS.glob("*.sql")):
            version, name = path.stem.split("_", 1)
            sql = path.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            cursor.execute(
                "SELECT checksum FROM schema_migrations WHERE version = %s", (version,)
            )
            existing = cursor.fetchone()
            if existing:
                if existing[0] != checksum:
                    raise RuntimeError(f"Migration checksum değişmiş: {path.name}")
                continue
            try:
                for statement in statements(sql):
                    cursor.execute(statement)
                cursor.execute(
                    "INSERT INTO schema_migrations(version, name, checksum) VALUES (%s, %s, %s)",
                    (version, name, checksum),
                )
                db.commit()
            except Exception:
                db.rollback()
                raise
    finally:
        cursor.close()
        db.close()


if __name__ == "__main__":
    run()
