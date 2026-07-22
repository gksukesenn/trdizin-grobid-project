import unittest
from pathlib import Path


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
        self.assertIn("GROBID: İşlenmedi", HTML)
        self.assertIn("GROBID işleniyor...", HTML)
        self.assertIn("TR Dizin: ${formatNumber(session.trdizin_reference_count)}", HTML)
        self.assertNotIn("article.reference_count", HTML)

    def test_success_updates_cached_counts_and_failure_preserves_previous(self) -> None:
        for field in (
            "processed: true",
            "trdizin_reference_count: p.trdizin_reference_count",
            "grobid_reference_count: p.grobid_reference_count",
            "matched_count: p.matched_count",
            "unmatched_trdizin_count: p.unmatched_trdizin_count",
            "unmatched_grobid_count: p.unmatched_grobid_count",
            "duration_ms: p.duration_ms",
            "state.processResult = previousSession.result || null",
        ):
            self.assertIn(field, HTML)

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
            "!currentSession.processed",
            "!currentSession.isProcessing",
            "processSelectedArticle(false)",
            "if (previousSession.isProcessing) return",
            "if (previousSession.processed && !force)",
            "`/api/trdizin/articles/${publicationId}/process-and-compare`",
        ):
            self.assertIn(contract, HTML)

    def test_process_button_tracks_retry_and_reprocess_states(self) -> None:
        self.assertIn('elements.processButton.textContent = "GROBID işleniyor..."', HTML)
        self.assertIn('elements.processButton.textContent = "Yeniden işle"', HTML)
        self.assertIn('elements.processButton.textContent = "Tekrar dene"', HTML)
        self.assertIn('() => processSelectedArticle(true)', HTML)


if __name__ == "__main__":
    unittest.main()
