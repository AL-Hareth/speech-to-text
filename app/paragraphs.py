"""Group Whisper segments into paragraphs by pauses; detect dominant script per paragraph."""
from __future__ import annotations

import re

from app import config

_AR = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_LAT = re.compile(r"[A-Za-z]")
_SENT_END = re.compile(r"[.!?؟。]\s*$")


def is_rtl(text: str) -> bool:
    """True if Arabic letters dominate (decides paragraph direction in the PDF)."""
    return len(_AR.findall(text)) >= len(_LAT.findall(text)) and bool(_AR.search(text))


def build_paragraphs(segments: list[dict], pause_s: float | None = None,
                     max_words: int | None = None) -> list[dict]:
    pause_s = config.PARAGRAPH_PAUSE_S if pause_s is None else pause_s
    max_words = config.PARAGRAPH_MAX_WORDS if max_words is None else max_words
    paras: list[dict] = []
    cur: list[dict] = []
    nwords = 0

    def flush() -> None:
        nonlocal cur, nwords
        if cur:
            text = " ".join(s["text"] for s in cur if s["text"]).strip()
            if text:
                para = {"id": len(paras), "start": cur[0]["start"], "end": cur[-1]["end"],
                        "text": text, "rtl": is_rtl(text), "seg_range": [cur[0]["_i"], cur[-1]["_i"]]}
                if cur[0].get("speaker"):
                    para["speaker"] = cur[0]["speaker"]
                paras.append(para)
        cur, nwords = [], 0

    for i, seg in enumerate(segments):
        seg = {**seg, "_i": i}
        if cur:
            gap = seg["start"] - cur[-1]["end"]
            long_enough = nwords >= max_words and _SENT_END.search(cur[-1]["text"] or "")
            spk_change = seg.get("speaker") != cur[-1].get("speaker")
            if gap >= pause_s or long_enough or nwords >= max_words * 2 or spk_change:
                flush()
        cur.append(seg)
        nwords += len(seg["text"].split())
    flush()
    return paras
