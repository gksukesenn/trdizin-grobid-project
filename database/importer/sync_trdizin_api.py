import json
import os
import time
from typing import Any

import mysql.connector
import requests
from mysql.connector import Error


API_URL = (
    "https://search.trdizin.gov.tr/"
    "api/defaultSearch/publication/"
)

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

TARGET_COUNT = int(
    os.getenv("SYNC_TARGET_COUNT", "10000")
)
PAGE_SIZE = int(
    os.getenv("SYNC_PAGE_SIZE", "100")
)
START_PAGE = int(
    os.getenv("SYNC_START_PAGE", "1")
)
PAGE_DELAY = float(
    os.getenv("SYNC_PAGE_DELAY_SECONDS", "1")
)


UPSERT_SQL = """
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
    %s, %s, %s, %s, %s, %s,
    NULL, NULL, %s, %s, %s
)
ON DUPLICATE KEY UPDATE
    title = VALUES(title),
    doi = VALUES(doi),
    publication_year = VALUES(publication_year),
    journal_name = VALUES(journal_name),
    pdf_uuid = VALUES(pdf_uuid),
    source_page = VALUES(source_page),
    download_status = CASE
        WHEN articles.download_status = 'downloaded'
            THEN 'downloaded'
        WHEN VALUES(pdf_uuid) IS NOT NULL
            THEN 'remote'
        ELSE 'missing'
    END,
    trdizin_raw_json = VALUES(trdizin_raw_json)
"""


def connect_mysql(attempts: int = 30):
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
                print(
                    "MySQL bağlantısı kuruldu.",
                    flush=True,
                )
                return connection

        except Error as error:
            print(
                "MySQL bekleniyor: "
                f"{attempt}/{attempts} — {error}",
                flush=True,
            )
            time.sleep(2)

    raise RuntimeError(
        "MySQL bağlantısı kurulamadı."
    )


def clean_text(value: Any) -> str | None:
    if value is None:
        return None

    result = str(value).strip()
    return result or None


def clean_year(value: Any) -> int | None:
    try:
        result = int(value)
    except (TypeError, ValueError):
        return None

    if 1000 <= result <= 2100:
        return result

    return None


def get_journal_name(
    source: dict[str, Any],
) -> str | None:
    journal = source.get("journal") or {}

    if not isinstance(journal, dict):
        return None

    return clean_text(journal.get("name"))


def fetch_page(
    session: requests.Session,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    response = session.get(
        API_URL,
        params={
            "q": "",
            "order": "publicationYear-DESC",
            "page": page,
            "limit": PAGE_SIZE,
            "facet-documentType": "PAPER",
            "facet-accessType": "OPEN",
        },
        timeout=(20, 120),
    )
    response.raise_for_status()

    response_data = response.json()
    hits = response_data.get("hits", {})
    records = hits.get("hits", [])
    total_value = hits.get("total", 0)

    if not isinstance(records, list):
        raise RuntimeError(
            "API kayıt listesi beklenen "
            "biçimde değil."
        )

    if isinstance(total_value, dict):
        total = int(
            total_value.get("value", 0)
        )
    else:
        total = int(total_value or 0)

    return records, total


def prepare_row(
    record: dict[str, Any],
    page: int,
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

    pdf_uuid = clean_text(source.get("pdf"))

    return (
        publication_id,
        clean_text(source.get("orderTitle")),
        clean_text(source.get("doi")),
        clean_year(
            source.get("publicationYear")
        ),
        get_journal_name(source),
        pdf_uuid,
        page,
        (
            "remote"
            if pdf_uuid
            else "missing"
        ),
        json.dumps(
            record,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )


def main() -> None:
    if PAGE_SIZE not in {10, 20, 50, 100}:
        raise RuntimeError(
            "SYNC_PAGE_SIZE yalnızca "
            "10, 20, 50 veya 100 olabilir."
        )

    if TARGET_COUNT <= 0:
        raise RuntimeError(
            "SYNC_TARGET_COUNT sıfırdan "
            "büyük olmalıdır."
        )

    connection = connect_mysql()
    cursor = connection.cursor()

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "TRDizin-Grobid-Research/1.0"
            ),
            "Accept": "application/json",
        }
    )

    page = START_PAGE
    synced = 0
    skipped = 0

    try:
        while synced < TARGET_COUNT:
            print(
                f"API sayfası alınıyor: {page}",
                flush=True,
            )

            records, api_total = fetch_page(
                session,
                page,
            )

            if not records:
                print(
                    "API başka kayıt döndürmedi.",
                    flush=True,
                )
                break

            remaining = TARGET_COUNT - synced
            rows: list[tuple[Any, ...]] = []

            for record in records[:remaining]:
                if not isinstance(record, dict):
                    skipped += 1
                    continue

                row = prepare_row(record, page)

                if row is None:
                    skipped += 1
                    continue

                rows.append(row)

            if rows:
                cursor.executemany(
                    UPSERT_SQL,
                    rows,
                )
                connection.commit()
                synced += len(rows)

            print(
                f"Sayfa {page}: "
                f"{len(rows)} kayıt — "
                f"toplam {synced}/{TARGET_COUNT} "
                f"(API toplamı {api_total})",
                flush=True,
            )

            page += 1

            if synced < TARGET_COUNT:
                time.sleep(PAGE_DELAY)

    except Exception:
        connection.rollback()
        raise

    finally:
        session.close()
        cursor.close()
        connection.close()

    print()
    print("=" * 60)
    print(
        "TR Dizin API → MySQL "
        "senkronizasyonu tamamlandı."
    )
    print(
        "Aktarılan/güncellenen: "
        f"{synced}"
    )
    print(f"Atlanan: {skipped}")
    print("=" * 60)


if __name__ == "__main__":
    main()
