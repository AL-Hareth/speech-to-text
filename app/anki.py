"""Anki CSV export built locally from emphasised passages (formula-injection safe)."""
from __future__ import annotations

import csv
import io
from pathlib import Path

from app.export import fmt_mmss, write_text
from app.security import csv_safe


def _topic_for(result: dict, idx: int) -> str:
    title = ""
    for t in result.get("topics") or []:
        if t.get("start_para", 0) <= idx:
            title = t.get("title", "")
    return title


def anki_rows(result: dict) -> list[tuple[str, str]]:
    rows = []
    for i, p in enumerate(result.get("paragraphs", [])):
        if not p.get("emphasis"):
            continue
        front = f"[{fmt_mmss(p.get('start', 0))}]"
        topic = _topic_for(result, i)
        if topic:
            front += f" · {topic}"
        link = p.get("link") if isinstance(p.get("link"), dict) else None
        if link and link.get("label"):
            front += f" · {link['label']}"
        rows.append((front, " ".join(str(p.get("text", "")).split())))
    return rows


def to_anki_csv(result: dict) -> str:
    buf = io.StringIO()
    # Anki import headers: plain text only (no HTML interpretation of card text)
    buf.write("#separator:Comma\n#html:false\n#columns:Front,Back\n")
    w = csv.writer(buf, quoting=csv.QUOTE_ALL, lineterminator="\n")
    for front, back in anki_rows(result):
        w.writerow([csv_safe(front), csv_safe(back)])
    return buf.getvalue()


def write_anki(result: dict, out_dir: Path, filename: str) -> Path:
    return write_text(out_dir, filename, to_anki_csv(result))
