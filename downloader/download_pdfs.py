import csv
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


SEARCH_API_URL = (
    "https://search.trdizin.gov.tr/api/defaultSearch/publication/"
)

PDFS_DIRECTORY = Path(
    os.getenv("PDF_DIRECTORY", "/data/pdfs")
)

METADATA_DIRECTORY = Path(
    os.getenv("METADATA_DIRECTORY", "/data/metadata")
)

PAGE = int(os.getenv("DOWNLOAD_PAGE", "1"))
LIMIT = int(os.getenv("DOWNLOAD_LIMIT", "10"))
REQUEST_DELAY = float(os.getenv("REQUEST_DELAY_SECONDS", "1"))

MANIFEST_PATH = METADATA_DIRECTORY / "download_manifest.csv"

HEADERS = {
    "User-Agent": "TRDizin-Grobid-Research/0.1",
    "Accept": "application/json",
}


def create_session() -> requests.Session:
    retry_strategy = Retry(
        total=3,
        connect=3,
        read=3,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )

    adapter = HTTPAdapter(max_retries=retry_strategy)

    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", adapter)

    return session


def get_publications(
    session: requests.Session,
) -> list[dict[str, Any]]:
    params = {
        "q": "",
        "order": "publicationYear-DESC",
        "page": PAGE,
        "limit": LIMIT,
        "facet-documentType": "PAPER",
        "facet-accessType": "OPEN",
    }

    print("TR Dizin makale kayıtları alınıyor...")
    print(f"Sayfa: {PAGE}")
    print(f"İstenen kayıt sayısı: {LIMIT}")

    response = session.get(
        SEARCH_API_URL,
        params=params,
        timeout=60,
    )

    print(f"Arama API durum kodu: {response.status_code}")
    response.raise_for_status()

    data = response.json()
    records = data.get("hits", {}).get("hits", [])

    if not isinstance(records, list):
        raise RuntimeError("API kayıt listesi beklenen biçimde değil.")

    print(f"API tarafından dönen kayıt sayısı: {len(records)}")

    return records


def get_download_url(
    session: requests.Session,
    pdf_uuid: str,
) -> str:
    file_api_url = (
        "https://search.trdizin.gov.tr/api/getFile/"
        f"{pdf_uuid}?showViewer=false"
    )

    response = session.get(
        file_api_url,
        timeout=60,
    )
    response.raise_for_status()

    download_url = response.json()

    if not isinstance(download_url, str):
        raise RuntimeError(
            "TR Dizin geçerli bir PDF indirme adresi döndürmedi."
        )

    return download_url


def download_pdf(
    session: requests.Session,
    download_url: str,
    output_path: Path,
) -> int:
    temporary_path = output_path.with_suffix(".pdf.part")

    response = session.get(
        download_url,
        timeout=180,
        stream=True,
    )
    response.raise_for_status()

    content_type = response.headers.get(
        "Content-Type",
        "",
    ).lower()

    if "pdf" not in content_type:
        raise RuntimeError(
            f"Beklenmeyen içerik türü: {content_type}"
        )

    try:
        with temporary_path.open("wb") as pdf_file:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    pdf_file.write(chunk)

        with temporary_path.open("rb") as pdf_file:
            signature = pdf_file.read(5)

        if signature != b"%PDF-":
            raise RuntimeError(
                "İndirilen dosya geçerli bir PDF değil."
            )

        temporary_path.replace(output_path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path.stat().st_size


def get_title(source: dict[str, Any]) -> str:
    title = source.get("orderTitle")

    if isinstance(title, str):
        return title.strip()

    return ""


def write_manifest(rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "publication_id",
        "title",
        "doi",
        "publication_year",
        "journal",
        "pdf_uuid",
        "filename",
        "size_bytes",
        "status",
        "message",
        "processed_at",
    ]

    file_exists = MANIFEST_PATH.exists()

    with MANIFEST_PATH.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=fieldnames,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerows(rows)


def main() -> None:
    PDFS_DIRECTORY.mkdir(parents=True, exist_ok=True)
    METADATA_DIRECTORY.mkdir(parents=True, exist_ok=True)

    session = create_session()
    records = get_publications(session)

    manifest_rows: list[dict[str, Any]] = []

    downloaded_count = 0
    skipped_count = 0
    failed_count = 0

    for index, record in enumerate(records, start=1):
        source = record.get("_source", {})

        publication_id = str(
            source.get("id") or record.get("_id") or ""
        )

        pdf_uuid = source.get("pdf")
        title = get_title(source)
        doi = source.get("doi") or ""
        publication_year = source.get("publicationYear") or ""

        journal_data = source.get("journal") or {}
        journal_name = journal_data.get("name", "")

        output_path = PDFS_DIRECTORY / f"{publication_id}.pdf"

        print()
        print(f"[{index}/{len(records)}] Yayın: {publication_id}")
        print(f"Başlık: {title[:100] or 'Başlık bulunamadı'}")

        status = ""
        message = ""
        size_bytes = 0

        try:
            if not publication_id:
                raise RuntimeError("Yayın kodu bulunamadı.")

            if not isinstance(pdf_uuid, str) or not pdf_uuid:
                status = "skipped"
                message = "PDF kimliği bulunamadı."
                skipped_count += 1
                print("Atlandı: PDF kimliği yok.")

            elif output_path.exists():
                status = "skipped"
                message = "PDF daha önce indirilmiş."
                size_bytes = output_path.stat().st_size
                skipped_count += 1
                print("Atlandı: Dosya zaten mevcut.")

            else:
                download_url = get_download_url(
                    session,
                    pdf_uuid,
                )

                size_bytes = download_pdf(
                    session,
                    download_url,
                    output_path,
                )

                status = "downloaded"
                message = "PDF başarıyla indirildi."
                downloaded_count += 1

                size_mb = size_bytes / (1024 * 1024)
                print(f"İndirildi: {size_mb:.2f} MB")

        except Exception as error:
            status = "failed"
            message = str(error)
            failed_count += 1
            print(f"Hata: {error}")

        manifest_rows.append(
            {
                "publication_id": publication_id,
                "title": title,
                "doi": doi,
                "publication_year": publication_year,
                "journal": journal_name,
                "pdf_uuid": pdf_uuid or "",
                "filename": (
                    output_path.name
                    if publication_id
                    else ""
                ),
                "size_bytes": size_bytes,
                "status": status,
                "message": message,
                "processed_at": datetime.now(
                    timezone.utc
                ).isoformat(),
            }
        )

        if index < len(records):
            time.sleep(REQUEST_DELAY)

    write_manifest(manifest_rows)

    print()
    print("=" * 50)
    print("İndirme işlemi tamamlandı.")
    print(f"Yeni indirilen: {downloaded_count}")
    print(f"Atlanan: {skipped_count}")
    print(f"Başarısız: {failed_count}")
    print(f"CSV kayıt dosyası: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
