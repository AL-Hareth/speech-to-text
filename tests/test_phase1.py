"""Phase 1 tests: ffmpeg extraction (audio+video), pipeline w/ stub model, cache/resume, exports, security."""
from __future__ import annotations

import subprocess  # nosec B404
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import cache, media, pipeline
from app.export import to_srt, to_txt, write_text
from app.paragraphs import build_paragraphs, is_rtl
from app.security import InputError, csv_safe, safe_filename, safe_join
from app.transcribe import build_initial_prompt

FF = media.find_ffmpeg()


@pytest.fixture(autouse=True)
def appdata(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "appdata"))
    return tmp_path


def _gen(path: Path, video: bool, seconds: int = 30) -> Path:
    args = [FF, "-nostdin", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}"]
    if video:
        args += ["-f", "lavfi", "-i", f"testsrc=size=160x120:rate=5:duration={seconds}",
                 "-c:v", "mpeg4", "-shortest"]
    subprocess.run([*args, str(path)], check=True)  # nosec B603
    return path


class StubModel:
    """Mimics faster_whisper.WhisperModel.transcribe output (no download needed)."""

    def __init__(self, fail_after: int | None = None):
        self.fail_after, self.calls = fail_after, []

    def transcribe(self, audio, **kw):
        self.calls.append({**kw, "n": len(audio)})
        dur = len(audio) / 16000
        texts = ["هلأ رح نحكي عن ال", "neural network", "وهاد مهم بالامتحان (section 3.2).",
                 "Next we discuss backpropagation.", "يعني ال gradient descent بيشتغل هيك"]

        def gen():
            t = 0.0
            for i, txt in enumerate(texts):
                if self.fail_after is not None and i == self.fail_after:
                    raise KeyboardInterrupt("simulated crash")
                start, end = t, min(dur, t + 4)
                w = SimpleNamespace(start=start, end=end, word=txt, probability=0.9)
                yield SimpleNamespace(start=start, end=end, text=" " + txt, words=[w])
                t = end + (2.0 if i == 2 else 0.3)
        return gen(), SimpleNamespace(duration=dur, language="ar", language_probability=0.8)


@pytest.mark.parametrize("ext,video", [(".mp3", False), (".m4a", False), (".mp4", True), (".mkv", True)])
def test_extract_audio_and_temp_cleanup(tmp_path, ext, video):
    src = _gen(tmp_path / f"in{ext}", video)
    with media.temp_audio(src) as wav:
        assert 29.0 < media.wav_duration(wav) < 31.0
        kept = wav
    assert not kept.exists()


def test_reject_bad_inputs(tmp_path):
    (tmp_path / "x.exe").write_bytes(b"MZ")
    with pytest.raises(InputError):
        media.validate_media(tmp_path / "x.exe")
    with pytest.raises(InputError):
        media.validate_media(tmp_path / "missing.mp3")
    (tmp_path / "empty.mp3").write_bytes(b"")
    with pytest.raises(InputError):
        media.validate_media(tmp_path / "empty.mp3")
    (tmp_path / "junk.mp3").write_bytes(b"not audio at all" * 100)
    with pytest.raises(InputError):
        media.extract_audio(tmp_path / "junk.mp3")
    assert not list((Path(media.config.temp_dir())).glob("ls_*.wav"))


def test_ffmpeg_blocks_network_playlist(tmp_path):
    # A playlist disguised as .mp4 must not make ffmpeg open network URLs.
    evil = tmp_path / "evil.mp4"
    evil.write_text("#EXTM3U\n#EXT-X-TARGETDURATION:1\n#EXTINF:1,\nhttp://127.0.0.1:9/a.ts\n#EXT-X-ENDLIST\n")
    with pytest.raises(InputError):
        media.extract_audio(evil)


def test_pipeline_cache_and_resume(tmp_path):
    src = _gen(tmp_path / "lec.mp4", True)
    # 1) crash mid-way -> partial checkpoint saved
    pipeline.CHECKPOINT_EVERY_S = 0.0
    with pytest.raises(KeyboardInterrupt):
        pipeline.process_file(src, model_name="small", vocab=["backpropagation"],
                              model_factory=lambda n: StubModel(fail_after=3))
    # 2) resume: model called with the remaining audio only
    stub = StubModel()
    res = pipeline.process_file(src, model_name="small", vocab=["backpropagation"],
                                model_factory=lambda n: stub)
    assert "backpropagation" in stub.calls[0]["initial_prompt"]
    assert stub.calls[0]["vad_filter"] and stub.calls[0]["word_timestamps"]
    assert stub.calls[0]["task"] == "transcribe" and stub.calls[0]["language"] is None
    assert stub.calls[0]["n"] < 25 * 16000              # resumed, not restarted
    assert len(res["segments"]) == 3 + 5
    assert res["segments"][3]["start"] >= res["segments"][2]["end"]   # offset applied
    assert len(res["paragraphs"]) >= 2
    # 3) cached: no model load at all
    res2 = pipeline.process_file(src, model_name="small", vocab=["backpropagation"],
                                 model_factory=lambda n: pytest.fail("should use cache"))
    assert res2 == res
    assert cache.clear_all() >= 1


def test_paragraphs_and_direction():
    segs = [{"start": 0, "end": 2, "text": "هلأ رح نحكي عن neural network"},
            {"start": 2.2, "end": 4, "text": "وهاد مهم."},
            {"start": 7, "end": 9, "text": "Now the English part."}]
    paras = build_paragraphs(segs)
    assert len(paras) == 2 and paras[0]["rtl"] and not paras[1]["rtl"]
    assert not is_rtl("") and is_rtl("مرحبا")


def test_exports(tmp_path):
    segs = [{"start": 0, "end": 1.5, "text": "line\n\nwith gaps", "speaker": "Doctor"},
            {"start": 65.25, "end": 70, "text": "second"}]
    srt = to_srt(segs)
    assert "00:00:00,000 --> 00:00:01,500" in srt and "Doctor: line with gaps" in srt
    assert "00:01:05,250" in srt
    txt = to_txt(build_paragraphs(segs))
    assert "[01:05] second" in txt
    p = write_text(tmp_path, "../../evil.txt", txt)
    assert p.parent == tmp_path.resolve() and p.name == "evil.txt"


def test_security_helpers(tmp_path):
    assert safe_filename("..\\..\\CON.txt") == "output_CON.txt"
    assert safe_filename("a/b/../c:d?.srt") == "c_d_.srt"
    assert safe_filename("...") == "output"
    assert safe_join(tmp_path, "../x").parent == tmp_path.resolve()
    assert csv_safe("=1+1") == "'=1+1" and csv_safe("@x") == "'@x" and csv_safe("ok") == "ok"


def test_prompt_builder():
    p = build_initial_prompt(["3.2 Backprop", "x\x00y"], ["CNN", "cnn"])
    assert "CNN" in p and p.lower().count("cnn") == 1 and "\x00" not in p
    assert len(build_initial_prompt(["t" * 80] * 100)) <= 600


def test_cache_rejects_traversal():
    with pytest.raises(ValueError):
        cache.write_json("../../etc", "x", {})
    with pytest.raises(ValueError):
        cache.write_json("a" * 64, "../x", {})
