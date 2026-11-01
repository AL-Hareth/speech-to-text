"""Verify end-to-end outputs produced by the frozen CLI (audio + video)."""
import json
import os
import sys
from pathlib import Path

import fitz

out = Path(sys.argv[1])
ok = True


def check(cond, msg):
    global ok
    print(("[OK]   " if cond else "[FAIL] ") + msg)
    ok &= bool(cond)


for stem in ("lecture_audio", "lecture_video"):
    txt = out / f"{stem}.txt"
    check(txt.is_file(), f"{stem}.txt exists")
    if not txt.is_file():
        continue
    t = txt.read_text(encoding="utf-8-sig").lower()
    words = [w for w in ("neural", "network", "backpropagation", "gradient", "exam") if w in t]
    check(len(words) >= 3, f"{stem}: recognised key words {words}")
    srt = (out / f"{stem}.srt").read_text(encoding="utf-8")
    check("-->" in srt and "Speaker" in srt, f"{stem}.srt has timestamps + speaker names")
    pdf = out / f"{stem}.pdf"
    check(pdf.is_file() and pdf.stat().st_size > 10_000, f"{stem}.pdf exists")
    if pdf.is_file():
        ptxt = "".join(p.get_text() for p in fitz.open(pdf))
        check("Sec 3." in ptxt, f"{stem}.pdf links paragraphs to chapter sections")
        check("Speaker 1" in ptxt and "Speaker 2" in ptxt, f"{stem}.pdf has two speakers")
        check("Contents" in ptxt, f"{stem}.pdf has TOC")
    check((out / f"{stem}_anki.csv").is_file(), f"{stem}_anki.csv exists (emphasis detected)")

lock = Path(os.environ["LOCALAPPDATA"]) / "LectureScribe" / "models" / "lock.json"
check(lock.is_file(), "models/lock.json written (pinned revisions + hashes)")
if lock.is_file():
    for name, e in json.loads(lock.read_text()).items():
        print(f"  pinned {name}: {e['repo']} @ {e['revision']}")
tmp = Path(os.environ["LOCALAPPDATA"]) / "LectureScribe" / "tmp"
check(not list(tmp.glob("*.wav")), "no temp audio left behind")
print("E2E " + ("PASSED" if ok else "FAILED"))
sys.exit(0 if ok else 1)
