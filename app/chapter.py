"""Parse an English textbook chapter (PDF / PPTX) into sections with page/slide numbers.

Untrusted input: size limits, page limits, zip-bomb checks for PPTX, OCR (rapidocr, bundled
ONNX models, no network) only for pages without a text layer. All parser errors -> InputError.
"""
from __future__ import annotations

import logging
import re
import zipfile
from collections import Counter
from pathlib import Path

from app import config
from app.security import InputError, check_input_file

log = logging.getLogger(__name__)
CHAPTER_EXT = {".pdf", ".pptx"}
# "3.2 Title", "3.2. Title", "Chapter 3: Title", and OCR'd "3.2Title" (missing space)
_NUM = re.compile(r"^(?:(?:chapter|section|ch\.?)\s*)?(\d+(?:\.\d+){0,3})[.:)]?(?:\s+|(?=[A-Za-z]))(\S.*)$", re.I)
_WS = re.compile(r"\s+")


def _clean(s: str) -> str:
    return _WS.sub(" ", re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", s)).strip()


def _section(title: str, page: int, level: int = 1) -> dict:
    title = _clean(title)[:200]
    m = _NUM.match(title)
    return {"title": title, "number": m.group(1) if m else None, "page": page, "level": level, "text": ""}


def _finish(sections: list[dict]) -> list[dict]:
    out, total = [], 0
    for s in sections:
        s["text"] = _clean(s["text"])
        total += len(s["text"])
        if total > config.MAX_CHAPTER_CHARS:
            break
        if s["title"] or s["text"]:
            out.append(s)
    for i, s in enumerate(out):
        s["id"] = i
        s["label"] = f"Sec {s['number']}" if s["number"] else (s["title"][:40] or f"Section {i + 1}")
    return out


# ------------------------------------------------------------------------ PDF
def _ocr_engine():
    from rapidocr_onnxruntime import RapidOCR  # bundled models, offline
    return RapidOCR()


def _page_lines_text(page) -> list[tuple[str, float, bool]]:
    """(text, font size, bold) per line from the PDF text layer."""
    lines = []
    for b in page.get_text("dict").get("blocks", []):
        for ln in b.get("lines", []):
            spans = [s for s in ln.get("spans", []) if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans)
            size = max(s.get("size", 0) for s in spans)
            bold = all(("bold" in s.get("font", "").lower()) or (s.get("flags", 0) & 16) for s in spans)
            lines.append((text, float(size), bool(bold)))
    return lines


def _page_lines_ocr(page, ocr) -> list[tuple[str, float, bool]]:
    import numpy as np

    pix = page.get_pixmap(dpi=200)
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    if pix.n == 4:
        img = img[:, :, :3]
    result, _ = ocr(img)
    lines = []
    for box, text, score in result or []:
        if float(score) < 0.5:
            continue
        h = abs(box[3][1] - box[0][1]) * 72 / 200          # px -> pt
        lines.append((text, float(h), False))
    return lines


def parse_pdf(path: Path, ocr_factory=_ocr_engine) -> list[dict]:
    import fitz

    try:
        doc = fitz.open(str(path), filetype="pdf")
    except Exception:  # noqa: BLE001
        raise InputError(f"Could not open {path.name} (damaged or not a PDF).") from None
    with doc:
        if doc.needs_pass:
            raise InputError(f"{path.name} is password-protected.")
        if doc.page_count > config.MAX_CHAPTER_PAGES:
            raise InputError(f"{path.name} has too many pages (max {config.MAX_CHAPTER_PAGES}).")
        pages: list[list[tuple[str, float, bool]]] = []
        ocr, ocr_used = None, 0
        for page in doc:
            try:
                lines = _page_lines_text(page)
                if sum(len(t) for t, _, _ in lines) < 30 and page.get_images():
                    if ocr_used >= config.MAX_OCR_PAGES:
                        lines = []
                    else:
                        ocr = ocr or ocr_factory()
                        lines = _page_lines_ocr(page, ocr)
                        ocr_used += 1
            except Exception:  # noqa: BLE001 - skip unreadable page, keep going
                log.warning("Skipping unreadable chapter page %d", page.number + 1)
                lines = []
            pages.append(lines)
        toc = [(lvl, t, p) for lvl, t, p in doc.get_toc(simple=True) if 1 <= p <= doc.page_count]
    if ocr_used:
        log.info("OCR used on %d page(s)", ocr_used)
    return _sections_from_lines(pages, toc)


def _sections_from_lines(pages, toc) -> list[dict]:
    sizes = Counter()
    for lines in pages:
        for t, s, _ in lines:
            sizes[round(s, 1)] += len(t)
    if not sizes:
        raise InputError("No readable text found in the chapter.")
    body = sizes.most_common(1)[0][0]
    toc_titles = {_clean(t).lower(): (lvl, p) for lvl, t, p in toc}

    def is_heading(text: str, size: float, bold: bool) -> int:
        t = _clean(text)
        if not (2 <= len(t) <= 120) or t.endswith((".", ",", ";")) and not _NUM.match(t):
            return 0
        if t.lower() in toc_titles:
            return toc_titles[t.lower()][0]
        words = len(t.split())
        if size >= body * 1.5 and words <= 14:
            return 1
        if size >= body * 1.15 and words <= 14:
            return 2
        if _NUM.match(t) and (bold or size > body * 1.05) and words <= 14:
            return min(3, _NUM.match(t).group(1).count(".") + 1)
        if bold and words <= 8 and t[:1].isupper():
            return 3
        return 0

    sections = [_section("Introduction", 1, 1)]
    for pno, lines in enumerate(pages, start=1):
        for text, size, bold in lines:
            lvl = is_heading(text, size, bold)
            if lvl:
                sections.append(_section(text, pno, lvl))
            else:
                sections[-1]["text"] += " " + text
    if not sections[0]["text"].strip():
        sections.pop(0)
    return _finish(sections)


# ------------------------------------------------------------------------ PPTX
def check_zip(path: Path) -> None:
    """Reject zip bombs / malformed archives before handing the file to python-pptx."""
    try:
        with zipfile.ZipFile(path) as z:
            infos = z.infolist()
            if len(infos) > config.PPTX_MAX_ENTRIES:
                raise InputError("Presentation has too many parts.")
            total = 0
            for i in infos:
                if i.filename.startswith(("/", "\\")) or ".." in i.filename.replace("\\", "/").split("/"):
                    raise InputError("Presentation contains invalid paths.")
                total += i.file_size
                if i.file_size > 10 * 1024**2 and i.compress_size and i.file_size / i.compress_size > config.PPTX_MAX_RATIO:
                    raise InputError("Presentation looks like a zip bomb (suspicious compression).")
            if total > config.PPTX_MAX_UNCOMPRESSED:
                raise InputError("Presentation is too large when unpacked.")
            if "[Content_Types].xml" not in z.namelist():
                raise InputError("Not a valid PowerPoint file.")
    except zipfile.BadZipFile:
        raise InputError("Not a valid PowerPoint file.") from None


def parse_pptx(path: Path) -> list[dict]:
    check_zip(path)
    try:
        from pptx import Presentation  # lxml parser with resolve_entities=False (no XXE)

        prs = Presentation(str(path))
    except InputError:
        raise
    except Exception:  # noqa: BLE001
        raise InputError(f"Could not open {path.name} (damaged or unsupported).") from None
    sections: list[dict] = []
    for idx, slide in enumerate(prs.slides, start=1):
        if idx > config.MAX_CHAPTER_PAGES:
            break
        title = ""
        try:
            if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
                title = slide.shapes.title.text_frame.text
        except Exception:  # noqa: BLE001
            title = ""
        body: list[str] = []
        for shp in slide.shapes:
            try:
                if shp.has_text_frame and shp != slide.shapes.title:
                    body.append(shp.text_frame.text)
                if getattr(shp, "has_table", False) and shp.has_table:
                    body += [c.text for r in shp.table.rows for c in r.cells]
            except Exception:  # noqa: BLE001 - skip an unreadable shape
                log.info("Skipping unreadable shape on slide %d", idx)
        try:
            if slide.has_notes_slide:
                body.append(slide.notes_slide.notes_text_frame.text)
        except Exception:  # noqa: BLE001
            log.info("Skipping unreadable notes on slide %d", idx)
        title = _clean(title) or f"Slide {idx}"
        if sections and _clean(sections[-1]["title"]).lower() == title.lower():
            sections[-1]["text"] += " " + " ".join(body)     # continued slide
            continue
        s = _section(title, idx, 1)
        s["text"] = " ".join(body)
        sections.append(s)
    if not sections:
        raise InputError("No slides with text found.")
    return _finish(sections)


def parse_chapter(path: str | Path, ocr_factory=_ocr_engine) -> list[dict]:
    """Return [{id, title, number, label, page, level, text}] (page = PDF page or slide number)."""
    p = check_input_file(path, CHAPTER_EXT, config.MAX_PDF_BYTES)
    if p.suffix.lower() == ".pdf":
        return parse_pdf(p, ocr_factory)
    if p.stat().st_size > config.MAX_PPTX_BYTES:
        raise InputError("Presentation file too large.")
    return parse_pptx(p)


def headings(sections: list[dict], limit: int = 40) -> list[str]:
    return [s["title"] for s in sections if s.get("title")][:limit]
