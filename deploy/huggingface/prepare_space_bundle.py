import os
import shutil
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
INTERFACE_DIRECTORY = PROJECT_ROOT / "interface"

DEPLOY_DIRECTORY = (
    PROJECT_ROOT / "deploy" / "huggingface"
)

SOURCE_DATABASE = (
    DEPLOY_DIRECTORY
    / "data"
    / "trdizin-demo.sqlite"
)

BUNDLE_DIRECTORY = (
    DEPLOY_DIRECTORY / "bundle"
)

BUNDLE_DATABASE = (
    BUNDLE_DIRECTORY
    / "data"
    / "trdizin-demo.sqlite"
)


DOCKERFILE_CONTENT = """\
FROM python:3.12-slim

RUN useradd -m -u 1000 user

USER user

ENV HOME=/home/user \\
    PATH=/home/user/.local/bin:$PATH \\
    PYTHONUNBUFFERED=1 \\
    DATABASE_BACKEND=sqlite \\
    SQLITE_PATH=/home/user/app/data/trdizin-demo.sqlite \\
    TEMPLATE_DIRECTORY=/home/user/app/templates \\
    PDF_DIRECTORY=/data/pdfs \\
    XML_DIRECTORY=/data/grobid-output

WORKDIR /home/user/app

COPY --chown=user:user requirements.txt ./requirements.txt

RUN pip install --no-cache-dir \\
    --upgrade pip \\
    && pip install --no-cache-dir \\
    -r requirements.txt

COPY --chown=user:user app.py ./app.py
COPY --chown=user:user trdizin_app ./trdizin_app
COPY --chown=user:user templates ./templates
COPY --chown=user:user data ./data

EXPOSE 7860

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "7860"]
"""


README_CONTENT = """\
---
title: TR Dizin GROBID Karşılaştırma
emoji: 📚
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# TR Dizin – GROBID Kaynakça Karşılaştırma Sistemi

Bu Space, TR Dizin yayınları ile GROBID tarafından çıkarılan
kaynakçaların karşılaştırma sonuçlarını salt okunur olarak sunar.

## Canlı sürüm özellikleri

- Makale kimliği, başlık ve DOI ile arama
- TR Dizin ve GROBID kaynakçalarını görüntüleme
- Kesin DOI ve metin benzerliği eşleşmelerini inceleme
- Birleşik ve kısmi kaynakça sınıflandırmalarını görüntüleme
- Eşleşmeyen kaynakçaları inceleme
- PDF dosyalarını TR Dizin üzerinden anlık görüntüleme
- Ham TR Dizin JSON ve GROBID TEI XML çıktılarını görüntüleme

Canlı inceleme sürümü FastAPI ve salt okunur SQLite kullanır.
Yeni PDF yükleme veya canlı GROBID işleme gerçekleştirmez.
Tam veri işleme sistemi GitHub deposundaki Docker Compose
mimarisiyle çalışır.
"""


def copy_directory(
    source: Path,
    destination: Path,
) -> None:
    if destination.exists():
        shutil.rmtree(destination)

    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns(
            "__pycache__",
            "*.pyc",
            "*.before-*",
            "*.backup",
            "*.bak",
        ),
    )


def link_or_copy_database() -> str:
    if not SOURCE_DATABASE.exists():
        raise FileNotFoundError(
            "SQLite veritabanı bulunamadı: "
            f"{SOURCE_DATABASE}"
        )

    BUNDLE_DATABASE.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    BUNDLE_DATABASE.unlink(
        missing_ok=True
    )

    try:
        os.link(
            SOURCE_DATABASE,
            BUNDLE_DATABASE,
        )
        return "hard link"

    except OSError:
        shutil.copy2(
            SOURCE_DATABASE,
            BUNDLE_DATABASE,
        )
        return "dosya kopyası"


def main() -> None:
    if BUNDLE_DIRECTORY.exists():
        shutil.rmtree(BUNDLE_DIRECTORY)

    BUNDLE_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(
        INTERFACE_DIRECTORY / "app.py",
        BUNDLE_DIRECTORY / "app.py",
    )

    shutil.copy2(
        INTERFACE_DIRECTORY / "requirements.txt",
        BUNDLE_DIRECTORY / "requirements.txt",
    )

    copy_directory(
        INTERFACE_DIRECTORY / "trdizin_app",
        BUNDLE_DIRECTORY / "trdizin_app",
    )

    copy_directory(
        INTERFACE_DIRECTORY / "templates",
        BUNDLE_DIRECTORY / "templates",
    )

    (
        BUNDLE_DIRECTORY / "Dockerfile"
    ).write_text(
        DOCKERFILE_CONTENT,
        encoding="utf-8",
    )

    (
        BUNDLE_DIRECTORY / "README.md"
    ).write_text(
        README_CONTENT,
        encoding="utf-8",
    )

    database_method = link_or_copy_database()

    database_size_mb = (
        BUNDLE_DATABASE.stat().st_size
        / 1024
        / 1024
    )

    print()
    print("=" * 70)
    print("Hugging Face Space paketi hazırlandı.")
    print(f"Paket: {BUNDLE_DIRECTORY}")
    print(
        "SQLite ekleme yöntemi: "
        f"{database_method}"
    )
    print(
        "SQLite boyutu: "
        f"{database_size_mb:.2f} MB"
    )
    print("=" * 70)


if __name__ == "__main__":
    main()
