import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    trdizin_base_url: str
    grobid_base_url: str
    external_connect_timeout: float
    external_read_timeout: float
    max_pdf_bytes: int


def load_settings() -> Settings:
    return Settings(
        trdizin_base_url=os.getenv(
            "TRDIZIN_BASE_URL",
            "https://search.trdizin.gov.tr",
        ).rstrip("/"),
        grobid_base_url=os.getenv(
            "GROBID_URL",
            "http://grobid:8070",
        ).rstrip("/"),
        external_connect_timeout=float(
            os.getenv("EXTERNAL_CONNECT_TIMEOUT", "10")
        ),
        external_read_timeout=float(
            os.getenv("EXTERNAL_READ_TIMEOUT", "120")
        ),
        max_pdf_bytes=int(
            os.getenv("MAX_PDF_BYTES", str(50 * 1024 * 1024))
        ),
    )
