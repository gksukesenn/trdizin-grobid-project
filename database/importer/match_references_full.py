import os
from collections import Counter

from match_references import (
    INSERT_MATCH_SQL,
    connect_to_mysql,
    get_exact_doi_indexes,
    get_references,
    match_article,
)


# 0 = bütün tamamlanmamış makaleleri işle.
FULL_MATCH_ARTICLE_LIMIT = int(
    os.getenv("FULL_MATCH_ARTICLE_LIMIT", "0")
)


START_PROGRESS_SQL = """
INSERT INTO reference_matching_progress (
    publication_id,
    matching_status,
    error_message,
    started_at,
    completed_at
)
VALUES (
    %s,
    'running',
    NULL,
    NOW(),
    NULL
)
ON DUPLICATE KEY UPDATE
    matching_status = 'running',
    error_message = NULL,
    started_at = NOW(),
    completed_at = NULL
"""


COMPLETE_PROGRESS_SQL = """
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
VALUES (
    %s,
    'completed',
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    %s,
    NULL,
    NOW(),
    NOW()
)
ON DUPLICATE KEY UPDATE
    matching_status = 'completed',
    doi_match_count = VALUES(doi_match_count),
    text_match_count = VALUES(text_match_count),
    clean_match_count = VALUES(clean_match_count),
    merged_count = VALUES(merged_count),
    partial_count = VALUES(partial_count),
    unmatched_trdizin_count =
        VALUES(unmatched_trdizin_count),
    unmatched_grobid_count =
        VALUES(unmatched_grobid_count),
    error_message = NULL,
    completed_at = NOW()
"""


FAIL_PROGRESS_SQL = """
INSERT INTO reference_matching_progress (
    publication_id,
    matching_status,
    error_message,
    started_at,
    completed_at
)
VALUES (
    %s,
    'failed',
    %s,
    NOW(),
    NULL
)
ON DUPLICATE KEY UPDATE
    matching_status = 'failed',
    error_message = VALUES(error_message),
    completed_at = NULL
"""


DELETE_TEXT_MATCHES_SQL = """
DELETE FROM comparison_results
WHERE
    publication_id = %s
    AND field_name = 'raw_reference'
    AND comparison_status IN (
        'text_match',
        'text_match_clean',
        'grobid_merged',
        'grobid_partial'
    )
"""


def get_pending_article_ids(cursor):
    query = """
        SELECT gd.publication_id
        FROM grobid_documents AS gd
        LEFT JOIN reference_matching_progress AS progress
            ON progress.publication_id =
               gd.publication_id
        WHERE
            gd.processing_status = 'processed'
            AND (
                progress.publication_id IS NULL
                OR progress.matching_status <> 'completed'
            )
        ORDER BY gd.publication_id
    """

    parameters = ()

    if FULL_MATCH_ARTICLE_LIMIT > 0:
        query += "\nLIMIT %s"
        parameters = (FULL_MATCH_ARTICLE_LIMIT,)

    cursor.execute(query, parameters)

    return [
        int(row[0])
        for row in cursor.fetchall()
    ]


