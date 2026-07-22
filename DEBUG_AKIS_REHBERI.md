# Debug Akış Rehberi

Bu rehber yalnızca çalışan canlı sunum akışını anlatır. Uygulama bileşenleri `interface/app.py` içinde oluşturulan router üzerinden bağlanır.

## Akış 1 — TR Dizin araması

1. Tarayıcı: `interface/templates/index.html`, `loadArticles()`; `/api/trdizin/articles/search` çağrısını yapar.
2. Route: `interface/trdizin_app/presentation/api/routes/trdizin.py`, `search_articles()`; query/page/limit doğrular ve use case'i çağırır.
3. Use case: `application/use_cases/search_trdizin_articles.py`, `SearchTrDizinArticlesUseCase.execute()`.
4. Port: `application/ports/trdizin_gateway.py`, `TrDizinGateway.search_articles()` sözleşmesi.
5. Adapter: `infrastructure/external/trdizin_http_client.py`, `TrDizinHttpClient.search_articles()`; `api/defaultSearch/publication/` çağrısını yapar.
6. Mapper: aynı dosyadaki `_article_from_record()`; gerçek `_source.id`, `orderTitle`, `publicationYear`, `journal.name`, `pdf` alanlarını `Article` modeline çevirir.
7. Response: route `SearchResponse` biçimini üretir; `renderArticles()` arayüz listesini çizer.

Önerilen breakpointler: route `search_articles`, use case `execute`, adapter `search_articles`, mapper `_article_from_record`. İzlenecek değerler: `q`, `page`, `limit`, `records`, `total_value`, `article.pdf_uuid`.

## Akış 2 — Makaleyi GROBID'e gönderme

1. Tarayıcı: `interface/templates/index.html`, `processSelectedArticle()`; POST process çağrısını yapar.
2. Route: `presentation/api/routes/trdizin.py`, `process_article()`.
3. Use case: `application/use_cases/process_trdizin_article.py`, `ProcessTrDizinArticleUseCase.execute()`.
4. TR Dizin detail: `TrDizinHttpClient.get_article()` gerçek `api/publicationById/{id}` endpointini çağırır.
5. PDF: `resolve_pdf_url()` `api/getFile/{uuid}` ile gerçek URL'yi çözer; `fetch_pdf()` boyut sınırı içinde `bytes` üretir. Fiziksel dosya açılmaz.
6. GROBID: `infrastructure/external/grobid_http_client.py`, `GrobidHttpClient.extract_references()`; bytes'ı multipart `input` olarak `/api/processReferences` endpointine gönderir.
7. TEI parser: aynı dosyadaki `_parse_references()`; `listBibl/biblStruct` öğelerini JSON alanlarına dönüştürür.
8. JSON response: use case süre ve kaynakça sayısını ekler; route `ProcessResponse` döndürür; frontend `renderReferences()` veya `renderRawContent()` ile gösterir.

Canlı karşılaştırmada route `process_and_compare()`, `ProcessAndCompareTrDizinArticleUseCase.execute()` ve `application/services/reference_matcher.py:compare_references()` sırasıyla çalışır. Önce normalize DOI eşleşmeleri, ardından legacy 82/3 karşılıklı-en-iyi metin eşleştirmesi uygulanır. Frontend `renderLiveComparison()` sonucu yan yana gösterir.

PDF paneli ayrıca `stream_pdf()` route'u → `StreamTrDizinPdfUseCase.execute()` → `TrDizinHttpClient.open_pdf_stream()` akışını kullanır. `Range` upstream'e iletilir; 200/206 ve güvenli response header'ları korunur, stream kapanırken upstream bağlantı kapatılır.

Önerilen breakpointler: `ProcessTrDizinArticleUseCase.execute`, `get_article`, `resolve_pdf_url`, `fetch_pdf`, `extract_references`, `_parse_references`, route `process_article`. İzlenecek değerler: `article.pdf_uuid`, `pdf_url`, `len(pdf_content)`, `response.status_code`, `len(tei_xml)`, `len(references)`, `duration_ms`.

Hata akışı: bulunamayan yayın 404, PDF UUID eksikliği 422, TR Dizin/GROBID/TEI hataları 502 olur. Adapter mesajı route tarafından `detail` alanına aktarılır.
