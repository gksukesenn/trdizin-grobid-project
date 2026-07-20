import json
import os
import re
import time
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

# İlk testte 2 makale.
# 0 yapılırsa bütün processed makaleler aktarılır.
IMPORT_LIMIT = int(
    os.getenv(
        "TRDIZIN_REFERENCE_IMPORT_LIMIT",
        "2",
    )
)

BATCH_SIZE = int(
    os.getenv(
        "TRDIZIN_REFERENCE_BATCH_SIZE",
        "50",
    )
)

DOI_PATTERN = re.compile(
    r"\b10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    re.IGNORECASE,
)

DOI_URL_PATTERN = re.compile(
    r"https?://(?:dx\.)?doi\.org/\s*"
    r"(10\.\d{4,9}/.+)$",
    re.IGNORECASE,
)

YEAR_PATTERN = re.compile(
    r"(?<!\d)(1[0-9]{3}|20[0-9]{2}|2100)(?!\d)"
)


INSERT_REFERENCE_SQL = """
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
VALUES (
    %s, %s, %s, NULL, %s,
    %s, NULL, %s, %s
)
"""


def connect_to_mysql(attempts: int = 30):
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


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None

    text = re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip()

    return text or None


def extract_year(
    reference: dict[str, Any],
    context: str,
) -> str | None:
    year_value = normalize_text(
        reference.get("year")
    )

    if year_value:
        match = YEAR_PATTERN.search(year_value)

        if match:
            return match.group(1)

    match = YEAR_PATTERN.search(context)

    if match:
        return match.group(1)

    return None


def extract_doi(context: str) -> str | None:
    # TR Dizin kaynakça metinlerinde DOI'nin içinde
    # hatalı boşluklar bulunabiliyor:
    #
    # 10.5958/0974- 9357.2016.00103.3
    #
    # Yalnızca DOI noktalamasının hemen yanındaki
    # boşlukları temizliyoruz. Normal kelime
    # boşluklarını birleştirmiyoruz.
    normalized_context = re.sub(
        r"(?<=[-._;()/:])\s+(?=[A-Z0-9])",
        "",
        context,
        flags=re.IGNORECASE,
    )

    normalized_context = re.sub(
        r"(?<=[A-Z0-9])\s+(?=[-._;()/:])",
        "",
        normalized_context,
        flags=re.IGNORECASE,
    )

    match = DOI_PATTERN.search(
        normalized_context
    )

    if not match:
        return None

    doi = match.group(0).rstrip(
        ".,;:)]}"
    )

    # Bozuk ayrıştırılmış bir değerin MySQL
    # aktarımını durdurmasını engeller. Ham kaynakça
    # zaten raw_reference alanında korunmaktadır.
    if len(doi) > 255:
        return None

    return doi


