import json
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
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

GROBID_OUTPUT_DIRECTORY = Path(
    os.getenv(
        "GROBID_OUTPUT_DIRECTORY",
        "/data/grobid-output",
    )
)

# 0 verilirse klasördeki bütün TEI XML dosyaları aktarılır.
GROBID_IMPORT_LIMIT = int(
    os.getenv("GROBID_IMPORT_LIMIT", "10")
)

GROBID_IMPORT_ONLY_MISSING = (
    os.getenv(
        "GROBID_IMPORT_ONLY_MISSING",
        "false",
    ).strip().lower()
    in {"1", "true", "yes", "on"}
)

TEI_NAMESPACE = {
    "tei": "http://www.tei-c.org/ns/1.0"
}

XML_ID_ATTRIBUTE = (
    "{http://www.w3.org/XML/1998/namespace}id"
)


DOCUMENT_UPSERT_SQL = """
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
    %s, %s, %s, %s, %s, %s, %s
)
ON DUPLICATE KEY UPDATE
    tei_file_path = VALUES(tei_file_path),
    tei_xml = VALUES(tei_xml),
    reference_count = VALUES(reference_count),
    processing_status = VALUES(processing_status),
    processing_message = VALUES(processing_message),
    processed_at = VALUES(processed_at)
"""


REFERENCE_INSERT_SQL = """
INSERT INTO grobid_references (
    publication_id,
    reference_index,
    xml_id,
    raw_reference,
    title,
    authors_json,
    publication_year,
    journal_name,
    doi,
    grobid_raw_json
)
VALUES (
    %s, %s, %s, %s, %s,
    %s, %s, %s, %s, %s
)
"""


def connect_to_mysql(
    attempts: int = 30,
):
    print(
        "MySQL bağlantısı bekleniyor...",
        flush=True,
    )

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
                f"MySQL hazır değil: "
                f"{attempt}/{attempts} — {error}",
                flush=True,
            )

        time.sleep(2)

    raise RuntimeError(
        "MySQL bağlantısı kurulamadı."
    )


