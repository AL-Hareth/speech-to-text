"""Per-file-hash cache (JSON / npz only; never pickle). Supports resumable jobs."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from app import config

log = logging.getLogger(__name__)
_HEX = re.compile(r"^[0-9a-f]{16,64}$")
CACHE_VERSION = 1


def file_sha256(path: str | Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def settings_key(**settings: Any) -> str:
    blob = json.dumps({"v": CACHE_VERSION, **settings}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _entry_dir(file_hash: str) -> Path:
    if not _HEX.match(file_hash):
        raise ValueError("bad cache key")
    d = config.cache_dir() / file_hash
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(file_hash: str, name: str) -> Path:
    if not re.match(r"^[A-Za-z0-9_.-]{1,80}$", name) or ".." in name:
        raise ValueError("bad cache name")
    return _entry_dir(file_hash) / name


def write_json(file_hash: str, name: str, data: Any) -> None:
    """Atomic write so an interrupted job never leaves a corrupt cache file."""
    target = _path(file_hash, name + ".json")
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_json(file_hash: str, name: str) -> Any | None:
    p = _path(file_hash, name + ".json")
    if not p.is_file():
        return None
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        log.warning("Discarding unreadable cache entry")
        p.unlink(missing_ok=True)
        return None


def delete(file_hash: str, name: str) -> None:
    _path(file_hash, name + ".json").unlink(missing_ok=True)


def write_npz(file_hash: str, name: str, **arrays: np.ndarray) -> None:
    target = _path(file_hash, name + ".npz")
    fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".npz")
    os.close(fd)
    try:
        np.savez_compressed(tmp, **arrays)
        os.replace(tmp, target)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read_npz(file_hash: str, name: str) -> dict[str, np.ndarray] | None:
    p = _path(file_hash, name + ".npz")
    if not p.is_file():
        return None
    try:
        with np.load(p, allow_pickle=False) as z:
            return {k: z[k] for k in z.files}
    except (OSError, ValueError):
        p.unlink(missing_ok=True)
        return None


def clear_all() -> int:
    """Delete the whole cache directory. Returns number of entries removed."""
    root = config.cache_dir()
    n = 0
    for child in root.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child, ignore_errors=True)
            n += 1
        else:
            child.unlink(missing_ok=True)
    return n