def authors_to_json(
    authors: Any,
) -> str | None:
    if authors is None:
        return None

    return json.dumps(
        authors,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def parse_raw_json(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value

    if isinstance(value, str):
        parsed = json.loads(value)

        if isinstance(parsed, dict):
            return parsed

    raise ValueError(
        "TR Dizin ham JSON kaydı beklenen biçimde değil."
    )


def prepare_reference_rows(
    publication_id: int,
    references: list[Any],
) -> list[tuple[Any, ...]]:
    rows: list[tuple[Any, ...]] = []
    used_indexes: set[int] = set()

    for fallback_index, reference in enumerate(
        references,
        start=1,
    ):
        if not isinstance(reference, dict):
            reference = {
                "context": str(reference)
            }

        order_value = reference.get("order")

        try:
            reference_index = int(order_value)
        except (TypeError, ValueError):
            reference_index = fallback_index

        if (
            reference_index <= 0
            or reference_index in used_indexes
        ):
            reference_index = fallback_index

            while reference_index in used_indexes:
                reference_index += 1

        used_indexes.add(reference_index)

        context = normalize_text(
            reference.get("context")
        )

        if not context:
            context = json.dumps(
                reference,
                ensure_ascii=False,
            )

        rows.append(
            (
                publication_id,
                reference_index,
                context,
                authors_to_json(
                    reference.get("authors")
                ),
                extract_year(
                    reference,
                    context,
                ),
                extract_doi(context),
                json.dumps(
                    reference,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            )
        )

    return rows


def main() -> None:
    connection = connect_to_mysql()
    read_cursor = connection.cursor()
    write_cursor = connection.cursor()

    read_cursor.execute(
        """
        SELECT
            publication_id,
            COUNT(*) AS reference_count
        FROM trdizin_references
        GROUP BY publication_id
        """
    )

    existing_reference_counts = {
        int(publication_id): int(reference_count)
        for publication_id, reference_count
        in read_cursor.fetchall()
    }

    print(
        "Daha önce aktarılmış makale: "
        f"{len(existing_reference_counts)}",
        flush=True,
    )

    imported_articles = 0
    imported_references = 0
    failed_articles = 0
    last_publication_id = 0

    try:
        while True:
            remaining_limit = (
                IMPORT_LIMIT - imported_articles
                if IMPORT_LIMIT > 0
                else BATCH_SIZE
            )

            if (
                IMPORT_LIMIT > 0
                and remaining_limit <= 0
            ):
                break

            current_batch_size = min(
                BATCH_SIZE,
                remaining_limit,
            ) if IMPORT_LIMIT > 0 else BATCH_SIZE

            read_cursor.execute(
                """
                SELECT
                    a.publication_id,
                    a.trdizin_raw_json
                FROM articles AS a
                INNER JOIN grobid_documents AS gd
                    ON gd.publication_id =
                       a.publication_id
                WHERE
                    gd.processing_status = 'processed'
                    AND a.publication_id > %s
                ORDER BY a.publication_id
                LIMIT %s
                """,
                (
                    last_publication_id,
                    current_batch_size,
                ),
            )

            article_rows = read_cursor.fetchall()

            if not article_rows:
                break

            for publication_id, raw_json in article_rows:
                last_publication_id = int(
                    publication_id
                )

                try:
                    record = parse_raw_json(raw_json)

                    source = record.get(
                        "_source",
                        {},
                    )

                    if not isinstance(source, dict):
                        source = {}

                    references = source.get(
                        "references",
                        [],
                    )

                    if not isinstance(references, list):
                        references = []

                    reference_rows = (
                        prepare_reference_rows(
                            int(publication_id),
                            references,
                        )
                    )

                    existing_count = (
                        existing_reference_counts.get(
                            int(publication_id)
                        )
                    )

                    if (
                        existing_count is not None
                        and existing_count
                        == len(reference_rows)
                    ):
                        imported_articles += 1

                        print(
                            f"[{imported_articles}] "
                            f"{publication_id} → "
                            "zaten tamamlanmış, atlandı",
                            flush=True,
                        )

                        continue

                    # Eksik veya değişmiş kaynakçalar varsa
                    # o makalenin kayıtları yeniden oluşturulur.
                    write_cursor.execute(
                        """
                        DELETE FROM trdizin_references
                        WHERE publication_id = %s
                        """,
                        (publication_id,),
                    )

                    if reference_rows:
                        write_cursor.executemany(
                            INSERT_REFERENCE_SQL,
                            reference_rows,
                        )

                    connection.commit()

                    imported_articles += 1
                    imported_references += len(
                        reference_rows
                    )

                    print(
                        f"[{imported_articles}] "
                        f"{publication_id} → "
                        f"{len(reference_rows)} kaynakça",
                        flush=True,
                    )

                except Exception as error:
                    connection.rollback()
                    failed_articles += 1

                    print(
                        f"Hata — {publication_id}: "
                        f"{error}",
                        flush=True,
                    )

    finally:
        read_cursor.close()
        write_cursor.close()
        connection.close()

    print()
    print("=" * 60)
    print("TR Dizin kaynakça aktarımı tamamlandı.")
    print(
        f"İşlenen makale: "
        f"{imported_articles}"
    )
    print(
        f"Aktarılan kaynakça: "
        f"{imported_references}"
    )
    print(
        f"Başarısız makale: "
        f"{failed_articles}"
    )
    print("=" * 60)


if __name__ == "__main__":
    main()
