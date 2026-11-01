"""Background jobs (QThread): transcription batch and export. UI never blocks."""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QCoreApplication, QObject, QThread, Signal, Slot

from app.export import to_srt, to_txt, write_text
from app.pipeline import process_file
from app.errors import friendly_error  # noqa: F401 (re-export)
from app.security import InputError, safe_filename
from app.transcribe import load_model

log = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


def _return_home(obj: QObject) -> None:
    """Called from the worker's own thread just before finishing: move it back to the GUI thread."""
    app = QCoreApplication.instance()
    if app is not None and obj.thread() is not app.thread():
        obj.moveToThread(app.thread())


_MODELS: dict[str, object] = {}
_MODEL_LOCK = threading.Lock()


def cached_model(name: str):
    """Keep the loaded model for the session (loading large-v3 takes a while)."""
    with _MODEL_LOCK:
        if name not in _MODELS:
            _MODELS.clear()                       # only one model in memory at a time
            _MODELS[name] = load_model(name)
        return _MODELS[name]


class TranscribeWorker(QObject):
    progress = Signal(int, str, float)
    fileDone = Signal(int, dict)
    fileFailed = Signal(int, str)
    warning = Signal(str)
    finished = Signal()

    def __init__(self, files: list[str], model: str, vocab: list[str],
                 chapter: str | None = None,
                 model_factory: Callable[[str], object] | None = None,
                 embedder_factory: Callable[[], object] | None = None,
                 ocr_factory: Callable[[], object] | None = None,
                 speakers: bool = False, num_speakers: int = 0,
                 speaker_embedder_factory: Callable[[], object] | None = None, vad=None):
        super().__init__()
        self.speakers, self.num_speakers = speakers, num_speakers
        self.speaker_embedder_factory, self.vad = speaker_embedder_factory, vad
        self.files, self.model, self.vocab = list(files), model, list(vocab)
        self.chapter = chapter
        self.model_factory = model_factory or cached_model
        self.embedder_factory = embedder_factory
        self.ocr_factory = ocr_factory
        self._cancel = threading.Event()

    def _load_chapter(self):
        from app.analyze import load_chapter
        self.progress.emit(0, "chapter", 0.0)
        try:
            return load_chapter(self.chapter, self.ocr_factory)
        except InputError as e:
            self.warning.emit(f"Chapter skipped: {e}")
        except Exception as e:  # noqa: BLE001
            log.exception("chapter parse failed")
            self.warning.emit(f"Chapter skipped: {friendly_error(e)}")
        return None

    def _embedder(self):
        if self.embedder_factory:
            return self.embedder_factory()
        from app.embed import default_embedder
        return default_embedder()

    def _analyze(self, i: int, src: str, res: dict, chapter) -> None:
        from app.analyze import enrich
        enrich(res, src, embedder_factory=self._embedder, speakers=self.speakers,
               num_speakers=self.num_speakers, speaker_embedder_factory=self.speaker_embedder_factory,
               chapter=chapter, chapter_name=Path(self.chapter).name if chapter else None,
               progress=lambda st, fr: self.progress.emit(i, st, fr), warn=self.warning.emit, vad=self.vad)

    def cancel(self) -> None:
        self._cancel.set()

    @Slot()
    def run(self) -> None:
        try:
            chapter = self._load_chapter() if self.chapter else None
            from app.chapter import headings
            hd = headings(chapter[1]) if chapter else []
            for i, f in enumerate(self.files):
                if self._cancel.is_set():
                    break

                def prog(stage: str, frac: float, _i=i) -> None:
                    if self._cancel.is_set():
                        raise Cancelled()
                    if stage != "done":                      # 'done' is emitted after analysis
                        self.progress.emit(_i, stage, float(frac))

                try:
                    res = process_file(f, model_name=self.model, vocab=self.vocab,
                                       headings=hd, progress=prog,
                                       model_factory=self.model_factory)
                    if self._cancel.is_set():
                        raise Cancelled()
                    self._analyze(i, f, res, chapter)
                    self.progress.emit(i, "done", 1.0)
                    self.fileDone.emit(i, res)
                except Cancelled:
                    self.fileFailed.emit(i, "Cancelled — progress was saved and will resume next time.")
                    break
                except Exception as e:  # noqa: BLE001 - reported to the user
                    log.exception("transcription failed (file #%d)", i)
                    self.fileFailed.emit(i, friendly_error(e))
        finally:
            _return_home(self)
            self.finished.emit()


class ExportWorker(QObject):
    done = Signal(list)
    failed = Signal(str)
    finished = Signal()

    def __init__(self, results: list[dict], out_dir: str, opts, formats: set[str]):
        super().__init__()
        self.results, self.out_dir, self.opts, self.formats = results, Path(out_dir), opts, formats

    @Slot()
    def run(self) -> None:
        try:
            paths: list[str] = []
            for res in self.results:
                stem = safe_filename(Path(res.get("source_name", "lecture")).stem, default="lecture")
                if "txt" in self.formats:
                    paths.append(str(write_text(self.out_dir, stem + ".txt",
                                                to_txt(res["paragraphs"], self.opts.timestamps))))
                if "srt" in self.formats:
                    paths.append(str(write_text(self.out_dir, stem + ".srt", to_srt(res["segments"]))))
                if "anki" in self.formats and any(p.get("emphasis") for p in res["paragraphs"]):
                    from app.anki import write_anki
                    paths.append(str(write_anki(res, self.out_dir, stem + "_anki.csv")))
                if "pdf" in self.formats:
                    from app.pdf import build_pdf
                    paths.append(str(build_pdf(res, self.out_dir, stem + ".pdf", self.opts)))
            self.done.emit(paths)
        except Exception as e:  # noqa: BLE001
            log.exception("export failed")
            self.failed.emit(friendly_error(e))
        finally:
            _return_home(self)
            self.finished.emit()


def start_in_thread(owner: QObject, worker: QObject) -> QThread:
    """Run worker.run in a new QThread; cleans up automatically when finished."""
    th = QThread(owner)
    worker.moveToThread(th)
    th.started.connect(worker.run)
    worker.finished.connect(th.quit)
    th.finished.connect(th.deleteLater)
    # The worker is NOT deleteLater'd in its thread: it hands itself back to the GUI thread (see
    # _return_home) so Python can release it safely there. Avoids cross-thread destruction races.
    th.start()
    return th
