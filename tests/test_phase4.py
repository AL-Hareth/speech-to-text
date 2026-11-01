"""Phase 4: chapter parsing (PDF, scanned PDF via OCR, PPTX), zip-bomb defence, linking, gaps, topics."""
from __future__ import annotations

import io
import os
import time
import zipfile
from pathlib import Path

import fitz
import numpy as np
import pytest

from app import chapter as ch
from app.analyze import analyze, load_chapter
from app.security import InputError
from app.segment import segment_topics
from tests.helpers import HashEmbedder

SECTIONS = [
    ("3.1 Neural Networks", "A neural network is built from layers of neurons. Each neuron computes a "
     "weighted sum of inputs followed by an activation function such as ReLU or sigmoid."),
    ("3.2 Backpropagation", "Backpropagation computes the gradient of the loss with respect to every "
     "weight using the chain rule. Gradient descent then updates the weights with a learning rate."),
    ("3.3 Regularization", "Regularization reduces overfitting. Dropout randomly disables neurons and "
     "weight decay penalises large weights in the loss."),
]


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


def make_pdf(path: Path) -> Path:
    doc = fitz.open()
    page = doc.new_page()
    y = 60
    page.insert_text((50, y), "Chapter 3: Deep Learning", fontsize=22)
    y += 40
    for i, (title, body) in enumerate(SECTIONS):
        if i == 2:
            page = doc.new_page()
            y = 60
        page.insert_text((50, y), title, fontsize=16, fontname="helv")
        y += 26
        for k in range(0, len(body), 85):
            page.insert_text((50, y), body[k:k + 85], fontsize=10.5)
            y += 15
        y += 20
    doc.save(path)
    return path


def make_scanned(src: Path, dst: Path) -> Path:
    s = fitz.open(src)
    out = fitz.open()
    for p in s:
        pix = p.get_pixmap(dpi=150)
        np_ = out.new_page(width=p.rect.width, height=p.rect.height)
        np_.insert_image(np_.rect, stream=pix.tobytes("png"))
    out.save(dst)
    return dst


def make_pptx(path: Path) -> Path:
    from pptx import Presentation

    prs = Presentation()
    for title, body in SECTIONS:
        s = prs.slides.add_slide(prs.slide_layouts[1])
        s.shapes.title.text = title
        s.placeholders[1].text = body
    prs.save(path)
    return path


def test_parse_pdf(tmp_path):
    secs = ch.parse_chapter(make_pdf(tmp_path / "c.pdf"))
    by_num = {s["number"]: s for s in secs if s["number"]}
    assert {"3.1", "3.2", "3.3"} <= set(by_num)
    assert by_num["3.3"]["page"] == 2 and by_num["3.1"]["page"] == 1
    assert "chain rule" in by_num["3.2"]["text"] and by_num["3.2"]["label"] == "Sec 3.2"


def test_parse_scanned_pdf_with_ocr(tmp_path):
    scanned = make_scanned(make_pdf(tmp_path / "c.pdf"), tmp_path / "scan.pdf")
    assert not fitz.open(scanned)[0].get_text().strip()           # really no text layer
    secs = ch.parse_chapter(scanned)
    nums = {s["number"] for s in secs if s["number"]}
    assert {"3.1", "3.2", "3.3"} <= nums, [s["title"] for s in secs]
    assert any("gradient" in s["text"].lower() for s in secs)


def test_parse_pptx(tmp_path):
    secs = ch.parse_chapter(make_pptx(tmp_path / "c.pptx"))
    assert [s["number"] for s in secs] == ["3.1", "3.2", "3.3"]
    assert [s["page"] for s in secs] == [1, 2, 3] and "dropout" in secs[2]["text"].lower()