def get_completed_count(cursor):
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM reference_matching_progress
        WHERE matching_status = 'completed'
        """
    )

    return int(cursor.fetchone()[0])


def main():
    connection = connect_to_mysql()
    cursor = connection.cursor()

    article_ids = get_pending_article_ids(cursor)
    previously_completed = get_completed_count(cursor)

    print(
        "Daha önce tamamlanan makale: "
        f"{previously_completed}",
        flush=True,
    )

    print(
        "Bu çalıştırmada işlenecek makale: "
        f"{len(article_ids)}",
        flush=True,
    )

    if not article_ids:
        print("Tamamlanmamış makale bulunamadı.")
        cursor.close()
        connection.close()
        return

    completed_this_run = 0
    failed_this_run = 0

    total_doi_matches = 0
    total_text_matches = 0
    total_unmatched_trdizin = 0
    total_unmatched_grobid = 0

    total_status_counts = Counter(
        {
            "text_match_clean": 0,
            "grobid_merged": 0,
            "grobid_partial": 0,
        }
    )

    try:
        for position, publication_id in enumerate(
            article_ids,
            start=1,
        ):
            print()
            print(
                f"[{position}/{len(article_ids)}] "
                f"{publication_id}",
                flush=True,
            )

            # Bilgisayar bu makale sırasında kapanırsa
            # durum 'running' kalır. Sonraki çalıştırmada
            # yalnızca completed kayıtlar atlandığı için
            # bu makale yeniden işlenir.
            cursor.execute(
                START_PROGRESS_SQL,
                (publication_id,),
            )
            connection.commit()

            try:
                (
                    exact_trdizin_indexes,
                    exact_grobid_indexes,
                ) = get_exact_doi_indexes(
                    cursor,
                    publication_id,
                )

                trdizin_references = get_references(
                    cursor,
                    "trdizin_references",
                    publication_id,
                    exact_trdizin_indexes,
                )

                grobid_references = get_references(
                    cursor,
                    "grobid_references",
                    publication_id,
                    exact_grobid_indexes,
                )

                matches = match_article(
                    trdizin_references,
                    grobid_references,
                )

                cursor.execute(
                    DELETE_TEXT_MATCHES_SQL,
                    (publication_id,),
                )

                insert_rows = [
                    (
                        publication_id,
                        tr_reference["index"],
                        gr_reference["index"],
                        tr_reference["raw"],
                        gr_reference["raw"],
                        round(score / 100.0, 5),
                        match_status,
                    )
                    for (
                        tr_reference,
                        gr_reference,
                        score,
                        match_status,
                    ) in matches
                ]

                if insert_rows:
                    cursor.executemany(
                        INSERT_MATCH_SQL,
                        insert_rows,
                    )

                status_counts = Counter(
                    match_status
                    for (
                        _tr_reference,
                        _gr_reference,
                        _score,
                        match_status,
                    ) in matches
                )

                doi_match_count = len(
                    exact_trdizin_indexes
                )

                text_match_count = len(matches)

                unmatched_trdizin_count = (
                    len(trdizin_references)
                    - text_match_count
                )

                unmatched_grobid_count = (
                    len(grobid_references)
                    - text_match_count
                )

                cursor.execute(
                    COMPLETE_PROGRESS_SQL,
                    (
                        publication_id,
                        doi_match_count,
                        text_match_count,
                        status_counts[
                            "text_match_clean"
                        ],
                        status_counts[
                            "grobid_merged"
                        ],
                        status_counts[
                            "grobid_partial"
                        ],
                        unmatched_trdizin_count,
                        unmatched_grobid_count,
                    ),
                )

                connection.commit()

                completed_this_run += 1
                total_doi_matches += doi_match_count
                total_text_matches += text_match_count
                total_unmatched_trdizin += (
                    unmatched_trdizin_count
                )
                total_unmatched_grobid += (
                    unmatched_grobid_count
                )

                total_status_counts.update(
                    status_counts
                )

                print(
                    f"  DOI: {doi_match_count}",
                    flush=True,
                )

                print(
                    "  Metin: "
                    f"{text_match_count} "
                    f"(temiz: "
                    f"{status_counts['text_match_clean']}, "
                    f"birleşik: "
                    f"{status_counts['grobid_merged']}, "
                    f"kısmi: "
                    f"{status_counts['grobid_partial']})",
                    flush=True,
                )

                print(
                    "  Eşleşmeyen TR / GROBID: "
                    f"{unmatched_trdizin_count} / "
                    f"{unmatched_grobid_count}",
                    flush=True,
                )

            except Exception as error:
                connection.rollback()

                error_message = str(error)[:4000]

                cursor.execute(
                    FAIL_PROGRESS_SQL,
                    (
                        publication_id,
                        error_message,
                    ),
                )

                connection.commit()

                failed_this_run += 1

                print(
                    f"  Hata: {error_message}",
                    flush=True,
                )

    except KeyboardInterrupt:
        print()
        print(
            "İşlem kullanıcı tarafından durduruldu. "
            "Tamamlanan makaleler kaydedildi.",
            flush=True,
        )

    finally:
        cursor.close()
        connection.close()

    print()
    print("=" * 70)
    print("Tam kaynakça eşleştirme çalışması sona erdi.")
    print(
        f"Bu çalıştırmada tamamlanan: "
        f"{completed_this_run}"
    )
    print(
        f"Bu çalıştırmada başarısız: "
        f"{failed_this_run}"
    )
    print(
        f"Kesin DOI eşleşmesi: "
        f"{total_doi_matches}"
    )
    print(
        f"Metin eşleşmesi: "
        f"{total_text_matches}"
    )
    print(
        "Temiz metin eşleşmesi: "
        f"{total_status_counts['text_match_clean']}"
    )
    print(
        "GROBID birleşik kaynakça: "
        f"{total_status_counts['grobid_merged']}"
    )
    print(
        "GROBID kısmi kaynakça: "
        f"{total_status_counts['grobid_partial']}"
    )
    print(
        "Eşleşmeyen TR Dizin kaynakçası: "
        f"{total_unmatched_trdizin}"
    )
    print(
        "Eşleşmeyen GROBID kaynakçası: "
        f"{total_unmatched_grobid}"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
