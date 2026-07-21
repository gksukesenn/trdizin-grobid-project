import json
import os
import sqlite3
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import mysql.connector


MYSQL_HOST = os.getenv("MYSQL_HOST", "mysql")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_DATABASE = os.getenv(
    "MYSQL_DATABASE",
    "trdizin_grobid",
)
MYSQL_USER = os.getenv(
    "MYSQL_USER",
    "trdizin_app",
)
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")

SQLITE_OUTPUT_PATH = Path(
    os.getenv(
        "SQLITE_OUTPUT_PATH",
        (
            "/workspace/deploy/huggingface/"
            "data/trdizin-demo.sqlite"
        ),
    )
)

EXPORT_BATCH_SIZE = int(
    os.getenv("EXPORT_BATCH_SIZE", "1000")
)


SQLITE_SCHEMA = """
CREATE TABLE articles (
    publication_id INTEGER PRIMARY KEY,
    title TEXT,
    doi TEXT,
    publication_year INTEGER,
    journal_name TEXT,
    pdf_uuid TEXT,
    pdf_path TEXT,
    pdf_size_bytes INTEGER,
    source_page INTEGER,
    download_status TEXT,
    trdizin_raw_json TEXT
);

CREATE TABLE trdizin_references (
    publication_id INTEGER NOT NULL,
    reference_index INTEGER NOT NULL,
    raw_reference TEXT,
    title TEXT,
    authors_json TEXT,
    publication_year TEXT,
    journal_name TEXT,
    doi TEXT,
    trdizin_raw_json TEXT,
    PRIMARY KEY (
        publication_id,
        reference_index
    )
);

CREATE TABLE grobid_documents (
    publication_id INTEGER PRIMARY KEY,
    tei_xml TEXT,
    reference_count INTEGER NOT NULL DEFAULT 0,
    processing_status TEXT NOT NULL,
    processing_message TEXT
);

CREATE TABLE grobid_references (
    publication_id INTEGER NOT NULL,
    reference_index INTEGER NOT NULL,
    xml_id TEXT,
    raw_reference TEXT,
    title TEXT,
    authors_json TEXT,
    publication_year TEXT,
    journal_name TEXT,
    doi TEXT,
    PRIMARY KEY (
        publication_id,
        reference_index
    )
);

CREATE TABLE comparison_results (
    publication_id INTEGER NOT NULL,
    trdizin_reference_index INTEGER,
    grobid_reference_index INTEGER,
    field_name TEXT NOT NULL,
    similarity_score REAL,
    comparison_status TEXT NOT NULL
);

CREATE TABLE reference_matching_progress (
    publication_id INTEGER PRIMARY KEY,
    matching_status TEXT NOT NULL,
    doi_match_count INTEGER NOT NULL DEFAULT 0,
    text_match_count INTEGER NOT NULL DEFAULT 0,
    clean_match_count INTEGER NOT NULL DEFAULT 0,
    merged_count INTEGER NOT NULL DEFAULT 0,
    partial_count INTEGER NOT NULL DEFAULT 0,
    unmatched_trdizin_count INTEGER NOT NULL DEFAULT 0,
    unmatched_grobid_count INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    started_at TEXT,
    completed_at TEXT
);
"""


