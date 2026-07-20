import json
import os
import sys
from pathlib import Path

import requests


API_URL = "https://search.trdizin.gov.tr/api/defaultSearch/publication/"

METADATA_DIRECTORY = Path(
    os.getenv("METADATA_DIRECTORY", "/data/metadata")
)

DOWNLOAD_LIMIT = int(
    os.getenv("DOWNLOAD_LIMIT", "5")
)

PARAMS = {
    "q": "",
    "order": "publicationYear-DESC",
    "page": 1,
    "limit": DOWNLOAD_LIMIT,
    "facet-documentType": "PAPER",
    "facet-accessType": "OPEN",
}

HEADERS = {
    "Accept": "application/json",
    "User-Agent": "TRDizin-Grobid-Research/0.1",
}


def main() -> None:
    print("TR Dizin API testi başlatılıyor...")
    print(f"İstenen kayıt sayısı: {DOWNLOAD_LIMIT}")

    METADATA_DIRECTORY.mkdir(
        parents=True,
        exist_ok=True,
    )

    try:
        response = requests.get(
            API_URL,
            params=PARAMS,
            headers=HEADERS,
            timeout=60,
        )
    except requests.RequestException as error:
        print("TR Dizin bağlantısı kurulamadı.")
        print(f"Hata: {error}")
        sys.exit(1)

    print(f"HTTP durum kodu: {response.status_code}")
    print(f"İstek adresi: {response.url}")
    print(
        "İçerik türü: "
        f"{response.headers.get('Content-Type', 'bilinmiyor')}"
    )

    raw_output = METADATA_DIRECTORY / "trdizin_ham_yanit.txt"

    raw_output.write_text(
        response.text,
        encoding="utf-8",
    )

    if not response.ok:
        print("API başarılı yanıt vermedi.")
        print(f"Ham yanıt kaydedildi: {raw_output}")
        print(response.text[:1000])
        sys.exit(1)

    try:
        data = response.json()
    except ValueError:
        print("Sunucunun cevabı JSON biçiminde değil.")
        print(f"Ham yanıt kaydedildi: {raw_output}")
        sys.exit(1)

    json_output = METADATA_DIRECTORY / "trdizin_ornek.json"

    json_output.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("JSON başarıyla alındı.")
    print(f"JSON dosyası: {json_output}")

    if isinstance(data, dict):
        print("JSON içerisindeki ana alanlar:")

        for key in data.keys():
            print(f"  - {key}")

    elif isinstance(data, list):
        print(f"JSON liste uzunluğu: {len(data)}")

    print("\nİlk 2000 karakter:")
    print(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        )[:2000]
    )


if __name__ == "__main__":
    main()
