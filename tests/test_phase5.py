"""Phase 5: emphasis, Anki CSV, Q&A, speaker identification (stub + real ECAPA architecture), UI."""
from __future__ import annotations

import csv
import io
import os
import time
from pathlib import Path

import numpy as np
import pytest

from app.anki import to_anki_csv
from app.diarize import apply_speakers, diarize_audio
from app.emphasis import find_emphasis, mark_emphasis
from app.qa import TranscriptIndex
from tests.helpers import HashEmbedder

SR = 16000


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))


# ------------------------------------------------------------------ emphasis
@pytest.mark.parametrize("text", [
    "هاد الموضوع مهم كتير", "ركزوا معي هون", "انتبهوا لهاي النقطة", "هاد بيجي بالامتحان",
    "رح يجي سؤال عليه", "لازم تحفظوا التعريف", "This is important", "for the exam", "Remember this",
    "the key idea", "note that", "don't forget the sign", "مُهِمّة جداً", "هاي النقطة مهمه",
])
def test_emphasis_hits(text):
    assert find_emphasis(text)


@pytest.mark.parametrize("text", ["the keyboard and notebook", "هلأ رح نحكي عن ال network",
                                  "examples of keys", "importantly-ish? no: unimportant"])
def test_emphasis_misses(text):
    assert not find_emphasis(text)


# ------------------------------------------------------------------ anki + qa
def _result():
    paras = [
        {"id": 0, "start": 0, "end": 10, "text": "هلأ رح نحكي عن ال neural network"},
        {"id": 1, "start": 75, "end": 90, "text": "=HYPERLINK(\"http://evil\") انتبهوا لل learning rate مهم"},
        {"id": 2, "start": 130, "end": 140, "text": "the gradient descent update rule, remember it"},
        {"id": 3, "start": 200, "end": 210, "text": "-2+3 cmd|' /C calc'!A0 for the exam"},
    ]
    return {"file_hash": "cd" * 32, "paragraphs": paras, "segments": [],
            "topics": [{"title": "Intro", "start_para": 0}, {"title": "Optimisation", "start_para": 2}]}


def test_anki_csv_safe():
    res = _result()
    assert mark_emphasis(res) == 3
    text = to_anki_csv(res)
    assert text.startswith("#separator:Comma\n#html:false\n")
    rows = list(csv.reader(io.StringIO("\n".join(text.splitlines()[3:]))))
    assert len(rows) == 3
    assert rows[0][0].startswith("[01:15] · Intro") and rows[0][1].startswith("'=HYPERLINK")
    assert rows[2][1].startswith("'-2+3") and rows[1][0].startswith("[02:10] · Optimisation")
    for r in rows:
        for cell in r:
            assert cell[0] not in "=+-@" or cell.startswith("'")


def test_qa_search():
    idx = TranscriptIndex(_result(), HashEmbedder())
    hits = idx.search("what is the learning rate?")
    assert hits and hits[0]["para"] == 1 and hits[0]["start"] == 75
    assert idx.search("") == []
    assert all(h["score"] >= 0.25 for h in idx.search("gradient descent update"))


# ------------------------------------------------------------------ diarization (stub embedder)
def two_voices(pattern=("A", "B", "A", "B"), seg_s=4.0, gap_s=0.6):
    t = np.arange(int(seg_s * SR)) / SR
    voice = {"A": 0.3 * np.sin(2 * np.pi * 180 * t), "B": 0.3 * np.sin(2 * np.pi * 1100 * t)}
    parts, truth, pos = [], [], 0.0
    for p in pattern:
        parts += [voice[p], np.zeros(int(gap_s * SR))]
        truth.append((pos, pos + seg_s, p))
        pos += seg_s + gap_s
    return np.concatenate(parts).astype(np.float32), truth


def energy_vad(audio):
    frame = int(0.03 * SR)
    on = [np.sqrt(np.mean(audio[i:i + frame] ** 2)) > 0.02 for i in range(0, len(audio) - frame, frame)]
    regions, start = [], None
    for k, v in enumerate(on + [False]):
        if v and start is None:
            start = k
        elif not v and start is not None:
            regions.append((start * frame / SR, k * frame / SR))
            start = None
    return regions


class SpectrumEmbedder:
    name = "spectrum-test"

    def embed(self, windows):
        spec = np.abs(np.fft.rfft(windows, axis=1))
        bands = np.stack([spec[:, b:b + 200].sum(1) for b in range(0, 4000, 200)], axis=1)
        return bands / (np.linalg.norm(bands, axis=1, keepdims=True) + 1e-9)


@pytest.mark.parametrize("n", [None, 2])
def test_diarize_two_speakers(n):
    audio, truth = two_voices()
    turns = diarize_audio(audio, SpectrumEmbedder(), n, vad=energy_vad)
    assert [t["speaker"] for t in turns] == ["Speaker 1", "Speaker 2", "Speaker 1", "Speaker 2"]
    for t, (a, b, _) in zip(turns, truth):
        assert abs(t["start"] - a) < 0.8 and abs(t["end"] - b) < 0.8


