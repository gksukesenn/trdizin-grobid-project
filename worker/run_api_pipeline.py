import os
import subprocess
import sys
import time
from typing import Iterable

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

SYNC_TARGET_COUNT = int(
    os.getenv("PIPELINE_SYNC_TARGET_COUNT", "0")
)

SYNC_PAGE_SIZE = int(
    os.getenv("PIPELINE_SYNC_PAGE_SIZE", "10")
)

SYNC_START_PAGE = int(
    os.getenv("PIPELINE_SYNC_START_PAGE", "1")
)

BATCH_SIZE = int(
    os.getenv("PIPELINE_BATCH_SIZE", "3")
)

MAX_ARTICLES = int(
    os.getenv("PIPELINE_MAX_ARTICLES", "10")
)

PAUSE_SECONDS = float(
    os.getenv("PIPELINE_PAUSE_SECONDS", "2")
)

MAX_NO_PROGRESS_ROUNDS = int(
    os.getenv(
        "PIPELINE_MAX_NO_PROGRESS_ROUNDS",
        "3",
    )
)


def connect_mysql():
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        database=MYSQL_DATABASE,
        user=MYSQL_USER,
        password=MYSQL_PASSWORD,
        charset="utf8mb4",
    )


def run_script(
    label: str,
    script_path: str,
    environment: dict[str, str] | None = None,
) -> None:
    print()
    print("=" * 70, flush=True)
    print(label, flush=True)
    print("=" * 70, flush=True)

    command_environment = os.environ.copy()

    if environment:
        command_environment.update(environment)

    result = subprocess.run(
        [sys.executable, script_path],
        env=command_environment,
        check=False,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"{label} başarısız oldu. "
            f"Çıkış kodu: {result.returncode}"
        )


def ids_to_text(
    publication_ids: Iterable[int],
) -> str:
    return ",".join(
        str(publication_id)
        for publication_id in publication_ids
    )


