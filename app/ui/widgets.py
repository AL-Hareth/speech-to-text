"""Reusable widgets: drag-and-drop zone, step indicator."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class DropZone(QFrame):
    """Accepts local files with allowed extensions via drag-and-drop or click-to-browse."""

    filesDropped = Signal(list)
    rejected = Signal(str)

    def __init__(self, title: str, hint: str, exts: set[str], multiple: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("drop")
        self.exts, self.multiple = {e.lower() for e in exts}, multiple
        self.setAcceptDrops(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(110)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignCenter)
        t = QLabel(title)
        t.setObjectName("h2")
        t.setAlignment(Qt.AlignCenter)
        self.hint = QLabel(hint)
        self.hint.setObjectName("muted")
        self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setWordWrap(True)
        lay.addWidget(t)
        lay.addWidget(self.hint)

    def _filter(self, paths: list[str]) -> list[str]:
        ok, bad = [], []
        for p in paths:
            pp = Path(p)
            (ok if pp.is_file() and pp.suffix.lower() in self.exts else bad).append(str(pp))
        if bad:
            self.rejected.emit(f"Skipped {len(bad)} unsupported item(s).")
        return ok if self.multiple else ok[:1]

    def _set_hover(self, on: bool) -> None:
        self.setProperty("hover", "true" if on else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            self._set_hover(True)
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self._set_hover(False)

    def dropEvent(self, e):
        self._set_hover(False)
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        files = self._filter(paths)
        if files:
            self.filesDropped.emit(files)
        e.acceptProposedAction()

    def mouseReleaseEvent(self, e):
        pattern = "Supported files (" + " ".join("*" + x for x in sorted(self.exts)) + ")"
        if self.multiple:
            paths, _ = QFileDialog.getOpenFileNames(self, "Choose files", "", pattern)
        else:
            p, _ = QFileDialog.getOpenFileName(self, "Choose file", "", pattern)
            paths = [p] if p else []
        files = self._filter(paths)
        if files:
            self.filesDropped.emit(files)


class StepBar(QWidget):
    STEPS = ["Prepare", "Load model", "Transcribe", "Paragraphs", "Speakers · topics · links", "Done"]
    STAGE_TO_STEP = {"chapter": 0, "hash": 0, "extract": 0, "load_model": 1, "transcribe": 2,
                     "paragraphs": 3, "speakers": 4, "embed": 4, "link": 4, "topics": 4, "analysis_done": 4, "done": 5}

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.labels = []
        for i, s in enumerate(self.STEPS):
            lb = QLabel(f"{i + 1}  {s}")
            lb.setObjectName("step")
            self.labels.append(lb)
            lay.addWidget(lb)
        lay.addStretch(1)
        self.set_stage(None)

    def _state(self, lb: QLabel, st: str) -> None:
        lb.setProperty("state", st)
        lb.style().unpolish(lb)
        lb.style().polish(lb)

    def set_stage(self, stage: str | None, error: bool = False) -> None:
        cur = self.STAGE_TO_STEP.get(stage, -1) if stage else -1
        for i, lb in enumerate(self.labels):
            if error and i == cur:
                self._state(lb, "error")
            elif i < cur or (stage == "done"):
                self._state(lb, "done")
            elif i == cur:
                self._state(lb, "active")
            else:
                self._state(lb, "pending")
