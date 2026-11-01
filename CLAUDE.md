# LectureScribe — project memory

Windows desktop app (Python) that transcribes lecture audio/video (mixed Jordanian Arabic + English
terms), optionally links it to an English textbook chapter (PDF/PPTX), and exports a study PDF.
**100% free & local**: no API keys, no LLM calls, no telemetry. Only network use = model download
(HTTPS, pinned revision).

## Current phase
- Phase 1 (Core) — DONE.
- Phase 2 (PDF) — DONE. Next: Phase 3 (UI) — wait for user go-ahead.
- Phases: 1 Core · 2 PDF · 3 UI · 4 Chapter · 5 Extras · 6 Packaging.

## Folder structure
```
app/
  __main__.py   python -m app -> cli.main
  cli.py        minimal CLI (transcribe, clear-cache); logging setup (metadata only)
  config.py     paths (%LOCALAPPDATA%\LectureScribe\{cache,models,tmp,logs}), limits, model registry
  security.py   safe_filename/safe_join, check_input_file (type+size), csv_safe, InputError
  media.py      ffmpeg discovery (bundled first), extract 16k mono WAV, temp cleanup
  transcribe.py faster-whisper load/download (pinned rev + lock.json hashes), prompt, transcribe_audio
  paragraphs.py pause-based paragraphs, per-paragraph RTL detection
  pipeline.py   process_file: hash -> cache -> extract -> transcribe (checkpoint/resume) -> paragraphs
  cache.py      JSON/npz (allow_pickle=False) per file SHA256; atomic writes; clear_all
  export.py     .txt / .srt
  textshape.py  mixed RTL/LTR: clean -> wrap (logical) -> arabic_reshaper -> bidi.algorithm (L4 mirroring) -> font runs
  pdf.py        reportlab study PDF: cover, 2-pass clickable TOC + outline, TextBlock flowable (tags, highlight,
                page-splittable), notes margin, appendices A (read on your own) / B (emphasised); PdfOptions
  assets/fonts/ Inter + Noto Naskh Arabic static Regular/Bold TTF (OFL, licences alongside)
tools/make_fonts.py  rebuild static fonts from Google Fonts variable TTFs (SHA256-checked)
tests/test_phase1.py, tests/test_phase2.py (LS_PDF_CHECK_DIR=dir keeps rendered PNGs for visual review)
requirements.txt (runtime, pinned) · requirements-dev.txt (pytest, bandit, pip-audit)
```
Planned modules: ui, diarize, chapter, link, segment, emphasis, qa.

## Tech decisions
- faster-whisper 1.2.1; `multilingual=True`, `task=transcribe`, `language=None`, VAD, word timestamps,
  `condition_on_previous_text=False`, beam 5. GPU float16 if CUDA else CPU int8. Default model: medium.
- Initial prompt = bilingual lead-in + custom vocab + chapter headings (≤600 chars).
- Audio: ffmpeg argv list, `-protocol_whitelist file`, `file:` paths, mono 16 kHz WAV in tmp, deleted after.
- Resume: partial segments checkpointed every 20 s to `partial_<key>.json`; on restart audio is sliced
  from last segment end and timestamps offset.
- Cache key = file SHA256 + settings hash (model, prompt).
- Model revisions: `config.MODELS[*].revision` currently None → TOFU: first download resolves `main`
  to a commit SHA and stores it + file SHA256s in `models/lock.json`. **TODO: hardcode SHAs** (huggingface.co
  was blocked in the build container).
- PDF: reportlab, NO Paragraph/markup for untrusted text — custom flowables draw via canvas.drawString
  (no markup injection possible). Paragraph direction = dominant script (paragraphs.is_rtl). Use
  `bidi.algorithm.get_display` (pure-python, mirrors brackets), NOT `bidi.get_display` (rust, no mirroring).
  Arabic runs at 1.12x size. Unsupported chars -> '?'. Only internal links (bookmarks), no URIs.
  Paragraph dict fields consumed by PDF: text, start, rtl, speaker, emphasis, link{label,page,confidence},
  unsure, not_in_book. Sections: [{title, start_para}] (auto 5-min sections if none).
- Container note: huggingface.co is not reachable from the cloud dev container → real-model tests
  must run on the user's machine; tests use a stub WhisperModel.

## Commands
```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   (Windows: .venv\Scripts\pip)
python -m pytest -q tests
python -m app transcribe lecture.mp4 -o out -m medium --vocab terms.txt --pdf --notes
python -m app clear-cache
bandit -q -r app ; pip-audit -r requirements.txt
```

## Security checklist (updated each phase)
| Item | P1 | P2 |
|---|---|---|
| No secrets stored/required; .gitignore present | PASS | PASS |
| PDF text escaped / WeasyPrint url_fetcher blocks URLs | n/a (P2) | PASS (no markup parser; drawString only; control/bidi-override chars stripped) |
| ffmpeg via argv list, never shell=True; protocol whitelist=file | PASS | n/a |
| Output filenames sanitized, no path traversal (safe_join) | PASS | PASS (PDF via safe_join, atomic write) |
| Temp audio deleted after processing (+ leftover cleanup) | PASS | n/a |
| Max file size limits (media 4 GB, PDF/PPTX 200 MB) | PASS (media; PDF/PPTX in P4) | n/a |
| PPTX zip-bomb rejection | n/a (P4) | n/a |
| Parser errors handled gracefully (friendly messages) | PASS | PASS |
| Cache JSON/npz only, no pickle (allow_pickle=False) | PASS | n/a |
| Models: HTTPS only, pinned revision, safetensors/CT2 preferred | PARTIAL — HTTPS + TOFU SHA pin + hash lock; hardcoded SHAs TODO | n/a (fonts bundled, SHA256 recorded) |
| Cache in %LOCALAPPDATA% | PASS | n/a |
| CSV formula-injection escaping (csv_safe) | PASS (helper; used in P5) | n/a |
| Logging never contains transcript content | PASS | PASS |
| Pinned deps; pip-audit clean | PASS | PASS (pymupdf bumped to 1.26.7 for PYSEC-2026-3001) |
| No telemetry/auto-update (HF telemetry disabled, token=False) | PASS | PASS |
| No pickle / shell=True / eval / exec; bandit clean | PASS | PASS |
| Packaging: clean venv, SHA256, per-user install | n/a (P6) | n/a |
