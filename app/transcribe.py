"""faster-whisper transcription: model download (HTTPS, pinned), device choice, prompts."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol

from app import config

log = logging.getLogger(__name__)
_SHA = re.compile(r"^[0-9a-f]{40}$")
PROMPT_MAX_CHARS = 600


class WhisperLike(Protocol):
    def transcribe(self, audio: Any, **kwargs: Any) -> tuple[Iterable[Any], Any]: ...


# ---------------------------------------------------------------- prompt
def build_initial_prompt(headings: Iterable[str] = (), vocab: Iterable[str] = ()) -> str | None:
    """Chapter headings + custom vocabulary, de-duplicated and length-capped.

    A short bilingual lead-in nudges Whisper to keep English terms in Latin script
    inside Arabic speech instead of transliterating them.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for t in [*vocab, *headings]:
        t = re.sub(r"[\x00-\x1f\x7f]", " ", str(t))
        t = re.sub(r"\s+", " ", t).strip()[:80]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            terms.append(t)
    lead = "محاضرة بالعربي مع مصطلحات إنجليزية. Lecture in Arabic with English terms."
    if not terms:
        return lead
    out = lead + " " + ", ".join(terms)
    return out[:PROMPT_MAX_CHARS]


# ---------------------------------------------------------------- device
def pick_device() -> tuple[str, str]:
    try:
        import ctranslate2

        if ctranslate2.get_cuda_device_count() > 0:
            return "cuda", "float16"
    except Exception:  # noqa: BLE001 - any CUDA probing failure -> CPU
        log.info("CUDA not available, using CPU")
    return "cpu", "int8"


# ---------------------------------------------------------------- model files
def _lock_path() -> Path:
    return config.models_dir() / "lock.json"


def _read_lock() -> dict:
    try:
        return json.loads(_lock_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_lock(lock: dict) -> None:
    _lock_path().write_text(json.dumps(lock, indent=2), encoding="utf-8")


def _hash_files(folder: Path) -> dict[str, dict]:
    out = {}
    for f in sorted(folder.rglob("*")):
        if f.is_file():
            h = hashlib.sha256()
            with open(f, "rb") as fh:
                while b := fh.read(1 << 20):
                    h.update(b)
            out[f.relative_to(folder).as_posix()] = {"sha256": h.hexdigest(), "size": f.stat().st_size}
    return out


def ensure_model(name: str, allow_download: bool = True) -> Path:
    """Return a local folder for the model, downloading it over HTTPS if needed.

    Revision: the commit SHA from config, else the one recorded in lock.json on the
    first download. File SHA256s are recorded at first download and re-checked
    (by size on every load, full hash after every download).
    """
    registry = {**config.MODELS, **config.AUX_MODELS}
    if name not in registry:
        raise ValueError(f"Unknown model: {name}")
    if not config.HF_ENDPOINT.startswith("https://"):
        raise RuntimeError("Model endpoint must be HTTPS")
    spec = registry[name]
    lock = _read_lock()
    entry = lock.get(name, {})
    revision = spec["revision"] or entry.get("revision")

    from huggingface_hub import HfApi, snapshot_download

    common = dict(repo_id=spec["repo"], cache_dir=str(config.models_dir()),
                  allow_patterns=spec.get("patterns", config.MODEL_FILE_PATTERNS), endpoint=config.HF_ENDPOINT,
                  token=False)
    if revision and _SHA.match(revision):
        try:
            path = Path(snapshot_download(revision=revision, local_files_only=True, **common))  # nosec B615 - revision is a verified 40-hex SHA
            if _sizes_ok(path, entry.get("files")):
                return path
        except Exception:  # noqa: BLE001 - not cached yet
            log.info("Model %s not cached locally", name)
    if not allow_download:
        raise RuntimeError(f"Model '{name}' is not downloaded yet.")
    if not revision:
        revision = HfApi(endpoint=config.HF_ENDPOINT, token=False).model_info(spec["repo"], revision="main").sha
    if not revision or not _SHA.match(revision):
        raise RuntimeError("Could not pin model revision")
    log.info("Downloading model %s @ %s", spec["repo"], revision[:12])
    path = Path(snapshot_download(revision=revision, **common))  # nosec B615 - revision is a verified 40-hex SHA
    files = _hash_files(path)
    if not any(n.endswith(".safetensors") or n == "model.bin" for n in files):
        raise RuntimeError("Downloaded model is incomplete")
    if entry.get("revision") == revision and entry.get("files") and entry["files"] != files:
        raise RuntimeError("Model files do not match the recorded hashes")
    lock[name] = {"repo": spec["repo"], "revision": revision, "files": files}
    _write_lock(lock)
    return path


def _sizes_ok(path: Path, files: dict | None) -> bool:
    if not files:
        return False
    for fname, meta in files.items():
        f = path / fname
        if not f.is_file() or f.stat().st_size != meta.get("size"):
            return False
    return True


def load_model(name: str) -> WhisperLike:
    from faster_whisper import WhisperModel

    device, compute = pick_device()
    path = ensure_model(name)
    log.info("Loading model %s on %s/%s", name, device, compute)
    return WhisperModel(str(path), device=device, compute_type=compute)


# ---------------------------------------------------------------- transcription
def transcribe_audio(
    model: WhisperLike,
    audio: Any,
    *,
    offset: float = 0.0,
    initial_prompt: str | None = None,
    language: str | None = None,
    on_segment: Callable[[dict, float], None] | None = None,
) -> tuple[list[dict], dict]:
    """Run Whisper on a float32 16 kHz numpy array. Times are shifted by `offset`.

    on_segment(segment_dict, progress_0_to_1) is called after each segment so the
    caller can checkpoint (resume) and update progress.
    """
    segments_iter, info = model.transcribe(
        audio,
        language=language,          # None = auto-detect
        multilingual=True,          # per-segment language for Arabic/English code-switching
        task="transcribe",          # never translate
        vad_filter=True,
        word_timestamps=True,
        beam_size=5,
        initial_prompt=initial_prompt,
        condition_on_previous_text=False,   # limits hallucination loops
    )
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    out: list[dict] = []
    for s in segments_iter:
        words = [
            {"start": round(float(w.start) + offset, 3), "end": round(float(w.end) + offset, 3),
             "word": str(w.word), "p": round(float(getattr(w, "probability", 1.0)), 3)}
            for w in (getattr(s, "words", None) or [])
        ]
        seg = {"start": round(float(s.start) + offset, 3), "end": round(float(s.end) + offset, 3),
               "text": str(s.text).strip(), "words": words}
        out.append(seg)
        if on_segment:
            on_segment(seg, min(1.0, float(s.end) / duration) if duration else 0.0)
    meta = {"language": getattr(info, "language", None),
            "language_probability": float(getattr(info, "language_probability", 0.0) or 0.0)}
    return out, meta
