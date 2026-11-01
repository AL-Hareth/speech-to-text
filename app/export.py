"""Plain-text exports: .txt and .srt (speaker names included when present)."""
from __future__ import annotations

from pathlib import Path

from app.security import safe_join


def fmt_mmss(t: float) -> str:
    t = max(0, int(t))
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def fmt_srt_time(t: float) -> str:
    ms = max(0, int(round(t * 1000)))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _clean(text: str) -> str:
    # SRT blocks are separated by blank lines; collapse newlines inside text.
    return " ".join(str(text).split())


def to_txt(paragraphs: list[dict], timestamps: bool = True) -> str:
    lines = []
    for p in paragraphs:
        prefix = f"[{fmt_mmss(p['start'])}] " if timestamps else ""
        spk = f"{p['speaker']}: " if p.get("speaker") else ""
        lines.append(prefix + spk + _clean(p["text"]))
    return "\n\n".join(lines) + "\n"


def to_srt(segments: list[dict]) -> str:
    blocks = []
    n = 0
    for s in segments:
        text = _clean(s.get("text", ""))
        if not text:
            continue
        n += 1
        if s.get("speaker"):
            text = f"{s['speaker']}: {text}"
        blocks.append(f"{n}\n{fmt_srt_time(s['start'])} --> {fmt_srt_time(s['end'])}\n{text}\n")
    return "\n".join(blocks)


def write_text(out_dir: Path, filename: str, content: str) -> Path:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = safe_join(out_dir, filename)
    target.write_text(content, encoding="utf-8-sig" if target.suffix == ".txt" else "utf-8")
    return target
