from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]

SOURCE_DIRECTORY = (
    PROJECT_ROOT
    / "deploy"
    / "static-site"
    / "generated"
)

OUTPUT_DIRECTORY = (
    PROJECT_ROOT
    / "deploy"
    / "github-pages"
    / "site"
)

ARTICLES_PER_SHARD = int(
    os.getenv("PAGES_ARTICLES_PER_SHARD", "100")
)

PDF_CACHE_VERSION = os.getenv(
    "PAGES_PDF_CACHE_VERSION",
    "20260722",
)


STATIC_ADAPTER = r'''
(() => {
    "use strict";

    const nativeFetch =
        window.fetch.bind(window);

    const staticRoot =
        new URL("./", document.baseURI);

    const PDF_CACHE_VERSION =
        "__PDF_CACHE_VERSION__";

    let articleIndexPromise = null;
    let articleLookupPromise = null;

    const shardCache = new Map();

    function jsonResponse(
        data,
        status = 200,
    ) {
        return new Response(
            JSON.stringify(data),
            {
                status,
                headers: {
                    "Content-Type":
                        "application/json; charset=utf-8",
                },
            },
        );
    }

    async function fetchStaticJson(
        relativePath,
    ) {
        const response = await nativeFetch(
            new URL(relativePath, staticRoot),
        );

        if (!response.ok) {
            throw new Error(
                `Statik veri alınamadı: ${relativePath}`,
            );
        }

        return response.json();
    }

    async function loadArticleIndex() {
        if (!articleIndexPromise) {
            articleIndexPromise =
                fetchStaticJson(
                    "data/articles-index.json",
                );
        }

        return articleIndexPromise;
    }

    async function loadArticleLookup() {
        if (!articleLookupPromise) {
            articleLookupPromise =
                loadArticleIndex().then(
                    (indexData) => {
                        const lookup = new Map();

                        for (
                            const article
                            of indexData.articles
                        ) {
                            lookup.set(
                                Number(
                                    article.publication_id,
                                ),
                                article,
                            );
                        }

                        return lookup;
                    },
                );
        }

        return articleLookupPromise;
    }

    async function loadArticlePackage(
        publicationId,
    ) {
        const numericId =
            Number(publicationId);

        if (!Number.isInteger(numericId)) {
            throw new Error(
                "Geçersiz yayın kodu.",
            );
        }

        const lookup =
            await loadArticleLookup();

        const metadata =
            lookup.get(numericId);

        if (
            !metadata
            || !metadata.data_path
        ) {
            throw new Error(
                "Makale bulunamadı.",
            );
        }

        if (
            !shardCache.has(
                metadata.data_path,
            )
        ) {
            shardCache.set(
                metadata.data_path,
                fetchStaticJson(
                    metadata.data_path,
                ),
            );
        }

        const shardData =
            await shardCache.get(
                metadata.data_path,
            );

        const articlePackage =
            shardData.articles[
                String(numericId)
            ];

        if (!articlePackage) {
            throw new Error(
                "Makale paketi bulunamadı.",
            );
        }

        return articlePackage;
    }

    function normalizeSearchValue(value) {
        return String(value ?? "")
            .toLocaleLowerCase("tr-TR")
            .trim();
    }

    async function searchArticles(url) {
        const indexData =
            await loadArticleIndex();

        const query =
            normalizeSearchValue(
                url.searchParams.get("q"),
            );

        const processingStatus =
            String(
                url.searchParams.get(
                    "processing_status",
                ) ?? "",
            ).trim();

        const limit = Math.max(
            1,
            Number(
                url.searchParams.get("limit")
                ?? 25,
            ),
        );

        const offset = Math.max(
            0,
            Number(
                url.searchParams.get("offset")
                ?? 0,
            ),
        );

        const filteredArticles =
            indexData.articles.filter(
                (article) => {
                    if (
                        processingStatus
                        && article.processing_status
                            !== processingStatus
                    ) {
                        return false;
                    }

                    if (!query) {
                        return true;
                    }

                    const searchableText = [
                        article.publication_id,
                        article.title,
                        article.doi,
                        article.journal,
                    ]
                        .map(
                            normalizeSearchValue,
                        )
                        .join(" ");

                    return searchableText.includes(
                        query,
                    );
                },
            );

        return {
            total: filteredArticles.length,
            limit,
            offset,
            articles:
                filteredArticles.slice(
                    offset,
                    offset + limit,
                ),
        };
    }

    async function handleApiRequest(url) {
        if (
            url.pathname === "/api/health"
        ) {
            return jsonResponse(
                await fetchStaticJson(
                    "data/health.json",
                ),
            );
        }

        if (
            url.pathname
            === "/api/articles/search"
        ) {
            return jsonResponse(
                await searchArticles(url),
            );
        }

        const match = url.pathname.match(
            /^\/api\/articles\/(\d+)(?:\/([^/]+))?$/,
        );

        if (!match) {
            return null;
        }

        const publicationId =
            Number(match[1]);

        const action =
            match[2] ?? "detail";

        let articlePackage;

        try {
            articlePackage =
                await loadArticlePackage(
                    publicationId,
                );
        } catch (error) {
            return jsonResponse(
                {
                    detail:
                        error.message
                        || "Makale bulunamadı.",
                },
                404,
            );
        }

        if (action === "detail") {
            return jsonResponse(
                articlePackage.detail,
            );
        }

        if (
            action
            === "trdizin-references"
        ) {
            return jsonResponse(
                articlePackage
                    .trdizin_references,
            );
        }

        if (
            action
            === "grobid-references"
        ) {
            return jsonResponse(
                articlePackage
                    .grobid_references,
            );
        }

        if (action === "comparison") {
            return jsonResponse(
                articlePackage.comparison,
            );
        }

        return jsonResponse(
            {
                detail:
                    "Ham JSON ve TEI verileri "
                    + "hafif GitHub Pages "
                    + "sürümüne dahil edilmemiştir.",
            },
            404,
        );
    }

    window.fetch = async (
        input,
        options,
    ) => {
        const url = new URL(
            typeof input === "string"
                ? input
                : input.url,
            window.location.href,
        );

        if (
            url.pathname.startsWith(
                "/api/",
            )
        ) {
            const response =
                await handleApiRequest(url);

            if (response) {
                return response;
            }
        }

        return nativeFetch(
            input,
            options,
        );
    };

    let currentPdfUrl = "";

    window.getStaticPdfUrl = (
        detail,
    ) => {
        const publicationId =
            encodeURIComponent(
                detail.publication_id,
            );

        currentPdfUrl =
            "https://ai.ulakbim.gov.tr"
            + "/public/pdf-extraction/pdf/"
            + publicationId
            + "?v="
            + encodeURIComponent(
                PDF_CACHE_VERSION,
            );

        const fallbackLink =
            document.getElementById(
                "pdfFallbackLink",
            );

        if (fallbackLink) {
            fallbackLink.href =
                currentPdfUrl;
        }

        return currentPdfUrl;
    };

    document.addEventListener(
        "DOMContentLoaded",
        () => {
            const pdfFrame =
                document.getElementById(
                    "pdfFrame",
                );

            if (
                !pdfFrame
                || document.getElementById(
                    "pdfFallbackLink",
                )
            ) {
                return;
            }

            const fallbackLink =
                document.createElement("a");

            fallbackLink.id =
                "pdfFallbackLink";

            fallbackLink.href = "#";
            fallbackLink.target = "_blank";
            fallbackLink.rel =
                "noopener noreferrer";

            fallbackLink.textContent =
                "PDF'yi yeni sekmede aç";

            fallbackLink.style.display =
                "block";

            fallbackLink.style.padding =
                "9px 12px";

            fallbackLink.style.textAlign =
                "center";

            fallbackLink.style.fontWeight =
                "700";

            fallbackLink.style.color =
                "#2354c8";

            fallbackLink.addEventListener(
                "click",
                (event) => {
                    if (!currentPdfUrl) {
                        event.preventDefault();
                    }
                },
            );

            pdfFrame.insertAdjacentElement(
                "afterend",
                fallbackLink,
            );
        },
    );
})();
'''


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_json(
    path: Path,
    value: Any,
) -> None:
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    path.write_text(
        json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )


