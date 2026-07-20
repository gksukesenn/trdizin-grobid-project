import csv
import os
import time
from collections import Counter
from pathlib import Path

import requests


GROBID_URL = os.getenv(
    "GROBID_URL",
    "http://grobid:8070",
).rstrip("/")

PDF_DIRECTORY = Path(
    os.getenv("PDF_DIRECTORY", "/data/pdfs")
)

OUTPUT_DIRECTORY = Path(
    os.getenv(
        "OUTPUT_DIRECTORY",
        "/data/grobid-output",
    )
)

LOG_DIRECTORY = Path(
    os.getenv("LOG_DIRECTORY", "/data/logs")
)

INPUT_REPORT = LOG_DIRECTORY / "failed_grobid_final.csv"

OUTPUT_REPORT = (
    LOG_DIRECTORY
    / "failed_grobid_classification.csv"
)

REQUEST_DELAY_SECONDS = float(
    os.getenv("REQUEST_DELAY_SECONDS", "0.5")
)

OUTPUT_FIELDS = [
    "publication_id",
    "pdf_filename",
    "pdf_size_bytes",
    "http_status",
    "content_type",
    "response_size_bytes",
    "category",
    "message",
    "xml_filename",
]


def wait_for_grobid(
    session: requests.Session,
    attempts: int = 30,
) -> None:
    print("GROBID servisinin hazır olması bekleniyor...")

    for attempt in range(1, attempts + 1):
        try:
            response = session.get(
                f"{GROBID_URL}/api/isalive",
                timeout=10,
            )

            if (
                response.ok
                and response.text.strip().lower() == "true"
            ):
                print("GROBID hazır.")
                return

        except requests.RequestException:
            pass

        print(
            f"GROBID henüz hazır değil: "
            f"{attempt}/{attempts}"
        )

        time.sleep(2)

    raise RuntimeError(
        "GROBID servisine bağlanılamadı."
    )


def read_publication_ids() -> list[str]:
    if not INPUT_REPORT.exists():
        raise RuntimeError(
            f"Girdi raporu bulunamadı: {INPUT_REPORT}"
        )

    publication_ids: list[str] = []

    with INPUT_REPORT.open(
        encoding="utf-8",
        newline="",
    ) as csv_file:
        for row in csv.DictReader(csv_file):
            publication_id = (
                row.get("publication_id", "").strip()
            )

            if (
                publication_id.isdigit()
                and publication_id
                not in publication_ids
            ):
                publication_ids.append(
                    publication_id
                )

    return publication_ids


def is_valid_tei(content: bytes) -> bool:
    normalized = content.lstrip()

    return (
        normalized.startswith(b"<TEI")
        or normalized.startswith(b"<?xml")
    )


def save_xml(
    publication_id: str,
    content: bytes,
) -> Path:
    output_path = (
        OUTPUT_DIRECTORY
        / f"{publication_id}.tei.xml"
    )

    temporary_path = Path(
        f"{output_path}.part"
    )

    try:
        temporary_path.write_bytes(content)
        temporary_path.replace(output_path)

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise

    return output_path


def classify_response(
    publication_id: str,
    response: requests.Response,
) -> tuple[str, str, str]:
    response_text = response.content.decode(
        "utf-8",
        errors="replace",
    ).strip()

    if (
        response.status_code == 200
        and is_valid_tei(response.content)
    ):
        output_path = save_xml(
            publication_id,
            response.content,
        )

        reference_count = response.content.count(
            b"<biblStruct"
        )

        return (
            "recovered",
            (
                "Yeniden denemede geçerli TEI XML "
                f"oluşturuldu. Kaynakça: "
                f"{reference_count}"
            ),
            output_path.name,
        )

    if response.status_code == 204:
        return (
            "no_content",
            (
                "GROBID 204 No Content döndürdü. "
                "Kaynakça veya okunabilir metin "
                "tespit edilemedi."
            ),
            "",
        )

    if (
        response.status_code == 500
        and "[NO_BLOCKS]" in response_text
    ):
        return (
            "ocr_required",
            response_text,
            "",
        )

    if (
        response.status_code == 200
        and not response.content
    ):
        return (
            "no_content",
            "GROBID boş cevap döndürdü.",
            "",
        )

    preview = response_text[:500]

    return (
        "http_error",
        (
            f"HTTP {response.status_code}: "
            f"{preview or 'Cevap gövdesi boş'}"
        ),
        "",
    )


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    LOG_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    publication_ids = read_publication_ids()

    print(
        "Sınıflandırılacak PDF sayısı: "
        f"{len(publication_ids)}"
    )

    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": (
                "TRDizin-Grobid-Research/1.0"
            )
        }
    )

    wait_for_grobid(session)

    output_rows: list[dict[str, object]] = []

    for index, publication_id in enumerate(
        publication_ids,
        start=1,
    ):
        pdf_path = (
            PDF_DIRECTORY
            / f"{publication_id}.pdf"
        )

        print()
        print(
            f"[{index}/{len(publication_ids)}] "
            f"{pdf_path.name}"
        )

        row: dict[str, object] = {
            "publication_id": publication_id,
            "pdf_filename": pdf_path.name,
            "pdf_size_bytes": (
                pdf_path.stat().st_size
                if pdf_path.exists()
                else ""
            ),
            "http_status": "",
            "content_type": "",
            "response_size_bytes": "",
            "category": "",
            "message": "",
            "xml_filename": "",
        }

        if not pdf_path.exists():
            row["category"] = "missing_pdf"
            row["message"] = "PDF dosyası bulunamadı."
            output_rows.append(row)

            print("  PDF bulunamadı.")
            continue

        try:
            with pdf_path.open("rb") as pdf_file:
                response = session.post(
                    (
                        f"{GROBID_URL}"
                        "/api/processReferences"
                    ),
                    files={
                        "input": (
                            pdf_path.name,
                            pdf_file,
                            "application/pdf",
                        )
                    },
                    data={
                        "includeRawCitations": "1",
                    },
                    timeout=(20, 300),
                )

            (
                category,
                message,
                xml_filename,
            ) = classify_response(
                publication_id,
                response,
            )

            row["http_status"] = (
                response.status_code
            )
            row["content_type"] = (
                response.headers.get(
                    "Content-Type",
                    "",
                )
            )
            row["response_size_bytes"] = len(
                response.content
            )
            row["category"] = category
            row["message"] = message
            row["xml_filename"] = xml_filename

            print(
                f"  HTTP: {response.status_code}"
            )
            print(f"  Kategori: {category}")
            print(f"  Sonuç: {message}")

        except requests.RequestException as error:
            row["category"] = "request_error"
            row["message"] = str(error)

            print(f"  İstek hatası: {error}")

        except Exception as error:
            row["category"] = "unexpected_error"
            row["message"] = str(error)

            print(f"  Beklenmeyen hata: {error}")

        output_rows.append(row)

        if index < len(publication_ids):
            time.sleep(
                REQUEST_DELAY_SECONDS
            )

    with OUTPUT_REPORT.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=OUTPUT_FIELDS,
        )

        writer.writeheader()
        writer.writerows(output_rows)

    category_counts = Counter(
        str(row["category"])
        for row in output_rows
    )

    print()
    print("=" * 60)
    print("Başarısız PDF sınıflandırması tamamlandı.")

    for category, count in sorted(
        category_counts.items()
    ):
        print(f"{category}: {count}")

    print(f"Rapor: {OUTPUT_REPORT}")
    print("=" * 60)


if __name__ == "__main__":
    main()
