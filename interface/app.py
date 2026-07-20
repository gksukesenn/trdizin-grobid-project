import json
import os
from pathlib import Path
from typing import Any

import mysql.connector
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response
from mysql.connector import Error


PDF_DIRECTORY = Path(
    os.getenv("PDF_DIRECTORY", "/data/pdfs")
)

XML_DIRECTORY = Path(
    os.getenv("XML_DIRECTORY", "/data/grobid-output")
)

TEMPLATE_DIRECTORY = Path(
    os.getenv("TEMPLATE_DIRECTORY", "/app/templates")
)

INDEX_HTML = TEMPLATE_DIRECTORY / "index.html"

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
MYSQL_PASSWORD = os.getenv(
    "MYSQL_PASSWORD",
    "",
)


app = FastAPI(
    title="TR Dizin – GROBID Karşılaştırma Arayüzü",
    version="1.0.0",
)


def get_connection():
    try:
        connection = mysql.connector.connect(
            host=MYSQL_HOST,
            port=MYSQL_PORT,
            database=MYSQL_DATABASE,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            charset="utf8mb4",
            connection_timeout=15,
        )

        return connection

    except Error as error:
        raise HTTPException(
            status_code=503,
            detail=(
                "MySQL bağlantısı kurulamadı: "
                f"{error}"
            ),
        ) from error


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


def ensure_article_exists(
    cursor,
    publication_id: int,
) -> None:
    cursor.execute(
        """
        SELECT 1
        FROM articles
        WHERE publication_id = %s
        LIMIT 1
        """,
        (publication_id,),
    )

    if cursor.fetchone() is None:
        raise HTTPException(
            status_code=404,
            detail="Makale bulunamadı.",
        )


def serialize_article(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "publication_id": row["publication_id"],
        "title": row.get("title") or "",
        "doi": row.get("doi") or "",
        "publication_year": (
            row.get("publication_year") or ""
        ),
        "journal": row.get("journal_name") or "",
        "download_status": (
            row.get("download_status") or ""
        ),
        "processing_status": (
            row.get("processing_status")
            or "not_processed"
        ),
        "reference_count": (
            row.get("reference_count") or 0
        ),
        "has_pdf": (
            row.get("download_status")
            == "downloaded"
        ),
        "has_xml": (
            row.get("processing_status")
            == "processed"
        ),
    }


@app.get("/", response_class=HTMLResponse)
def home() -> HTMLResponse:
    if not INDEX_HTML.exists():
        raise HTTPException(
            status_code=500,
            detail="Arayüz şablonu bulunamadı.",
        )

    return HTMLResponse(
        INDEX_HTML.read_text(
            encoding="utf-8"
        )
    )


@app.get("/api/health")
def health() -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                (
                    SELECT COUNT(*)
                    FROM articles
                ) AS article_count,

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
        )

        counts = cursor.fetchone()

        return {
            "status": "ok",
            "mysql_connected": True,
            "pdf_directory_exists": (
                PDF_DIRECTORY.exists()
            ),
            "xml_directory_exists": (
                XML_DIRECTORY.exists()
            ),
            "pdf_file_count": len(
                list(
                    PDF_DIRECTORY.glob(
                        "*.pdf"
                    )
                )
            ),
            "xml_file_count": len(
                list(
                    XML_DIRECTORY.glob(
                        "*.tei.xml"
                    )
                )
            ),
            **counts,
        }

    finally:
        cursor.close()
        connection.close()


# Eski arayüzle uyumlu makale listesi.
@app.get("/api/articles")
def list_articles(
    limit: int = Query(
        default=10000,
        ge=1,
        le=10000,
    ),
) -> list[dict[str, Any]]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
            """
            SELECT
                a.publication_id,
                a.title,
                a.doi,
                a.publication_year,
                a.journal_name,
                a.download_status,
                gd.processing_status,
                gd.reference_count
            FROM articles AS a
            LEFT JOIN grobid_documents AS gd
                ON gd.publication_id =
                   a.publication_id
            WHERE
                a.download_status = 'downloaded'
            ORDER BY
                a.publication_id DESC
            LIMIT %s
            """,
            (limit,),
        )

        return [
            serialize_article(row)
            for row in cursor.fetchall()
        ]

    finally:
        cursor.close()
        connection.close()


