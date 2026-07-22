# TR Dizin – GROBID Canlı Kaynakça Karşılaştırma

Uygulama TR Dizin'den canlı metadata, kaynakça ve PDF alır; PDF'yi diske
yazmadan GROBID ile işler ve iki kaynakça listesini bellekte karşılaştırır.
TR Dizin asıl veri kaynağıdır. MySQL yalnız işlem geçmişi, uyumlu sonuç cache'i,
ground-truth annotation ve deney metrikleri için kullanılır.

## Başlatma

Gereksinimler: Git, Docker Engine, Docker Compose v2 ve internet erişimi.

```bash
git clone <repository-url>
cd trdizin-grobid-project
cp .env.example .env
docker compose up -d --build
```

Arayüz: <http://127.0.0.1:8000>

Compose `mysql`, `migrate`, `grobid` ve `interface` servislerini yönetir.
`migrate` şemayı uygulayıp başarıyla çıkar; uzun süre çalışan servis değildir.
MySQL verisi `mysql_data` named volume'unda tutulur. PDF veya TEI volume'a ya
da repository'ye yazılmaz.

## Sağlık ve canlı akış

```bash
curl --fail http://127.0.0.1:8000/api/health
curl --fail "http://127.0.0.1:8000/api/trdizin/articles/search?q=1448395&page=1&limit=10"
curl --fail -X POST "http://127.0.0.1:8000/api/trdizin/articles/1448395/process-and-compare"
```

İlk uyumlu işlem cache miss olur, TR Dizin PDF'si GROBID'e gönderilir ve sonuç
tek transaction içinde saklanır. Aynı publication ID, GROBID sürümü, matcher
sürümü ve önemli GROBID parametreleriyle sonraki çağrı `cache_hit=true` döner.

Manuel “Yeniden işle” butonu ve aşağıdaki çağrı cache'i atlar, eski run'ı
silmeden yeni run oluşturur:

```bash
curl --fail -X POST \
  "http://127.0.0.1:8000/api/trdizin/articles/1448395/process-and-compare?force=true"
```

`processing` içinde `cache_hit`, `processing_run_id`, `grobid_version`,
`algorithm_version` ve `persisted` alanları bulunur. MySQL geçici olarak
ulaşılamazsa ana canlı işlem devam eder, `persisted=false` döner ve health
`degraded` olur.

## Geçmiş API'si

```text
GET /api/history/articles
GET /api/history/articles/{publication_id}/runs
GET /api/history/runs/{run_id}
GET /api/history/runs/{run_id}/comparison
```

## Ground-truth API'si

```text
GET  /api/ground-truth/articles/{publication_id}
POST /api/ground-truth/articles/{publication_id}/annotations
PUT  /api/ground-truth/annotations/{annotation_id}
```

Düzeltmeler eski GROBID/reference/match satırlarını değiştirmez; annotator ve
timestamp bilgili ayrı annotation olarak saklanır.

## Deney ve metrik API'si

```text
POST /api/experiments
GET  /api/experiments
GET  /api/experiments/{experiment_id}
POST /api/experiments/{experiment_id}/metrics
```

`precision`, `recall` ve `f1` değerleri `experiment_metrics` içinde saklanabilir.
Bu sürüm metrikleri otomatik hesaplamaz.

## Migration

SQL dosyaları `database/migrations/` altındadır. `schema_migrations`, version,
isim, SHA-256 checksum ve uygulanma zamanını tutar. Uygulanmış migration atlanır;
aynı version'ın içeriği değiştirilirse runner hata verir.

```bash
docker compose run --rm migrate
```

Migration'lar additive olmalıdır; mevcut migration dosyalarını değiştirmeyin ve
destructive `DROP TABLE/DROP COLUMN` kullanmayın.

## Backup ve restore

Backup:

```bash
docker compose exec -T mysql sh -c \
  'mysqldump -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  > trdizin-live.sql
```

Restore işlemi hedef veritabanındaki mevcut verilerle birleşir; önce doğru
ortamı ve backup'ı doğrulayın:

```bash
docker compose exec -T mysql sh -c \
  'mysql -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" "$MYSQL_DATABASE"' \
  < trdizin-live.sql
```

`docker compose down` named volume'u silmez. `down -v` kalıcı veriyi sileceği
için normal kullanımda çalıştırılmamalıdır.

## Test ve loglar

```bash
docker compose logs -f mysql migrate grobid interface
docker run --rm -e PYTHONPATH=/app \
  -v "$PWD/tests:/tests:ro" -v "$PWD/interface:/interface:ro" \
  trdizin-grobid-project-interface python -m unittest discover -s /tests -v
```

MySQL integration testi yalnız disposable test database'inde
`RUN_MYSQL_INTEGRATION=1` ile çalıştırılmalıdır; kullanıcı volume'u test hedefi
olarak kullanılmamalıdır.

## Legacy archive

Eski downloader/importer/worker/batch araştırma sistemi
`archive/full-pipeline-v1` branch'inde korunmaktadır ve bu uygulamanın parçası
değildir.
