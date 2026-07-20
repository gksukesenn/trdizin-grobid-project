import os
import re
import time
import unicodedata
from typing import Any, Dict, List, Optional, Set, Tuple

import mysql.connector
from mysql.connector import Error
from rapidfuzz import fuzz


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

MATCH_ARTICLE_LIMIT = int(
    os.getenv("MATCH_ARTICLE_LIMIT", "20")
)

TEXT_MATCH_THRESHOLD = float(
    os.getenv("TEXT_MATCH_THRESHOLD", "82")
)

MATCH_MARGIN = float(
    os.getenv("MATCH_MARGIN", "3")
)


INSERT_MATCH_SQL = """
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
VALUES (
    %s, %s, %s,
    'raw_reference',
    %s, %s, %s,
    %s
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


def normalize_reference(value: Optional[str]) -> str:
    if not value:
        return ""

    text = unicodedata.normalize(
        "NFKC",
        value,
    ).lower()

    # URL öneklerini kaldırır, DOI ve devamındaki
    # anlamlı parçaları metinde bırakır.
    text = re.sub(
        r"https?://(?:dx\.)?doi\.org/",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    text = re.sub(
        r"https?://",
        " ",
        text,
        flags=re.IGNORECASE,
    )

    # Noktalama işaretlerini boşluğa dönüştürür.
    text = "".join(
        character if character.isalnum() else " "
        for character in text
    )

    return re.sub(
        r"\s+",
        " ",
        text,
    ).strip()


def calculate_score(
    trdizin_reference: Dict[str, Any],
    grobid_reference: Dict[str, Any],
) -> float:
    tr_text = trdizin_reference["normalized"]
    gr_text = grobid_reference["normalized"]

    if len(tr_text) < 15 or len(gr_text) < 15:
        return 0.0

    ratio_score = fuzz.ratio(
        tr_text,
        gr_text,
    )

    token_sort_score = fuzz.token_sort_ratio(
        tr_text,
        gr_text,
    )

    token_set_score = fuzz.token_set_ratio(
        tr_text,
        gr_text,
    )

    score = (
        token_set_score * 0.45
        + token_sort_score * 0.35
        + ratio_score * 0.20
    )

    tr_year = trdizin_reference.get("year")
    gr_year = grobid_reference.get("year")

    if tr_year and gr_year:
        if tr_year == gr_year:
            score += 5.0
        else:
            score -= 8.0

    shorter_length = min(
        len(tr_text),
        len(gr_text),
    )

    longer_length = max(
        len(tr_text),
        len(gr_text),
    )

    if (
        longer_length > 0
        and shorter_length / longer_length < 0.45
    ):
        score -= 8.0

    return max(
        0.0,
        min(100.0, score),
    )


def classify_match(
    trdizin_reference: Dict[str, Any],
    grobid_reference: Dict[str, Any],
) -> str:
    tr_text = trdizin_reference["normalized"]
    gr_text = grobid_reference["normalized"]

    if not tr_text or not gr_text:
        return "text_match_clean"

    shorter_length = min(
        len(tr_text),
        len(gr_text),
    )

    longer_length = max(
        len(tr_text),
        len(gr_text),
    )

    length_ratio = (
        shorter_length / longer_length
        if longer_length > 0
        else 1.0
    )

    partial_score = fuzz.partial_ratio(
        tr_text,
        gr_text,
    )

    # TR Dizin kaydı GROBID metninin içinde büyük ölçüde
    # bulunuyor fakat GROBID metni belirgin biçimde uzunsa,
    # GROBID muhtemelen sonraki/önceki kaynakçayı da eklemiştir.
    if (
        partial_score >= 95.0
        and length_ratio < 0.80
        and len(gr_text) > len(tr_text)
    ):
        return "grobid_merged"

    # GROBID metni TR Dizin kaydının yalnızca bir bölümüyse,
    # kaynakçanın başı veya sonu kesilmiş olabilir.
    if (
        partial_score >= 95.0
        and length_ratio < 0.80
        and len(gr_text) < len(tr_text)
    ):
        return "grobid_partial"

    return "text_match_clean"


def get_article_ids(cursor) -> List[int]:
    cursor.execute(
        """
        SELECT gd.publication_id
        FROM grobid_documents AS gd
        WHERE
            gd.processing_status = 'processed'

            AND EXISTS (
                SELECT 1
                FROM trdizin_references AS tr
                WHERE tr.publication_id =
                      gd.publication_id
            )

            AND EXISTS (
                SELECT 1
                FROM grobid_references AS gr
                WHERE gr.publication_id =
                      gd.publication_id
            )

        ORDER BY gd.publication_id
        LIMIT %s
        """,
        (MATCH_ARTICLE_LIMIT,),
    )

    return [
        int(row[0])
        for row in cursor.fetchall()
    ]


def get_exact_doi_indexes(
    cursor,
    publication_id: int,
) -> Tuple[Set[int], Set[int]]:
    cursor.execute(
        """
        SELECT
            trdizin_reference_index,
            grobid_reference_index
        FROM comparison_results
        WHERE
            publication_id = %s
            AND field_name = 'doi'
            AND comparison_status = 'exact_match'
        """,
        (publication_id,),
    )

    trdizin_indexes: Set[int] = set()
    grobid_indexes: Set[int] = set()

    for tr_index, gr_index in cursor.fetchall():
        if tr_index is not None:
            trdizin_indexes.add(int(tr_index))

        if gr_index is not None:
            grobid_indexes.add(int(gr_index))

    return trdizin_indexes, grobid_indexes


def get_references(
    cursor,
    table_name: str,
    publication_id: int,
    excluded_indexes: Set[int],
) -> List[Dict[str, Any]]:
    if table_name not in {
        "trdizin_references",
        "grobid_references",
    }:
        raise ValueError("Geçersiz tablo adı.")

    cursor.execute(
        f"""
        SELECT
            reference_index,
            raw_reference,
            publication_year
        FROM {table_name}
        WHERE publication_id = %s
        ORDER BY reference_index
        """,
        (publication_id,),
    )

    references: List[Dict[str, Any]] = []

    for index, raw_reference, year in cursor.fetchall():
        reference_index = int(index)

        if reference_index in excluded_indexes:
            continue

        references.append(
            {
                "index": reference_index,
                "raw": raw_reference or "",
                "year": (
                    str(year).strip()
                    if year is not None
                    else None
                ),
                "normalized": normalize_reference(
                    raw_reference
                ),
            }
        )

    return references


def best_candidate(
    scores: List[Tuple[float, int]],
) -> Tuple[Optional[int], float, float]:
    if not scores:
        return None, 0.0, 0.0

    ordered_scores = sorted(
        scores,
        key=lambda item: item[0],
        reverse=True,
    )

    best_score, best_index = ordered_scores[0]

    second_score = (
        ordered_scores[1][0]
        if len(ordered_scores) > 1
        else 0.0
    )

    return best_index, best_score, second_score


def match_article(
    trdizin_references: List[Dict[str, Any]],
    grobid_references: List[Dict[str, Any]],
) -> List[
    Tuple[
        Dict[str, Any],
        Dict[str, Any],
        float,
        str,
    ]
]:
    if not trdizin_references or not grobid_references:
        return []

    score_matrix: Dict[Tuple[int, int], float] = {}

    for tr_position, tr_reference in enumerate(
        trdizin_references
    ):
        for gr_position, gr_reference in enumerate(
            grobid_references
        ):
            score_matrix[
                (tr_position, gr_position)
            ] = calculate_score(
                tr_reference,
                gr_reference,
            )

    tr_best: Dict[int, Tuple[Optional[int], float, float]] = {}

    for tr_position in range(
        len(trdizin_references)
    ):
        scores = [
            (
                score_matrix[
                    (tr_position, gr_position)
                ],
                gr_position,
            )
            for gr_position in range(
                len(grobid_references)
            )
        ]

        tr_best[tr_position] = best_candidate(
            scores
        )

    gr_best: Dict[int, Tuple[Optional[int], float, float]] = {}

    for gr_position in range(
        len(grobid_references)
    ):
        scores = [
            (
                score_matrix[
                    (tr_position, gr_position)
                ],
                tr_position,
            )
            for tr_position in range(
                len(trdizin_references)
            )
        ]

        gr_best[gr_position] = best_candidate(
            scores
        )

    matches = []

    for tr_position, (
        gr_position,
        score,
        tr_second_score,
    ) in tr_best.items():
        if gr_position is None:
            continue

        (
            reverse_tr_position,
            reverse_score,
            gr_second_score,
        ) = gr_best[gr_position]

        if reverse_tr_position != tr_position:
            continue

        if score < TEXT_MATCH_THRESHOLD:
            continue

        if (
            score - tr_second_score < MATCH_MARGIN
            or reverse_score - gr_second_score
            < MATCH_MARGIN
        ):
            continue

        match_status = classify_match(
            trdizin_references[tr_position],
            grobid_references[gr_position],
        )

        matches.append(
            (
                trdizin_references[tr_position],
                grobid_references[gr_position],
                score,
                match_status,
            )
        )

    return matches


def main() -> None:
    connection = connect_to_mysql()
    cursor = connection.cursor()

    article_ids = get_article_ids(cursor)

    print(
        f"Test edilecek makale: "
        f"{len(article_ids)}",
        flush=True,
    )

    print(
        f"Metin eşleşme eşiği: "
        f"{TEXT_MATCH_THRESHOLD}",
        flush=True,
    )

    total_matches = 0
    total_unmatched_trdizin = 0
    total_unmatched_grobid = 0

    total_status_counts = {
        "text_match_clean": 0,
        "grobid_merged": 0,
        "grobid_partial": 0,
    }

    try:
        for position, publication_id in enumerate(
            article_ids,
            start=1,
        ):
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
                """
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
                """,
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

            connection.commit()

            matched_count = len(matches)

            article_status_counts = {
                "text_match_clean": 0,
                "grobid_merged": 0,
                "grobid_partial": 0,
            }

            for (
                _tr_reference,
                _gr_reference,
                _score,
                match_status,
            ) in matches:
                article_status_counts[
                    match_status
                ] += 1

                total_status_counts[
                    match_status
                ] += 1

            total_matches += matched_count
            total_unmatched_trdizin += (
                len(trdizin_references)
                - matched_count
            )
            total_unmatched_grobid += (
                len(grobid_references)
                - matched_count
            )

            print(
                f"[{position}/{len(article_ids)}] "
                f"{publication_id} → "
                f"DOI: {len(exact_trdizin_indexes)}, "
                f"metin: {matched_count} "
                f"(temiz: "
                f"{article_status_counts['text_match_clean']}, "
                f"birleşik: "
                f"{article_status_counts['grobid_merged']}, "
                f"kısmi: "
                f"{article_status_counts['grobid_partial']}), "
                f"kalan TR: "
                f"{len(trdizin_references) - matched_count}, "
                f"kalan GROBID: "
                f"{len(grobid_references) - matched_count}",
                flush=True,
            )

    except Exception:
        connection.rollback()
        raise

    finally:
        cursor.close()
        connection.close()

    print()
    print("=" * 65)
    print("Metin benzerliği testi tamamlandı.")
    print(f"Test edilen makale: {len(article_ids)}")
    print(f"Yeni metin eşleşmesi: {total_matches}")
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
    print("=" * 65)


if __name__ == "__main__":
    main()
