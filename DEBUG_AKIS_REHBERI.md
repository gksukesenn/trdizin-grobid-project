# Debug Akış Rehberi

## 1. Canlı TR Dizin araması

```text
Tarayıcı
→ FastAPI route
→ SearchTrDizinArticlesUseCase
→ TrDizinGateway
→ TrDizinHttpClient
→ TR Dizin API
→ arayüz
```

1. `interface/templates/index.html` — `loadArticles()` arama parametrelerini
   `/api/trdizin/articles/search` endpointine gönderir.
2. `interface/trdizin_app/presentation/api/routes/trdizin.py` —
   `search_articles()` query/page/limit doğrulaması yapar. Tam sayısal sorguda
   `GetTrDizinArticleUseCase`, diğer sorgularda `SearchTrDizinArticlesUseCase`
   çağrılır.
3. `application/use_cases/search_trdizin_articles.py` — use case yalnız
   `TrDizinGateway` portunu bilir.
4. `infrastructure/external/trdizin_http_client.py` — `search_articles()`
   canlı TR Dizin API isteğini yapar; `_article_from_record()` response'u
   `Article` modeline map eder.
5. Frontend `state.articles` değerini ve publication ID bazlı session bilgisini
   birleştirip kartları render eder.

Önerilen breakpointler:

- `index.html`: `loadArticles()` içindeki response sonrası
- `trdizin.py`: `search_articles()` başlangıcı
- `trdizin_http_client.py`: `search_articles()` ve `_article_from_record()`

Beklenen değişkenler: `q`, `page`, `limit`, `records`, `publication_id`,
`pdf_uuid`.

## 2. Makale seçimi, PDF ve otomatik karşılaştırma

```text
selectArticle()
→ detail ve references route'ları
→ canlı PDF stream
→ processSelectedArticle(false)
→ ProcessAndCompareTrDizinArticleUseCase
→ PDF bytes
→ GrobidHttpClient
→ TEI parser
→ reference mapper ve matcher
→ JSON response
→ frontend session state
```

1. `index.html` — `selectArticle()` detail ve TR Dizin references isteklerini
   yapar, iframe kaynağını `/api/trdizin/articles/{id}/pdf` olarak ayarlar.
2. `stream_trdizin_pdf.py` — `StreamTrDizinPdfUseCase`, gateway üzerinden PDF
   URL'sini çözer ve Range bilgisini stream portuna iletir.
3. `trdizin_http_client.py` — `resolve_pdf_url()`, `open_pdf_stream()` ve
   `fetch_pdf()` timeout/boyut/içerik kontrollerini uygular. Disk yazımı yoktur.
4. `index.html` — kaynakçalar yüklendikten sonra `processSelectedArticle(false)`
   otomatik çağrılır.
5. `process_and_compare_trdizin_article.py` — makale, TR Dizin references, PDF,
   GROBID extraction ve matching workflow'unu yönetir.
6. `grobid_http_client.py` — PDF bytes'ı `processReferences` endpointine
   multipart gönderir; `_parse_references()` TEI'yi ayrıştırır.
7. `reference_mapper.py` TR Dizin references'ı, `reference_matcher.py` iki
   listeyi karşılaştırır.
8. Frontend sonucu `articleSessions[publicationId]` içine koyar ve comparison
   görünümüne geçer. `selectionToken` ve publication ID kontrolü eski isteğin
   yeni makale ekranına yazılmasını engeller.

Önerilen breakpointler:

- `index.html`: `selectArticle()`, `processSelectedArticle()`
- `trdizin.py`: `stream_pdf()`, `process_and_compare()`
- `process_and_compare_trdizin_article.py`: `execute()`
- `trdizin_http_client.py`: `resolve_pdf_url()`, `fetch_pdf()`
- `grobid_http_client.py`: `extract_references()`, `_parse_references()`
- `reference_matcher.py`: `compare_references()`

Muhtemel hata noktaları: TR Dizin timeout/response değişikliği, PDF olmayan
makale, maksimum PDF boyutu, GROBID readiness/timeout ve geçersiz TEI.