def get_latest_article_ids(
    limit: int,
) -> list[int]:
    connection = connect_mysql()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT publication_id
            FROM articles
            WHERE pdf_uuid IS NOT NULL
            ORDER BY publication_id DESC
            LIMIT %s
            """,
            (limit,),
        )

        return [
            int(row[0])
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()
        connection.close()


def get_candidate_ids(
    limit: int,
) -> list[int]:
    connection = connect_mysql()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT a.publication_id
            FROM articles AS a

            LEFT JOIN reference_matching_progress AS rmp
                ON rmp.publication_id = a.publication_id

            WHERE a.pdf_uuid IS NOT NULL
              AND a.trdizin_raw_json IS NOT NULL

              AND EXISTS (
                  SELECT 1
                  FROM trdizin_references AS tr
                  WHERE tr.publication_id =
                        a.publication_id
              )

              AND (
                  rmp.publication_id IS NULL
                  OR rmp.matching_status <> 'completed'
              )

            ORDER BY a.publication_id DESC
            LIMIT %s
            """,
            (limit,),
        )

        return [
            int(row[0])
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()
        connection.close()


def count_completed(
    publication_ids: list[int],
) -> int:
    if not publication_ids:
        return 0

    placeholders = ", ".join(
        ["%s"] * len(publication_ids)
    )

    connection = connect_mysql()
    cursor = connection.cursor()

    try:
        cursor.execute(
            f"""
            SELECT COUNT(*)
            FROM reference_matching_progress
            WHERE publication_id IN ({placeholders})
              AND matching_status = 'completed'
            """,
            tuple(publication_ids),
        )

        return int(cursor.fetchone()[0])

    finally:
        cursor.close()
        connection.close()


def synchronize_articles() -> None:
    if SYNC_TARGET_COUNT <= 0:
        print(
            "API makale senkronizasyonu atlandı."
        )
        return

    run_script(
        "TR Dizin API makaleleri MySQL'e aktarılıyor",
        "/app/sync_trdizin_api.py",
        {
            "SYNC_TARGET_COUNT": str(
                SYNC_TARGET_COUNT
            ),
            "SYNC_PAGE_SIZE": str(
                SYNC_PAGE_SIZE
            ),
            "SYNC_START_PAGE": str(
                SYNC_START_PAGE
            ),
        },
    )

    latest_ids = get_latest_article_ids(
        SYNC_TARGET_COUNT
    )

    if not latest_ids:
        return

    start_publication_id = min(latest_ids) - 1

    run_script(
        "TR Dizin kaynakçaları MySQL'e aktarılıyor",
        "/app/import_trdizin_references.py",
        {
            "TRDIZIN_REFERENCE_IMPORT_LIMIT": "0",
            "TRDIZIN_REFERENCE_BATCH_SIZE": "100",
            "TRDIZIN_REFERENCE_START_PUBLICATION_ID":
                str(start_publication_id),
        },
    )


def process_batch(
    publication_ids: list[int],
) -> None:
    publication_ids_text = ids_to_text(
        publication_ids
    )

    run_script(
        "PDF'ler geçici alınarak GROBID ile işleniyor",
        "/app/process_remote_pdfs.py",
        {
            "REMOTE_PUBLICATION_IDS":
                publication_ids_text,
            "REMOTE_PROCESS_LIMIT":
                str(len(publication_ids)),
        },
    )

    run_script(
        "GROBID XML sonuçları MySQL'e aktarılıyor",
        "/app/import_grobid.py",
        {
            "GROBID_IMPORT_PUBLICATION_IDS":
                publication_ids_text,
            "GROBID_IMPORT_LIMIT": "0",
            "GROBID_IMPORT_ONLY_MISSING": "true",
        },
    )

    run_script(
        "Kesin DOI eşleşmeleri oluşturuluyor",
        "/app/match_exact_doi.py",
        {
            "MATCH_PUBLICATION_IDS":
                publication_ids_text,
        },
    )

    run_script(
        "Metin eşleşmeleri ve özetler oluşturuluyor",
        "/app/match_references.py",
        {
            "MATCH_PUBLICATION_IDS":
                publication_ids_text,
            "MATCH_ARTICLE_LIMIT":
                str(len(publication_ids)),
        },
    )


def main() -> None:
    print()
    print("#" * 70)
    print("TR Dizin API tabanlı otomatik worker")
    print("#" * 70)

    synchronize_articles()

    processed_total = 0
    round_number = 0
    no_progress_rounds = 0

    while True:
        if (
            MAX_ARTICLES > 0
            and processed_total >= MAX_ARTICLES
        ):
            break

        remaining = (
            MAX_ARTICLES - processed_total
            if MAX_ARTICLES > 0
            else BATCH_SIZE
        )

        current_batch_size = min(
            BATCH_SIZE,
            remaining,
        ) if MAX_ARTICLES > 0 else BATCH_SIZE

        publication_ids = get_candidate_ids(
            current_batch_size
        )

        if not publication_ids:
            print(
                "İşlenecek yeni makale bulunamadı."
            )
            break

        round_number += 1

        print()
        print("#" * 70)
        print(f"Worker turu: {round_number}")
        print(
            "Makale kimlikleri: "
            f"{ids_to_text(publication_ids)}"
        )
        print("#" * 70)

        completed_before = count_completed(
            publication_ids
        )

        process_batch(publication_ids)

        completed_after = count_completed(
            publication_ids
        )

        progress = (
            completed_after - completed_before
        )

        processed_total += max(progress, 0)

        print()
        print(
            "Bu turda tamamlanan makale: "
            f"{max(progress, 0)}"
        )
        print(
            "Toplam tamamlanan makale: "
            f"{processed_total}"
        )

        if progress > 0:
            no_progress_rounds = 0
        else:
            no_progress_rounds += 1

        if (
            no_progress_rounds
            >= MAX_NO_PROGRESS_ROUNDS
        ):
            raise RuntimeError(
                "Worker ilerleme sağlayamadığı için "
                "güvenli şekilde durduruldu."
            )

        time.sleep(PAUSE_SECONDS)

    print()
    print("=" * 70)
    print("API tabanlı worker tamamlandı.")
    print(
        "Tamamlanan toplam makale: "
        f"{processed_total}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
