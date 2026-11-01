"""User-facing error messages (no Qt dependency; never includes transcript text)."""
from __future__ import annotations

from app.security import InputError


def friendly_error(e: BaseException) -> str:
    """Map exceptions to messages safe and useful for end users (never transcript text)."""
    if isinstance(e, InputError):
        return str(e)
    if isinstance(e, MemoryError):
        return "Not enough memory. Try a smaller model (small or medium)."
    mod = type(e).__module__ or ""
    if mod.startswith(("huggingface_hub", "httpx", "requests", "urllib3")) or isinstance(e, (ConnectionError, TimeoutError)):
        return "Couldn't download a required model. Check your internet connection and try again."
    if isinstance(e, ImportError):
        return "A required component is missing. Please reinstall LectureScribe."
    if isinstance(e, PermissionError):
        return "Permission denied. Choose a different output folder."
    if isinstance(e, OSError) and getattr(e, "errno", None) == 28:
        return "The disk is full. Free some space and try again."
    return f"Unexpected error ({type(e).__name__}). Details were saved to the log file."
