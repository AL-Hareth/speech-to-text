"""Media input: validate audio/video and extract 16 kHz mono WAV via ffmpeg."""
from __future__ import annotations

import contextlib
import logging
import os
import shutil
import subprocess  # nosec B404 - used with argument lists only, never shell=True
import tempfile
import wave
from pathlib import Path
from typing import Iterator

from app import config
from app.security import InputError, check_input_file

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".wav", ".m4a", ".ogg", ".flac", ".aac", ".wma"}
VIDEO_EXT = {".mp4", ".mkv", ".mov", ".avi", ".webm"}
MEDIA_EXT = AUDIO_EXT | VIDEO_EXT
SAMPLE_RATE = 16000


def find_ffmpeg() -> str:
    """Prefer the bundled ffmpeg; fall back to PATH."""
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for cand in (config.resource_dir() / "ffmpeg" / exe, config.resource_dir() / exe):
        if cand.is_file():
            return str(cand)
    found = shutil.which("ffmpeg")
    if not found:
        raise InputError("ffmpeg was not found. Please reinstall LectureScribe.")
    return found


def validate_media(path: str | Path) -> Path:
    return check_input_file(path, MEDIA_EXT, config.MAX_MEDIA_BYTES)


def is_video(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_EXT


def _ffmpeg_cmd(ffmpeg: str, src: Path, dst: Path) -> list[str]:
    return [
        ffmpeg, "-nostdin", "-hide_banner", "-loglevel", "error", "-y",
        # Only local files may be opened: blocks playlists/concat that try to
        # fetch http://, tcp://, etc. from inside a crafted media file.
        "-protocol_whitelist", "file",
        "-i", "file:" + str(src),
        "-map", "0:a:0", "-vn", "-sn", "-dn",
        "-ac", "1", "-ar", str(SAMPLE_RATE), "-c:a", "pcm_s16le",
        "-t", str(config.MAX_MEDIA_SECONDS),
        "-f", "wav", "file:" + str(dst),
    ]


def extract_audio(src: str | Path, out_dir: Path | None = None) -> Path:
    """Decode any supported audio/video file to a temp 16 kHz mono WAV. Caller deletes it."""
    src = validate_media(src)
    out_dir = Path(out_dir or config.temp_dir())
    fd, tmp = tempfile.mkstemp(prefix="ls_", suffix=".wav", dir=out_dir)
    os.close(fd)
    dst = Path(tmp)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        res = subprocess.run(  # nosec B603 - fixed argv list, no shell
            _ffmpeg_cmd(find_ffmpeg(), src, dst),
            stdin=subprocess.DEVNULL, capture_output=True,
            timeout=config.FFMPEG_TIMEOUT_S, check=False, creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        dst.unlink(missing_ok=True)
        raise InputError("Audio extraction timed out.") from None
    except BaseException:
        dst.unlink(missing_ok=True)
        raise
    if res.returncode != 0 or dst.stat().st_size <= 44:
        dst.unlink(missing_ok=True)
        log.warning("ffmpeg failed (rc=%s) for a %s input", res.returncode, src.suffix)
        if b"does not contain any stream" in res.stderr or b"matches no streams" in res.stderr:
            raise InputError(f"No audio track found in {src.name}.")
        raise InputError(f"Could not read audio from {src.name} (unsupported or damaged file).")
    return dst


@contextlib.contextmanager
def temp_audio(src: str | Path) -> Iterator[Path]:
    """Context manager: extracted WAV that is always deleted afterwards."""
    wav = extract_audio(src)
    try:
        yield wav
    finally:
        wav.unlink(missing_ok=True)


def wav_duration(path: Path) -> float:
    with contextlib.closing(wave.open(str(path), "rb")) as w:
        return w.getnframes() / float(w.getframerate() or SAMPLE_RATE)


def cleanup_temp() -> None:
    """Remove leftover temp WAVs from crashed runs."""
    for f in config.temp_dir().glob("ls_*.wav"):
        with contextlib.suppress(OSError):
            f.unlink()
