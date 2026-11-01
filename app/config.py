"""Paths, limits and model registry. No secrets live here (none are needed)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "LectureScribe"

# Disable any library telemetry before huggingface_hub / others are imported.
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
os.environ.setdefault("DO_NOT_TRACK", "1")

# ---- Size / duration limits for untrusted inputs -------------------------
MAX_MEDIA_BYTES = 4 * 1024**3        # 4 GB audio/video
MAX_PDF_BYTES = 200 * 1024**2        # 200 MB
MAX_PPTX_BYTES = 200 * 1024**2       # 200 MB (compressed)
MAX_MEDIA_SECONDS = 6 * 3600         # 6 h of audio
FFMPEG_TIMEOUT_S = 3600

# ---- Whisper models (downloaded on first use, never bundled) -------------
# revision MUST be a 40-hex commit SHA before release. While None, the first
# download is resolved to its commit SHA and recorded in models/lock.json
# (trust-on-first-use); later loads verify file SHA256s against that lock.
MODELS: dict[str, dict] = {
    "small": {"repo": "Systran/faster-whisper-small", "revision": None},
    "medium": {"repo": "Systran/faster-whisper-medium", "revision": None},
    "large-v3": {"repo": "Systran/faster-whisper-large-v3", "revision": None},
}
DEFAULT_MODEL = "medium"
MODEL_FILE_PATTERNS = [
    "config.json", "model.bin", "tokenizer.json",
    "vocabulary.json", "vocabulary.txt", "preprocessor_config.json",
]
HF_ENDPOINT = "https://huggingface.co"

# Auxiliary models (same download/lock mechanism). Weights: safetensors ONLY (no pickle .bin).
AUX_MODELS: dict[str, dict] = {
    "embedder": {
        "repo": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "revision": None,
        "patterns": ["config.json", "modules.json", "sentence_bert_config.json",
                     "config_sentence_transformers.json", "model.safetensors", "tokenizer.json",
                     "tokenizer_config.json", "special_tokens_map.json", "sentencepiece.bpe.model",
                     "1_Pooling/config.json"],
        "required": ["model.safetensors", "modules.json"],
    },
    # ECAPA-TDNN speaker embeddings. Only the weights are fetched (no HyperPyYAML -> no code exec);
    # loaded with torch.load(weights_only=True) (restricted unpickler, tensors only).
    "ecapa": {
        "repo": "speechbrain/spkrec-ecapa-voxceleb", "revision": None,
        "patterns": ["embedding_model.ckpt"], "required": ["embedding_model.ckpt"],
    },
}
MAX_SPEAKERS = 8

# ---- Chapter parsing limits -----------------------------------------------
MAX_CHAPTER_PAGES = 400
MAX_OCR_PAGES = 60
MAX_CHAPTER_CHARS = 2_000_000
PPTX_MAX_ENTRIES = 5000
PPTX_MAX_UNCOMPRESSED = 600 * 1024**2
PPTX_MAX_RATIO = 120

# ---- Linking thresholds (cosine similarity) --------------------------------
LINK_SURE = 0.50
LINK_UNSURE = 0.35

# ---- Paragraphing ---------------------------------------------------------
PARAGRAPH_PAUSE_S = 1.5
PARAGRAPH_MAX_WORDS = 140


def data_dir() -> Path:
    """%LOCALAPPDATA%\\LectureScribe on Windows; XDG-ish fallback elsewhere."""
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    p = Path(base) / APP_NAME
    p.mkdir(parents=True, exist_ok=True)
    return p


def sub_dir(name: str) -> Path:
    p = data_dir() / name
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    return sub_dir("cache")


def models_dir() -> Path:
    return sub_dir("models")


def temp_dir() -> Path:
    return sub_dir("tmp")


def logs_dir() -> Path:
    return sub_dir("logs")


def resource_dir() -> Path:
    """Folder holding bundled resources (PyInstaller _MEIPASS or repo root)."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
