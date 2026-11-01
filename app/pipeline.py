"""End-to-end job: media -> WAV -> transcript (cached, resumable) -> paragraphs."""
from __future__ import annotations

import logging
import time
import wave
from pathlib import Path
from typing import Callable

import numpy as np

from app import cache, config, media
from app.paragraphs import build_paragraphs
from app.transcribe import WhisperLike, build_initial_prompt, load_model, transcribe_audio

log = logging.getLogger(__name__)
Progress = Callable[[str, float], None]
CHECKPOINT_EVERY_S = 20.0


def read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise ValueError("unexpected WAV format")
        raw = w.readframes(w.getnframes())
    return np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0


def process_file(
    src: str | Path,
    model_name: str = config.DEFAULT_MODEL,
    vocab: list[str] | None = None,
    headings: list[str] | None = None,
    progress: Progress | None = None,
    model_factory: Callable[[str], WhisperLike] = load_model,
) -> dict:
    """Transcribe one file. Returns a result dict (also cached by file hash)."""
    prog = progress or (lambda stage, f: None)
    src = media.validate_media(src)
    prog("hash", 0.0)
    fhash = cache.file_sha256(src)
    prompt = build_initial_prompt(headings or [], vocab or [])
    key = cache.settings_key(model=model_name, prompt=prompt)
    final_name, partial_name = f"transcript_{key}", f"partial_{key}"

    cached = cache.read_json(fhash, final_name)
    if _valid_result(cached):
        prog("done", 1.0)
        return cached

    partial = cache.read_json(fhash, partial_name)
    segments: list[dict] = partial["segments"] if _valid_partial(partial) else []
    resume_at = segments[-1]["end"] if segments else 0.0
    if resume_at:
        log.info("Resuming job at %.1fs", resume_at)

    prog("extract", 0.0)
    with media.temp_audio(src) as wav:
        audio = read_wav(wav)
    duration = len(audio) / media.SAMPLE_RATE
    if duration < 0.1:
        raise media.InputError("The recording contains no audio.")

    meta: dict = {"language": partial.get("language") if partial else None}
    remaining = audio[int(resume_at * media.SAMPLE_RATE):]
    if len(remaining) > media.SAMPLE_RATE // 2:          # > 0.5 s left to do
        prog("load_model", 0.0)
        model = model_factory(model_name)
        last_ckpt = time.monotonic()

        def on_segment(seg: dict, _f: float) -> None:
            nonlocal last_ckpt
            segments.append(seg)
            prog("transcribe", min(1.0, seg["end"] / duration))
            if time.monotonic() - last_ckpt >= CHECKPOINT_EVERY_S:
                cache.write_json(fhash, partial_name, {"segments": segments, **meta})
                last_ckpt = time.monotonic()

        prog("transcribe", resume_at / duration)
        _, meta2 = transcribe_audio(model, remaining, offset=resume_at,
                                    initial_prompt=prompt, on_segment=on_segment)
        meta["language"] = meta["language"] or meta2.get("language")
    del audio, remaining

    prog("paragraphs", 0.0)
    result = {
        "version": cache.CACHE_VERSION,
        "source_name": src.name,
        "file_hash": fhash,
        "model": model_name,
        "duration": round(duration, 2),
        "language": meta.get("language"),
        "created": time.strftime("%Y-%m-%d %H:%M"),
        "segments": segments,
        "paragraphs": build_paragraphs(segments),
    }
    cache.write_json(fhash, final_name, result)
    cache.delete(fhash, partial_name)
    prog("done", 1.0)
    return result


def _valid_segments(segs: object) -> bool:
    return isinstance(segs, list) and all(
        isinstance(s, dict) and isinstance(s.get("text"), str)
        and isinstance(s.get("start"), (int, float)) and isinstance(s.get("end"), (int, float))
        for s in segs)


def _valid_partial(d: object) -> bool:
    return isinstance(d, dict) and _valid_segments(d.get("segments"))


def _valid_result(d: object) -> bool:
    return (isinstance(d, dict) and d.get("version") == cache.CACHE_VERSION
            and _valid_segments(d.get("segments")) and isinstance(d.get("paragraphs"), list))
