import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    trdizin_base_url: str
    grobid_base_url: str
    external_connect_timeout: float
    external_read_timeout: float
    max_pdf_bytes: int
    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str
    persistence_enabled: bool
    grobid_version: str
    algorithm_version: str


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
        mysql_host=os.getenv("MYSQL_HOST", "mysql"),
        mysql_port=int(os.getenv("MYSQL_PORT", "3306")),
        mysql_database=os.getenv("MYSQL_DATABASE", "trdizin_live"),
        mysql_user=os.getenv("MYSQL_USER", "trdizin_app"),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        persistence_enabled=os.getenv("PERSISTENCE_ENABLED", "true").lower() == "true",
        grobid_version=os.getenv("GROBID_VERSION", "0.8.0"),
        algorithm_version=os.getenv("ALGORITHM_VERSION", "live-matcher-v1"),
    )
