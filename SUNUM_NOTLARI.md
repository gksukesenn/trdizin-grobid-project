# Sunum Notları

## Amaç

Uygulama, TR Dizin'in kayıtlı kaynakçalarıyla aynı makalenin PDF'sinden GROBID
tarafından çıkarılan kaynakçaları canlı olarak karşılaştırır.

## Mimari tercih

Tek FastAPI uygulaması içinde küçük bir modüler monolit kullanılır:

- Route: HTTP doğrulama ve response
- Use case: iş akışı
- Port: dış servis sözleşmesi
- Adapter: TR Dizin ve GROBID HTTP ayrıntıları
- Domain/application service: modeller, mapping ve saf matching

Bu kapsam için Kafka, Celery, MySQL veya ayrı mikroservisler gerekli değildir.

## PDF neden kaydedilmiyor?

TR Dizin metadata içindeki PDF UUID ile `getFile` URL'si çözülür. Browser PDF
endpointi uzak cevabı stream eder; karşılaştırma use case'i PDF bytes'ı doğrudan
GROBID'e yollar. `data/pdfs`, yerel TEI veya JSON dosyası oluşturulmaz. Böylece
temiz klon kişisel arşivlerden bağımsız çalışır.

## Docker'ın rolü

Compose yalnız iki servis içerir:

- `grobid`: kaynakça extraction servisi
- `interface`: FastAPI backend ve HTML/JavaScript frontend

Interface, GROBID `/api/isalive` healthcheck'i başarılı olmadan başlatılmaz.

## Demo

```bash
cp .env.example .env
docker compose up -d --build
curl --fail http://127.0.0.1:8000/api/health
```

Arayüzde `1448395` aranır. Beklenen akış: makale ve PDF açılır, TR Dizin
kaynakçaları görünür, GROBID otomatik çalışır ve comparison sekmesine geçilir.
Son doğrulanmış örnekte 39 TR Dizin, 40 GROBID ve 39 eşleşme görülmüştür; canlı
API sonucu zamanla değişebilir.

## Debug sırasında izlenecek değerler

- `publication_id`, `pdf_uuid`, `pdf_url`
- `len(pdf_content)`
- `len(trdizin_references)`, `len(extraction.references)`
- `matched_count`, `unmatched_trdizin_count`, `unmatched_grobid_count`
- Frontend `selectionToken`, `articleSessions[publicationId].isProcessing`

## Legacy archive

Eski downloader, importer, MySQL, worker ve batch araştırma pipeline'ı
`archive/full-pipeline-v1` branch'inde korunmaktadır.