def source_article_path(
    publication_id: int,
) -> Path:
    source_shard = publication_id // 1000

    return (
        SOURCE_DIRECTORY
        / "data"
        / "articles"
        / str(source_shard)
        / f"{publication_id}.json"
    )


def clean_article_package(
    package: dict[str, Any],
) -> dict[str, Any]:
    package.pop(
        "trdizin_json",
        None,
    )

    package.pop(
        "tei_path",
        None,
    )

    trdizin_references = package.get(
        "trdizin_references",
        {},
    )

    for reference in (
        trdizin_references.get(
            "references",
            [],
        )
    ):
        reference.pop(
            "raw_json",
            None,
        )

    return package


def prepare_index_html() -> None:
    source_path = (
        SOURCE_DIRECTORY / "index.html"
    )

    html = source_path.read_text(
        encoding="utf-8",
    )

    for option_value in (
        "trdizin-json",
        "grobid-tei",
    ):
        html = re.sub(
            (
                r"\s*<option\b"
                r"[^>]*value=[\"']"
                + re.escape(option_value)
                + r"[\"'][^>]*>"
                r".*?</option>"
            ),
            "",
            html,
            count=1,
            flags=re.IGNORECASE
            | re.DOTALL,
        )

    (
        OUTPUT_DIRECTORY / "index.html"
    ).write_text(
        html,
        encoding="utf-8",
    )


