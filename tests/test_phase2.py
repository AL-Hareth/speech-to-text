"""Phase 2: PDF generation with mixed RTL/LTR text + render check (PyMuPDF)."""
from __future__ import annotations

import os
from pathlib import Path

import fitz  # PyMuPDF
import pytest

from app import textshape as ts
from app.paragraphs import build_paragraphs
from app.pdf import PdfOptions, build_pdf

MIXED = [
    "هلأ رح نحكي عن ال neural network وكيف بنعمل training إلها.",
    "وهاد مهم كتير بالامتحان (section 3.2) لازم تحفظوا المعادلة.",
    "The gradient descent algorithm updates the weights; انتبهوا للـ learning rate = 0.01.",
    "الصفحة 45 فيها الرسمة (Figure 3.2) اللي بتوضح ال backpropagation خطوة بخطوة.",
    "Now we move to chapter 4: convolutional networks (CNN).",
]


@pytest.fixture
def result():
    segs, t = [], 0.0
    for i, txt in enumerate(MIXED * 6):
        segs.append({"start": t, "end": t + 8, "text": txt})
        t += 10 if i % 2 else 8.2
    paras = build_paragraphs(segs, max_words=40)
    for i, p in enumerate(paras):
        p["emphasis"] = "مهم" in p["text"]
        p["speaker"] = "Doctor" if i % 3 else "طالب"
        if i == 1:
            p["link"] = {"label": "Sec 3.2", "page": 45, "confidence": 0.82}
        if i == 2:
            p["unsure"] = True
        if i == 3:
            p["not_in_book"] = True
    return {"source_name": "محاضرة <b>1</b> & co.mp4", "model": "medium", "duration": 312.0,
            "language": "ar", "created": "2026-11-01 10:00", "segments": segs, "paragraphs": paras}


def test_visual_order_and_shaping():
    v = ts.visual("هاد مهم (section 3.2) كتير", rtl=True)
    assert "(section 3.2)" in v                 # LTR run intact, brackets mirrored correctly
    assert "3.2" in ts.visual("الفقرة 3.2 مهمة", rtl=True)
    shaped = ts.visual("مهم", rtl=True)
    assert all(0xFB50 <= ord(c) <= 0xFEFF for c in shaped)   # presentation (joined) forms
    assert ts.clean("a\u202eb\x00c") == "abc"                # bidi overrides / controls stripped


@pytest.mark.parametrize("notes", [False, True])
def test_build_and_render(tmp_path, result, notes):
    out = build_pdf(result, tmp_path, "../x/lecture.pdf",
                    PdfOptions(notes_margin=notes, timestamps=True,
                               title="Intro <b>bold</b> & <a href='http://x'>"),
                    read_on_own=[{"title": "3.4 Regularization", "page": 52}])
    assert out.parent == tmp_path.resolve() and out.name == "lecture.pdf"
    doc = fitz.open(out)
    assert doc.page_count >= 4
    fonts = {f[3] for p in doc for f in p.get_fonts()}
    assert any("Inter" in f for f in fonts) and any("NotoNaskh" in f for f in fonts)
    # internal TOC links only (no URIs)
    links = [lk for p in doc for lk in p.get_links()]
    assert links and all(lk.get("kind") == fitz.LINK_GOTO for lk in links)
    assert doc.get_toc()                                    # PDF outline exists
    txt = "".join(p.get_text() for p in doc)
    assert "<b>bold</b>" in txt                                    # markup-like title rendered literally
    assert "�" not in txt
    for i in range(min(3, doc.page_count)):
        doc[i].get_pixmap(dpi=110).save(tmp_path / f"page{i}.png")
    keep = os.environ.get("LS_PDF_CHECK_DIR")      # set to keep PNGs for visual review
    if keep:
        Path(keep).mkdir(parents=True, exist_ok=True)
        for i in range(min(3, doc.page_count)):
            doc[i].get_pixmap(dpi=110).save(Path(keep) / f"notes{int(notes)}_p{i}.png")
