import unittest
from pathlib import Path
import re


HTML = (Path(__file__).parents[1] / "interface/templates/index.html").read_text(
    encoding="utf-8"
)


class LiveUiContractTests(unittest.TestCase):
    def test_local_archive_counters_are_not_rendered(self) -> None:
        self.assertNotIn('id="healthStats"', HTML)
        self.assertNotIn('fetchJson("/api/health")', HTML)
        self.assertNotIn("data.pdf_file_count", HTML)
        self.assertNotIn("data.processed_document_count", HTML)
        self.assertNotIn("data.matched_article_count", HTML)

    def test_cards_use_live_session_status_instead_of_zero_reference(self) -> None:
        self.assertIn("articleSessions: {}", HTML)
        self.assertIn("Durum: Henüz kontrol edilmedi", HTML)
        self.assertIn("GROBID işleniyor...", HTML)
        self.assertIn("TR Dizin: ${formatNumber(session.trdizin_reference_count)}", HTML)
        self.assertNotIn("article.reference_count", HTML)
        self.assertNotIn("GROBID: İşlenmedi", HTML)

    def test_success_updates_cached_counts_and_failure_preserves_previous(self) -> None:
        for field in (
            "processed: true",
            "trdizin_reference_count: p.trdizin_reference_count",
            "grobid_reference_count: p.grobid_reference_count",
            "matched_count: p.matched_count",
            "unmatched_trdizin_count: p.unmatched_trdizin_count",
            "unmatched_grobid_count: p.unmatched_grobid_count",
            "duration_ms: p.duration_ms",
            "processingRunId: p.processing_run_id",
            "cacheHit: Boolean(p.cache_hit)",
            "statusChecked: true",
            "processFailed: false",
            "state.processResult = previousSession.result || null",
        ):
            self.assertIn(field, HTML)

    def test_cached_response_updates_and_rerenders_article_card_immediately(self) -> None:
        session_update = HTML.index("state.articleSessions[sessionKey] = {", HTML.index("const result = await response.json()"))
        rerender = HTML.index("renderArticles();", session_update)
        selected_panel_update = HTML.index("if (state.selectedId === publicationId)", rerender)
        self.assertLess(session_update, rerender)
        self.assertLess(rerender, selected_panel_update)
        self.assertIn("session?.processed", HTML)
        self.assertIn("<span>Cache’de mevcut</span>", HTML)
        self.assertIn("<span>Yeni işlendi</span>", HTML)

    def test_unknown_processing_state_is_not_reported_as_unprocessed(self) -> None:
        render_body = HTML.split("function renderArticles()", 1)[1].split(
            "function renderPagination()", 1
        )[0]
        self.assertIn("session?.isProcessing", render_body)
        self.assertIn("session?.processed", render_body)
        self.assertIn("session?.processFailed", render_body)
        self.assertIn("Durum: Henüz kontrol edilmedi", render_body)
        self.assertNotIn("GROBID: İşlenmedi", render_body)

    def test_render_articles_uses_only_string_keyed_session_processing_state(self) -> None:
        render_body = HTML.split("function renderArticles()", 1)[1].split(
            "function renderPagination()", 1
        )[0]
        self.assertIn(
            "state.articleSessions[String(article.publication_id)]",
            render_body,
        )
        self.assertIn("session?.processed", render_body)
        self.assertNotRegex(
            render_body,
            r"article\.(processed|isProcessing|reference_count|grobid_reference_count|matched_count)",
        )

        load_body = HTML.split("async function loadArticles", 1)[1].split(
            "function renderArticles()", 1
        )[0]
        self.assertIn("hydrateArticleSessions", load_body)
        self.assertNotRegex(load_body, r"\.\.\.\s*\(state\.articleSessions")

    def test_list_hydration_is_batched_and_race_guarded(self) -> None:
        load_body = HTML.split("async function loadArticles", 1)[1].split(
            "function renderArticles()", 1
        )[0]
        hydrate_body = HTML.split("async function hydrateArticleSessions", 1)[1].split(
            "function renderArticles()", 1
        )[0]
        self.assertIn("state.articles.map((article) => article.publication_id)", load_body)
        self.assertIn('fetch("/api/history/cache-status"', hydrate_body)
        self.assertIn("body: JSON.stringify({publication_ids: publicationIds})", hydrate_body)
        self.assertIn("hydrationToken !== state.hydrationToken", hydrate_body)
        self.assertIn("state.articleSessions[sessionKey] = {", hydrate_body)
        self.assertEqual(hydrate_body.count("renderArticles();"), 2)
        self.assertNotIn("process-and-compare", hydrate_body)

    def test_hydrated_card_distinguishes_cache_miss_and_database_failure(self) -> None:
        render_body = HTML.split("function renderArticles()", 1)[1].split(
            "function renderPagination()", 1
        )[0]
        for text in (
            "Cache’de mevcut", "Henüz işlenmedi", "Durum kontrol edilemedi",
            "Run #${session.processingRunId}",
        ):
            self.assertIn(text, render_body)
        self.assertIn("!currentSession.result", HTML)
        self.assertIn("previousSession.processed && previousSession.result && !force", HTML)

    def test_success_writes_complete_session_before_card_render(self) -> None:
        success_body = HTML.split("const result = await response.json()", 1)[1].split(
            "} catch (error)", 1
        )[0]
        assignment = success_body.index("state.articleSessions[sessionKey] = {")
        rerender = success_body.index("renderArticles();", assignment)
        for required in (
            "processed: true",
            "isProcessing: false",
            "result,",
            "processingRunId: p.processing_run_id",
            "cacheHit: Boolean(p.cache_hit)",
        ):
            self.assertLess(success_body.index(required, assignment), rerender)

    def test_unmatched_counts_have_separate_summary_cards(self) -> None:
        self.assertIn(
            "<strong>${p.unmatched_trdizin_count}</strong><span>Eşleşmeyen TR Dizin</span>",
            HTML,
        )
        self.assertIn(
            "<strong>${p.unmatched_grobid_count}</strong><span>Eşleşmeyen GROBID</span>",
            HTML,
        )
        self.assertNotIn("Eşleşmeyen TR / GROBID", HTML)

    def test_selection_auto_processes_once_and_guards_races(self) -> None:
        for contract in (
            "selectionToken: 0",
            "const selectionToken = ++state.selectionToken",
            "selectionToken !== state.selectionToken",
            "!currentSession.result",
            "!currentSession.isProcessing",
            "processSelectedArticle(false)",
            "if (previousSession.isProcessing) return",
            "if (previousSession.processed && previousSession.result && !force)",
            "`/api/trdizin/articles/${publicationId}/process-and-compare?force=${force}`",
        ):
            self.assertIn(contract, HTML)

    def test_process_button_tracks_retry_and_reprocess_states(self) -> None:
        self.assertIn('elements.processButton.textContent = "GROBID işleniyor..."', HTML)
        self.assertIn('elements.processButton.textContent = "Yeniden işle"', HTML)
        self.assertIn('elements.processButton.textContent = "Tekrar dene"', HTML)
        self.assertIn('() => processSelectedArticle(true)', HTML)
        self.assertIn('p.cache_hit ? "Cache’den geldi" : "Yeni işlendi"', HTML)
        self.assertIn("Run #${p.processing_run_id}", HTML)


if __name__ == "__main__":
    unittest.main()
