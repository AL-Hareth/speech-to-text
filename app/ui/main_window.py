"""LectureScribe main window: setup & run tab, review & export tab."""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFileDialog, QFrame, QGridLayout,
                               QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox,
                               QTabWidget, QVBoxLayout, QWidget)

from app import cache, config
from app.media import MEDIA_EXT
from app.pdf import PdfOptions
from app.pipeline import revert_edits, save_edits
from app.settings import Settings, default_output_dir
from app.ui.review import ReviewPanel
from app.ui.theme import stylesheet
from app.ui.widgets import DropZone, StepBar
from app.ui.worker import ExportWorker, TranscribeWorker, friendly_error, start_in_thread

log = logging.getLogger(__name__)
CHAPTER_EXT = {".pdf", ".pptx"}
MODEL_LABELS = {"small": "small — fastest, lower accuracy",
                "medium": "medium — good balance (recommended)",
                "large-v3": "large-v3 — best for dialect, slow on CPU"}


def card(*widgets_or_layouts) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 12, 14, 12)
    for w in widgets_or_layouts:
        (lay.addLayout if hasattr(w, "addWidget") and not isinstance(w, QWidget) else lay.addWidget)(w)
    return f


def heading(text: str, obj: str = "h2") -> QLabel:
    lb = QLabel(text)
    lb.setObjectName(obj)
    return lb


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings | None = None, model_factory=None, embedder_factory=None,
                 ocr_factory=None, speaker_embedder_factory=None, vad=None):
        super().__init__()
        self.settings = settings or Settings.load()
        self.model_factory = model_factory          # tests inject stubs
        self.embedder_factory = embedder_factory
        self.ocr_factory = ocr_factory
        self.speaker_embedder_factory = speaker_embedder_factory
        self.vad = vad
        self.files: list[str] = []
        self.chapter: str | None = None
        self.results: dict[str, dict] = {}          # source path -> result
        self.last_pdf: str | None = None
        self.worker = None
        self.dirty = False
        self.setWindowTitle("LectureScribe")
        self.resize(1100, 760)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setContentsMargins(18, 14, 18, 14)

        top = QHBoxLayout()
        top.addWidget(heading("LectureScribe", "h1"))
        sub = heading("Local lecture transcription · Arabic + English", "muted")
        top.addWidget(sub)
        top.addStretch(1)
        self.theme_btn = QPushButton()
        self.theme_btn.clicked.connect(self.toggle_theme)
        top.addWidget(self.theme_btn)
        outer.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_setup(), "1 · Setup && Run")
        self.tabs.addTab(self._build_review(), "2 · Review && Export")
        outer.addWidget(self.tabs, 1)
        self.apply_theme()
        self._refresh_buttons()

    # ================================================================ setup tab
    def _build_setup(self) -> QWidget:
        w = QWidget()
        grid = QGridLayout(w)
        grid.setContentsMargins(0, 10, 0, 0)
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)

        self.media_drop = DropZone("Drop audio or video files", "mp3 · wav · m4a · ogg · flac · aac · wma · "
                                   "mp4 · mkv · mov · avi · webm  —  or click to browse", MEDIA_EXT)
        self.media_drop.filesDropped.connect(self.add_files)
        self.media_drop.rejected.connect(self.set_status)
        self.chapter_drop = DropZone("Textbook chapter (optional)", "PDF or PPTX, English", CHAPTER_EXT,
                                     multiple=False)
        self.chapter_drop.filesDropped.connect(self.set_chapter)
        self.chapter_drop.rejected.connect(self.set_status)

        self.file_list = QListWidget()
        self.file_list.setMinimumHeight(90)
        rm = QPushButton("Remove selected")
        rm.clicked.connect(self.remove_selected)
        clr = QPushButton("Clear list")
        clr.clicked.connect(self.clear_files)
        row = QHBoxLayout()
        row.addWidget(heading("Files"))
        row.addStretch(1)
        row.addWidget(rm)
        row.addWidget(clr)
        files_card = card(row, self.file_list)

        # options
        self.project = QComboBox()
        self.project.setEditable(True)
        self.project.addItems(sorted(self.settings.projects))
        self.project.setCurrentText(self.settings.project)
        self.project.activated.connect(lambda _i: self.change_project(self.project.currentText()))
        self.project.lineEdit().editingFinished.connect(lambda: self.change_project(self.project.currentText()))
        self.model = QComboBox()
        for k in config.MODELS:
            self.model.addItem(MODEL_LABELS.get(k, k), k)
        self.model.setCurrentIndex(max(0, self.model.findData(self.settings.model)))
        self.cb_ts = QCheckBox("Timestamps")
        self.cb_hl = QCheckBox("Highlight emphasis")
        self.cb_notes = QCheckBox("Notes margin")
        self.cb_spk = QCheckBox("Speaker identification")
        self.cb_qa = QCheckBox("Q&&A search")
        for cb, val in ((self.cb_ts, self.settings.timestamps), (self.cb_hl, self.settings.highlights),
                        (self.cb_notes, self.settings.notes_margin), (self.cb_spk, self.settings.speakers),
                        (self.cb_qa, self.settings.qa_search)):
            cb.setChecked(val)
        self.n_spk = QSpinBox()
        self.n_spk.setRange(0, config.MAX_SPEAKERS)
        self.n_spk.setSpecialValueText("auto")
        self.n_spk.setPrefix("")
        self.n_spk.setToolTip("Number of speakers (auto = detect)")
        self.n_spk.setValue(self.settings.num_speakers)
        self.n_spk.setEnabled(self.cb_spk.isChecked())
        self.cb_spk.toggled.connect(self.n_spk.setEnabled)
        self.cb_spk.setToolTip("Detect who is speaking (downloads a small voice model on first use)")
        self.cb_qa.setToolTip("Show the 'Ask the transcript' panel in the Review tab")
        self.cb_qa.toggled.connect(lambda on: self.qa_box.setVisible(on))
        opts = QGridLayout()
        opts.addWidget(QLabel("Project"), 0, 0)
        opts.addWidget(self.project, 0, 1, 1, 2)
        opts.addWidget(QLabel("Model"), 1, 0)
        opts.addWidget(self.model, 1, 1, 1, 2)
        opts.addWidget(self.cb_ts, 2, 0)
        opts.addWidget(self.cb_hl, 2, 1)
        opts.addWidget(self.cb_notes, 2, 2)
        spk_row = QHBoxLayout()
        spk_row.addWidget(self.cb_spk)
        spk_row.addWidget(QLabel("speakers:"))
        spk_row.addWidget(self.n_spk)
        spk_row.addStretch(1)
        opts.addLayout(spk_row, 3, 0, 1, 2)
        opts.addWidget(self.cb_qa, 3, 2)
        self.vocab = QPlainTextEdit()
        self.vocab.setPlaceholderText("Custom vocabulary — one term per line (e.g. backpropagation, "
                                      "Dr. Khaled, ReLU). Saved per project.")
        self.vocab.setPlainText("\n".join(self.settings.vocab()))
        self.vocab.setMaximumHeight(110)
        opts_card = card(heading("Settings"), opts, heading("Custom vocabulary"), self.vocab)

        # run
        self.start_btn = QPushButton("Start transcription")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self.start)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.cancel)
        self.clear_cache_btn = QPushButton("Clear cache")
        self.clear_cache_btn.clicked.connect(self.clear_cache)
        self.steps = StepBar()
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.status = QLabel("Add files to begin.")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        btns = QHBoxLayout()
        btns.addWidget(self.start_btn)
        btns.addWidget(self.cancel_btn)
        btns.addStretch(1)
        btns.addWidget(self.clear_cache_btn)
        run_card = card(self.steps, self.progress, self.status, btns)

        grid.addWidget(self.media_drop, 0, 0)
        grid.addWidget(self.chapter_drop, 0, 1)
        grid.addWidget(files_card, 1, 0)
        grid.addWidget(opts_card, 1, 1)
        grid.addWidget(run_card, 2, 0, 1, 2)
        grid.setColumnStretch(0, 3)
        grid.setColumnStretch(1, 2)
        grid.setRowStretch(1, 1)
        return w

    # ================================================================ review tab
    def _build_review(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 10, 0, 0)
        top = QHBoxLayout()
        self.result_pick = QComboBox()
        self.result_pick.currentIndexChanged.connect(self.show_result)
        self.save_btn = QPushButton("Save edits")
        self.save_btn.clicked.connect(self.save_edits)
        self.revert_btn = QPushButton("Revert to original")
        self.revert_btn.clicked.connect(self.revert)
        top.addWidget(QLabel("Recording"))
        top.addWidget(self.result_pick, 1)
        top.addWidget(self.save_btn)
        top.addWidget(self.revert_btn)
        lay.addLayout(top)
        self.review = ReviewPanel(embedder_factory=self._get_embedder)
        self.review.changed.connect(self._mark_dirty)
        lay.addWidget(self.review, 1)
        self.qa_box = self.review.qa_box
        self.qa_box.setVisible(self.cb_qa.isChecked())

        out = QHBoxLayout()
        self.out_label = QLabel()
        self.out_label.setObjectName("muted")
        choose = QPushButton("Output folder…")
        choose.clicked.connect(self.choose_output)
        self.export_btn = QPushButton("Export PDF · TXT · SRT · Anki")
        self.export_btn.setObjectName("primary")
        self.export_btn.clicked.connect(self.export)
        self.open_pdf_btn = QPushButton("Open PDF")
        self.open_pdf_btn.clicked.connect(self.open_pdf)
        self.open_dir_btn = QPushButton("Open folder")
        self.open_dir_btn.clicked.connect(lambda: self._open_local(self.output_dir()))
        out.addWidget(choose)
        out.addWidget(self.out_label, 1)
        out.addWidget(self.open_dir_btn)
        out.addWidget(self.open_pdf_btn)
        out.addWidget(self.export_btn)
        lay.addWidget(card(out))
        self._update_out_label()
        return w

    # ================================================================ actions
    def set_status(self, msg: str) -> None:
        self.status.setText(msg)
        if hasattr(self, "statusBar"):
            self.statusBar().showMessage(msg, 8000)

    def add_files(self, paths: list[str]) -> None:
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                it = QListWidgetItem(f"{Path(p).name}   —  waiting")
                it.setData(Qt.UserRole, p)
                self.file_list.addItem(it)
        self.set_status(f"{len(self.files)} file(s) ready.")
        self._refresh_buttons()

    def remove_selected(self) -> None:
        for it in self.file_list.selectedItems():
            self.files.remove(it.data(Qt.UserRole))
            self.file_list.takeItem(self.file_list.row(it))
        self._refresh_buttons()

    def clear_files(self) -> None:
        self.files.clear()
        self.file_list.clear()
        self._refresh_buttons()

    def set_chapter(self, paths: list[str]) -> None:
        self.chapter = paths[0] if paths else None
        if self.chapter:
            self.chapter_drop.hint.setText(f"✓ {Path(self.chapter).name}  — linked after transcription\n"
                                           "(click to choose a different file)")

    def change_project(self, name: str) -> None:
        self.settings.set_vocab(self.vocab.toPlainText())
        self.settings.select_project(name)
        if self.project.findText(self.settings.project) < 0:
            self.project.addItem(self.settings.project)
        self.project.setCurrentText(self.settings.project)
        self.vocab.setPlainText("\n".join(self.settings.vocab()))
        self.settings.save()

    def _collect_settings(self) -> None:
        s = self.settings
        s.model = self.model.currentData()
        s.timestamps, s.highlights = self.cb_ts.isChecked(), self.cb_hl.isChecked()
        s.notes_margin = self.cb_notes.isChecked()
        s.speakers, s.num_speakers = self.cb_spk.isChecked(), self.n_spk.value()
        s.qa_search = self.cb_qa.isChecked()
        s.set_vocab(self.vocab.toPlainText())
        s.save()

    def start(self) -> None:
        if self.worker or not self.files:
            return
        self._collect_settings()
        self.worker = TranscribeWorker(self.files, self.settings.model, self.settings.vocab(),
                                       chapter=self.chapter, model_factory=self.model_factory,
                                       embedder_factory=self.embedder_factory,
                                       ocr_factory=self.ocr_factory,
                                       speakers=self.settings.speakers,
                                       num_speakers=self.settings.num_speakers,
                                       speaker_embedder_factory=self.speaker_embedder_factory,
                                       vad=self.vad)
        self.worker.warning.connect(self._on_warning)
        self._warnings: list[str] = []
        self.worker.progress.connect(self._on_progress)
        self.worker.fileDone.connect(self._on_file_done)
        self.worker.fileFailed.connect(self._on_file_failed)
        self.worker.finished.connect(self._on_finished)
        self._batch = list(self.files)
        self._failures = 0
        self.steps.set_stage("hash")
        self.thread_ = start_in_thread(self, self.worker)
        self._refresh_buttons()

    def cancel(self) -> None:
        if self.worker:
            self.worker.cancel()
            self.set_status("Cancelling…")

    def _item(self, i: int) -> QListWidgetItem | None:
        path = self._batch[i]
        for r in range(self.file_list.count()):
            if self.file_list.item(r).data(Qt.UserRole) == path:
                return self.file_list.item(r)
        return None

    def _on_progress(self, i: int, stage: str, frac: float) -> None:
        n = len(self._batch)
        self.steps.set_stage(stage)
        step = StepBar.STAGE_TO_STEP.get(stage, 0)
        within = (step + (frac if stage == "transcribe" else 1.0 if stage == "done" else 0.0)) / 5
        self.progress.setValue(int(1000 * (i + min(1.0, within)) / n))
        label = {"speakers": "Identifying speakers", "chapter": "Reading chapter (OCR if scanned)", "embed": "Analysing topics",
                 "link": "Linking to chapter", "topics": "Finding topics", "analysis_done": "Finishing",
                 "hash": "Checking file", "extract": "Extracting audio",
                 "load_model": "Loading model (first run downloads it — may take a while)",
                 "transcribe": f"Transcribing… {frac * 100:.0f}%", "paragraphs": "Building paragraphs",
                 "done": "Done"}.get(stage, stage)
        self.set_status(f"[{i + 1}/{n}] {Path(self._batch[i]).name}: {label}")
        it = self._item(i)
        if it:
            it.setText(f"{Path(self._batch[i]).name}   —  {label}")

    def _on_file_done(self, i: int, res: dict) -> None:
        path = self._batch[i]
        self.results[path] = res
        it = self._item(i)
        if it:
            it.setText(f"{Path(path).name}   —  ✓ done ({len(res['paragraphs'])} paragraphs)")
        if self.result_pick.findData(path) < 0:
            self.result_pick.addItem(Path(path).name, path)

    def _on_warning(self, msg: str) -> None:
        self._warnings.append(msg)
        self.set_status(msg)

    def _on_file_failed(self, i: int, msg: str) -> None:
        self._failures += 1
        it = self._item(i)
        if it:
            it.setText(f"{Path(self._batch[i]).name}   —  ✗ {msg}")
        self.steps.set_stage(None)
        self.set_status(msg)

    def _on_finished(self) -> None:
        self.worker = None
        ok = len(self._batch) - self._failures
        if ok and not self._failures:
            self.steps.set_stage("done")
            self.progress.setValue(1000)
            extra = ("  Note: " + self._warnings[-1]) if self._warnings else ""
            self.set_status(f"Finished {ok} file(s). Open the Review tab to check and export.{extra}")
            self.tabs.setCurrentIndex(1)
        elif self._failures:
            self.set_status(f"Finished with problems: {ok} ok, {self._failures} failed. See the file list.")
        self._refresh_buttons()

    def clear_cache(self) -> None:
        if QMessageBox.question(self, "Clear cache", "Delete all cached transcripts? "
                                "Recordings will need to be transcribed again.") != QMessageBox.Yes:
            return
        n = cache.clear_all()
        self.set_status(f"Cache cleared ({n} item(s)).")

    # --------------------------------------------------------------- review/export
    def current_result(self) -> dict | None:
        return self.results.get(self.result_pick.currentData())

    def show_result(self, *_):
        self.review.set_result(self.current_result())
        self.dirty = False
        self._refresh_buttons()

    def _mark_dirty(self) -> None:
        self.dirty = True
        self._refresh_buttons()

    def save_edits(self) -> None:
        res = self.current_result()
        if not res:
            return
        try:
            save_edits(res)
            self.dirty = False
            self.statusBar().showMessage("Edits saved.", 5000)
        except Exception as e:  # noqa: BLE001
            log.exception("save edits failed")
            QMessageBox.warning(self, "Save failed", friendly_error(e))
        self._refresh_buttons()

    def revert(self) -> None:
        res = self.current_result()
        if not res or QMessageBox.question(self, "Revert", "Discard all edits for this recording?") \
                != QMessageBox.Yes:
            return
        revert_edits(res)
        orig = cache.read_json(res["file_hash"], f"transcript_{res['cache_key']}")
        if orig:
            orig["cache_key"] = res["cache_key"]
            for k in ("topics", "read_on_own", "chapter"):      # keep analysis, drop manual edits
                if k in res:
                    orig[k] = res[k]
            if res.get("chapter"):
                self._relink(orig)
            self.results[self.result_pick.currentData()] = orig
        self.show_result()

    def _relink(self, res: dict) -> None:
        """Re-run analysis (cached embeddings) after revert."""
        from app.analyze import analyze, load_chapter
        from app.embed import default_embedder
        try:
            emb = self.embedder_factory() if self.embedder_factory else default_embedder()
            ch = load_chapter(self.chapter, self.ocr_factory) if self.chapter else None
            analyze(res, emb, ch, res["chapter"]["name"] if ch else None)
        except Exception:  # noqa: BLE001
            log.exception("re-analysis failed")

    def _get_embedder(self):
        from app.embed import default_embedder
        return self.embedder_factory() if self.embedder_factory else default_embedder()

    def output_dir(self) -> Path:
        return Path(self.settings.output_dir) if self.settings.output_dir else default_output_dir()

    def _update_out_label(self) -> None:
        self.out_label.setText(f"Output: {self.output_dir()}")

    def choose_output(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Choose output folder", str(self.output_dir()))
        if d:
            self.settings.output_dir = d
            self.settings.save()
            self._update_out_label()

    def pdf_options(self) -> PdfOptions:
        return PdfOptions(timestamps=self.cb_ts.isChecked(), notes_margin=self.cb_notes.isChecked(),
                          highlights=self.cb_hl.isChecked(), speakers=True)

    def export(self) -> None:
        res = self.current_result()
        if not res or self.worker:
            return
        if self.dirty:
            self.save_edits()
        self._collect_settings()
        self.worker = ExportWorker([res], str(self.output_dir()), self.pdf_options(), {"txt", "srt", "pdf", "anki"})
        self.worker.done.connect(self._on_exported)
        self.worker.failed.connect(self._on_export_failed)
        self.worker.finished.connect(self._on_export_finished)
        self.statusBar().showMessage("Exporting…")
        self.thread_ = start_in_thread(self, self.worker)
        self._refresh_buttons()

    def _on_exported(self, paths: list[str]) -> None:
        self.last_pdf = next((p for p in paths if p.endswith(".pdf")), None)
        self.statusBar().showMessage(f"Exported {len(paths)} file(s) to {self.output_dir()}", 10000)

    def _on_export_failed(self, msg: str) -> None:
        QMessageBox.warning(self, "Export failed", msg)

    def _on_export_finished(self) -> None:
        self.worker = None
        self._refresh_buttons()

    def open_pdf(self) -> None:
        if self.last_pdf:
            self._open_local(Path(self.last_pdf))

    def _open_local(self, path: Path) -> None:
        """Open only local files/folders we produced (never URLs)."""
        path = Path(path)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    # --------------------------------------------------------------- misc
    def _refresh_buttons(self) -> None:
        busy = self.worker is not None
        self.start_btn.setEnabled(bool(self.files) and not busy)
        self.cancel_btn.setEnabled(busy and isinstance(self.worker, TranscribeWorker))
        self.clear_cache_btn.setEnabled(not busy)
        has = self.current_result() is not None
        self.export_btn.setEnabled(has and not busy)
        self.save_btn.setEnabled(has and self.dirty)
        self.revert_btn.setEnabled(has)
        self.open_pdf_btn.setEnabled(bool(self.last_pdf) and not busy)

    def apply_theme(self) -> None:
        QApplication.instance().setStyleSheet(stylesheet(self.settings.theme))
        self.theme_btn.setText("☀ Light" if self.settings.theme == "dark" else "☾ Dark")

    def toggle_theme(self) -> None:
        self.settings.theme = "light" if self.settings.theme == "dark" else "dark"
        self.settings.save()
        self.apply_theme()

    def closeEvent(self, e):
        if self.worker and isinstance(self.worker, TranscribeWorker):
            if QMessageBox.question(self, "Quit", "A transcription is running. Quit anyway? "
                                    "Progress is saved and will resume next time.") != QMessageBox.Yes:
                e.ignore()
                return
            self.worker.cancel()
            if getattr(self, "thread_", None):
                self.thread_.wait(5000)
        self._collect_settings()
        e.accept()


def run() -> int:
    from app.cli import setup_logging
    from app.media import cleanup_temp
    setup_logging()
    cleanup_temp()
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("LectureScribe")
    win = MainWindow()
    win.show()
    return app.exec()
