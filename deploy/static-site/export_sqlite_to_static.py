from __future__ import annotations

import json
import os
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SQLITE_PATH = Path(
    os.getenv(
        "STATIC_SOURCE_SQLITE",
        str(
            PROJECT_ROOT
            / "deploy"
            / "huggingface"
            / "data"
            / "trdizin-demo.sqlite"
        ),
    )
)

OUTPUT_DIRECTORY = Path(
    os.getenv(
        "STATIC_OUTPUT_DIRECTORY",
        str(
            PROJECT_ROOT
            / "deploy"
            / "static-site"
            / "generated"
        ),
    )
)

SHARD_SIZE = int(
    os.getenv("STATIC_ARTICLE_SHARD_SIZE", "1000")
)

PROGRESS_INTERVAL = int(
    os.getenv("STATIC_PROGRESS_INTERVAL", "250")
)


def parse_json_value(value: Any) -> Any:
    if value is None:
        return None

    if isinstance(
        value,
        (dict, list, int, float, bool),
    ):
        return value

    if isinstance(value, bytes):
        value = value.decode(
            "utf-8",
            errors="replace",
        )

    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value

    return value


def parse_authors(value: Any) -> list[Any]:
    parsed = parse_json_value(value)

    if isinstance(parsed, list):
        return parsed

    if parsed is None:
        return []

    return [parsed]


