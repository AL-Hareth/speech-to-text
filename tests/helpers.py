"""Test doubles (no model downloads)."""
from __future__ import annotations

import hashlib
import re

import numpy as np


class HashEmbedder:
    """Deterministic bag-of-words embedder: shared English terms -> high cosine similarity."""

    name = "hash-test"
    STOP = {"the", "and", "of", "to", "a", "in", "is", "we", "this", "that", "for", "on", "with", "are"}

    def encode(self, texts):
        out = np.zeros((len(texts), 256), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in re.findall(r"[a-z]{3,}|[ء-ي]{3,}", t.lower()):
                if w in self.STOP:
                    continue
                w = w[:-1] if w.endswith("s") else w
                out[i, int(hashlib.md5(w.encode(), usedforsecurity=False).hexdigest(), 16) % 256] += 1
            n = np.linalg.norm(out[i])
            out[i] = out[i] / n if n else out[i]
            if not n:
                out[i, 0] = 1.0
        return out