TABLE_EXPORTS = [
    {
        "name": "articles",
        "select": """
            SELECT
                publication_id,
                title,
                doi,
                publication_year,
                journal_name,
                pdf_uuid,
                pdf_path,
                pdf_size_bytes,
                source_page,
                download_status,
                trdizin_raw_json
            FROM articles
            ORDER BY publication_id
        """,
        "insert": """
            INSERT INTO articles (
                publication_id,
                title,
                doi,
                publication_year,
                journal_name,
                pdf_uuid,
                pdf_path,
                pdf_size_bytes,
                source_page,
                download_status,
                trdizin_raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
    },
    {
        "name": "trdizin_references",
        "select": """
            SELECT
                publication_id,
                reference_index,
                raw_reference,
                title,
                authors_json,
                publication_year,
                journal_name,
                doi,
                trdizin_raw_json
            FROM trdizin_references
            ORDER BY publication_id, reference_index
        """,
        "insert": """
            INSERT INTO trdizin_references (
                publication_id,
                reference_index,
                raw_reference,
                title,
                authors_json,
                publication_year,
                journal_name,
                doi,
                trdizin_raw_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
    },
    {
        "name": "grobid_documents",
        "select": """
            SELECT
                publication_id,
                tei_xml,
                reference_count,
                processing_status,
                processing_message
            FROM grobid_documents
            ORDER BY publication_id
        """,
        "insert": """
            INSERT INTO grobid_documents (
                publication_id,
                tei_xml,
                reference_count,
                processing_status,
                processing_message
            )
            VALUES (?, ?, ?, ?, ?)
        """,
    },
    {
        "name": "grobid_references",
        "select": """
            SELECT
                publication_id,
                reference_index,
                xml_id,
                raw_reference,
                title,
                authors_json,
                publication_year,
                journal_name,
                doi
            FROM grobid_references
            ORDER BY publication_id, reference_index
        """,
        "insert": """
            INSERT INTO grobid_references (
                publication_id,
                reference_index,
                xml_id,
                raw_reference,
                title,
                authors_json,
                publication_year,
                journal_name,
                doi
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
    },
    {
        "name": "comparison_results",
        "select": """
            SELECT
                publication_id,
                trdizin_reference_index,
                grobid_reference_index,
                field_name,
                similarity_score,
                comparison_status
            FROM comparison_results
            ORDER BY publication_id
        """,
        "insert": """
            INSERT INTO comparison_results (
                publication_id,
                trdizin_reference_index,
                grobid_reference_index,
                field_name,
                similarity_score,
                comparison_status
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """,
    },
    {
        "name": "reference_matching_progress",
        "select": """
            SELECT
                publication_id,
                matching_status,
                doi_match_count,
                text_match_count,
                clean_match_count,
                merged_count,
                partial_count,
                unmatched_trdizin_count,
                unmatched_grobid_count,
                error_message,
                started_at,
                completed_at
            FROM reference_matching_progress
            ORDER BY publication_id
        """,
        "insert": """
            INSERT INTO reference_matching_progress (
                publication_id,
                matching_status,
                doi_match_count,
                text_match_count,
                clean_match_count,
                merged_count,
                partial_count,
                unmatched_trdizin_count,
                unmatched_grobid_count,
                error_message,
                started_at,
                completed_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
    },
]


SQLITE_INDEXES = """
CREATE INDEX idx_articles_doi
    ON articles (doi);

CREATE INDEX idx_articles_pdf_uuid
    ON articles (pdf_uuid);

CREATE INDEX idx_articles_download_status
    ON articles (download_status);

CREATE INDEX idx_trdizin_publication
    ON trdizin_references (
        publication_id,
        reference_index
    );

CREATE INDEX idx_grobid_status
    ON grobid_documents (
        processing_status
    );

CREATE INDEX idx_grobid_publication
    ON grobid_references (
        publication_id,
        reference_index
    );

CREATE INDEX idx_comparison_publication
    ON comparison_results (
        publication_id
    );

CREATE INDEX idx_comparison_status
    ON comparison_results (
        comparison_status
    );

CREATE INDEX idx_matching_status
    ON reference_matching_progress (
        matching_status
    );
"""


def normalize_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(value, Decimal):
        return float(value)

    if isinstance(value, (datetime, date, time)):
        return value.isoformat()

    if isinstance(value, (dict, list)):
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )

    if isinstance(value, bytes):
        return value.decode(
            "utf-8",
            errors="replace",
        )

    if isinstance(value, bool):
        return int(value)

    return value


def connect_mysql():
    print(
        f"MySQL bağlantısı kuruluyor: "
        f"{MYSQL_HOST}:{MYSQL_PORT}/"
        f"{MYSQL_DATABASE}",
        flush=True,
    )

    connection = mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
        connection_timeout=30,
    )

    print("MySQL bağlantısı kuruldu.", flush=True)
    return connection


def prepare_sqlite() -> sqlite3.Connection:
    SQLITE_OUTPUT_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if SQLITE_OUTPUT_PATH.exists():
        print(
            "Eski SQLite dosyası siliniyor: "
            f"{SQLITE_OUTPUT_PATH}",
            flush=True,
        )
        SQLITE_OUTPUT_PATH.unlink()

    connection = sqlite3.connect(
        SQLITE_OUTPUT_PATH
    )

    connection.execute(
        "PRAGMA journal_mode = OFF"
    )
    connection.execute(
        "PRAGMA synchronous = OFF"
    )
    connection.execute(
        "PRAGMA temp_store = MEMORY"
    )
    connection.execute(
        "PRAGMA foreign_keys = OFF"
    )
    connection.execute(
        "PRAGMA cache_size = -200000"
    )

    connection.executescript(SQLITE_SCHEMA)
    connection.commit()

    return connection


def get_table_count(
    mysql_connection,
    table_name: str,
) -> int:
    cursor = mysql_connection.cursor()

    try:
        cursor.execute(
            f"SELECT COUNT(*) FROM {table_name}"
        )
        row = cursor.fetchone()
        return int(row[0])
    finally:
        cursor.close()


def export_table(
    mysql_connection,
    sqlite_connection,
    table_export: dict[str, str],
) -> None:
    table_name = table_export["name"]

    total_count = get_table_count(
        mysql_connection,
        table_name,
    )

    print()
    print("=" * 70)
    print(
        f"Tablo aktarılıyor: {table_name}"
    )
    print(f"Toplam kayıt: {total_count}")
    print("=" * 70)

    cursor = mysql_connection.cursor()
    exported_count = 0

    try:
        cursor.execute(table_export["select"])
        sqlite_connection.execute("BEGIN")

        while True:
            rows = cursor.fetchmany(
                EXPORT_BATCH_SIZE
            )

            if not rows:
                break

            normalized_rows = [
                tuple(
                    normalize_value(value)
                    for value in row
                )
                for row in rows
            ]

            sqlite_connection.executemany(
                table_export["insert"],
                normalized_rows,
            )

            exported_count += len(rows)

            print(
                f"{table_name}: "
                f"{exported_count}/{total_count}",
                flush=True,
            )

        sqlite_connection.commit()

    except Exception:
        sqlite_connection.rollback()
        raise

    finally:
        cursor.close()

    if exported_count != total_count:
        raise RuntimeError(
            f"{table_name}: kayıt sayısı uyuşmuyor. "
            f"MySQL={total_count}, "
            f"SQLite={exported_count}"
        )


def main() -> None:
    mysql_connection = connect_mysql()
    sqlite_connection = prepare_sqlite()

    try:
        for table_export in TABLE_EXPORTS:
            export_table(
                mysql_connection,
                sqlite_connection,
                table_export,
            )

        print()
        print("SQLite indeksleri oluşturuluyor...")
        sqlite_connection.executescript(
            SQLITE_INDEXES
        )

        sqlite_connection.execute("ANALYZE")
        sqlite_connection.execute(
            "PRAGMA user_version = 1"
        )
        sqlite_connection.commit()

        integrity_result = (
            sqlite_connection.execute(
                "PRAGMA integrity_check"
            ).fetchone()[0]
        )

        print(
            "SQLite bütünlük kontrolü: "
            f"{integrity_result}"
        )

        if integrity_result != "ok":
            raise RuntimeError(
                "SQLite bütünlük kontrolü "
                "başarısız oldu."
            )

    finally:
        sqlite_connection.close()
        mysql_connection.close()

    file_size_mb = (
        SQLITE_OUTPUT_PATH.stat().st_size
        / 1024
        / 1024
    )

    print()
    print("=" * 70)
    print("MySQL → SQLite aktarımı tamamlandı.")
    print(f"Dosya: {SQLITE_OUTPUT_PATH}")
    print(f"Boyut: {file_size_mb:.2f} MB")
    print("=" * 70)


if __name__ == "__main__":
    main()
