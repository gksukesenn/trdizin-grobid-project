import os
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import mysql.connector
import requests
from mysql.connector import Error

from process_pdfs import (
    OUTPUT_DIRECTORY,
    LOG_DIRECTORY,
    create_session,
    process_pdf,
    wait_for_grobid,
    write_manifest,
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

REMOTE_PROCESS_LIMIT = int(
    os.getenv("REMOTE_PROCESS_LIMIT", "2")
)

REMOTE_QUERY_BATCH_SIZE = int(
    os.getenv("REMOTE_QUERY_BATCH_SIZE", "100")
)

REMOTE_PUBLICATION_IDS = [
    int(value.strip())
    for value in os.getenv(
        "REMOTE_PUBLICATION_IDS",
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
                "MySQL bekleniyor: "
                f"{attempt}/{attempts} — {error}"
            )
            time.sleep(2)

    raise RuntimeError(
        "MySQL bağlantısı kurulamadı."
    )


def get_exact_candidates(
    connection,
) -> list[tuple[int, str]]:
    placeholders = ", ".join(
        ["%s"] * len(REMOTE_PUBLICATION_IDS)
    )

    cursor = connection.cursor()

    try:
        cursor.execute(
            f"""
            SELECT publication_id, pdf_uuid
            FROM articles
            WHERE publication_id IN ({placeholders})
              AND pdf_uuid IS NOT NULL
            ORDER BY publication_id DESC
            """,
            tuple(REMOTE_PUBLICATION_IDS),
        )

        return [
            (int(publication_id), str(pdf_uuid))
            for publication_id, pdf_uuid
            in cursor.fetchall()
        ]
    finally:
        cursor.close()


def iter_remote_candidates(
    connection,
) -> Iterator[tuple[int, str]]:
    if REMOTE_PUBLICATION_IDS:
        yield from get_exact_candidates(connection)
        return

    cursor = connection.cursor()
    last_publication_id = 9_223_372_036_854_775_807
    yielded_count = 0

    try:
        while True:
            cursor.execute(
                """
                SELECT publication_id, pdf_uuid
                FROM articles
                WHERE pdf_uuid IS NOT NULL
                  AND publication_id < %s
                ORDER BY publication_id DESC
                LIMIT %s
                """,
                (
                    last_publication_id,
                    REMOTE_QUERY_BATCH_SIZE,
                ),
            )

            rows = cursor.fetchall()

            if not rows:
                break

            for publication_id, pdf_uuid in rows:
                publication_id = int(publication_id)
                last_publication_id = publication_id

                output_path = (
                    OUTPUT_DIRECTORY
                    / f"{publication_id}.tei.xml"
                )

                if (
                    output_path.exists()
                    and output_path.stat().st_size > 0
                ):
                    continue

                yield publication_id, str(pdf_uuid)
                yielded_count += 1

                if (
                    REMOTE_PROCESS_LIMIT > 0
                    and yielded_count
                    >= REMOTE_PROCESS_LIMIT
                ):
                    return
    finally:
        cursor.close()


def download_remote_pdf(
    session: requests.Session,
    publication_id: int,
    pdf_uuid: str,
) -> Path:
    file_api_url = (
        "https://search.trdizin.gov.tr/"
        f"api/getFile/{pdf_uuid}"
        "?showViewer=false"
    )

    api_response = session.get(
        file_api_url,
        headers={
            "Accept": "application/json",
        },
        timeout=(20, 120),
    )
    api_response.raise_for_status()

    download_url = api_response.json()

    if not isinstance(download_url, str):
        raise RuntimeError(
            "TR Dizin geçerli PDF bağlantısı döndürmedi."
        )

    file_descriptor, temporary_name = (
        tempfile.mkstemp(
            prefix=f"{publication_id}-",
            suffix=".pdf",
        )
    )
    os.close(file_descriptor)

    temporary_path = Path(temporary_name)

    try:
        with session.get(
            download_url,
            headers={
                "Accept": "application/pdf",
            },
            stream=True,
            allow_redirects=True,
            timeout=(20, 180),
        ) as response:
            response.raise_for_status()

            with temporary_path.open("wb") as pdf_file:
                for chunk in response.iter_content(
                    chunk_size=64 * 1024,
                ):
                    if chunk:
                        pdf_file.write(chunk)

        if temporary_path.stat().st_size == 0:
            raise RuntimeError(
                "İndirilen geçici PDF boş."
            )

        with temporary_path.open("rb") as pdf_file:
            if pdf_file.read(5) != b"%PDF-":
                raise RuntimeError(
                    "İndirilen içerik geçerli PDF değil."
                )

        return temporary_path

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOG_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    session = create_session()
    wait_for_grobid(session)

    connection = connect_mysql()

    candidates = list(
        iter_remote_candidates(connection)
    )

    connection.close()

    print(
        "İşlenecek uzak PDF sayısı: "
        f"{len(candidates)}"
    )

    if not candidates:
        print("İşlenecek uzak PDF bulunamadı.")
        return

    manifest_rows: list[dict[str, object]] = []

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for index, (
        publication_id,
        pdf_uuid,
    ) in enumerate(candidates, start=1):
        output_path = (
            OUTPUT_DIRECTORY
            / f"{publication_id}.tei.xml"
        )

        print()
        print(
            f"[{index}/{len(candidates)}] "
            f"{publication_id}"
        )

        status = ""
        message = ""
        reference_count = 0
        xml_size_bytes = 0
        temporary_pdf: Path | None = None

        try:
            if (
                output_path.exists()
                and output_path.stat().st_size > 0
            ):
                existing_content = (
                    output_path.read_bytes()
                )

                reference_count = (
                    existing_content.count(
                        b"<biblStruct"
                    )
                )
                xml_size_bytes = (
                    output_path.stat().st_size
                )

                status = "skipped"
                message = (
                    "TEI XML daha önce oluşturulmuş."
                )
                skipped_count += 1

                print(
                    "Atlandı: XML zaten mevcut. "
                    f"Kaynakça: {reference_count}"
                )

            else:
                print(
                    "PDF, TR Dizin'den "
                    "geçici olarak alınıyor..."
                )

                temporary_pdf = download_remote_pdf(
                    session,
                    publication_id,
                    pdf_uuid,
                )

                print(
                    "Geçici PDF boyutu: "
                    f"{temporary_pdf.stat().st_size} byte"
                )

                (
                    xml_size_bytes,
                    reference_count,
                ) = process_pdf(
                    session,
                    temporary_pdf,
                    output_path,
                )

                status = "processed"
                message = (
                    "Uzak PDF GROBID ile işlendi."
                )
                processed_count += 1

                print(
                    "İşlendi: "
                    f"{reference_count} kaynakça, "
                    f"{xml_size_bytes} byte"
                )

        except Exception as error:
            status = "failed"
            message = str(error)
            failed_count += 1

            print(f"Hata: {error}")

        finally:
            if temporary_pdf is not None:
                temporary_pdf.unlink(
                    missing_ok=True
                )
                print("Geçici PDF silindi.")

        manifest_rows.append(
            {
                "publication_id": publication_id,
                "pdf_filename": (
                    f"remote-{publication_id}.pdf"
                ),
                "xml_filename": output_path.name,
                "status": status,
                "reference_count": reference_count,
                "xml_size_bytes": xml_size_bytes,
                "message": message,
                "processed_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )

    write_manifest(manifest_rows)

    print()
    print("=" * 60)
    print("Uzak PDF GROBID işlemi tamamlandı.")
    print(f"Yeni işlenen: {processed_count}")
    print(f"Atlanan: {skipped_count}")
    print(f"Başarısız: {failed_count}")
    print("=" * 60)


if __name__ == "__main__":
    main()
