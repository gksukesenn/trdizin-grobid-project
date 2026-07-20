import csv
import os
import time
from pathlib import Path

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

REPORT_PATH = Path(
    os.getenv(
        "FAILED_REPORT_PATH",
        "/data/logs/failed_grobid_classification.csv",
    )
)


UPSERT_SQL = """
INSERT INTO grobid_documents (
    publication_id,
    tei_file_path,
    tei_xml,
    reference_count,
    processing_status,
    processing_message,
    processed_at
)
VALUES (
    %s,
    NULL,
    NULL,
    0,
    %s,
    %s,
    NOW()
)
ON DUPLICATE KEY UPDATE
    tei_file_path = IF(
        processing_status = 'processed',
        tei_file_path,
        NULL
    ),
    tei_xml = IF(
        processing_status = 'processed',
        tei_xml,
        NULL
    ),
    reference_count = IF(
        processing_status = 'processed',
        reference_count,
        0
    ),
    processing_status = IF(
        processing_status = 'processed',
        processing_status,
        VALUES(processing_status)
    ),
    processing_message = IF(
        processing_status = 'processed',
        processing_message,
        VALUES(processing_message)
    ),
    processed_at = IF(
        processing_status = 'processed',
        processed_at,
        VALUES(processed_at)
    )
"""


def connect_to_mysql(attempts=30):
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
                "MySQL hazır değil: "
                f"{attempt}/{attempts} — {error}",
                flush=True,
            )

        time.sleep(2)

    raise RuntimeError(
        "MySQL bağlantısı kurulamadı."
    )


def main():
    if not REPORT_PATH.exists():
        raise RuntimeError(
            "Sınıflandırma raporu bulunamadı: "
            f"{REPORT_PATH}"
        )

    accepted_categories = {
        "no_content",
        "ocr_required",
        "http_error",
        "request_error",
        "missing_pdf",
        "unexpected_error",
    }

    rows = []
    skipped_count = 0

    with REPORT_PATH.open(
        encoding="utf-8",
        newline="",
    ) as csv_file:
        reader = csv.DictReader(csv_file)

        for row in reader:
            publication_id_text = (
                row.get("publication_id", "").strip()
            )

            category = (
                row.get("category", "").strip()
            )

            message = (
                row.get("message", "").strip()
            )

            if (
                not publication_id_text.isdigit()
                or category not in accepted_categories
            ):
                skipped_count += 1
                continue

            rows.append(
                (
                    int(publication_id_text),
                    category,
                    message,
                )
            )

    print(
        f"Aktarılacak durum kaydı: {len(rows)}",
        flush=True,
    )

    connection = connect_to_mysql()
    cursor = connection.cursor()

    try:
        if rows:
            cursor.executemany(
                UPSERT_SQL,
                rows,
            )

        connection.commit()

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    print()
    print("=" * 55)
    print("GROBID başarısızlık durumları aktarıldı.")
    print(f"Aktarılan/güncellenen: {len(rows)}")
    print(f"Atlanan geçersiz kayıt: {skipped_count}")
    print("=" * 55)


if __name__ == "__main__":
    main()
