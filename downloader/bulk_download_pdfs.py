import csv
import json
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

PDF_DIRECTORY = Path(
    os.getenv("PDF_DIRECTORY", "/data/pdfs")
)

METADATA_DIRECTORY = Path(
    os.getenv("METADATA_DIRECTORY", "/data/metadata")
)

LOG_DIRECTORY = Path(
    os.getenv("LOG_DIRECTORY", "/data/logs")
)

PAGES_DIRECTORY = METADATA_DIRECTORY / "api-pages"
STATE_PATH = METADATA_DIRECTORY / "bulk_state.json"
MANIFEST_PATH = LOG_DIRECTORY / "bulk_download_manifest.csv"

TARGET_COUNT = int(os.getenv("TARGET_COUNT", "10000"))
PAGE_SIZE = int(os.getenv("PAGE_SIZE", "100"))
START_PAGE = int(os.getenv("START_PAGE", "1"))

REQUEST_DELAY_SECONDS = float(
    os.getenv("REQUEST_DELAY_SECONDS", "1")
)

PAGE_DELAY_SECONDS = float(
    os.getenv("PAGE_DELAY_SECONDS", "2")
)

RUN_ID = datetime.now(timezone.utc).strftime(
    "%Y%m%dT%H%M%SZ"
)

HEADERS = {
    "User-Agent": "TRDizin-Grobid-Research/1.0",
    "Accept": "application/json",
}

