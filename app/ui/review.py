"""Review screen: edit paragraph text and speakers, search, save edits."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QPushButton, QStyledItemDelegate, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from app.export import fmt_mmss
from app.link import set_manual_link
from app.paragraphs import is_rtl

COL_TIME, COL_SPK, COL_SEC, COL_TEXT = 0, 1, 2, 3
NONE_LABEL = "— none —"


def link_label(p: dict) -> str:
    link = p.get("link") if isinstance(p.get("link"), dict) else None
    if link and link.get("label"):
        conf = link.get("confidence")
        s = link["label"] + (f", p.{link['page']}" if link.get("page") else "")
        if link.get("manual"):
            return s + "  ✎"
        return s + (f"  {round(100 * conf)}%" if isinstance(conf, (int, float)) else "") + \
            ("  ? unsure" if p.get("unsure") else "")
    if p.get("not_in_book"):
        return "✗ not in book"
    return ""


class SectionDelegate(QStyledItemDelegate):
    """Combo box editor to re-assign a paragraph to a chapter section."""

    def __init__(self, panel: "ReviewPanel"):
        super().__init__(panel)
        self.panel = panel

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItem(NONE_LABEL, None)
        for s in self.panel.sections():
            cb.addItem(f"{s['label']} — {s['title'][:60]} (p.{s.get('page')})", s["id"])
        return cb

    def setEditorData(self, editor, index):
        p = self.panel.result["paragraphs"][index.row()]
        sid = (p.get("link") or {}).get("section_id") if isinstance(p.get("link"), dict) else None
        i = editor.findData(sid)
        editor.setCurrentIndex(max(0, i))

    def setModelData(self, editor, model, index):
        self.panel.assign(index.row(), editor.currentData())


def _norm(s: str) -> str:
    """Search normalization: casefold + unify common Arabic letter variants."""
    s = s.casefold()
    for a, b in (("أ", "ا"), ("إ", "ا"), ("آ", "ا"), ("ة", "ه"), ("ى", "ي"), ("ـ", "")):
        s = s.replace(a, b)
    return s


class ReviewPanel(QWidget):
    changed = Signal()              # emitted on any edit (unsaved)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.result: dict | None = None
        self._loading = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search transcript…  (ابحث)")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.apply_filter)
        self.count = QLabel("")
        self.count.setObjectName("muted")
        self.rename_btn = QPushButton("Rename speaker…")
        self.rename_btn.clicked.connect(self.rename_speaker)
        bar.addWidget(self.search, 1)
        bar.addWidget(self.count)
        bar.addWidget(self.rename_btn)
        lay.addLayout(bar)

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Time", "Speaker", "Chapter link", "Text"])
        self.table.setItemDelegateForColumn(COL_SEC, SectionDelegate(self))
        self.table.verticalHeader().setVisible(False)
        self.table.setWordWrap(True)
        self.table.setAlternatingRowColors(False)
        h = self.table.horizontalHeader()
        h.setSectionResizeMode(COL_TIME, QHeaderView.ResizeToContents)
        h.setSectionResizeMode(COL_SPK, QHeaderView.Interactive)
        h.setSectionResizeMode(COL_TEXT, QHeaderView.Stretch)
        h.setSectionResizeMode(COL_SEC, QHeaderView.Interactive)
        self.table.setColumnWidth(COL_SPK, 110)
        self.table.setColumnWidth(COL_SEC, 170)
        self.table.itemChanged.connect(self._on_item_changed)
        lay.addWidget(self.table, 1)

    # ------------------------------------------------------------------ data
    def set_result(self, result: dict | None) -> None:
        self._loading = True
        self.result = result
        self.table.setRowCount(0)
        paras = (result or {}).get("paragraphs", [])
        self.table.setRowCount(len(paras))
        for r, p in enumerate(paras):
            t = QTableWidgetItem(fmt_mmss(p.get("start", 0)))
            t.setFlags(t.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(r, COL_TIME, t)
            self.table.setItem(r, COL_SPK, QTableWidgetItem(p.get("speaker") or ""))
            sec = QTableWidgetItem(link_label(p))
            if not self.sections():
                sec.setFlags(sec.flags() & ~Qt.ItemIsEditable)
            sec.setToolTip("Double-click to re-assign to a chapter section")
            self.table.setItem(r, COL_SEC, sec)
            txt = QTableWidgetItem(p.get("text", ""))
            txt.setTextAlignment((Qt.AlignRight if p.get("rtl") else Qt.AlignLeft) | Qt.AlignVCenter)
            self.table.setItem(r, COL_TEXT, txt)
        self.table.setColumnHidden(COL_SEC, not self.sections())
        self.table.resizeRowsToContents()
        self._loading = False
        self.apply_filter()

    def sections(self) -> list[dict]:
        ch = (self.result or {}).get("chapter") or {}
        return ch.get("sections") or []

    def assign(self, row: int, section_id) -> None:
        """Manual re-assignment from the Chapter link column."""
        if not self.result:
            return
        from app.analyze import refresh_after_edit
        p = self.result["paragraphs"][row]
        sec = next((s for s in self.sections() if s["id"] == section_id), None)
        set_manual_link(p, sec)
        refresh_after_edit(self.result)
        self._loading = True
        self.table.item(row, COL_SEC).setText(link_label(p))
        self._loading = False
        self.changed.emit()

    def _on_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or not self.result:
            return
        p = self.result["paragraphs"][item.row()]
        if item.column() == COL_TEXT:
            new = " ".join(item.text().split())
            if new != p.get("text"):
                p["text"], p["edited"], p["rtl"] = new, True, is_rtl(new)
                self._loading = True
                item.setTextAlignment((Qt.AlignRight if p["rtl"] else Qt.AlignLeft) | Qt.AlignVCenter)
                self._loading = False
                self.table.resizeRowToContents(item.row())
                self.changed.emit()
        elif item.column() == COL_SPK:
            name = " ".join(item.text().split())[:40]
            if name != (p.get("speaker") or ""):
                p["speaker"] = name or None
                self.changed.emit()

    def rename_speaker(self) -> None:
        if not self.result:
            return
        names = sorted({p.get("speaker") for p in self.result["paragraphs"] if p.get("speaker")})
        if not names:
            return
        old, ok = QInputDialog.getItem(self, "Rename speaker", "Speaker:", names, 0, False)
        if not ok:
            return
        new, ok = QInputDialog.getText(self, "Rename speaker", f"New name for “{old}”:")
        new = " ".join(new.split())[:40]
        if ok and new:
            for p in self.result["paragraphs"]:
                if p.get("speaker") == old:
                    p["speaker"] = new
            self.set_result(self.result)
            self.changed.emit()

    def apply_filter(self, *_):
        q = _norm(self.search.text().strip())
        shown = 0
        for r in range(self.table.rowCount()):
            item = self.table.item(r, COL_TEXT)
            hit = not q or (item is not None and q in _norm(item.text()))
            self.table.setRowHidden(r, not hit)
            shown += hit
        self.count.setText(f"{shown} / {self.table.rowCount()} paragraphs" if q else
                           f"{self.table.rowCount()} paragraphs")
