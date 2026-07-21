import os
import time

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

PUBLICATION_IDS = [
    int(value.strip())
    for value in os.getenv(
        "MATCH_PUBLICATION_IDS",
        "",
    ).split(",")
    if value.strip()
]


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
                print("MySQL bağlantısı kuruldu.")
                return connection

        except Error as error:
            print(
                f"MySQL bekleniyor: "
                f"{attempt}/{attempts} — {error}",
                flush=True,
            )
            time.sleep(2)

    raise RuntimeError(
        "MySQL bağlantısı kurulamadı."
    )


def main() -> None:
    if not PUBLICATION_IDS:
        raise RuntimeError(
            "MATCH_PUBLICATION_IDS boş bırakılamaz."
        )

    placeholders = ", ".join(
        ["%s"] * len(PUBLICATION_IDS)
    )

    connection = connect_mysql()
    cursor = connection.cursor()

    try:
        cursor.execute(
            f"""
            DELETE FROM comparison_results
            WHERE publication_id IN ({placeholders})
              AND field_name = 'doi'
              AND comparison_status = 'exact_match'
            """,
            tuple(PUBLICATION_IDS),
        )

        query = f"""
        INSERT INTO comparison_results (
            publication_id,
            trdizin_reference_index,
            grobid_reference_index,
            field_name,
            trdizin_value,
            grobid_value,
            similarity_score,
            comparison_status
        )
        SELECT
            tr.publication_id,
            tr.reference_index,
            gr.reference_index,
            'doi',
            tr.normalized_doi,
            gr.normalized_doi,
            1.00000,
            'exact_match'
        FROM (
            SELECT
                publication_id,
                normalized_doi,
                MIN(reference_index) AS reference_index
            FROM (
                SELECT
                    publication_id,
                    reference_index,
                    LOWER(
                        TRIM(
                            REPLACE(
                                REPLACE(
                                    REPLACE(
                                        REPLACE(
                                            doi,
                                            'https://doi.org/',
                                            ''
                                        ),
                                        'http://doi.org/',
                                        ''
                                    ),
                                    'https://dx.doi.org/',
                                    ''
                                ),
                                'doi:',
                                ''
                            )
                        )
                    ) AS normalized_doi
                FROM trdizin_references
                WHERE publication_id IN ({placeholders})
                  AND doi IS NOT NULL
                  AND TRIM(doi) <> ''
            ) AS normalized_trdizin
            GROUP BY
                publication_id,
                normalized_doi
        ) AS tr

        INNER JOIN (
            SELECT
                publication_id,
                normalized_doi,
                MIN(reference_index) AS reference_index
            FROM (
                SELECT
                    publication_id,
                    reference_index,
                    LOWER(
                        TRIM(
                            REPLACE(
                                REPLACE(
                                    REPLACE(
                                        REPLACE(
                                            doi,
                                            'https://doi.org/',
                                            ''
                                        ),
                                        'http://doi.org/',
                                        ''
                                    ),
                                    'https://dx.doi.org/',
                                    ''
                                ),
                                'doi:',
                                ''
                            )
                        )
                    ) AS normalized_doi
                FROM grobid_references
                WHERE publication_id IN ({placeholders})
                  AND doi IS NOT NULL
                  AND TRIM(doi) <> ''
            ) AS normalized_grobid
            GROUP BY
                publication_id,
                normalized_doi
        ) AS gr
            ON gr.publication_id = tr.publication_id
           AND gr.normalized_doi = tr.normalized_doi
        """

        parameters = (
            tuple(PUBLICATION_IDS)
            + tuple(PUBLICATION_IDS)
        )

        cursor.execute(query, parameters)
        connection.commit()

        cursor.execute(
            f"""
            SELECT
                publication_id,
                COUNT(*) AS doi_match_count
            FROM comparison_results
            WHERE publication_id IN ({placeholders})
              AND field_name = 'doi'
              AND comparison_status = 'exact_match'
            GROUP BY publication_id
            ORDER BY publication_id
            """,
            tuple(PUBLICATION_IDS),
        )

        counts = {
            int(publication_id): int(count)
            for publication_id, count
            in cursor.fetchall()
        }

        for publication_id in PUBLICATION_IDS:
            print(
                f"{publication_id} → "
                f"{counts.get(publication_id, 0)} "
                "kesin DOI eşleşmesi"
            )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()


if __name__ == "__main__":
    main()
