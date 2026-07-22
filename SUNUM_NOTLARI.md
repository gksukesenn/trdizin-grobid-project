# Sunum Notları

## Projenin amacı

TR Dizin'deki bir makalenin kaynakçasını GROBID ile otomatik çıkarmak ve yapılandırılmış JSON/ham TEI olarak göstermek. Araştırma amaçlı eski toplu indirme, içe aktarma ve eşleştirme hattı korunur; sunumun ana yolu bu önceden üretilmiş verilere bağlı değildir.

## Neden local PDF bağımlılığı kaldırıldı?

Yerel PDF klasörü geliştiricinin makinesine ait gizli bir önkoşuldu ve temiz GitHub klonunda ekranın boş kalmasına yol açıyordu. Yeni akış PDF UUID'yi canlı metadata'dan alır, `getFile` ile URL'yi çözer ve içeriği yalnızca bellekte tutar. Bu yaklaşım yeniden üretilebilirliği artırır, disk artıklarını ve telifli PDF'lerin yanlışlıkla commit edilmesi riskini azaltır.

## Mimari karar

Modüler monolit seçildi: tek FastAPI uygulaması içinde route, use case, port ve adapter sınırları var. Sunum ölçeğinde ayrı servis/kuyruk/framework operasyon maliyeti gereksizdir; GROBID ve MySQL zaten Docker servisleridir.

- Route HTTP giriş/çıkışını yönetir; dış URL veya SQL bilmez.
- Use case iş sırasını yönetir; HTTP endpoint ayrıntısını bilmez.
- Port uygulamanın ihtiyaç duyduğu küçük sözleşmedir.
- Adapter portu gerçek TR Dizin/GROBID HTTP çağrılarıyla uygular; timeout, retry, response doğrulama burada kalır.

## Docker ve servis iletişimi

Compose MySQL'i geçmiş ekranlar, GROBID'i kaynakça çıkarma, interface'i HTTP/UI için başlatır. Interface dış dünyada `search.trdizin.gov.tr` ile HTTPS üzerinden; Compose ağında `http://grobid:8070` ile konuşur. MySQL'in boş olması canlı arama/process use case'ini etkilemez.

## PDF yaşam döngüsü

`TrDizinHttpClient.fetch_pdf()` stream parçalarını boyut kontrollü bir `bytearray` içinde toplar ve `bytes` döndürür. `GrobidHttpClient` bunu `BytesIO` ile multipart gönderir. `open`, `NamedTemporaryFile`, `data/pdfs` veya çıktı XML yazımı yoktur; request bittikten sonra nesneler serbest kalır.

## Temiz klon demosu

```bash
cp .env.example .env
docker compose up -d --build mysql grobid interface
curl --fail "http://localhost:8000/api/trdizin/articles/search?page=1&limit=10"
curl --fail -X POST "http://localhost:8000/api/trdizin/articles/1448395/process-and-compare"
```

Doğrulanmış örnek `1448395` PDF içerir. 22 Temmuz 2026 canlı karşılaştırmasında 39 TR Dizin ve 40 GROBID kaynakçasından 39 eşleşme bulundu; `data/pdfs` ile `data/grobid-output` dosya sayıları değişmedi.

## Debug anlatımı

Breakpoint sırası:

1. `routes/trdizin.py:search_articles` veya `process_article`
2. ilgili use case'in `execute()` metodu
3. `TrDizinHttpClient.get_article/resolve_pdf_url/fetch_pdf`
4. `GrobidHttpClient.extract_references`
5. `GrobidHttpClient._parse_references`

Beklenen değişkenler: pozitif `publication_id`, dolu `pdf_uuid`, HTTPS `pdf_url`, `%PDF-` ile başlayan `pdf_content`, 200 GROBID cevabı, `<TEI` içeren XML, liste türünde `references` ve pozitif `duration_ms`.

Muhtemel hata noktaları: TR Dizin DNS/ağ gecikmesi, publication'ın PDF'siz olması, imzacı URL'nin süresinin dolması, 50 MB PDF sınırı, GROBID'in henüz hazır olmaması, taranmış/OCR gerektiren PDF veya geçersiz TEI. HTTP cevabındaki Türkçe `detail` mesajı kullanıcıya gösterilir; log için `docker compose logs -f interface grobid` kullanılır.
