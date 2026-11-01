"""Local transcript Q&A: return the most relevant passages (no generated answers)."""
from __future__ import annotations

import numpy as np

from app.embed import Embedder, encode_cached
from app.emphasis import norm_ar

MIN_SCORE = 0.25
KEYWORD_BOOST = 0.15


class TranscriptIndex:
    def __init__(self, result: dict, embedder: Embedder):
        self.result = result
        self.embedder = embedder
        self.paras = result.get("paragraphs", [])
        texts = [p.get("text", "") for p in self.paras]
        self.vecs = encode_cached(embedder, texts, result["file_hash"], "emb_para") if texts else \
            np.zeros((0, 1), dtype=np.float32)
        self.norm = [norm_ar(t).casefold() for t in texts]

    def search(self, question: str, k: int = 5) -> list[dict]:
        q = " ".join(str(question).split())[:500]
        if not q or not self.paras:
            return []
        qv = self.embedder.encode([q])[0]
        scores = self.vecs @ qv
        terms = [t for t in norm_ar(q).casefold().split() if len(t) >= 3]
        for i, t in enumerate(self.norm):
            if terms:
                frac = sum(term in t for term in terms) / len(terms)
                scores[i] += KEYWORD_BOOST * frac
        order = np.argsort(-scores)[:k]
        return [{"para": int(i), "start": self.paras[i]["start"], "score": round(float(scores[i]), 3),
                 "text": self.paras[i].get("text", "")}
                for i in order if scores[i] >= MIN_SCORE]
