"""Phase 3: UI smoke test (offscreen): batch run in background thread, review edits, export, themes."""
from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from app.settings import Settings, clean_terms  # noqa: E402
from tests.test_phase1 import StubModel, _gen  # noqa: E402


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _wait(qapp, cond, timeout=60):
    end = time.monotonic() + timeout
    while not cond():
        qapp.processEvents()
        if time.monotonic() > end:
            raise TimeoutError
        time.sleep(0.02)


def test_settings_roundtrip_and_validation(tmp_path):
    s = Settings()
    s.select_project("Bio 101")
    s.set_vocab("ReLU, backprop\nReLU\n=evil\x00")
    s.theme = "light"
    s.save()
    s2 = Settings.load()
    assert s2.project == "Bio 101" and s2.vocab() == ["ReLU", "backprop", "=evil"] and s2.theme == "light"
    Settings.path().write_text('{"theme": "<script>", "model": "x", "projects": {"a": {"vocab": [1, "ok"]}}}')
    s3 = Settings.load()
    assert s3.theme == "dark" and s3.model == "medium" and s3.projects["a"]["vocab"] == ["ok"]
    assert len(clean_terms(["t"] * 1000 + [f"x{i}" for i in range(1000)])) == 300


def test_full_ui_flow(qapp, tmp_path, monkeypatch):
    from app.ui.main_window import MainWindow

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
    s = Settings()
    s.output_dir = str(tmp_path / "out")
    win = MainWindow(settings=s, model_factory=lambda n: StubModel())
    win.show()
    a = _gen(tmp_path / "a.mp3", False)
    v = _gen(tmp_path / "b.mp4", True)
    (tmp_path / "x.exe").write_bytes(b"MZ")
    win.media_drop.filesDropped.emit(win.media_drop._filter([str(a), str(v), str(tmp_path / "x.exe")]))
    assert win.files == [str(a), str(v)]
    win.vocab.setPlainText("backpropagation\nReLU")
    win.start()
    assert win.worker is not None                       # runs in background
    _wait(qapp, lambda: win.worker is None)
    assert len(win.results) == 2 and win.tabs.currentIndex() == 1
    assert win.result_pick.count() == 2

    # review: edit text + speaker, search
    t = win.review.table
    t.item(0, 2).setText("Edited  paragraph about ReLU")
    t.item(0, 1).setText("Doctor")
    assert win.dirty and win.save_btn.isEnabled()
    win.review.search.setText("relu")
    assert not t.isRowHidden(0) and sum(not t.isRowHidden(r) for r in range(t.rowCount())) >= 1
    win.save_edits()
    res = win.current_result()
    assert res["segments"][0]["text"] == "Edited paragraph about ReLU" and res["segments"][0]["speaker"] == "Doctor"

    # re-processing returns the edited version from cache
    from app.pipeline import process_file
    again = process_file(win.result_pick.currentData(), model_name=s.model, vocab=s.vocab(),
                         model_factory=lambda n: pytest.fail("cache expected"))
    assert again["paragraphs"][0]["text"] == "Edited paragraph about ReLU"

    # export in background
    win.export()
    _wait(qapp, lambda: win.worker is None)
    assert win.last_pdf and Path(win.last_pdf).is_file()
    assert {p.suffix for p in (tmp_path / "out").iterdir()} == {".pdf", ".txt", ".srt"}
    assert win.open_pdf_btn.isEnabled()

    # themes render; keep screenshots for visual review if requested
    keep = os.environ.get("LS_UI_CHECK_DIR")
    for theme in ("dark", "light"):
        win.settings.theme = theme
        win.apply_theme()
        for tab in (0, 1):
            win.tabs.setCurrentIndex(tab)
            qapp.processEvents()
            img = win.grab()
            assert not img.isNull()
            if keep:
                Path(keep).mkdir(parents=True, exist_ok=True)
                img.save(str(Path(keep) / f"{theme}_tab{tab}.png"))
    win.revert()
    assert win.current_result()["paragraphs"][0]["text"] != "Edited paragraph about ReLU"
    win.close()


def test_cancel_and_friendly_errors(qapp, tmp_path, monkeypatch):
    from app.ui.main_window import MainWindow
    from app.ui.worker import friendly_error
    from app.security import InputError

    assert friendly_error(InputError("File too large")) == "File too large"
    assert "internet" in friendly_error(ConnectionError("x"))
    assert "secret transcript" not in friendly_error(ValueError("secret transcript"))

    class Slow(StubModel):
        def transcribe(self, audio, **kw):
            segs, info = super().transcribe(audio, **kw)

            def slow():
                for s in segs:
                    time.sleep(0.3)
                    yield s
            return slow(), info

    win = MainWindow(settings=Settings(), model_factory=lambda n: Slow())
    win.add_files([str(_gen(tmp_path / "c.wav", False))])
    win.start()
    _wait(qapp, lambda: "Transcribing" in win.status.text())
    win.cancel()
    _wait(qapp, lambda: win.worker is None)
    assert "Cancelled" in win.file_list.item(0).text()
    win.close()