def compact_json(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def write_json(
    path: Path,
    data: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        compact_json(data),
        encoding="utf-8",
    )


def article_shard(
    publication_id: int,
) -> str:
    return str(
        publication_id // SHARD_SIZE
    )


def serialize_article_index(
    row: sqlite3.Row,
) -> dict[str, Any]:
    processing_status = (
        row["processing_status"]
        or "not_processed"
    )

    return {
        "publication_id": row["publication_id"],
        "title": row["title"] or "",
        "doi": row["doi"] or "",
        "publication_year": (
            row["publication_year"] or ""
        ),
        "journal": row["journal_name"] or "",
        "download_status": (
            row["download_status"] or ""
        ),
        "processing_status": processing_status,
        "reference_count": (
            row["reference_count"] or 0
        ),
        "has_pdf": bool(row["pdf_uuid"]),
        "has_xml": (
            processing_status == "processed"
        ),
    }


def get_health(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    row = connection.execute(
        """
        SELECT
            (
                SELECT COUNT(*)
                FROM articles
            ) AS article_count,

            (
                SELECT COUNT(*)
                FROM articles
                WHERE pdf_uuid IS NOT NULL
                  AND TRIM(pdf_uuid) <> ''
            ) AS pdf_count,

            (
                SELECT COUNT(*)
                FROM grobid_documents
                WHERE processing_status = 'processed'
            ) AS processed_document_count,

            (
                SELECT COUNT(*)
                FROM trdizin_references
            ) AS trdizin_reference_count,

            (
                SELECT COUNT(*)
                FROM grobid_references
            ) AS grobid_reference_count,

            (
                SELECT COUNT(*)
                FROM reference_matching_progress
                WHERE matching_status = 'completed'
            ) AS matched_article_count
        """
    ).fetchone()

    return {
        "status": "ok",
        "mysql_connected": False,
        "pdf_directory_exists": False,
        "xml_directory_exists": False,
        "pdf_file_count": int(
            row["pdf_count"]
        ),
        "xml_file_count": int(
            row["processed_document_count"]
        ),
        "article_count": int(
            row["article_count"]
        ),
        "processed_document_count": int(
            row["processed_document_count"]
        ),
        "trdizin_reference_count": int(
            row["trdizin_reference_count"]
        ),
        "grobid_reference_count": int(
            row["grobid_reference_count"]
        ),
        "matched_article_count": int(
            row["matched_article_count"]
        ),
    }


def get_article_index(
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT
            a.publication_id,
            a.title,
            a.doi,
            a.publication_year,
            a.journal_name,
            a.pdf_uuid,
            a.download_status,
            gd.processing_status,
            gd.reference_count
        FROM articles AS a

        LEFT JOIN grobid_documents AS gd
            ON gd.publication_id =
               a.publication_id

        WHERE
            a.download_status = 'downloaded'
            OR a.pdf_uuid IS NOT NULL

        ORDER BY a.publication_id DESC
        """
    ).fetchall()

    return [
        serialize_article_index(row)
        for row in rows
    ]


def get_article_detail(
    connection: sqlite3.Connection,
    publication_id: int,
) -> tuple[dict[str, Any], Any]:
    row = connection.execute(
        """
        SELECT
            a.publication_id,
            a.title,
            a.doi,
            a.publication_year,
            a.journal_name,
            a.pdf_uuid,
            a.pdf_path,
            a.pdf_size_bytes,
            a.download_status,
            a.trdizin_raw_json,

            gd.processing_status,
            gd.processing_message,
            gd.reference_count
                AS grobid_reference_count,

            progress.doi_match_count,
            progress.text_match_count,
            progress.clean_match_count,
            progress.merged_count,
            progress.partial_count,
            progress.unmatched_trdizin_count,
            progress.unmatched_grobid_count,

            (
                SELECT COUNT(*)
                FROM trdizin_references AS tr
                WHERE tr.publication_id =
                      a.publication_id
            ) AS trdizin_reference_count

        FROM articles AS a

        LEFT JOIN grobid_documents AS gd
            ON gd.publication_id =
               a.publication_id

        LEFT JOIN reference_matching_progress
            AS progress
            ON progress.publication_id =
               a.publication_id

        WHERE a.publication_id = ?
        """,
        (publication_id,),
    ).fetchone()

    if row is None:
        raise RuntimeError(
            f"Makale bulunamadı: {publication_id}"
        )

    detail = {
        "publication_id": row["publication_id"],
        "title": row["title"] or "",
        "doi": row["doi"] or "",
        "publication_year": (
            row["publication_year"] or ""
        ),
        "journal_name": (
            row["journal_name"] or ""
        ),
        "pdf_uuid": row["pdf_uuid"] or "",
        "pdf_path": row["pdf_path"] or "",
        "pdf_size_bytes": (
            row["pdf_size_bytes"] or 0
        ),
        "download_status": (
            row["download_status"] or ""
        ),
        "processing_status": (
            row["processing_status"]
            or "not_processed"
        ),
        "processing_message": (
            row["processing_message"] or ""
        ),
        "grobid_reference_count": (
            row["grobid_reference_count"] or 0
        ),
        "doi_match_count": (
            row["doi_match_count"] or 0
        ),
        "text_match_count": (
            row["text_match_count"] or 0
        ),
        "clean_match_count": (
            row["clean_match_count"] or 0
        ),
        "merged_count": (
            row["merged_count"] or 0
        ),
        "partial_count": (
            row["partial_count"] or 0
        ),
        "unmatched_trdizin_count": (
            row["unmatched_trdizin_count"] or 0
        ),
        "unmatched_grobid_count": (
            row["unmatched_grobid_count"] or 0
        ),
        "trdizin_reference_count": (
            row["trdizin_reference_count"] or 0
        ),
    }

    return (
        detail,
        parse_json_value(
            row["trdizin_raw_json"]
        ),
    )


def get_trdizin_references(
    connection: sqlite3.Connection,
    publication_id: int,
) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT
            reference_index,
            raw_reference,
            title,
            authors_json,
            publication_year,
            journal_name,
            doi,
            trdizin_raw_json
        FROM trdizin_references
        WHERE publication_id = ?
        ORDER BY reference_index
        """,
        (publication_id,),
    ).fetchall()

    references = [
        {
            "index": row["reference_index"],
            "raw_reference": (
                row["raw_reference"] or ""
            ),
            "title": row["title"] or "",
            "authors": parse_authors(
                row["authors_json"]
            ),
            "year": (
                row["publication_year"] or ""
            ),
            "journal": (
                row["journal_name"] or ""
            ),
            "doi": row["doi"] or "",
            "raw_json": parse_json_value(
                row["trdizin_raw_json"]
            ),
        }
        for row in rows
    ]

    return {
        "publication_id": publication_id,
        "reference_count": len(references),
        "references": references,
    }


def get_grobid_references(
    connection: sqlite3.Connection,
    publication_id: int,
) -> dict[str, Any]:
    rows = connection.execute(
        """
        SELECT
            reference_index,
            xml_id,
            raw_reference,
            title,
            authors_json,
            publication_year,
            journal_name,
            doi
        FROM grobid_references
        WHERE publication_id = ?
        ORDER BY reference_index
        """,
        (publication_id,),
    ).fetchall()

    references = [
        {
            "index": row["reference_index"],
            "xml_id": row["xml_id"] or "",
            "raw_reference": (
                row["raw_reference"] or ""
            ),
            "title": row["title"] or "",
            "authors": parse_authors(
                row["authors_json"]
            ),
            "year": (
                row["publication_year"] or ""
            ),
            "journal": (
                row["journal_name"] or ""
            ),
            "doi": row["doi"] or "",
        }
        for row in rows
    ]

    return {
        "publication_id": publication_id,
        "reference_count": len(references),
        "references": references,
    }


def get_comparison(
    connection: sqlite3.Connection,
    publication_id: int,
    trdizin_references: dict[str, Any],
    grobid_references: dict[str, Any],
) -> dict[str, Any]:
    summary_row = connection.execute(
        """
        SELECT
            doi_match_count,
            text_match_count,
            clean_match_count,
            merged_count,
            partial_count,
            unmatched_trdizin_count,
            unmatched_grobid_count,
            matching_status
        FROM reference_matching_progress
        WHERE publication_id = ?
        """,
        (publication_id,),
    ).fetchone()

    if summary_row is None:
        summary = {
            "doi_match_count": 0,
            "text_match_count": 0,
            "clean_match_count": 0,
            "merged_count": 0,
            "partial_count": 0,
            "unmatched_trdizin_count": 0,
            "unmatched_grobid_count": 0,
            "matching_status": "not_matched",
        }
    else:
        summary = dict(summary_row)

    match_rows = connection.execute(
        """
        SELECT
            cr.field_name,
            cr.comparison_status,
            cr.similarity_score,
            cr.trdizin_reference_index,
            cr.grobid_reference_index,

            tr.raw_reference
                AS trdizin_raw_reference,
            tr.publication_year
                AS trdizin_year,
            tr.doi
                AS trdizin_doi,

            gr.raw_reference
                AS grobid_raw_reference,
            gr.publication_year
                AS grobid_year,
            gr.doi
                AS grobid_doi

        FROM comparison_results AS cr

        LEFT JOIN trdizin_references AS tr
            ON tr.publication_id =
               cr.publication_id
           AND tr.reference_index =
               cr.trdizin_reference_index

        LEFT JOIN grobid_references AS gr
            ON gr.publication_id =
               cr.publication_id
           AND gr.reference_index =
               cr.grobid_reference_index

        WHERE cr.publication_id = ?

        ORDER BY
            COALESCE(
                cr.trdizin_reference_index,
                cr.grobid_reference_index
            ),
            cr.field_name
        """,
        (publication_id,),
    ).fetchall()

    matches = [
        dict(row)
        for row in match_rows
    ]

    matched_trdizin_indexes = {
        row["trdizin_reference_index"]
        for row in match_rows
        if row["trdizin_reference_index"]
        is not None
    }

    matched_grobid_indexes = {
        row["grobid_reference_index"]
        for row in match_rows
        if row["grobid_reference_index"]
        is not None
    }

    unmatched_trdizin = [
        {
            "reference_index": reference["index"],
            "raw_reference": (
                reference["raw_reference"]
            ),
            "publication_year": (
                reference["year"]
            ),
            "doi": reference["doi"],
        }
        for reference
        in trdizin_references["references"]
        if reference["index"]
        not in matched_trdizin_indexes
    ]

    unmatched_grobid = [
        {
            "reference_index": reference["index"],
            "raw_reference": (
                reference["raw_reference"]
            ),
            "publication_year": (
                reference["year"]
            ),
            "doi": reference["doi"],
        }
        for reference
        in grobid_references["references"]
        if reference["index"]
        not in matched_grobid_indexes
    ]

    return {
        "publication_id": publication_id,
        "summary": summary,
        "matches": matches,
        "unmatched_trdizin": unmatched_trdizin,
        "unmatched_grobid": unmatched_grobid,
    }


def get_tei_xml(
    connection: sqlite3.Connection,
    publication_id: int,
) -> str | None:
    row = connection.execute(
        """
        SELECT
            tei_xml,
            processing_status
        FROM grobid_documents
        WHERE publication_id = ?
        """,
        (publication_id,),
    ).fetchone()

    if row is None:
        return None

    if row["processing_status"] != "processed":
        return None

    return row["tei_xml"] or None


def prepare_output_directory() -> None:
    if OUTPUT_DIRECTORY.exists():
        shutil.rmtree(OUTPUT_DIRECTORY)

    (
        OUTPUT_DIRECTORY
        / "data"
        / "articles"
    ).mkdir(
        parents=True,
        exist_ok=True,
    )

    (
        OUTPUT_DIRECTORY
        / "data"
        / "tei"
    ).mkdir(
        parents=True,
        exist_ok=True,
    )


def main() -> None:
    if not SQLITE_PATH.exists():
        raise FileNotFoundError(
            "SQLite veritabanı bulunamadı: "
            f"{SQLITE_PATH}"
        )

    if SHARD_SIZE <= 0:
        raise ValueError(
            "STATIC_ARTICLE_SHARD_SIZE "
            "sıfırdan büyük olmalıdır."
        )

    prepare_output_directory()

    connection = sqlite3.connect(
        SQLITE_PATH
    )
    connection.row_factory = sqlite3.Row
    connection.execute(
        "PRAGMA query_only = ON"
    )

    try:
        health = get_health(connection)
        articles = get_article_index(
            connection
        )

        write_json(
            OUTPUT_DIRECTORY
            / "data"
            / "health.json",
            health,
        )

        write_json(
            OUTPUT_DIRECTORY
            / "data"
            / "articles-index.json",
            {
                "total": len(articles),
                "articles": articles,
            },
        )

        total = len(articles)

        for position, article in enumerate(
            articles,
            start=1,
        ):
            publication_id = int(
                article["publication_id"]
            )

            detail, trdizin_raw_json = (
                get_article_detail(
                    connection,
                    publication_id,
                )
            )

            trdizin_data = (
                get_trdizin_references(
                    connection,
                    publication_id,
                )
            )

            grobid_data = (
                get_grobid_references(
                    connection,
                    publication_id,
                )
            )

            comparison_data = get_comparison(
                connection,
                publication_id,
                trdizin_data,
                grobid_data,
            )

            shard = article_shard(
                publication_id
            )

            tei_xml = get_tei_xml(
                connection,
                publication_id,
            )

            tei_relative_path = None

            if tei_xml:
                tei_relative_path = (
                    f"data/tei/{shard}/"
                    f"{publication_id}.xml"
                )

                tei_path = (
                    OUTPUT_DIRECTORY
                    / tei_relative_path
                )

                tei_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )

                tei_path.write_text(
                    tei_xml,
                    encoding="utf-8",
                )

            package = {
                "publication_id": publication_id,
                "detail": detail,
                "trdizin_references": trdizin_data,
                "grobid_references": grobid_data,
                "comparison": comparison_data,
                "trdizin_json": {
                    "publication_id":
                        publication_id,
                    "data": trdizin_raw_json,
                },
                "tei_path": tei_relative_path,
            }

            article_path = (
                OUTPUT_DIRECTORY
                / "data"
                / "articles"
                / shard
                / f"{publication_id}.json"
            )

            write_json(
                article_path,
                package,
            )

            if (
                position == 1
                or position % PROGRESS_INTERVAL == 0
                or position == total
            ):
                print(
                    "Statik makale paketi: "
                    f"{position}/{total}",
                    flush=True,
                )

        write_json(
            OUTPUT_DIRECTORY
            / "data"
            / "manifest.json",
            {
                "generated_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "article_count": total,
                "shard_size": SHARD_SIZE,
                "format_version": 1,
            },
        )

    finally:
        connection.close()

    output_size_bytes = sum(
        path.stat().st_size
        for path in OUTPUT_DIRECTORY.rglob("*")
        if path.is_file()
    )

    print()
    print("=" * 70)
    print("SQLite → statik veri aktarımı tamamlandı.")
    print(f"Makale sayısı: {total}")
    print(f"Çıktı: {OUTPUT_DIRECTORY}")
    print(
        "Toplam boyut: "
        f"{output_size_bytes / 1024 / 1024:.2f} MB"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
