"""Link transcript paragraphs to chapter sections (cosine similarity) + gap analysis."""
from __future__ import annotations

import numpy as np

from app import config

CHUNK_WORDS = 90
MIN_WORDS_NOT_IN_BOOK = 8


def section_passages(sections: list[dict]) -> tuple[list[str], list[int]]:
    """Each section -> title passage + body chunks (~90 words). Returns texts and owning section ids."""
    texts, owners = [], []
    for s in sections:
        texts.append(s["title"])
        owners.append(s["id"])
        words = s.get("text", "").split()
        for i in range(0, len(words), CHUNK_WORDS):
            chunk = " ".join(words[i:i + CHUNK_WORDS])
            if len(chunk) > 20:
                texts.append(f"{s['title']}: {chunk}")
                owners.append(s["id"])
    return texts, owners


def section_scores(para_vecs: np.ndarray, pass_vecs: np.ndarray, owners: list[int],
                   n_sections: int) -> np.ndarray:
    """(paragraphs x sections) = max cosine over each section's passages."""
    sims = para_vecs @ pass_vecs.T
    out = np.full((para_vecs.shape[0], n_sections), -1.0, dtype=np.float32)
    own = np.asarray(owners)
    for sid in range(n_sections):
        cols = np.where(own == sid)[0]
        if cols.size:
            out[:, sid] = sims[:, cols].max(axis=1)
    return out


def confidence(score: float) -> float:
    """Map raw cosine to a 0..1 badge value (LINK_UNSURE -> ~0.3, LINK_SURE -> ~0.6)."""
    lo, hi = config.LINK_UNSURE - 0.15, config.LINK_SURE + 0.25
    return float(np.clip((score - lo) / (hi - lo), 0.0, 1.0))


def link_paragraphs(paragraphs: list[dict], sections: list[dict], scores: np.ndarray,
                    continuity_bonus: float = 0.03) -> None:
    """Annotate paragraphs in place with link / unsure / not_in_book (manual links are kept)."""
    prev = None
    for i, p in enumerate(paragraphs):
        if isinstance(p.get("link"), dict) and p["link"].get("manual"):
            prev = p["link"].get("section_id")
            continue
        row = scores[i].copy()
        if prev is not None and 0 <= prev < row.size:
            row[prev] += continuity_bonus             # lectures tend to stay on a section
        sid = int(row.argmax())
        best = float(scores[i, sid])
        p.pop("link", None)
        p["unsure"] = False
        p["not_in_book"] = False
        if best >= config.LINK_UNSURE:
            s = sections[sid]
            p["link"] = {"section_id": sid, "label": s["label"], "page": s.get("page"),
                         "confidence": round(confidence(best), 2), "score": round(best, 3)}
            p["unsure"] = best < config.LINK_SURE
            prev = sid
        elif len(p.get("text", "").split()) >= MIN_WORDS_NOT_IN_BOOK:
            p["not_in_book"] = True


def set_manual_link(p: dict, section: dict | None) -> None:
    if section is None:
        p.pop("link", None)
        p["unsure"] = p["not_in_book"] = False
        p["link"] = {"manual": True, "section_id": None, "label": None}
        return
    p["link"] = {"section_id": section["id"], "label": section["label"], "page": section.get("page"),
                 "confidence": 1.0, "manual": True}
    p["unsure"] = p["not_in_book"] = False


def gap_analysis(paragraphs: list[dict], sections: list[dict]) -> list[dict]:
    """Sections no paragraph was confidently linked to -> 'Read on your own'."""
    covered = {p["link"]["section_id"] for p in paragraphs
               if isinstance(p.get("link"), dict) and p["link"].get("section_id") is not None
               and (p["link"].get("manual") or not p.get("unsure"))}
    return [{"id": s["id"], "title": s["title"], "page": s.get("page")}
            for s in sections if s["id"] not in covered and s.get("has_text", len(s.get("text", "")) > 40)]
