"""Post-transcription analysis: chapter parse (cached), linking, gap analysis, topic segmentation."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from app import cache
from app.chapter import parse_chapter
from app.embed import Embedder, encode_cached
from app.link import gap_analysis, link_paragraphs, section_passages, section_scores
from app.segment import segment_topics

log = logging.getLogger(__name__)
CHAPTER_CACHE_VERSION = 1


def load_chapter(path: str | Path, ocr_factory=None) -> tuple[str, list[dict]]:
    """Parse (or load cached) chapter sections. Returns (chapter file hash, sections)."""
    from app import config
    from app.chapter import CHAPTER_EXT, _ocr_engine
    from app.security import check_input_file

    p = check_input_file(path, CHAPTER_EXT, config.MAX_PDF_BYTES)
    h = cache.file_sha256(p)
    hit = cache.read_json(h, f"chapter_v{CHAPTER_CACHE_VERSION}")
    if isinstance(hit, list) and all(isinstance(s, dict) and isinstance(s.get("title"), str) for s in hit):
        return h, hit
    secs = parse_chapter(p, ocr_factory or _ocr_engine)
    cache.write_json(h, f"chapter_v{CHAPTER_CACHE_VERSION}", secs)
    return h, secs


def analyze(result: dict, embedder: Embedder, chapter: tuple[str, list[dict]] | None = None,
            chapter_name: str | None = None, progress: Callable[[str, float], None] | None = None) -> dict:
    """Mutates result: paragraph links/flags, result['topics'], result['read_on_own'], result['chapter']."""
    prog = progress or (lambda s, f: None)
    paras = result.get("paragraphs", [])
    prog("embed", 0.0)
    pv = encode_cached(embedder, [p.get("text", "") for p in paras], result["file_hash"], "emb_para")
    sections = None
    result["read_on_own"] = []
    if chapter:
        ch_hash, sections = chapter
        texts, owners = section_passages(sections)
        sv = encode_cached(embedder, texts, ch_hash, "emb_chap")
        prog("link", 0.5)
        if len(paras):
            link_paragraphs(paras, sections, section_scores(pv, sv, owners, len(sections)))
        result["read_on_own"] = gap_analysis(paras, sections)
        result["chapter"] = {"name": chapter_name or "chapter", "hash": ch_hash,
                             "sections": [{**{k: s[k] for k in ("id", "title", "label", "page", "level")},
                                           "has_text": len(s.get("text", "")) > 40} for s in sections]}
    else:
        result.pop("chapter", None)
        for p in paras:
            for k in ("link", "unsure", "not_in_book"):
                p.pop(k, None)
    prog("topics", 0.8)
    result["topics"] = segment_topics(paras, pv, sections) if len(paras) else []
    prog("analysis_done", 1.0)
    return result


def refresh_after_edit(result: dict) -> None:
    """Recompute gaps + topic titles after manual re-assignment (no re-embedding of chapter)."""
    ch = result.get("chapter")
    if ch and ch.get("sections"):
        result["read_on_own"] = gap_analysis(result["paragraphs"], ch["sections"])
