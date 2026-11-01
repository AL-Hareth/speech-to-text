"""Emphasis detection (regex): phrases lecturers use to flag important / exam material."""
from __future__ import annotations

import re

_HARAKAT = re.compile(r"[ً-ٰٟـ]")    # diacritics + tatweel


def norm_ar(s: str) -> str:
    s = _HARAKAT.sub("", s)
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ى", "ي"), ("ة", "ه")):
        s = s.replace(a, b)
    return s


# Arabic patterns are matched on norm_ar() text; optional و/ف/ب/ل prefixes and ال where natural.
_AR = [
    r"(?<!\w)[وف]?مهم(?:ه|ين|ات)?(?!\w)",                 # مهم، مهمة، مهمين
    r"(?<!\w)[وف]?ركزو?ا?(?!\w)", r"(?<!\w)[وف]?ركزوا(?!\w)",
    r"(?<!\w)[وف]?انتبهو?ا?(?!\w)",
    r"(?<!\w)[بو]?[يت]?يجي\s+(?:ب|في\s*)?(?:ال)?امتحان",       # بيجي بالامتحان / رح يجي بالامتحان
    r"(?<!\w)ب?ال?امتحان(?!\w)",
    r"(?<!\w)(?:رح|راح|ح)\s+[يت]?يجي(?!\w)",
    r"(?<!\w)لازم\s+[تن]حفظو?ا?(?!\w)", r"(?<!\w)احفظو?ا?(?!\w)",
]
_EN = [r"\bimportant\b", r"\bexams?\b", r"\bremember\b", r"\bkey\b", r"\bnote\b", r"\bdon'?t\s+forget\b"]
_AR_RE = re.compile("|".join(_AR))
_EN_RE = re.compile("|".join(_EN), re.I)


def find_emphasis(text: str) -> list[str]:
    """Return the matched trigger phrases (empty list = not emphasised)."""
    hits = [m.group(0).strip() for m in _EN_RE.finditer(text)]
    hits += [m.group(0).strip() for m in _AR_RE.finditer(norm_ar(text))]
    out: list[str] = []
    for h in hits:
        if h and h not in out:
            out.append(h)
    return out


def mark_emphasis(result: dict) -> int:
    """Flag segments and paragraphs in place. Returns number of emphasised paragraphs."""
    for s in result.get("segments", []):
        s["emphasis"] = bool(find_emphasis(s.get("text", "")))
    n = 0
    for p in result.get("paragraphs", []):
        terms = find_emphasis(p.get("text", ""))
        p["emphasis"] = bool(terms)
        p["emphasis_terms"] = terms[:5]
        n += p["emphasis"]
    return n
