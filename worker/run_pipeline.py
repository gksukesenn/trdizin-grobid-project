import os
import subprocess
import sys
import time
from pathlib import Path


PDF_DIRECTORY = Path(
    os.getenv("PDF_DIRECTORY", "/data/pdfs")
)

XML_DIRECTORY = Path(
    os.getenv(
        "OUTPUT_DIRECTORY",
        "/data/grobid-output",
    )
)

BATCH_PAUSE_SECONDS = float(
    os.getenv("BATCH_PAUSE_SECONDS", "5")
)

MAX_NO_PROGRESS_ROUNDS = int(
    os.getenv("MAX_NO_PROGRESS_ROUNDS", "3")
)


def get_pdf_ids() -> set[str]:
    return {
        path.stem
        for path in PDF_DIRECTORY.glob("*.pdf")
    }


def get_xml_ids() -> set[str]:
    suffix = ".tei.xml"

    return {
        path.name.removesuffix(suffix)
        for path in XML_DIRECTORY.glob(
            f"*{suffix}"
        )
    }


def get_pending_ids() -> set[str]:
    return get_pdf_ids() - get_xml_ids()


def run_command(
    command: list[str],
    label: str,
) -> int:
    print()
    print("=" * 60, flush=True)
    print(label, flush=True)
    print("=" * 60, flush=True)

    result = subprocess.run(
        command,
        check=False,
    )

    print(
        f"{label} çıkış kodu: "
        f"{result.returncode}",
        flush=True,
    )

    return result.returncode


def import_new_xml_files() -> int:
    return run_command(
        [
            sys.executable,
            "/app/import_grobid.py",
        ],
        "Yeni TEI XML dosyaları MySQL'e aktarılıyor",
    )


def main() -> None:
    PDF_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    XML_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    no_progress_rounds = 0
    round_number = 0

    while True:
        round_number += 1

        pdf_count = len(get_pdf_ids())
        xml_count = len(get_xml_ids())
        pending_before = get_pending_ids()

        print()
        print("#" * 60, flush=True)
        print(
            f"Worker turu: {round_number}",
            flush=True,
        )
        print(
            f"Toplam PDF: {pdf_count}",
            flush=True,
        )
        print(
            f"Mevcut TEI XML: {xml_count}",
            flush=True,
        )
        print(
            "İşlenmemiş PDF: "
            f"{len(pending_before)}",
            flush=True,
        )
        print("#" * 60, flush=True)

        if not pending_before:
            import_code = import_new_xml_files()

            if import_code != 0:
                raise RuntimeError(
                    "Son MySQL aktarımı başarısız oldu."
                )

            print()
            print("=" * 60, flush=True)
            print(
                "Bütün PDF'ler GROBID ile işlendi.",
                flush=True,
            )
            print(
                "Yeni sonuçlar MySQL'e aktarıldı.",
                flush=True,
            )
            print("=" * 60, flush=True)
            return

        process_code = run_command(
            [
                sys.executable,
                "/app/process_pdfs.py",
            ],
            "Yeni PDF grubu GROBID ile işleniyor",
        )

        if process_code != 0:
            print(
                "Processor hata kodu verdi; "
                "oluşturulan geçerli XML'ler korunuyor.",
                flush=True,
            )

        import_code = import_new_xml_files()

        if import_code != 0:
            raise RuntimeError(
                "MySQL aktarımı başarısız oldu."
            )

        pending_after = get_pending_ids()
        produced_count = (
            len(pending_before)
            - len(pending_after)
        )

        print()
        print(
            "Bu turda üretilen yeni XML: "
            f"{produced_count}",
            flush=True,
        )
        print(
            "Kalan işlenmemiş PDF: "
            f"{len(pending_after)}",
            flush=True,
        )

        if produced_count > 0:
            no_progress_rounds = 0
        else:
            no_progress_rounds += 1

            print(
                "İlerleme olmayan tur: "
                f"{no_progress_rounds}/"
                f"{MAX_NO_PROGRESS_ROUNDS}",
                flush=True,
            )

        if (
            no_progress_rounds
            >= MAX_NO_PROGRESS_ROUNDS
        ):
            raise RuntimeError(
                "Arka arkaya ilerleme sağlanamadı. "
                "Sürekli hata veren PDF'leri incelemek "
                "için worker durduruldu."
            )

        time.sleep(BATCH_PAUSE_SECONDS)


if __name__ == "__main__":
    main()