MANIFEST_FIELDS = [
    "run_id",
    "page",
    "position",
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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_session() -> requests.Session:
    retry_strategy = Retry(
        total=5,
        connect=5,
        read=5,
        status=5,
        backoff_factor=2,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
        respect_retry_after_header=True,
    )

    adapter = HTTPAdapter(
        max_retries=retry_strategy
    )

    session = requests.Session()
    session.headers.update(HEADERS)
    session.mount("https://", adapter)

    return session


def atomic_write_json(
    path: Path,
    payload: dict[str, Any],
) -> None:
    temporary_path = path.with_suffix(
        path.suffix + ".tmp"
    )

    temporary_path.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(path)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {
            "page": START_PAGE,
        }

    try:
        return json.loads(
            STATE_PATH.read_text(
                encoding="utf-8"
            )
        )
    except (OSError, ValueError):
        print(
            "Uyarı: Durum dosyası okunamadı. "
            "Birinci sayfadan başlanacak.",
            flush=True,
        )

        return {
            "page": START_PAGE,
        }


def save_state(
    page: int,
    local_pdf_count: int,
    last_publication_id: str = "",
    status: str = "running",
) -> None:
    atomic_write_json(
        STATE_PATH,
        {
            "page": page,
            "target_count": TARGET_COUNT,
            "local_pdf_count": local_pdf_count,
            "last_publication_id": (
                last_publication_id
            ),
            "status": status,
            "updated_at": utc_now(),
        },
    )


def append_manifest(
    row: dict[str, Any],
) -> None:
    file_exists = MANIFEST_PATH.exists()

    with MANIFEST_PATH.open(
        "a",
        encoding="utf-8",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=MANIFEST_FIELDS,
        )

        if not file_exists:
            writer.writeheader()

        writer.writerow(row)


def get_existing_pdf_ids() -> set[str]:
    valid_ids: set[str] = set()

    for pdf_path in PDF_DIRECTORY.glob(
        "*.pdf"
    ):
        try:
            with pdf_path.open("rb") as pdf_file:
                signature = pdf_file.read(5)

            if signature == b"%PDF-":
                valid_ids.add(pdf_path.stem)
            else:
                print(
                    "Geçersiz mevcut dosya "
                    f"yeniden indirilecek: "
                    f"{pdf_path.name}",
                    flush=True,
                )

        except OSError:
            continue

    return valid_ids


def fetch_page(
    session: requests.Session,
    page: int,
) -> tuple[list[dict[str, Any]], int]:
    params = {
        "q": "",
        "order": "publicationYear-DESC",
        "page": page,
        "limit": PAGE_SIZE,
        "facet-documentType": "PAPER",
        "facet-accessType": "OPEN",
    }

    response = session.get(
        SEARCH_API_URL,
        params=params,
        timeout=(20, 120),
    )

    response.raise_for_status()

    data = response.json()
    hits_block = data.get("hits", {})
    records = hits_block.get("hits", [])

    if not isinstance(records, list):
        raise RuntimeError(
            "API kayıt listesi beklenen biçimde değil."
        )

    total_data = hits_block.get("total", 0)

    if isinstance(total_data, dict):
        total = int(total_data.get("value", 0))
    else:
        total = int(total_data or 0)

    # Karşılaştırmada kullanılabilmesi için ham
    # API kayıtlarını sayfa sayfa saklıyoruz.
    atomic_write_json(
        PAGES_DIRECTORY
        / f"page_{page:05d}.json",
        {
            "page": page,
            "page_size": PAGE_SIZE,
            "total_result_count": total,
            "retrieved_at": utc_now(),
            "records": records,
        },
    )

    return records, total


def get_download_url(
    session: requests.Session,
    pdf_uuid: str,
) -> str:
    file_api_url = (
        "https://search.trdizin.gov.tr/"
        f"api/getFile/{pdf_uuid}"
        "?showViewer=false"
    )

    response = session.get(
        file_api_url,
        timeout=(20, 120),
    )

    response.raise_for_status()

    download_url = response.json()

    if not isinstance(download_url, str):
        raise RuntimeError(
            "TR Dizin geçerli indirme "
            "adresi döndürmedi."
        )

    return download_url


def download_pdf(
    session: requests.Session,
    download_url: str,
    output_path: Path,
) -> int:
    temporary_path = Path(
        f"{output_path}.part"
    )

    try:
        response = session.get(
            download_url,
            timeout=(20, 300),
            stream=True,
        )

        response.raise_for_status()

        with temporary_path.open(
            "wb"
        ) as pdf_file:
            for chunk in response.iter_content(
                chunk_size=1024 * 1024
            ):
                if chunk:
                    pdf_file.write(chunk)

        with temporary_path.open(
            "rb"
        ) as pdf_file:
            signature = pdf_file.read(5)

        if signature != b"%PDF-":
            raise RuntimeError(
                "İndirilen dosya geçerli "
                "bir PDF değil."
            )

        temporary_path.replace(output_path)

    except Exception:
        temporary_path.unlink(
            missing_ok=True
        )
        raise

    return output_path.stat().st_size


def clean_text(value: Any) -> str:
    if value is None:
        return ""

    return str(value).strip()


def get_title(
    source: dict[str, Any],
) -> str:
    return clean_text(
        source.get("orderTitle")
    )


def get_journal_name(
    source: dict[str, Any],
) -> str:
    journal = source.get("journal") or {}

    if not isinstance(journal, dict):
        return ""

    return clean_text(
        journal.get("name")
    )


def make_manifest_row(
    *,
    page: int,
    position: int,
    publication_id: str,
    source: dict[str, Any],
    status: str,
    message: str,
    size_bytes: int = 0,
) -> dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "page": page,
        "position": position,
        "publication_id": publication_id,
        "title": get_title(source),
        "doi": clean_text(source.get("doi")),
        "publication_year": clean_text(
            source.get("publicationYear")
        ),
        "journal": get_journal_name(source),
        "pdf_uuid": clean_text(
            source.get("pdf")
        ),
        "filename": (
            f"{publication_id}.pdf"
            if publication_id
            else ""
        ),
        "size_bytes": size_bytes,
        "status": status,
        "message": message,
        "processed_at": utc_now(),
    }


