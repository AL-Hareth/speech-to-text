"""Small, dependency-free helpers for handling untrusted input safely."""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10)),
}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')


class InputError(ValueError):
    """User-facing error for rejected input (message is safe to show)."""


def safe_filename(name: str, default: str = "output", max_len: int = 120) -> str:
    """Return a Windows-safe single path component (no traversal, no reserved names)."""
    name = unicodedata.normalize("NFC", str(name))
    name = name.replace("\\", "/").split("/")[-1]          # drop any directory part
    name = _BAD_CHARS.sub("_", name)
    name = name.strip(" .")                                 # no leading dots / trailing dots+spaces
    name = re.sub(r"\.{2,}", ".", name)
    if not name or name.split(".")[0].upper() in _RESERVED:
        name = f"{default}_{name}" if name else default
    return name[:max_len].rstrip(" .") or default


def safe_join(base: Path, filename: str) -> Path:
    """Join a sanitized filename to base and verify the result stays inside base."""
    base = Path(base).resolve()
    target = (base / safe_filename(filename)).resolve()
    if target.parent != base:
        raise InputError("Invalid output file name.")
    return target


def check_input_file(path: str | Path, allowed_ext: set[str], max_bytes: int) -> Path:
    """Validate an untrusted input path: exists, regular file, allowed type, size limit."""
    p = Path(path)
    try:
        p = p.resolve(strict=True)
    except (OSError, RuntimeError):
        raise InputError(f"File not found: {Path(path).name}") from None
    if not p.is_file():
        raise InputError(f"Not a file: {p.name}")
    if p.suffix.lower() not in allowed_ext:
        raise InputError(f"Unsupported file type: {p.suffix or '(none)'}")
    size = p.stat().st_size
    if size == 0:
        raise InputError(f"File is empty: {p.name}")
    if size > max_bytes:
        raise InputError(f"File too large ({size // 1024**2} MB > {max_bytes // 1024**2} MB): {p.name}")
    return p


def csv_safe(value: object) -> str:
    """Neutralize spreadsheet formula injection."""
    s = "" if value is None else str(value)
    if s and s[0] in "=+-@\t\r":
        return "'" + s
    return s
