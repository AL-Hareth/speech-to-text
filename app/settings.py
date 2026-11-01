"""User settings + per-project custom vocabulary (JSON in %LOCALAPPDATA%, validated on load)."""
from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app import config

log = logging.getLogger(__name__)
MAX_TERMS = 300
MAX_TERM_LEN = 80
MAX_PROJECTS = 200
_NAME = re.compile(r"[\x00-\x1f\x7f]")


def clean_terms(raw: str | list[str]) -> list[str]:
    """Split on newlines/commas, strip controls, de-duplicate, cap count and length."""
    items = raw if isinstance(raw, list) else re.split(r"[\n,،;]", str(raw))
    out: list[str] = []
    seen: set[str] = set()
    for t in items:
        t = _NAME.sub(" ", str(t)).strip()[:MAX_TERM_LEN]
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
        if len(out) >= MAX_TERMS:
            break
    return out


def clean_name(name: str) -> str:
    return _NAME.sub("", str(name)).strip()[:60] or "Default"


@dataclass
class Settings:
    theme: str = "dark"                 # dark | light
    model: str = config.DEFAULT_MODEL
    timestamps: bool = True
    highlights: bool = True
    notes_margin: bool = False
    speakers: bool = False
    num_speakers: int = 0               # 0 = auto
    qa_search: bool = True
    output_dir: str = ""
    project: str = "Default"
    projects: dict[str, dict] = field(default_factory=lambda: {"Default": {"vocab": []}})

    # ----------------------------------------------------------- projects
    def vocab(self) -> list[str]:
        return list(self.projects.get(self.project, {}).get("vocab", []))

    def set_vocab(self, terms: str | list[str]) -> None:
        self.projects.setdefault(self.project, {})["vocab"] = clean_terms(terms)

    def select_project(self, name: str) -> None:
        name = clean_name(name)
        if name not in self.projects and len(self.projects) < MAX_PROJECTS:
            self.projects[name] = {"vocab": []}
        if name in self.projects:
            self.project = name

    # ----------------------------------------------------------- io
    @staticmethod
    def path() -> Path:
        return config.data_dir() / "settings.json"

    @classmethod
    def load(cls) -> "Settings":
        s = cls()
        try:
            raw = json.loads(cls.path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return s
        if not isinstance(raw, dict):
            return s
        for key, default in asdict(cls()).items():
            val = raw.get(key)
            if key == "projects":
                continue
            if isinstance(default, int) and not isinstance(default, bool) and isinstance(val, int) \
                    and not isinstance(val, bool):
                setattr(s, key, max(0, min(val, config.MAX_SPEAKERS)))
            elif isinstance(default, bool) and isinstance(val, bool):
                setattr(s, key, val)
            elif isinstance(default, str) and isinstance(val, str):
                setattr(s, key, val[:500])
        if s.theme not in ("dark", "light"):
            s.theme = "dark"
        if s.model not in config.MODELS:
            s.model = config.DEFAULT_MODEL
        projs = raw.get("projects")
        if isinstance(projs, dict):
            s.projects = {}
            for name, val in list(projs.items())[:MAX_PROJECTS]:
                vocab = val.get("vocab") if isinstance(val, dict) else None
                s.projects[clean_name(name)] = {
                    "vocab": clean_terms([v for v in vocab if isinstance(v, str)]) if isinstance(vocab, list) else []}
        s.projects.setdefault("Default", {"vocab": []})
        s.project = clean_name(s.project)
        if s.project not in s.projects:
            s.project = "Default"
        return s

    def save(self) -> None:
        target = self.path()
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(asdict(self), f, ensure_ascii=False, indent=1)
            os.replace(tmp, target)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            log.warning("Could not save settings")


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.is_dir() else Path.home()) / "LectureScribe"
