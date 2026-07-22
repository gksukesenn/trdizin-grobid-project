from __future__ import annotations

import re
import unicodedata
from typing import Any

from rapidfuzz import fuzz


TEXT_MATCH_THRESHOLD = 82.0
MATCH_MARGIN = 3.0


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    for prefix in ("https://doi.org/", "http://doi.org/", "https://dx.doi.org/", "doi:"):
        text = text.replace(prefix, "")
    return text.strip()


def normalize_reference(value: Any) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFKC", str(value)).lower()
    text = re.sub(r"https?://(?:dx\.)?doi\.org/", " ", text, flags=re.I)
    text = re.sub(r"https?://", " ", text, flags=re.I)
    text = "".join(character if character.isalnum() else " " for character in text)
    return re.sub(r"\s+", " ", text).strip()


def calculate_score(tr: dict[str, Any], gr: dict[str, Any]) -> float:
    tr_text = tr["normalized"]
    gr_text = gr["normalized"]
    if len(tr_text) < 15 or len(gr_text) < 15:
        return 0.0
    score = (
        fuzz.token_set_ratio(tr_text, gr_text) * 0.45
        + fuzz.token_sort_ratio(tr_text, gr_text) * 0.35
        + fuzz.ratio(tr_text, gr_text) * 0.20
    )
    if tr.get("year") and gr.get("year"):
        score += 5.0 if tr["year"] == gr["year"] else -8.0
    shorter, longer = min(len(tr_text), len(gr_text)), max(len(tr_text), len(gr_text))
    if longer and shorter / longer < 0.45:
        score -= 8.0
    return max(0.0, min(100.0, score))


def classify_match(tr: dict[str, Any], gr: dict[str, Any]) -> str:
    tr_text, gr_text = tr["normalized"], gr["normalized"]
    if not tr_text or not gr_text:
        return "text_match_clean"
    shorter, longer = min(len(tr_text), len(gr_text)), max(len(tr_text), len(gr_text))
    ratio = shorter / longer if longer else 1.0
    partial = fuzz.partial_ratio(tr_text, gr_text)
    if partial >= 95.0 and ratio < 0.80 and len(gr_text) > len(tr_text):
        return "grobid_merged"
    if partial >= 95.0 and ratio < 0.80 and len(gr_text) < len(tr_text):
        return "grobid_partial"
    return "text_match_clean"


def compare_references(tr_refs: list[dict[str, Any]], gr_refs: list[dict[str, Any]]) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    used_tr: set[int] = set()
    used_gr: set[int] = set()
    doi_to_gr: dict[str, int] = {}
    for pos, ref in enumerate(gr_refs):
        doi = normalize_doi(ref.get("doi"))
        if doi:
            doi_to_gr.setdefault(doi, pos)
    seen_tr_dois: set[str] = set()
    for tr_pos, tr_ref in enumerate(tr_refs):
        doi = normalize_doi(tr_ref.get("doi"))
        gr_pos = doi_to_gr.get(doi) if doi and doi not in seen_tr_dois else None
        if doi:
            seen_tr_dois.add(doi)
        if gr_pos in used_gr:
            gr_pos = None
        if gr_pos is not None:
            used_tr.add(tr_pos); used_gr.add(gr_pos)
            matches.append(_match(tr_pos, gr_pos, "exact_match", 100.0, tr_refs, gr_refs))

    tr_work = [(pos, _prepared(ref)) for pos, ref in enumerate(tr_refs) if pos not in used_tr]
    gr_work = [(pos, _prepared(ref)) for pos, ref in enumerate(gr_refs) if pos not in used_gr]
    scores = {(ti, gi): calculate_score(tr, gr) for ti, (_, tr) in enumerate(tr_work) for gi, (_, gr) in enumerate(gr_work)}
    tr_best = {ti: _best([(scores[(ti, gi)], gi) for gi in range(len(gr_work))]) for ti in range(len(tr_work))}
    gr_best = {gi: _best([(scores[(ti, gi)], ti) for ti in range(len(tr_work))]) for gi in range(len(gr_work))}
    for ti, (gi, score, second) in tr_best.items():
        if gi is None or gr_best[gi][0] != ti or score < TEXT_MATCH_THRESHOLD:
            continue
        if score - second < MATCH_MARGIN or gr_best[gi][1] - gr_best[gi][2] < MATCH_MARGIN:
            continue
        tr_pos, tr = tr_work[ti]; gr_pos, gr = gr_work[gi]
        used_tr.add(tr_pos); used_gr.add(gr_pos)
        matches.append(_match(tr_pos, gr_pos, classify_match(tr, gr), score, tr_refs, gr_refs))
    matches.sort(key=lambda item: item["trdizin_index"])
    return {
        "matches": matches,
        "unmatched_trdizin": [ref for pos, ref in enumerate(tr_refs) if pos not in used_tr],
        "unmatched_grobid": [ref for pos, ref in enumerate(gr_refs) if pos not in used_gr],
    }


def _prepared(ref: dict[str, Any]) -> dict[str, Any]:
    return {"normalized": normalize_reference(ref.get("raw_reference")), "year": ref.get("year")}


def _best(values: list[tuple[float, int]]) -> tuple[int | None, float, float]:
    if not values:
        return None, 0.0, 0.0
    ordered = sorted(values, reverse=True)
    return ordered[0][1], ordered[0][0], ordered[1][0] if len(ordered) > 1 else 0.0


def _match(ti: int, gi: int, status: str, score: float, tr: list, gr: list) -> dict[str, Any]:
    return {"trdizin_index": ti, "grobid_index": gi, "status": status, "score": round(score, 2), "trdizin_reference": tr[ti], "grobid_reference": gr[gi]}
