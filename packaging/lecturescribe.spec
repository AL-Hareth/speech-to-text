# PyInstaller spec — onedir build with two executables sharing one runtime:
#   LectureScribe.exe      (windowed GUI)
#   lecturescribe-cli.exe  (console: transcribe / clear-cache / selftest)
# Models are NOT bundled (downloaded on first use, pinned + hashed). ffmpeg + fonts + OCR models are bundled.
import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules, copy_metadata

ROOT = Path(SPECPATH).parent
IS_WIN = sys.platform == "win32"
FFMPEG = ROOT / "build" / "ffmpeg" / ("ffmpeg.exe" if IS_WIN else "ffmpeg")
if not FFMPEG.is_file():
    raise SystemExit(f"ffmpeg not found at {FFMPEG} (run packaging/get_ffmpeg.ps1 first)")

datas = [(str(ROOT / "app" / "assets" / "fonts"), "app/assets/fonts"),
         (str(ROOT / "THIRD_PARTY_NOTICES.md"), ".")]
binaries = [(str(FFMPEG), "ffmpeg")]
hiddenimports = [
    "app.ui.main_window", "app.cli", "app.selftest",
    "sklearn.cluster", "sklearn.utils._typedefs", "sklearn.neighbors._partition_nodes",
    "speechbrain.lobes.models.ECAPA_TDNN", "speechbrain.lobes.features",
]
datas += collect_data_files("faster_whisper")            # silero VAD ONNX
datas += collect_data_files("rapidocr_onnxruntime")      # OCR ONNX models + config.yaml
for pkg in ("speechbrain", "sentence_transformers"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
hiddenimports += collect_submodules("transformers.models.bert")
hiddenimports += collect_submodules("transformers.models.xlm_roberta")
# packages that look up their own / their deps' versions via importlib.metadata at import time
for pkg in ("transformers", "sentence-transformers", "speechbrain", "huggingface-hub", "tokenizers",
            "safetensors", "torch", "tqdm", "regex", "numpy", "filelock", "packaging", "pyyaml",
            "faster-whisper", "ctranslate2", "scikit-learn", "hyperpyyaml", "rapidocr-onnxruntime"):
    try:
        datas += copy_metadata(pkg)
    except Exception as e:  # noqa: BLE001
        print(f"metadata not found for {pkg}: {e}")

excludes = ["tkinter", "matplotlib", "IPython", "jupyter", "notebook", "pytest", "bandit", "pip_audit",
            "torch.utils.tensorboard", "tensorboard", "PySide6.QtWebEngineCore", "PySide6.QtQuick",
            "PySide6.QtQml", "PySide6.QtPdf", "PySide6.QtMultimedia"]


def analysis(script):
    return Analysis([str(ROOT / script)], pathex=[str(ROOT)], binaries=binaries, datas=datas,
                    hiddenimports=hiddenimports, excludes=excludes, noarchive=False,
                    hookspath=[], runtime_hooks=[])


a_gui = analysis("lecturescribe.py")
a_cli = analysis("lecturescribe_cli.py")
pyz_gui = PYZ(a_gui.pure)
pyz_cli = PYZ(a_cli.pure)
exe_gui = EXE(pyz_gui, a_gui.scripts, [], exclude_binaries=True, name="LectureScribe",
              console=False, upx=False, disable_windowed_traceback=False)
exe_cli = EXE(pyz_cli, a_cli.scripts, [], exclude_binaries=True, name="lecturescribe-cli",
              console=True, upx=False)
coll = COLLECT(exe_gui, a_gui.binaries, a_gui.datas, exe_cli, a_cli.binaries, a_cli.datas,
               upx=False, name="LectureScribe")
