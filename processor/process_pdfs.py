import csv
import os
import time
from datetime import datetime, timezone
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
    os.getenv("OUTPUT_DIRECTORY", "/data/grobid-output")
)

LOG_DIRECTORY = Path(
    os.getenv("LOG_DIRECTORY", "/data/logs")
)

PROCESS_LIMIT = int(
    os.getenv("PROCESS_LIMIT", "2")
)

MANIFEST_PATH = LOG_DIRECTORY / "grobid_manifest.csv"


def create_session() -> requests.Session:
    session = requests.Session()

    session.headers.update(
        {
            "User-Agent": "TRDizin-Grobid-Research/0.1",
        }
    )

    return session


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


def pdf_sort_key(pdf_path: Path) -> int:
    try:
        return int(pdf_path.stem)
    except ValueError:
        return -1


def get_pdf_files() -> list[Path]:
    all_pdf_files = sorted(
        PDF_DIRECTORY.glob("*.pdf"),
        key=pdf_sort_key,
        reverse=True,
    )

    pending_pdf_files: list[Path] = []

    for pdf_path in all_pdf_files:
        output_path = (
            OUTPUT_DIRECTORY
            / f"{pdf_path.stem}.tei.xml"
        )

        # Geçerli ve dolu XML zaten varsa bu PDF tamamlanmıştır.
        if (
            output_path.exists()
            and output_path.stat().st_size > 0
        ):
            continue

        pending_pdf_files.append(pdf_path)

    print(
        f"Toplam PDF dosyası: {len(all_pdf_files)}"
    )

    print(
        "Henüz XML'i olmayan PDF: "
        f"{len(pending_pdf_files)}"
    )

    return pending_pdf_files[:PROCESS_LIMIT]


def process_pdf(
    session: requests.Session,
    pdf_path: Path,
    output_path: Path,
) -> tuple[int, int]:
    temporary_path = Path(
        f"{output_path}.part"
    )

    try:
        with pdf_path.open("rb") as pdf_file:
            response = session.post(
                f"{GROBID_URL}/api/processReferences",
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
                timeout=(15, 300),
            )

        response.raise_for_status()

        xml_content = response.content
        normalized_content = xml_content.lstrip()

        if not (
            normalized_content.startswith(b"<TEI")
            or normalized_content.startswith(b"<?xml")
        ):
            raise RuntimeError(
                "GROBID geçerli bir TEI XML döndürmedi."
            )

        temporary_path.write_bytes(xml_content)
        temporary_path.replace(output_path)

        reference_count = xml_content.count(
            b"<biblStruct"
        )

        return output_path.stat().st_size, reference_count

    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise


def write_manifest(
    rows: list[dict[str, object]],
) -> None:
    fieldnames = [
        "publication_id",
        "pdf_filename",
        "xml_filename",
        "status",
        "reference_count",
        "xml_size_bytes",
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
    PDF_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

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

    pdf_files = get_pdf_files()

    print(f"İşlenecek PDF sayısı: {len(pdf_files)}")

    if not pdf_files:
        print("İşlenecek PDF bulunamadı.")
        return

    manifest_rows: list[dict[str, object]] = []

    processed_count = 0
    skipped_count = 0
    failed_count = 0

    for index, pdf_path in enumerate(
        pdf_files,
        start=1,
    ):
        publication_id = pdf_path.stem
        output_path = (
            OUTPUT_DIRECTORY
            / f"{publication_id}.tei.xml"
        )

        print()
        print(
            f"[{index}/{len(pdf_files)}] "
            f"{pdf_path.name}"
        )

        status = ""
        message = ""
        reference_count = 0
        xml_size_bytes = 0

        try:
            if (
                output_path.exists()
                and output_path.stat().st_size > 0
            ):
                existing_content = output_path.read_bytes()

                reference_count = existing_content.count(
                    b"<biblStruct"
                )

                xml_size_bytes = output_path.stat().st_size
                status = "skipped"
                message = "TEI XML daha önce oluşturulmuş."
                skipped_count += 1

                print(
                    "Atlandı: XML zaten mevcut. "
                    f"Kaynakça: {reference_count}"
                )

            else:
                if output_path.exists():
                    output_path.unlink()

                (
                    xml_size_bytes,
                    reference_count,
                ) = process_pdf(
                    session,
                    pdf_path,
                    output_path,
                )

                status = "processed"
                message = "TEI XML başarıyla oluşturuldu."
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

        manifest_rows.append(
            {
                "publication_id": publication_id,
                "pdf_filename": pdf_path.name,
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
    print("=" * 50)
    print("GROBID işlemi tamamlandı.")
    print(f"Yeni işlenen: {processed_count}")
    print(f"Atlanan: {skipped_count}")
    print(f"Başarısız: {failed_count}")
    print(f"İşlem kaydı: {MANIFEST_PATH}")


if __name__ == "__main__":
    main()