def normalize_text(value: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def element_text(
    element: ET.Element | None,
) -> str | None:
    if element is None:
        return None

    text = normalize_text(
        " ".join(element.itertext())
    )

    return text or None


def extract_raw_reference(
    bibl_struct: ET.Element,
) -> str | None:
    raw_note = bibl_struct.find(
        ".//tei:note[@type='raw_reference']",
        TEI_NAMESPACE,
    )

    raw_text = element_text(raw_note)

    if raw_text:
        return raw_text

    return element_text(bibl_struct)


def extract_title(
    bibl_struct: ET.Element,
) -> str | None:
    paths = [
        ".//tei:analytic/tei:title",
        ".//tei:monogr/tei:title[@level='m']",
        ".//tei:title",
    ]

    for path in paths:
        title_element = bibl_struct.find(
            path,
            TEI_NAMESPACE,
        )

        title = element_text(title_element)

        if title:
            return title

    return None


def extract_authors(
    bibl_struct: ET.Element,
) -> list[str]:
    author_elements = bibl_struct.findall(
        ".//tei:analytic/tei:author",
        TEI_NAMESPACE,
    )

    if not author_elements:
        author_elements = bibl_struct.findall(
            ".//tei:author",
            TEI_NAMESPACE,
        )

    authors: list[str] = []

    for author_element in author_elements:
        author = element_text(author_element)

        if author and author not in authors:
            authors.append(author)

    return authors


def extract_year(
    bibl_struct: ET.Element,
) -> str | None:
    date_elements = bibl_struct.findall(
        ".//tei:date",
        TEI_NAMESPACE,
    )

    for date_element in date_elements:
        candidates = [
            date_element.attrib.get("when", ""),
            element_text(date_element) or "",
        ]

        for candidate in candidates:
            match = re.search(
                r"(?<!\d)(1[0-9]{3}|20[0-9]{2}|2100)(?!\d)",
                candidate,
            )

            if match:
                return match.group(1)

    return None


def extract_journal(
    bibl_struct: ET.Element,
) -> str | None:
    journal_paths = [
        ".//tei:monogr/tei:title[@level='j']",
        ".//tei:monogr/tei:title[@level='m']",
    ]

    for path in journal_paths:
        journal_element = bibl_struct.find(
            path,
            TEI_NAMESPACE,
        )

        journal = element_text(journal_element)

        if journal:
            return journal

    return None


def extract_doi(
    bibl_struct: ET.Element,
) -> str | None:
    idno_elements = bibl_struct.findall(
        ".//tei:idno",
        TEI_NAMESPACE,
    )

    for idno_element in idno_elements:
        idno_type = idno_element.attrib.get(
            "type",
            "",
        ).upper()

        if idno_type == "DOI":
            return element_text(idno_element)

    return None


def publication_id_from_path(
    xml_path: Path,
) -> int | None:
    suffix = ".tei.xml"

    if not xml_path.name.endswith(suffix):
        return None

    publication_id_text = xml_path.name[
        :-len(suffix)
    ]

    if not publication_id_text.isdigit():
        return None

    return int(publication_id_text)


def get_xml_files() -> list[Path]:
    xml_files = sorted(
        GROBID_OUTPUT_DIRECTORY.glob(
            "*.tei.xml"
        ),
        key=lambda path: (
            publication_id_from_path(path) or -1
        ),
        reverse=True,
    )

    if GROBID_IMPORT_LIMIT > 0:
        xml_files = xml_files[
            :GROBID_IMPORT_LIMIT
        ]

    return xml_files


def get_existing_document_ids(
    cursor,
) -> set[int]:
    cursor.execute(
        """
        SELECT publication_id
        FROM grobid_documents
        WHERE processing_status = 'processed'
        """
    )

    return {
        int(row[0])
        for row in cursor.fetchall()
    }


def article_exists(
    cursor,
    publication_id: int,
) -> bool:
    cursor.execute(
        """
        SELECT 1
        FROM articles
        WHERE publication_id = %s
        LIMIT 1
        """,
        (publication_id,),
    )

    return cursor.fetchone() is not None


def parse_references(
    root: ET.Element,
    publication_id: int,
) -> list[tuple[Any, ...]]:
    bibl_structs = root.findall(
        ".//tei:biblStruct",
        TEI_NAMESPACE,
    )

    rows: list[tuple[Any, ...]] = []

    for reference_index, bibl_struct in enumerate(
        bibl_structs,
        start=1,
    ):
        xml_id = bibl_struct.attrib.get(
            XML_ID_ATTRIBUTE,
            f"b{reference_index - 1}",
        )

        raw_reference = extract_raw_reference(
            bibl_struct
        )
        title = extract_title(bibl_struct)
        authors = extract_authors(bibl_struct)
        publication_year = extract_year(
            bibl_struct
        )
        journal_name = extract_journal(
            bibl_struct
        )
        doi = extract_doi(bibl_struct)

        structured_data = {
            "xml_id": xml_id,
            "raw_reference": raw_reference,
            "title": title,
            "authors": authors,
            "publication_year": publication_year,
            "journal_name": journal_name,
            "doi": doi,
        }

        rows.append(
            (
                publication_id,
                reference_index,
                xml_id,
                raw_reference,
                title,
                json.dumps(
                    authors,
                    ensure_ascii=False,
                ),
                publication_year,
                journal_name,
                doi,
                json.dumps(
                    structured_data,
                    ensure_ascii=False,
                ),
            )
        )

    return rows


def main() -> None:
    xml_files = get_xml_files()

    print(
        f"Bulunan TEI XML dosyası: "
        f"{len(xml_files)}",
        flush=True,
    )

    if not xml_files:
        raise RuntimeError(
            "Aktarılacak TEI XML bulunamadı."
        )

    connection = connect_to_mysql()
    cursor = connection.cursor()

    existing_document_ids: set[int] = set()

    if GROBID_IMPORT_ONLY_MISSING:
        existing_document_ids = (
            get_existing_document_ids(cursor)
        )

        print(
            "MySQL'de mevcut GROBID belgesi: "
            f"{len(existing_document_ids)}",
            flush=True,
        )

        xml_files = [
            xml_path
            for xml_path in xml_files
            if publication_id_from_path(xml_path)
            not in existing_document_ids
        ]

        print(
            "MySQL'e aktarılacak yeni TEI XML: "
            f"{len(xml_files)}",
            flush=True,
        )

    imported_documents = 0
    imported_references = 0
    skipped_documents = 0
    failed_documents = 0

    try:
        for index, xml_path in enumerate(
            xml_files,
            start=1,
        ):
            publication_id = (
                publication_id_from_path(xml_path)
            )

            if publication_id is None:
                skipped_documents += 1

                print(
                    f"[{index}/{len(xml_files)}] "
                    f"Atlandı: geçersiz dosya adı "
                    f"{xml_path.name}",
                    flush=True,
                )
                continue

            if (
                GROBID_IMPORT_ONLY_MISSING
                and publication_id in existing_document_ids
            ):
                skipped_documents += 1

                print(
                    f"[{index}/{len(xml_files)}] "
                    f"{xml_path.name}",
                    flush=True,
                )

                print(
                    "  Atlandı: MySQL'de zaten mevcut.",
                    flush=True,
                )

                continue

            print(
                f"[{index}/{len(xml_files)}] "
                f"{xml_path.name}",
                flush=True,
            )

            if not article_exists(
                cursor,
                publication_id,
            ):
                skipped_documents += 1

                print(
                    "  Atlandı: articles tablosunda "
                    "makale bulunamadı.",
                    flush=True,
                )
                continue

            try:
                tei_xml = xml_path.read_text(
                    encoding="utf-8"
                )

                root = ET.fromstring(tei_xml)

                reference_rows = parse_references(
                    root,
                    publication_id,
                )

                processed_at = datetime.fromtimestamp(
                    xml_path.stat().st_mtime,
                    tz=timezone.utc,
                ).replace(tzinfo=None)

                tei_file_path = (
                    f"/data/grobid-output/"
                    f"{xml_path.name}"
                )

                cursor.execute(
                    DOCUMENT_UPSERT_SQL,
                    (
                        publication_id,
                        tei_file_path,
                        tei_xml,
                        len(reference_rows),
                        "processed",
                        (
                            "TEI XML ve kaynakçalar "
                            "veritabanına aktarıldı."
                        ),
                        processed_at,
                    ),
                )

                # Aktarım tekrar çalıştırılırsa aynı
                # kaynakçaların çoğalmasını engeller.
                cursor.execute(
                    """
                    DELETE FROM grobid_references
                    WHERE publication_id = %s
                    """,
                    (publication_id,),
                )

                if reference_rows:
                    cursor.executemany(
                        REFERENCE_INSERT_SQL,
                        reference_rows,
                    )

                connection.commit()

                imported_documents += 1
                imported_references += len(
                    reference_rows
                )

                print(
                    f"  Aktarıldı: "
                    f"{len(reference_rows)} kaynakça",
                    flush=True,
                )

            except Exception as error:
                connection.rollback()
                failed_documents += 1

                print(
                    f"  Hata: {error}",
                    flush=True,
                )

    finally:
        cursor.close()
        connection.close()

    print()
    print("=" * 55)
    print("GROBID veritabanı aktarımı tamamlandı.")
    print(
        f"Aktarılan belge: "
        f"{imported_documents}"
    )
    print(
        f"Aktarılan kaynakça: "
        f"{imported_references}"
    )
    print(
        f"Atlanan belge: "
        f"{skipped_documents}"
    )
    print(
        f"Başarısız belge: "
        f"{failed_documents}"
    )
    print("=" * 55)


if __name__ == "__main__":
    main()