def test_reject_bad_chapters(tmp_path):
    bomb = tmp_path / "bomb.pptx"
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("ppt/big.xml", b"\0" * (60 * 1024**2))
    with pytest.raises(InputError, match="zip bomb"):
        ch.parse_chapter(bomb)
    trav = tmp_path / "trav.pptx"
    with zipfile.ZipFile(trav, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr("../../evil.txt", "x")
    with pytest.raises(InputError, match="invalid paths"):
        ch.parse_chapter(trav)
    (tmp_path / "fake.pdf").write_bytes(b"%PDF-1.4 garbage" * 10)
    with pytest.raises(InputError):
        ch.parse_chapter(tmp_path / "fake.pdf")
    (tmp_path / "fake.pptx").write_bytes(b"not a zip")
    with pytest.raises(InputError):
        ch.parse_chapter(tmp_path / "fake.pptx")
    enc = fitz.open()
    enc.new_page().insert_text((50, 50), "secret")
    enc.save(tmp_path / "enc.pdf", encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="pw", owner_pw="pw")
    with pytest.raises(InputError, match="password"):
        ch.parse_chapter(tmp_path / "enc.pdf")


def _result(texts_times):
    paras = [{"id": i, "start": t, "end": t + 20, "text": tx, "rtl": False}
             for i, (tx, t) in enumerate(texts_times)]
    return {"file_hash": "ab" * 32, "paragraphs": paras, "segments": [], "source_name": "l.mp4",
            "duration": 900.0, "model": "stub", "created": "x", "language": "ar"}


def test_link_gaps_topics(tmp_path):
    res = _result([
        ("هلأ رح نحكي عن ال neural network وكل neuron فيه activation function زي ReLU", 0),
        ("ال neuron بيحسب weighted sum لل inputs وبعدين ال activation function", 30),
        ("so the layers of neurons in a neural network", 60),
        ("ال backpropagation بيحسب ال gradient لل loss باستخدام ال chain rule", 200),
        ("وبعدين gradient descent بيعمل update لل weights مع learning rate", 230),
        ("remember the chain rule for the gradient of each weight", 260),
        ("يا شباب الامتحان يوم الأحد الساعة عشرة بالقاعة الكبيرة لا تتأخروا أبداً please", 500),
        ("the exam is on Sunday at ten in the big hall do not be late everyone", 530),
        ("bring your student card and a calculator to the exam hall on Sunday", 560),
    ])
    chap = load_chapter(make_pdf(tmp_path / "c.pdf"))
    analyze(res, HashEmbedder(), chap, "c.pdf")
    p = res["paragraphs"]
    assert p[0]["link"]["label"] == "Sec 3.1" and p[3]["link"]["label"] == "Sec 3.2"
    assert 0 < p[3]["link"]["confidence"] <= 1 and p[3]["link"]["page"] == 1
    assert p[7]["not_in_book"] and "link" not in p[7]
    assert [r["title"] for r in res["read_on_own"]] == ["3.3 Regularization"]
    assert len(res["topics"]) == 3 and res["topics"][1]["start_para"] == 3
    assert res["topics"][0]["title"].startswith("3.1 Neural Networks")
    # cached embeddings are npz (no pickle) and reused
    calls = []

    class Counting(HashEmbedder):
        def encode(self, texts):
            calls.append(len(texts))
            return super().encode(texts)
    analyze(res, Counting(), chap, "c.pdf")
    assert calls == []


def test_topics_without_chapter():
    emb = HashEmbedder()
    res = _result([("dropout disables neurons randomly", 0), ("dropout reduces overfitting neurons", 30),
                   ("dropout neurons overfitting again", 60), ("matrix multiplication of tensors", 200),
                   ("tensors matrix shapes multiplication", 230), ("matrix tensors broadcasting", 260)])
    topics = segment_topics(res["paragraphs"], emb.encode([x["text"] for x in res["paragraphs"]]))
    assert [t["start_para"] for t in topics] == [0, 3]
    assert "dropout" in topics[0]["title"] and "matrix" in topics[1]["title"] or "tensor" in topics[1]["title"]


def test_pdf_with_links_and_appendix(tmp_path):
    from app.pdf import build_pdf

    res = _result([("ال backpropagation بيحسب ال gradient لل loss باستخدام ال chain rule", 0),
                   ("the exam is on Sunday at ten in the big hall do not be late everyone", 100)])
    analyze(res, HashEmbedder(), load_chapter(make_pdf(tmp_path / "c.pdf")), "c.pdf")
    out = build_pdf(res, tmp_path, "x.pdf")
    txt = "".join(pg.get_text() for pg in fitz.open(out))
    assert "Sec 3.2, p.1" in txt and "Not in book" in txt and "Read on your own" in txt
    assert "3.3 Regularization" in txt


def test_ui_chapter_flow(tmp_path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from app.settings import Settings
    from app.ui.main_window import MainWindow
    from app.ui.review import COL_SEC
    from tests.test_phase1 import StubModel, _gen

    qapp = QApplication.instance() or QApplication([])
    s = Settings()
    s.output_dir = str(tmp_path / "out")
    win = MainWindow(settings=s, model_factory=lambda n: StubModel(), embedder_factory=HashEmbedder)
    win.add_files([str(_gen(tmp_path / "a.mp3", False))])
    win.set_chapter([str(make_pptx(tmp_path / "c.pptx"))])
    win.start()
    end = time.monotonic() + 60
    while win.worker is not None and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)
    res = win.current_result()
    assert res["chapter"]["name"] == "c.pptx" and len(res["chapter"]["sections"]) == 3
    assert not win.review.table.isColumnHidden(COL_SEC)
    win.review.assign(0, 2)                                # manual re-assign -> 3.3
    assert res["paragraphs"][0]["link"]["manual"] and res["paragraphs"][0]["link"]["label"] == "Sec 3.3"
    assert "3.3" not in [r["title"][:3] for r in res["read_on_own"]]
    assert win.dirty
    keep = os.environ.get("LS_UI_CHECK_DIR")
    if keep:
        win.resize(1200, 760)
        win.tabs.setCurrentIndex(1)
        qapp.processEvents()
        win.grab().save(str(Path(keep) / "review_chapter.png"))
    win.close()