def flush_shard(
    shard_number: int,
    articles: dict[str, Any],
) -> str:
    relative_path = (
        f"data/shards/"
        f"{shard_number:04d}.json"
    )

    write_json(
        OUTPUT_DIRECTORY / relative_path,
        {
            "articles": articles,
        },
    )

    return relative_path


def main() -> None:
    if ARTICLES_PER_SHARD <= 0:
        raise ValueError(
            "PAGES_ARTICLES_PER_SHARD "
            "sıfırdan büyük olmalıdır."
        )

    if not SOURCE_DIRECTORY.exists():
        raise FileNotFoundError(
            "Kaynak statik paket bulunamadı: "
            f"{SOURCE_DIRECTORY}"
        )

    if OUTPUT_DIRECTORY.exists():
        shutil.rmtree(
            OUTPUT_DIRECTORY
        )

    (
        OUTPUT_DIRECTORY
        / "data"
        / "shards"
    ).mkdir(
        parents=True,
        exist_ok=True,
    )

    prepare_index_html()

    adapter = STATIC_ADAPTER.replace(
        "__PDF_CACHE_VERSION__",
        PDF_CACHE_VERSION,
    )

    (
        OUTPUT_DIRECTORY
        / "static-adapter.js"
    ).write_text(
        adapter,
        encoding="utf-8",
    )

    (
        OUTPUT_DIRECTORY / ".nojekyll"
    ).write_text(
        "",
        encoding="utf-8",
    )

    health = read_json(
        SOURCE_DIRECTORY
        / "data"
        / "health.json"
    )

    original_index = read_json(
        SOURCE_DIRECTORY
        / "data"
        / "articles-index.json"
    )

    articles = original_index[
        "articles"
    ]

    output_articles: list[
        dict[str, Any]
    ] = []

    current_shard: dict[
        str,
        Any,
    ] = {}

    current_shard_number = 0

    for position, article in enumerate(
        articles,
        start=1,
    ):
        publication_id = int(
            article["publication_id"]
        )

        package_path = (
            source_article_path(
                publication_id
            )
        )

        package = clean_article_package(
            read_json(package_path)
        )

        current_shard[
            str(publication_id)
        ] = package

        article_copy = dict(article)

        article_copy["data_path"] = (
            f"data/shards/"
            f"{current_shard_number:04d}.json"
        )

        output_articles.append(
            article_copy
        )

        if (
            len(current_shard)
            >= ARTICLES_PER_SHARD
            or position == len(articles)
        ):
            flush_shard(
                current_shard_number,
                current_shard,
            )

            current_shard = {}
            current_shard_number += 1

        if (
            position == 1
            or position % 500 == 0
            or position == len(articles)
        ):
            print(
                "GitHub Pages paketi: "
                f"{position}/{len(articles)}",
                flush=True,
            )

    write_json(
        OUTPUT_DIRECTORY
        / "data"
        / "health.json",
        health,
    )

    write_json(
        OUTPUT_DIRECTORY
        / "data"
        / "articles-index.json",
        {
            "total": len(
                output_articles
            ),
            "articles":
                output_articles,
        },
    )

    write_json(
        OUTPUT_DIRECTORY
        / "data"
        / "manifest.json",
        {
            "generated_at":
                datetime.now(
                    timezone.utc
                ).isoformat(),
            "article_count":
                len(output_articles),
            "articles_per_shard":
                ARTICLES_PER_SHARD,
            "shard_count":
                current_shard_number,
            "raw_trdizin_json_included":
                False,
            "tei_xml_included":
                False,
            "pdf_source":
                (
                    "https://ai.ulakbim.gov.tr/"
                    "public/pdf-extraction/pdf/"
                    "{publication_id}"
                ),
            "format_version": 2,
        },
    )

    total_size = sum(
        path.stat().st_size
        for path
        in OUTPUT_DIRECTORY.rglob("*")
        if path.is_file()
    )

    largest_files = sorted(
        (
            (
                path.stat().st_size,
                path,
            )
            for path
            in OUTPUT_DIRECTORY.rglob("*")
            if path.is_file()
        ),
        reverse=True,
    )[:5]

    print()
    print("=" * 70)
    print(
        "Hafif GitHub Pages paketi hazırlandı."
    )
    print(
        f"Makale sayısı: "
        f"{len(output_articles)}"
    )
    print(
        f"Shard sayısı: "
        f"{current_shard_number}"
    )
    print(
        "Toplam boyut: "
        f"{total_size / 1024 / 1024:.2f} MB"
    )
    print()
    print("En büyük dosyalar:")

    for size, path in largest_files:
        print(
            f"  {size / 1024 / 1024:.2f} MB "
            f"{path.relative_to(OUTPUT_DIRECTORY)}"
        )

    print("=" * 70)


if __name__ == "__main__":
    main()
