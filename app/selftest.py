"""Self-test for the frozen app: verifies every bundled component imports and works (no network)."""
from __future__ import annotations

import subprocess  # nosec B404 - fixed argv
import tempfile
import traceback
from pathlib import Path


def _check(name: str, fn, results: list) -> None:
    try:
        detail = fn() or ""
        results.append((name, True, str(detail)))
    except Exception as e:  # noqa: BLE001
        results.append((name, False, f"{type(e).__name__}: {e}"))
        traceback.print_exc()


def run_checks() -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def ffmpeg():
        from app.media import find_ffmpeg
        exe = find_ffmpeg()
        out = subprocess.run([exe, "-hide_banner", "-version"], capture_output=True, timeout=30,  # nosec B603
                             check=True).stdout.decode(errors="replace").splitlines()[0]
        return f"{exe} | {out[:60]}"

    def pdf():
        from app.pdf import build_pdf
        res = {"source_name": "selftest.mp3", "duration": 3, "model": "-", "created": "-",
               "paragraphs": [{"id": 0, "start": 0, "end": 3, "text": "اختبار (test 3.2) مهم", "rtl": True,
                               "emphasis": True}], "segments": []}
        with tempfile.TemporaryDirectory() as d:
            p = build_pdf(res, Path(d), "selftest.pdf")
            return f"{p.stat().st_size} bytes"

    def whisper():
        import ctranslate2
        import faster_whisper
        from faster_whisper.vad import get_speech_timestamps  # noqa: F401  (bundled silero ONNX)
        import numpy as np
        get_speech_timestamps(np.zeros(16000, dtype=np.float32))
        return f"faster-whisper {faster_whisper.__version__}, ctranslate2 {ctranslate2.__version__}, " \
               f"cuda devices {ctranslate2.get_cuda_device_count()}"

    def ocr():
        from rapidocr_onnxruntime import RapidOCR
        RapidOCR()
        return "models loaded"

    def torch_sb():
        import torch
        from speechbrain.lobes.features import Fbank
        from speechbrain.lobes.models.ECAPA_TDNN import ECAPA_TDNN  # noqa: F401
        Fbank(n_mels=80)(torch.zeros(1, 16000))
        return f"torch {torch.__version__}"

    def st():
        import sentence_transformers
        import sklearn.cluster  # noqa: F401
        return f"sentence-transformers {sentence_transformers.__version__}"

    def docs():
        import fitz
        import pptx  # noqa: F401
        return f"PyMuPDF {fitz.VersionBind}"

    for name, fn in [("ffmpeg", ffmpeg), ("pdf+fonts", pdf), ("whisper+vad", whisper), ("ocr", ocr),
                     ("torch+speechbrain", torch_sb), ("embeddings+sklearn", st), ("pdf/pptx parsers", docs)]:
        _check(name, fn, results)
    return results


def report(results) -> int:
    for name, ok, detail in results:
        print(f"[{'OK' if ok else 'FAIL'}] {name}: {detail}")
    bad = [r for r in results if not r[1]]
    print("SELFTEST " + ("PASSED" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1