def test_apply_speakers_splits_segments():
    turns = [{"start": 0, "end": 4.2, "speaker": "Speaker 1"}, {"start": 4.6, "end": 9, "speaker": "Speaker 2"}]
    words = [{"start": 3.0, "end": 3.5, "word": " first"}, {"start": 3.6, "end": 4.0, "word": " part"},
             {"start": 4.7, "end": 5.0, "word": " second"}, {"start": 5.1, "end": 5.4, "word": " part"}]
    res = {"segments": [{"start": 3.0, "end": 5.4, "text": "first part second part", "words": words}],
           "paragraphs": []}
    apply_speakers(res, turns)
    assert [(s["speaker"], s["text"]) for s in res["segments"]] == [("Speaker 1", "first part"),
                                                                     ("Speaker 2", "second part")]
    assert [p["speaker"] for p in res["paragraphs"]] == ["Speaker 1", "Speaker 2"]
    assert res["speakers"] == ["Speaker 1", "Speaker 2"]


# ------------------------------------------------------------------ real ECAPA architecture
def test_ecapa_loader_weights_only(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    pytest.importorskip("speechbrain")
    from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN

    from app import diarize, transcribe

    m = ECAPA_TDNN(80, channels=[1024, 1024, 1024, 1024, 3072], kernel_sizes=[5, 3, 3, 3, 1],
                   dilations=[1, 2, 3, 4, 1], attention_channels=128, lin_neurons=192)
    torch.save(m.state_dict(), tmp_path / "embedding_model.ckpt")
    monkeypatch.setattr(transcribe, "ensure_model", lambda name, **k: tmp_path)
    emb = diarize.EcapaEmbedder()
    audio, _ = two_voices()
    windows, spans = diarize.make_windows(audio, energy_vad(audio))
    v = emb.embed(windows)
    assert v.shape == (len(spans), 192) and np.isfinite(v).all()

    # a malicious pickle checkpoint must be refused by the weights_only loader
    class Evil:
        def __reduce__(self):
            return (os.system, ("echo pwned",))
    bad = tmp_path / "bad"
    bad.mkdir()
    torch.save({"x": Evil()}, bad / "embedding_model.ckpt", _use_new_zipfile_serialization=True)
    monkeypatch.setattr(transcribe, "ensure_model", lambda name, **k: bad)
    with pytest.raises(Exception, match="(?i)weights_only|unpickl|unsupported"):
        diarize.EcapaEmbedder()


# ------------------------------------------------------------------ UI
def test_ui_speakers_qa_anki(tmp_path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import wave

    from PySide6.QtWidgets import QApplication

    from app.settings import Settings
    from app.ui.main_window import MainWindow
    from app.ui.review import COL_SPK
    from tests.test_phase1 import StubModel

    qapp = QApplication.instance() or QApplication([])
    audio, _ = two_voices(("A", "B", "A", "B", "A"))
    wav = tmp_path / "talk.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((audio * 32767).astype("<i2").tobytes())
    s = Settings()
    s.output_dir = str(tmp_path / "out")
    s.speakers, s.num_speakers = True, 0
    win = MainWindow(settings=s, model_factory=lambda n: StubModel(), embedder_factory=HashEmbedder,
                     speaker_embedder_factory=SpectrumEmbedder, vad=energy_vad)
    assert win.cb_spk.isChecked() and win.n_spk.isEnabled() and not win.qa_box.isHidden()
    win.add_files([str(wav)])
    win.start()
    end = time.monotonic() + 60
    while win.worker is not None and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)
    res = win.current_result()
    assert res["diarization"] == {"num_speakers": 0}
    spk = [p.get("speaker") for p in res["paragraphs"]]
    assert {"Speaker 1", "Speaker 2"} <= set(spk)
    assert any(p.get("emphasis") for p in res["paragraphs"])         # "مهم بالامتحان" in stub text
    # re-assign a paragraph's speaker through the table, then rename
    win.review.table.item(0, COL_SPK).setText("Doctor")
    assert res["paragraphs"][0]["speaker"] == "Doctor" and win.dirty
    # Q&A panel
    win.review.ask.setText("backpropagation")
    win.review.run_question()
    first = win.review.answers.item(0)
    assert first is not None and "backpropagation" in first.text().lower()
    win.review._jump(first)
    # export incl. Anki CSV
    win.export()
    end = time.monotonic() + 60
    while win.worker is not None and time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.02)
    out = {p.suffix for p in (tmp_path / "out").iterdir()}
    assert {".pdf", ".txt", ".srt", ".csv"} <= out
    srt = next((tmp_path / "out").glob("*.srt")).read_text(encoding="utf-8")
    assert "Doctor:" in srt and "Speaker 2:" in srt
    keep = os.environ.get("LS_UI_CHECK_DIR")
    if keep:
        win.resize(1200, 800)
        win.tabs.setCurrentIndex(1)
        qapp.processEvents()
        win.grab().save(str(Path(keep) / "review_speakers_qa.png"))
        win.tabs.setCurrentIndex(0)
        qapp.processEvents()
        win.grab().save(str(Path(keep) / "setup_p5.png"))
    win.close()
