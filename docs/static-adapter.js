
(() => {
    "use strict";

    const nativeFetch =
        window.fetch.bind(window);

    const staticRoot =
        new URL("./", document.baseURI);

    const PDF_CACHE_VERSION =
        "20260722";

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
