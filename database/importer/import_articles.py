import json
import os
import re
import time
from pathlib import Path
from typing import Any

import mysql.connector
from mysql.connector import Error


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

METADATA_DIRECTORY = Path(
    os.getenv(
        "METADATA_DIRECTORY",
        "/data/metadata/api-pages",
    )
)

PDF_DIRECTORY = Path(
    os.getenv(
        "PDF_DIRECTORY",
        "/data/pdfs",
    )
)

IMPORT_START_PAGE = int(
    os.getenv("IMPORT_START_PAGE", "1")
)

# 0 verilirse tüm sayfalar aktarılır.
IMPORT_PAGE_LIMIT = int(
    os.getenv("IMPORT_PAGE_LIMIT", "2")
)


INSERT_SQL = """
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
VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s, %s
)
ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    doi = VALUES(doi),
    publication_year = VALUES(publication_year),
    journal_name = VALUES(journal_name),
    pdf_uuid = VALUES(pdf_uuid),
    pdf_path = VALUES(pdf_path),
    pdf_size_bytes = VALUES(pdf_size_bytes),
    source_page = VALUES(source_page),
    download_status = VALUES(download_status),
    trdizin_raw_json = VALUES(trdizin_raw_json)
"""


def connect_to_mysql(
    attempts: int = 30,
):
    print("MySQL bağlantısı bekleniyor...", flush=True)

    for attempt in range(1, attempts + 1):
        try:
            connection = mysql.connector.connect(
                host=MYSQL_HOST,
                port=MYSQL_PORT,
                database=MYSQL_DATABASE,
                user=MYSQL_USER,
                password=MYSQL_PASSWORD,
                charset="utf8mb4",
            )

            if connection.is_connected():
                print("MySQL bağlantısı kuruldu.", flush=True)
                return connection

        except Error as error:
            print(
                f"MySQL hazır değil: "
                f"{attempt}/{attempts} — {error}",
                flush=True,
            )

        time.sleep(2)

    raise RuntimeError(
        "MySQL bağlantısı kurulamadı."
    )


def get_page_number(path: Path) -> int:
    match = re.search(
        r"page_(\d+)\.json$",
        path.name,
    )

    if not match:
        return -1

    return int(match.group(1))


def get_page_files() -> list[Path]:
    page_files = sorted(
        METADATA_DIRECTORY.glob("page_*.json"),
        key=get_page_number,
    )

    page_files = [
        path
        for path in page_files
        if get_page_number(path) >= IMPORT_START_PAGE
    ]

    if IMPORT_PAGE_LIMIT > 0:
        page_files = page_files[:IMPORT_PAGE_LIMIT]

    return page_files


def clean_text(value: Any) -> str | None:
    if value is None:
        return None

    text = str(value).strip()

    return text or None


def clean_year(value: Any) -> int | None:
    try:
        year = int(value)
    except (TypeError, ValueError):
        return None

    if 1000 <= year <= 2100:
        return year

    return None


def prepare_row(
    record: dict[str, Any],
    source_page: int,
) -> tuple[Any, ...] | None:
    source = record.get("_source", {})

    if not isinstance(source, dict):
        return None

    publication_id_value = (
        source.get("id")
        or record.get("_id")
    )

    try:
        publication_id = int(
            publication_id_value
        )
    except (TypeError, ValueError):
        return None

    journal = source.get("journal") or {}

    if not isinstance(journal, dict):
        journal = {}

    pdf_uuid = clean_text(
        source.get("pdf")
    )

    pdf_file = (
        PDF_DIRECTORY
        / f"{publication_id}.pdf"
    )

    if pdf_file.exists():
        pdf_path = (
            f"/data/pdfs/{publication_id}.pdf"
        )
        pdf_size_bytes = pdf_file.stat().st_size
        download_status = "downloaded"
    else:
        pdf_path = None
        pdf_size_bytes = None
        download_status = "missing"

    raw_json = json.dumps(
        record,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return (
        publication_id,
        clean_text(source.get("orderTitle")),
        clean_text(source.get("doi")),
        clean_year(source.get("publicationYear")),
        clean_text(journal.get("name")),
        pdf_uuid,
        pdf_path,
        pdf_size_bytes,
        source_page,
        download_status,
        raw_json,
    )


def main() -> None:
    page_files = get_page_files()

    print(
        f"Bulunan JSON sayfası: "
        f"{len(page_files)}",
        flush=True,
    )

    if not page_files:
        raise RuntimeError(
            "Aktarılacak JSON sayfası bulunamadı."
        )

    connection = connect_to_mysql()
    cursor = connection.cursor()

    total_inserted = 0
    total_skipped = 0

    try:
        for index, page_path in enumerate(
            page_files,
            start=1,
        ):
            page_data = json.loads(
                page_path.read_text(
                    encoding="utf-8"
                )
            )

            source_page = int(
                page_data.get(
                    "page",
                    get_page_number(page_path),
                )
            )

            records = page_data.get(
                "records",
                [],
            )

            if not isinstance(records, list):
                print(
                    f"Atlandı: {page_path.name} "
                    "kayıt listesi içermiyor.",
                    flush=True,
                )
                continue

            rows: list[tuple[Any, ...]] = []

            for record in records:
                if not isinstance(record, dict):
                    total_skipped += 1
                    continue

                row = prepare_row(
                    record,
                    source_page,
                )

                if row is None:
                    total_skipped += 1
                    continue

                rows.append(row)

            if rows:
                cursor.executemany(
                    INSERT_SQL,
                    rows,
                )
                connection.commit()

                total_inserted += len(rows)

            print(
                f"[{index}/{len(page_files)}] "
                f"{page_path.name} → "
                f"{len(rows)} kayıt aktarıldı.",
                flush=True,
            )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    print()
    print("=" * 50)
    print("TR Dizin JSON aktarımı tamamlandı.")
    print(f"Aktarılan/güncellenen: {total_inserted}")
    print(f"Atlanan geçersiz kayıt: {total_skipped}")
    print("=" * 50)


if __name__ == "__main__":
    main()
