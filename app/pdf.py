"""Study PDF (reportlab): cover, clickable TOC, paragraphs with meta tags, notes margin, appendix.

All untrusted text is drawn with canvas.drawString via app.textshape (no markup parser,
no external resources, internal links only).
"""
from __future__ import annotations

import io
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import BaseDocTemplate, Flowable, Frame, NextPageTemplate, PageBreak, PageTemplate, Spacer

from app import textshape as ts
from app.export import fmt_mmss
from app.security import safe_join

PAGE_W, PAGE_H = A4
MARGIN = 54
NOTES_W = 170
SPEAKER_COLORS = ["#1f4e9c", "#a3271f", "#1d7a3a", "#6a2c91", "#9a5b00", "#0b7a7a", "#444444"]
INK = colors.HexColor("#1b1b1b")
MUTED = colors.HexColor("#6b6b6b")
HIGHLIGHT = colors.HexColor("#fff3a3")
RED = colors.HexColor("#c0392b")
GRAY = colors.HexColor("#8a8a8a")
ACCENT = colors.HexColor("#1f4e9c")


@dataclass
class PdfOptions:
    timestamps: bool = True
    notes_margin: bool = False
    highlights: bool = True
    speakers: bool = True
    appendix_emphasis: bool = True
    appendix_read: bool = True
    title: str | None = None
    section_minutes: int = 5          # auto-sections when no topics/chapter sections given


@dataclass
class Tag:
    text: str
    color: colors.Color = MUTED
    filled: bool = False              # filled pill (white text) vs plain coloured text


