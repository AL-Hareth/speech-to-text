"""Mixed Arabic/English text for reportlab: shaping, bidi reordering, font runs, wrapping.

reportlab draws glyphs left-to-right with no shaping, so for every *visual line* we:
  1. wrap in logical order (by width of the shaped text),
  2. arabic_reshaper  -> contextual letter forms + lam-alef ligatures,
  3. bidi (UBA incl. L4 mirroring) -> visual order with the paragraph's base direction,
  4. split into runs per font (Noto Naskh Arabic for Arabic, Inter for the rest).
Text is drawn with canvas.drawString only, so no markup is ever interpreted.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

import arabic_reshaper
from bidi.algorithm import get_display  # pure-python UBA: applies bracket mirroring (L4)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from app import config

FONT_DIR = config.resource_dir() / "app" / "assets" / "fonts"
LATIN, LATIN_B = "Inter", "Inter-Bold"
ARABIC, ARABIC_B = "NotoNaskh", "NotoNaskh-Bold"
ARABIC_SCALE = 1.12   # Naskh looks small next to Inter at the same point size

_AR_RANGE = re.compile(r"[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
_CTRL = re.compile("[\\x00-\\x08\\x0b-\\x1f\\x7f\\u202a-\\u202e\\u2066-\\u2069\\u200e\\u200f\\u061c]")
_RESHAPER = arabic_reshaper.ArabicReshaper(configuration={"delete_harakat": False,
                                                            "support_ligatures": True})


@lru_cache(maxsize=1)
def register_fonts() -> dict[str, set[int]]:
    """Register embedded fonts once; return each font's codepoint coverage."""
    files = {LATIN: "Inter-Regular.ttf", LATIN_B: "Inter-Bold.ttf",
             ARABIC: "NotoNaskhArabic-Regular.ttf", ARABIC_B: "NotoNaskhArabic-Bold.ttf"}
    cover: dict[str, set[int]] = {}
    for name, fn in files.items():
        f = TTFont(name, str(FONT_DIR / fn))
        pdfmetrics.registerFont(f)
        cover[name] = set(f.face.charToGlyph.keys())
    return cover


def clean(text: str) -> str:
    """Normalize untrusted text: NFC, drop control/bidi-override chars, collapse spaces."""
    text = unicodedata.normalize("NFC", str(text))
    text = _CTRL.sub("", text)
    return re.sub(r"\s+", " ", text).strip()


def has_arabic(text: str) -> bool:
    return bool(_AR_RANGE.search(text))


def visual(line: str, rtl: bool) -> str:
    """Logical line -> shaped, visually ordered string (left-to-right drawing order)."""
    if not line:
        return ""
    shaped = _RESHAPER.reshape(line) if has_arabic(line) else line
    if not rtl and not has_arabic(shaped):
        return shaped
    return get_display(shaped, base_dir="R" if rtl else "L")


def runs(vis: str, bold: bool = False) -> list[tuple[str, str]]:
    """Split a visual string into (text, font) runs; unsupported chars -> '?' (never boxes)."""
    cover = register_fonts()
    lat, ar = (LATIN_B, ARABIC_B) if bold else (LATIN, ARABIC)
    out: list[tuple[str, str]] = []
    for ch in vis:
        cp = ord(ch)
        if _AR_RANGE.match(ch) or (cp not in cover[lat] and cp in cover[ar]):
            font = ar
        elif cp in cover[lat]:
            font = lat
        else:
            ch, font = "?", lat
        if out and out[-1][1] == font:
            out[-1] = (out[-1][0] + ch, font)
        else:
            out.append((ch, font))
    return out


def font_size(font: str, size: float) -> float:
    return size * ARABIC_SCALE if font.startswith(ARABIC) else size


def runs_width(rs: list[tuple[str, str]], size: float) -> float:
    return sum(pdfmetrics.stringWidth(t, f, font_size(f, size)) for t, f in rs)


def line_width(line: str, size: float, bold: bool = False) -> float:
    shaped = _RESHAPER.reshape(line) if has_arabic(line) else line
    return runs_width(runs(shaped, bold), size)


def wrap(text: str, max_width: float, size: float, bold: bool = False) -> list[str]:
    """Greedy word wrap in logical order (bidi is applied per finished line)."""
    words = clean(text).split(" ")
    lines: list[str] = []
    cur = ""
    for w in words:
        if not w:
            continue
        cand = f"{cur} {w}" if cur else w
        if line_width(cand, size, bold) <= max_width:
            cur = cand
            continue
        if cur:
            lines.append(cur)
        # a single over-long token: hard-split by characters
        while line_width(w, size, bold) > max_width and len(w) > 1:
            cut = len(w)
            while cut > 1 and line_width(w[:cut], size, bold) > max_width:
                cut -= 1
            lines.append(w[:cut])
            w = w[cut:]
        cur = w
    if cur:
        lines.append(cur)
    return lines


def draw_line(canvas, x: float, y: float, line: str, rtl: bool, size: float,
              bold: bool = False) -> float:
    """Draw one logical line at (x, y) left edge; returns drawn width."""
    rs = runs(visual(line, rtl), bold)
    cx = x
    for t, f in rs:
        fs = font_size(f, size)
        canvas.setFont(f, fs)
        canvas.drawString(cx, y, t)
        cx += pdfmetrics.stringWidth(t, f, fs)
    return cx - x