# Yeni arayüzün arama ve sayfalama endpointi.
@app.get("/api/articles/search")
def search_articles(
    q: str = Query(
        default="",
        max_length=200,
    ),
    processing_status: str = Query(
        default="",
        max_length=30,
    ),
    limit: int = Query(
        default=50,
        ge=1,
        le=200,
    ),
    offset: int = Query(
        default=0,
        ge=0,
    ),
) -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    where_clauses = [
        "a.download_status = 'downloaded'"
    ]

    parameters: list[Any] = []

    if q.strip():
        search_value = f"%{q.strip()}%"

        where_clauses.append(
            """
            (
                CAST(
                    a.publication_id
                    AS CHAR
                ) LIKE %s
                OR a.title LIKE %s
                OR a.doi LIKE %s
                OR a.journal_name LIKE %s
            )
            """
        )

        parameters.extend(
            [
                search_value,
                search_value,
                search_value,
                search_value,
            ]
        )

    if processing_status.strip():
        where_clauses.append(
            """
            COALESCE(
                gd.processing_status,
                'not_processed'
            ) = %s
            """
        )

        parameters.append(
            processing_status.strip()
        )

    where_sql = " AND ".join(
        where_clauses
    )

    try:
        cursor.execute(
            f"""
            SELECT COUNT(*) AS total
            FROM articles AS a
            LEFT JOIN grobid_documents AS gd
                ON gd.publication_id =
                   a.publication_id
            WHERE {where_sql}
            """,
            tuple(parameters),
        )

        total = int(
            cursor.fetchone()["total"]
        )

        cursor.execute(
            f"""
            SELECT
                a.publication_id,
                a.title,
                a.doi,
                a.publication_year,
                a.journal_name,
                a.download_status,
                gd.processing_status,
                gd.reference_count
            FROM articles AS a
            LEFT JOIN grobid_documents AS gd
                ON gd.publication_id =
                   a.publication_id
            WHERE {where_sql}
            ORDER BY
                a.publication_id DESC
            LIMIT %s OFFSET %s
            """,
            tuple(
                parameters
                + [limit, offset]
            ),
        )

        articles = [
            serialize_article(row)
            for row in cursor.fetchall()
        ]

        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "articles": articles,
        }

    finally:
        cursor.close()
        connection.close()


@app.get("/api/articles/{publication_id}")
def article_detail(
    publication_id: int,
) -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        cursor.execute(
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
                progress.unmatched_grobid_count

            FROM articles AS a

            LEFT JOIN grobid_documents AS gd
                ON gd.publication_id =
                   a.publication_id

            LEFT JOIN reference_matching_progress
                AS progress
                ON progress.publication_id =
                   a.publication_id

            WHERE a.publication_id = %s
            """,
            (publication_id,),
        )

        row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Makale bulunamadı.",
            )

        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM trdizin_references
            WHERE publication_id = %s
            """,
            (publication_id,),
        )

        row["trdizin_reference_count"] = int(
            cursor.fetchone()["count"]
        )

        return row

    finally:
        cursor.close()
        connection.close()


@app.get(
    "/api/articles/{publication_id}/trdizin-references"
)
def trdizin_references(
    publication_id: int,
) -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        ensure_article_exists(
            cursor,
            publication_id,
        )

        cursor.execute(
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
            WHERE publication_id = %s
            ORDER BY reference_index
            """,
            (publication_id,),
        )

        rows = cursor.fetchall()

        references = []

        for row in rows:
            references.append(
                {
                    "index": (
                        row[
                            "reference_index"
                        ]
                    ),
                    "raw_reference": (
                        row[
                            "raw_reference"
                        ]
                        or ""
                    ),
                    "title": (
                        row["title"] or ""
                    ),
                    "authors": parse_authors(
                        row["authors_json"]
                    ),
                    "year": (
                        row[
                            "publication_year"
                        ]
                        or ""
                    ),
                    "journal": (
                        row["journal_name"]
                        or ""
                    ),
                    "doi": row["doi"] or "",
                    "raw_json": (
                        parse_json_value(
                            row[
                                "trdizin_raw_json"
                            ]
                        )
                    ),
                }
            )

        return {
            "publication_id": publication_id,
            "reference_count": len(
                references
            ),
            "references": references,
        }

    finally:
        cursor.close()
        connection.close()


@app.get(
    "/api/articles/{publication_id}/grobid-references"
)
@app.get(
    "/api/articles/{publication_id}/references"
)
def grobid_references(
    publication_id: int,
) -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        ensure_article_exists(
            cursor,
            publication_id,
        )

        cursor.execute(
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
            WHERE publication_id = %s
            ORDER BY reference_index
            """,
            (publication_id,),
        )

        rows = cursor.fetchall()

        references = []

        for row in rows:
            references.append(
                {
                    "index": (
                        row[
                            "reference_index"
                        ]
                    ),
                    "xml_id": (
                        row["xml_id"] or ""
                    ),
                    "raw_reference": (
                        row[
                            "raw_reference"
                        ]
                        or ""
                    ),
                    "title": (
                        row["title"] or ""
                    ),
                    "authors": parse_authors(
                        row["authors_json"]
                    ),
                    "year": (
                        row[
                            "publication_year"
                        ]
                        or ""
                    ),
                    "journal": (
                        row["journal_name"]
                        or ""
                    ),
                    "doi": row["doi"] or "",
                }
            )

        return {
            "publication_id": publication_id,
            "reference_count": len(
                references
            ),
            "references": references,
        }

    finally:
        cursor.close()
        connection.close()