# --------------------------------------------------------------------------- flowables
class TextBlock(Flowable):
    """A paragraph of mixed-direction text, splittable across pages."""

    def __init__(self, text: str, *, rtl: bool | None = None, size: float = 10.5,
                 leading: float | None = None, bold: bool = False, color=INK,
                 align: str = "start", tags: list[Tag] | None = None, highlight: bool = False,
                 bookmark: str | None = None, outline_level: int | None = None,
                 space_after: float = 8, _lines: list[str] | None = None, _first: bool = True):
        super().__init__()
        self.text = ts.clean(text)
        self.rtl = ts.has_arabic(self.text) and _dominant_rtl(self.text) if rtl is None else rtl
        self.size, self.bold, self.color, self.align = size, bold, color, align
        self.leading = leading or size * (1.75 if self.rtl else 1.45)
        self.tags = tags or []
        self.highlight, self.bookmark, self.outline_level = highlight, bookmark, outline_level
        self.space_after = space_after
        self._lines = _lines
        self._first = _first
        self._pages: dict[str, int] | None = None

    # meta line height
    def _tag_h(self) -> float:
        return 14 if (self.tags and self._first) else 0

    def wrap(self, aw, ah):
        self.aw = aw
        if self._lines is None:
            self._lines = ts.wrap(self.text, aw - (8 if self.highlight else 0), self.size, self.bold)
        self.height = self._tag_h() + len(self._lines) * self.leading + self.space_after
        return aw, self.height

    def split(self, aw, ah):
        self.wrap(aw, ah)
        n = int((ah - self._tag_h() - self.space_after) // self.leading)
        if n < 2 or n >= len(self._lines):
            return []
        kw = dict(rtl=self.rtl, size=self.size, leading=self.leading, bold=self.bold,
                  color=self.color, align=self.align, highlight=self.highlight,
                  space_after=self.space_after)
        a = TextBlock(self.text, tags=self.tags, bookmark=self.bookmark,
                      outline_level=self.outline_level, _lines=self._lines[:n], **kw)
        b = TextBlock(self.text, _lines=self._lines[n:], _first=False, **kw)
        return [a, b]

    def draw(self):
        c = self.canv
        y = self.height          # content spans [space_after, height]; gap below
        if self.bookmark and self._first:
            c.bookmarkHorizontal(self.bookmark, 0, self.height)
            if self.outline_level is not None:
                c.addOutlineEntry(self.text[:120], self.bookmark, level=self.outline_level)
            if self._pages is not None:
                self._pages[self.bookmark] = c.getPageNumber()
        if self.highlight:
            c.setFillColor(HIGHLIGHT)
            # covers tags + all text lines (content spans [space_after, height])
            c.roundRect(-3, self.space_after - 4, self.aw + 6,
                        self.height - self.space_after + 6, 3, stroke=0, fill=1)
        if self._tag_h():
            _draw_tags(c, self.tags, y - 10, self.aw, self.rtl)
            y -= self._tag_h()
        c.setFillColor(self.color)
        pad = 4 if self.highlight else 0
        for line in self._lines:
            y -= self.leading
            base = y + (self.leading - self.size) * 0.45
            w = ts.line_width(line, self.size, self.bold)
            if self.align == "center":
                x = (self.aw - w) / 2
            elif self.rtl:
                x = self.aw - w - pad
            else:
                x = pad
            ts.draw_line(c, x, base, line, self.rtl, self.size, self.bold)


class TocEntry(Flowable):
    def __init__(self, title: str, key: str, pages: dict[str, int], level: int = 0):
        super().__init__()
        self.title, self.key, self.pages, self.level = ts.clean(title), key, pages, level
        self.rtl = _dominant_rtl(self.title)

    def wrap(self, aw, ah):
        self.aw = aw
        return aw, 18

    def draw(self):
        c = self.canv
        size = 10.5 if self.level == 0 else 9.5
        indent = 14 * self.level
        num = str(self.pages.get(self.key, 0))
        nw = pdfmetrics.stringWidth(num, ts.LATIN, size)
        room = self.aw - nw - indent - 30
        title = self.title
        while title and ts.line_width(title, size) > room:
            title = title[:-2]
        if title != self.title:
            title = title.rstrip() + "…"
        tw = ts.line_width(title, size)
        c.setFillColor(INK)
        ts.draw_line(c, indent, 5, title, self.rtl, size, self.level == 0)
        c.setFillColor(MUTED)
        c.setFont(ts.LATIN, size)
        c.drawRightString(self.aw, 5, num)
        c.setStrokeColor(colors.HexColor("#c8c8c8"))
        c.setDash(1, 2)
        c.line(indent + tw + 6, 6, self.aw - nw - 6, 6)
        c.setDash()
        c.linkRect("", self.key, (0, 0, self.aw, 16), relative=1, thickness=0)


# --------------------------------------------------------------------------- helpers
def _dominant_rtl(text: str) -> bool:
    from app.paragraphs import is_rtl
    return is_rtl(text)


def _draw_tags(c, tags: list[Tag], y: float, aw: float, rtl: bool) -> None:
    size = 7.5
    widths = [ts.line_width(t.text, size, t.filled) + (10 if t.filled else 6) for t in tags]
    cursor = aw if rtl else 0.0          # tags flow from the paragraph's start side
    for t, w in zip(tags, widths):
        x = cursor - w if rtl else cursor
        cursor = x - 4 if rtl else x + w + 4
        if t.filled:
            c.setFillColor(t.color)
            c.roundRect(x, y - 3, w, 11.5, 3, stroke=0, fill=1)
            c.setFillColor(colors.white)
            ts.draw_line(c, x + 5, y, t.text, _dominant_rtl(t.text), size, True)
        else:
            c.setFillColor(t.color)
            ts.draw_line(c, x + 3, y, t.text, _dominant_rtl(t.text), size)


def speaker_colors(paragraphs: list[dict]) -> dict[str, colors.Color]:
    names: list[str] = []
    for p in paragraphs:
        s = p.get("speaker")
        if s and s not in names:
            names.append(s)
    return {n: colors.HexColor(SPEAKER_COLORS[i % len(SPEAKER_COLORS)]) for i, n in enumerate(names)}


def para_tags(p: dict, opts: PdfOptions, spk: dict) -> list[Tag]:
    tags: list[Tag] = []
    if opts.timestamps:
        tags.append(Tag(f"[{fmt_mmss(p['start'])}]", MUTED))
    if opts.speakers and p.get("speaker") in spk:
        tags.append(Tag(p["speaker"], spk[p["speaker"]], filled=True))
    link = p.get("link")            # {"label": "Sec 3.2", "page": 45, "confidence": 0.82}
    if isinstance(link, dict) and link.get("label"):
        txt = f"-> {link['label']}" + (f", p.{int(link['page'])}" if link.get("page") else "")
        tags.append(Tag(txt, ACCENT))
        if isinstance(link.get("confidence"), (int, float)):
            tags.append(Tag(f"{round(100 * float(link['confidence']))}%", ACCENT, filled=True))
    if p.get("unsure"):
        tags.append(Tag("Unsure", GRAY, filled=True))
    if p.get("not_in_book"):
        tags.append(Tag("Not in book", RED, filled=True))
    return tags


def auto_sections(paragraphs: list[dict], minutes: int) -> list[dict]:
    """Time-based sections when no topic segmentation is available."""
    secs: list[dict] = []
    span = max(1, minutes) * 60
    for i, p in enumerate(paragraphs):
        bucket = int(p["start"] // span)
        if not secs or secs[-1]["_b"] != bucket:
            secs.append({"_b": bucket, "start_para": i,
                         "title": f"{fmt_mmss(bucket * span)} – {fmt_mmss((bucket + 1) * span)}"})
    return secs


# --------------------------------------------------------------------------- document
def _story(result: dict, opts: PdfOptions, pages: dict[str, int],
           sections: list[dict], read_on_own: list[dict]) -> list:
    paras = result.get("paragraphs", [])
    spk = speaker_colors(paras) if opts.speakers else {}
    title = opts.title or Path(result.get("source_name", "Lecture")).stem
    st: list = []

    # cover
    st += [Spacer(1, 150),
           TextBlock(title, size=26, bold=True, align="center", space_after=18),
           TextBlock("LectureScribe study notes", size=11, color=MUTED, align="center", space_after=30)]
    dur = float(result.get("duration") or 0)
    for label, val in [("Date", result.get("created", "")), ("Duration", fmt_mmss(dur)),
                       ("Model", result.get("model", "")), ("Language", result.get("language") or "auto")]:
        st.append(TextBlock(f"{label}: {val}", rtl=False, size=11, align="center", space_after=4))
    if spk:
        st.append(Spacer(1, 18))
        st.append(TextBlock("Speakers", rtl=False, size=11, bold=True, align="center", space_after=6))
        for name, col in spk.items():
            st.append(TextBlock(f"■ {name}", size=11, color=col, align="center", space_after=2))
    if opts.highlights or any(p.get("link") for p in paras):
        st.append(Spacer(1, 24))
        st.append(TextBlock("Legend: yellow = emphasised by speaker · red tag = not in book · "
                            "gray tag = unsure link", rtl=False, size=8.5, color=MUTED, align="center"))

    st += [NextPageTemplate("body"), PageBreak()]

    # TOC
    st.append(TextBlock("Contents", rtl=False, size=16, bold=True, space_after=12))
    for i, s in enumerate(sections):
        st.append(TocEntry(s["title"], f"sec{i}", pages))
    appendix = []
    emph = [p for p in paras if p.get("emphasis")] if opts.appendix_emphasis else []
    if read_on_own and opts.appendix_read:
        appendix.append(("Appendix A — Read on your own", "appA"))
    if emph:
        appendix.append(("Appendix B — Emphasised passages", "appB"))
    for t, k in appendix:
        st.append(TocEntry(t, k, pages))
    st.append(PageBreak())

    # body
    starts = {s["start_para"]: (i, s) for i, s in enumerate(sections)}
    for i, p in enumerate(paras):
        if i in starts:
            si, s = starts[i]
            st.append(TextBlock(s["title"], size=14, bold=True, color=ACCENT,
                                bookmark=f"sec{si}", outline_level=0, space_after=10))
            st[-1]._pages = pages
        st.append(TextBlock(p.get("text", ""), rtl=p.get("rtl"), tags=para_tags(p, opts, spk),
                            highlight=bool(opts.highlights and p.get("emphasis")), space_after=10))

    # appendices
    if read_on_own and opts.appendix_read:
        st.append(PageBreak())
        h = TextBlock("Appendix A — Read on your own", size=14, bold=True, color=ACCENT,
                      bookmark="appA", outline_level=0, space_after=10)
        h._pages = pages
        st.append(h)
        for r in read_on_own:
            pg = f" (p.{int(r['page'])})" if r.get("page") else ""
            st.append(TextBlock(f"• {r.get('title', '')}{pg}", space_after=4))
    if emph:
        st.append(PageBreak())
        h = TextBlock("Appendix B — Emphasised passages", size=14, bold=True, color=ACCENT,
                      bookmark="appB", outline_level=0, space_after=10)
        h._pages = pages
        st.append(h)
        for p in emph:
            st.append(TextBlock(p.get("text", ""), rtl=p.get("rtl"),
                                tags=[Tag(f"[{fmt_mmss(p['start'])}]", MUTED)], highlight=opts.highlights))
    return st


def _doc(buf, opts: PdfOptions, title: str) -> BaseDocTemplate:
    doc = BaseDocTemplate(buf, pagesize=A4, title=ts.clean(title)[:200], author="LectureScribe",
                          creator="LectureScribe", subject="Lecture study notes",
                          leftMargin=MARGIN, rightMargin=MARGIN, topMargin=MARGIN, bottomMargin=MARGIN)
    body_w = PAGE_W - 2 * MARGIN - (NOTES_W if opts.notes_margin else 0)
    cover = Frame(MARGIN, MARGIN, PAGE_W - 2 * MARGIN, PAGE_H - 2 * MARGIN, id="cover")
    body = Frame(MARGIN, MARGIN, body_w, PAGE_H - 2 * MARGIN, id="body",
                 leftPadding=0, rightPadding=0)

    def on_body(c, d):
        c.saveState()
        c.setFont(ts.LATIN, 8)
        c.setFillColor(MUTED)
        c.drawCentredString(PAGE_W / 2, MARGIN / 2, str(c.getPageNumber()))
        if opts.notes_margin:
            x0, x1 = MARGIN + body_w + 16, PAGE_W - MARGIN / 2
            c.setStrokeColor(colors.HexColor("#d5dbe3"))
            c.setLineWidth(0.5)
            c.line(x0 - 6, MARGIN, x0 - 6, PAGE_H - MARGIN)
            c.drawString(x0, PAGE_H - MARGIN + 6, "Notes")
            y = PAGE_H - MARGIN - 18
            while y > MARGIN:
                c.line(x0, y, x1, y)
                y -= 20
        c.restoreState()

    doc.addPageTemplates([PageTemplate("cover", [cover]), PageTemplate("body", [body], onPage=on_body)])
    return doc


def build_pdf(result: dict, out_dir: Path, filename: str, opts: PdfOptions | None = None,
              sections: list[dict] | None = None, read_on_own: list[dict] | None = None) -> Path:
    """Render the study PDF. Two passes so TOC page numbers are correct."""
    opts = opts or PdfOptions()
    ts.register_fonts()
    paras = result.get("paragraphs", [])
    sections = [s for s in (sections or auto_sections(paras, opts.section_minutes))
                if 0 <= int(s.get("start_para", -1)) < len(paras)]
    title = opts.title or Path(result.get("source_name", "Lecture")).stem
    pages: dict[str, int] = {}
    _doc(io.BytesIO(), opts, title).build(_story(result, opts, pages, sections, read_on_own or []))
    first = dict(pages)
    buf = io.BytesIO()
    _doc(buf, opts, title).build(_story(result, opts, first, sections, read_on_own or []))

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = safe_join(out_dir, filename)
    fd, tmp = tempfile.mkstemp(dir=out_dir, suffix=".pdf.tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(buf.getvalue())
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return target
