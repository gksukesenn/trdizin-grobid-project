# TR Dizin – GROBID Canlı Kaynakça Karşılaştırma

Bu branch, TR Dizin'den canlı makale ve PDF alıp PDF'yi kalıcı olarak
kaydetmeden GROBID ile işleyen ve iki kaynakça listesini bellekte karşılaştıran
live-only uygulamadır.

## Gereksinimler

- Git
- Docker Engine
- Docker Compose v2
- TR Dizin API ve Docker image registry için internet erişimi

## Kurulum ve çalıştırma

```bash
git clone <repository-url>
cd trdizin-grobid-project
cp .env.example .env
docker compose up -d --build
```

Arayüz: <http://127.0.0.1:8000>

Compose yalnız `grobid` ve `interface` servislerini başlatır. Uygulama MySQL,
yerel PDF/XML, downloader, importer veya worker gerektirmez.

## Sağlık ve canlı API kontrolleri

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail "http://127.0.0.1:8000/api/trdizin/articles/search?page=1&limit=10"
curl --fail "http://127.0.0.1:8000/api/trdizin/articles/search?q=1448395&page=1&limit=10"
curl --fail "http://127.0.0.1:8000/api/trdizin/articles/1448395"
curl --fail "http://127.0.0.1:8000/api/trdizin/articles/1448395/references"
curl --fail -H "Range: bytes=0-1023" \
  "http://127.0.0.1:8000/api/trdizin/articles/1448395/pdf" -o /tmp/trdizin-range.pdf
curl --fail -X POST \
  "http://127.0.0.1:8000/api/trdizin/articles/1448395/process-and-compare"
```

Son komut ağ ve PDF boyutuna bağlı olarak sürebilir. PDF yalnız bellekte
tutulur; repository veya `data/` altında PDF, TEI ya da comparison dosyası
oluşturulmaz.

## Arayüz akışı

1. Başlık, DOI, dergi veya publication ID ile canlı arama yapılır.
2. Makale seçilince metadata, TR Dizin kaynakçaları ve canlı PDF yüklenir.
3. GROBID işlemi otomatik başlar.
4. Karşılaştırma, ayrı eşleşmeyen sayaçları ve ham TEI gösterilir.
5. Aynı sayfa oturumunda başarılı sonuç publication ID ile cache'lenir.

## Loglar ve durdurma

```bash
docker compose ps
docker compose logs -f interface grobid
docker compose down
```

## Testler

Image oluşturulduktan sonra:

```bash
docker run --rm \
  -e PYTHONPATH=/app \
  -v "$PWD/tests:/tests:ro" \
  -v "$PWD/interface:/interface:ro" \
  trdizin-grobid-project-interface \
  python -m unittest discover -s /tests -v
```

## Ortam değişkenleri

`.env.example` güvenli varsayılanları içerir:

- `TRDIZIN_BASE_URL`
- `GROBID_URL`
- `EXTERNAL_CONNECT_TIMEOUT`
- `EXTERNAL_READ_TIMEOUT`
- `MAX_PDF_BYTES`

Gerçek `.env` dosyasını commit etmeyin.

## Debug

Çağrı zinciri ve önerilen breakpointler için [DEBUG_AKIS_REHBERI.md](DEBUG_AKIS_REHBERI.md),
sunum özeti için [SUNUM_NOTLARI.md](SUNUM_NOTLARI.md) kullanılabilir.

## Legacy archive

Downloader, importer, MySQL, worker, batch GROBID ve deployment/export araçları
`archive/full-pipeline-v1` branch'inde korunmaktadır. Live-only branch bu
araştırma pipeline'ını içermez.