@app.get(
    "/api/articles/{publication_id}/comparison"
)
def article_comparison(
    publication_id: int,
) -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor(
        dictionary=True
    )

    try:
        ensure_article_exists(
            cursor,
            publication_id,
        )

        cursor.execute(
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
            WHERE publication_id = %s
            """,
            (publication_id,),
        )

        summary = cursor.fetchone() or {
            "doi_match_count": 0,
            "text_match_count": 0,
            "clean_match_count": 0,
            "merged_count": 0,
            "partial_count": 0,
            "unmatched_trdizin_count": 0,
            "unmatched_grobid_count": 0,
            "matching_status": "not_matched",
        }

        cursor.execute(
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

            WHERE cr.publication_id = %s

            ORDER BY
                COALESCE(
                    cr.trdizin_reference_index,
                    cr.grobid_reference_index
                ),
                cr.field_name
            """,
            (publication_id,),
        )

        matches = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                tr.reference_index,
                tr.raw_reference,
                tr.publication_year,
                tr.doi
            FROM trdizin_references AS tr
            WHERE
                tr.publication_id = %s

                AND NOT EXISTS (
                    SELECT 1
                    FROM comparison_results AS cr
                    WHERE
                        cr.publication_id =
                            tr.publication_id
                        AND
                        cr.trdizin_reference_index =
                            tr.reference_index
                )

            ORDER BY tr.reference_index
            """,
            (publication_id,),
        )

        unmatched_trdizin = cursor.fetchall()

        cursor.execute(
            """
            SELECT
                gr.reference_index,
                gr.raw_reference,
                gr.publication_year,
                gr.doi
            FROM grobid_references AS gr
            WHERE
                gr.publication_id = %s

                AND NOT EXISTS (
                    SELECT 1
                    FROM comparison_results AS cr
                    WHERE
                        cr.publication_id =
                            gr.publication_id
                        AND
                        cr.grobid_reference_index =
                            gr.reference_index
                )

            ORDER BY gr.reference_index
            """,
            (publication_id,),
        )

        unmatched_grobid = cursor.fetchall()

        return {
            "publication_id": publication_id,
            "summary": summary,
            "matches": matches,
            "unmatched_trdizin": (
                unmatched_trdizin
            ),
            "unmatched_grobid": (
                unmatched_grobid
            ),
        }

    finally:
        cursor.close()
        connection.close()


@app.get(
    "/api/articles/{publication_id}/trdizin-json"
)
def trdizin_json(
    publication_id: int,
) -> dict[str, Any]:
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT trdizin_raw_json
            FROM articles
            WHERE publication_id = %s
            """,
            (publication_id,),
        )

        row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="Makale bulunamadı.",
            )

        return {
            "publication_id": publication_id,
            "data": parse_json_value(
                row[0]
            ),
        }

    finally:
        cursor.close()
        connection.close()


@app.get(
    "/api/articles/{publication_id}/grobid-tei"
)
def grobid_tei(
    publication_id: int,
) -> Response:
    connection = get_connection()
    cursor = connection.cursor()

    try:
        cursor.execute(
            """
            SELECT
                tei_xml,
                processing_status
            FROM grobid_documents
            WHERE publication_id = %s
            """,
            (publication_id,),
        )

        row = cursor.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail="GROBID kaydı bulunamadı.",
            )

        tei_xml, processing_status = row

        if (
            processing_status != "processed"
            or not tei_xml
        ):
            raise HTTPException(
                status_code=404,
                detail=(
                    "Bu makale için geçerli "
                    "TEI XML bulunmuyor."
                ),
            )

        return Response(
            content=tei_xml,
            media_type="application/xml",
        )

    finally:
        cursor.close()
        connection.close()


@app.get("/pdfs/{publication_id}.pdf")
def get_pdf(
    publication_id: int,
) -> FileResponse:
    pdf_path = (
        PDF_DIRECTORY
        / f"{publication_id}.pdf"
    )

    if not pdf_path.exists():
        raise HTTPException(
            status_code=404,
            detail="PDF bulunamadı.",
        )

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=f"{publication_id}.pdf",
        content_disposition_type="inline",
    )


@app.get("/tei/{publication_id}.xml")
def get_tei(
    publication_id: int,
) -> FileResponse:
    xml_path = (
        XML_DIRECTORY
        / f"{publication_id}.tei.xml"
    )

    if not xml_path.exists():
        raise HTTPException(
            status_code=404,
            detail="TEI XML bulunamadı.",
        )

    return FileResponse(
        path=xml_path,
        media_type="application/xml",
        filename=(
            f"{publication_id}.tei.xml"
        ),
        content_disposition_type="inline",
    )