def main() -> None:
    if PAGE_SIZE not in {10, 20, 50, 100}:
        raise RuntimeError(
            "PAGE_SIZE yalnızca "
            "10, 20, 50 veya 100 olabilir."
        )

    PDF_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOG_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    PAGES_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    existing_ids = get_existing_pdf_ids()
    state = load_state()

    page = max(
        START_PAGE,
        int(state.get("page", START_PAGE)),
    )

    downloaded_this_run = 0
    failed_this_run = 0
    skipped_this_run = 0
    consecutive_failures = 0

    print("=" * 60, flush=True)
    print(
        "TR Dizin 10.000 PDF toplu indirme",
        flush=True,
    )
    print(
        f"Hedef PDF sayısı: {TARGET_COUNT}",
        flush=True,
    )
    print(
        f"Başlangıçtaki geçerli PDF: "
        f"{len(existing_ids)}",
        flush=True,
    )
    print(
        f"Başlangıç sayfası: {page}",
        flush=True,
    )
    print(
        "Paralel indirme: kapalı",
        flush=True,
    )
    print("=" * 60, flush=True)

    if len(existing_ids) >= TARGET_COUNT:
        print(
            "Hedef zaten tamamlanmış.",
            flush=True,
        )

        save_state(
            page,
            len(existing_ids),
            status="completed",
        )
        return

    session = create_session()

    try:
        while len(existing_ids) < TARGET_COUNT:
            print(
                f"\nAPI sayfası alınıyor: {page}",
                flush=True,
            )

            try:
                records, total = fetch_page(
                    session,
                    page,
                )

            except requests.HTTPError as error:
                status_code = (
                    error.response.status_code
                    if error.response is not None
                    else None
                )

                print(
                    "Sayfa alınamadı. "
                    f"HTTP: {status_code}",
                    flush=True,
                )

                save_state(
                    page,
                    len(existing_ids),
                    status="paused_api_error",
                )
                return

            except Exception as error:
                print(
                    f"Sayfa alınamadı: {error}",
                    flush=True,
                )

                save_state(
                    page,
                    len(existing_ids),
                    status="paused_api_error",
                )
                return

            if not records:
                print(
                    "API bu sayfada kayıt döndürmedi.",
                    flush=True,
                )

                save_state(
                    page,
                    len(existing_ids),
                    status="finished_no_more_records",
                )
                return

            print(
                f"API toplam sonucu: {total}",
                flush=True,
            )
            print(
                f"Bu sayfadaki kayıt: "
                f"{len(records)}",
                flush=True,
            )

            for position, record in enumerate(
                records,
                start=1,
            ):
                if len(existing_ids) >= TARGET_COUNT:
                    break

                source = record.get(
                    "_source",
                    {},
                )

                if not isinstance(source, dict):
                    source = {}

                publication_id = clean_text(
                    source.get("id")
                    or record.get("_id")
                )

                if not publication_id:
                    skipped_this_run += 1

                    append_manifest(
                        make_manifest_row(
                            page=page,
                            position=position,
                            publication_id="",
                            source=source,
                            status="skipped",
                            message=(
                                "Yayın kodu bulunamadı."
                            ),
                        )
                    )
                    continue

                if publication_id in existing_ids:
                    print(
                        f"[{page}:{position}] "
                        f"{publication_id} zaten var "
                        f"({len(existing_ids)}/"
                        f"{TARGET_COUNT})",
                        flush=True,
                    )
                    continue

                pdf_uuid = source.get("pdf")

                print(
                    f"[{page}:{position}] "
                    f"{publication_id} indiriliyor "
                    f"({len(existing_ids)}/"
                    f"{TARGET_COUNT})",
                    flush=True,
                )

                if (
                    not isinstance(pdf_uuid, str)
                    or not pdf_uuid.strip()
                ):
                    skipped_this_run += 1

                    append_manifest(
                        make_manifest_row(
                            page=page,
                            position=position,
                            publication_id=(
                                publication_id
                            ),
                            source=source,
                            status="skipped",
                            message=(
                                "PDF kimliği bulunamadı."
                            ),
                        )
                    )

                    save_state(
                        page,
                        len(existing_ids),
                        publication_id,
                    )
                    continue

                output_path = (
                    PDF_DIRECTORY
                    / f"{publication_id}.pdf"
                )

                status_code: int | None = None

                try:
                    download_url = get_download_url(
                        session,
                        pdf_uuid,
                    )

                    size_bytes = download_pdf(
                        session,
                        download_url,
                        output_path,
                    )

                    existing_ids.add(
                        publication_id
                    )

                    downloaded_this_run += 1
                    consecutive_failures = 0

                    size_mb = (
                        size_bytes
                        / (1024 * 1024)
                    )

                    print(
                        f"  Başarılı: "
                        f"{size_mb:.2f} MB "
                        f"→ toplam "
                        f"{len(existing_ids)}/"
                        f"{TARGET_COUNT}",
                        flush=True,
                    )

                    append_manifest(
                        make_manifest_row(
                            page=page,
                            position=position,
                            publication_id=(
                                publication_id
                            ),
                            source=source,
                            status="downloaded",
                            message=(
                                "PDF başarıyla indirildi."
                            ),
                            size_bytes=size_bytes,
                        )
                    )

                except requests.HTTPError as error:
                    failed_this_run += 1
                    consecutive_failures += 1

                    if error.response is not None:
                        status_code = (
                            error.response.status_code
                        )

                    message = (
                        f"HTTP hatası: {status_code}"
                    )

                    print(
                        f"  Hata: {message}",
                        flush=True,
                    )

                    append_manifest(
                        make_manifest_row(
                            page=page,
                            position=position,
                            publication_id=(
                                publication_id
                            ),
                            source=source,
                            status="failed",
                            message=message,
                        )
                    )

                except Exception as error:
                    failed_this_run += 1
                    consecutive_failures += 1

                    print(
                        f"  Hata: {error}",
                        flush=True,
                    )

                    append_manifest(
                        make_manifest_row(
                            page=page,
                            position=position,
                            publication_id=(
                                publication_id
                            ),
                            source=source,
                            status="failed",
                            message=str(error),
                        )
                    )

                save_state(
                    page,
                    len(existing_ids),
                    publication_id,
                )

                # Sunucu erişim engeli veya hız sınırlaması
                # verirse otomatik olarak duruyoruz.
                if status_code in {403, 429}:
                    print(
                        "Sunucu erişim/hız sınırı "
                        "bildirdi. İşlem güvenli "
                        "şekilde durduruldu.",
                        flush=True,
                    )

                    save_state(
                        page,
                        len(existing_ids),
                        publication_id,
                        status="paused_rate_limit",
                    )
                    return

                if consecutive_failures >= 10:
                    print(
                        "Arka arkaya 10 hata oluştu. "
                        "Sunucuyu zorlamamak için "
                        "işlem durduruldu.",
                        flush=True,
                    )

                    save_state(
                        page,
                        len(existing_ids),
                        publication_id,
                        status=(
                            "paused_consecutive_errors"
                        ),
                    )
                    return

                time.sleep(
                    REQUEST_DELAY_SECONDS
                )

            page += 1

            save_state(
                page,
                len(existing_ids),
            )

            if len(existing_ids) < TARGET_COUNT:
                time.sleep(
                    PAGE_DELAY_SECONDS
                )

    except KeyboardInterrupt:
        print(
            "\nKullanıcı tarafından durduruldu. "
            "İlerleme kaydedildi.",
            flush=True,
        )

        save_state(
            page,
            len(existing_ids),
            status="paused_by_user",
        )
        return

    save_state(
        page,
        len(existing_ids),
        status="completed",
    )

    print("\n" + "=" * 60, flush=True)
    print(
        "10.000 PDF hedefi tamamlandı.",
        flush=True,
    )
    print(
        f"Bu çalıştırmada indirilen: "
        f"{downloaded_this_run}",
        flush=True,
    )
    print(
        f"Bu çalıştırmada atlanan: "
        f"{skipped_this_run}",
        flush=True,
    )
    print(
        f"Bu çalıştırmada başarısız: "
        f"{failed_this_run}",
        flush=True,
    )
    print(
        f"Toplam geçerli PDF: "
        f"{len(existing_ids)}",
        flush=True,
    )
    print("=" * 60, flush=True)


if __name__ == "__main__":
    main()
