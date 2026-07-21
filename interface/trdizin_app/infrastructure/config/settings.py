import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_backend: str

    mysql_host: str
    mysql_port: int
    mysql_database: str
    mysql_user: str
    mysql_password: str

    sqlite_path: Path

    pdf_directory: Path
    xml_directory: Path
    metadata_directory: Path
    template_directory: Path

    trdizin_base_url: str


def load_settings() -> Settings:
    database_backend = os.getenv(
        "DATABASE_BACKEND",
        "mysql",
    ).strip().lower()

    if database_backend not in {"mysql", "sqlite"}:
        raise ValueError(
            "DATABASE_BACKEND yalnızca "
            "'mysql' veya 'sqlite' olabilir."
        )

    return Settings(
        database_backend=database_backend,

        mysql_host=os.getenv(
            "MYSQL_HOST",
            "mysql",
        ),
        mysql_port=int(
            os.getenv("MYSQL_PORT", "3306")
        ),
        mysql_database=os.getenv(
            "MYSQL_DATABASE",
            "trdizin_grobid",
        ),
        mysql_user=os.getenv(
            "MYSQL_USER",
            "trdizin_app",
        ),
        mysql_password=os.getenv(
            "MYSQL_PASSWORD",
            "",
        ),

        sqlite_path=Path(
            os.getenv(
                "SQLITE_PATH",
                "/app/data/trdizin-demo.sqlite",
            )
        ),

        pdf_directory=Path(
            os.getenv(
                "PDF_DIRECTORY",
                "/data/pdfs",
            )
        ),
        xml_directory=Path(
            os.getenv(
                "XML_DIRECTORY",
                "/data/grobid-output",
            )
        ),
        metadata_directory=Path(
            os.getenv(
                "METADATA_DIRECTORY",
                "/data/metadata",
            )
        ),
        template_directory=Path(
            os.getenv(
                "TEMPLATE_DIRECTORY",
                "/app/templates",
            )
        ),

        trdizin_base_url=os.getenv(
            "TRDIZIN_BASE_URL",
            "https://search.trdizin.gov.tr",
        ).rstrip("/"),
    )
