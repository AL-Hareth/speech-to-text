# LectureScribe — project memory

Windows desktop app (Python) that transcribes lecture audio/video (mixed Jordanian Arabic + English
terms), optionally links it to an English textbook chapter (PDF/PPTX), and exports a study PDF.
**100% free & local**: no API keys, no LLM calls, no telemetry. Only network use = model download
(HTTPS, pinned revision).

## Current phase
- Phase 1 (Core) — DONE.
- Phase 2 (PDF) — DONE.
- Phase 3 (UI) — DONE.
- Phase 4 (Chapter) — DONE. Next: Phase 5 (Extras) — wait for user go-ahead.
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
  settings.py   Settings dataclass (theme, model, toggles, output_dir, projects{name:{vocab}}), validated JSON load
  ui/main_window.py  MainWindow: tab 1 Setup&Run (drop zones, file list, project/model/toggles, vocab, StepBar,
                progress, cancel, clear cache), tab 2 Review&Export; run() = GUI entry
  ui/review.py  ReviewPanel: QTableWidget (time/speaker/text editable), search (Arabic-normalized), rename speaker
  ui/worker.py  TranscribeWorker / ExportWorker in QThread (start_in_thread), friendly_error(), cached_model()
  ui/widgets.py DropZone (local files, ext filter), StepBar ; ui/theme.py dark/light QSS
  chapter.py    parse_chapter(PDF: PyMuPDF text dict + outline, heading heuristics by font size/bold/numbering;
                pages w/o text layer -> rapidocr OCR (bundled ONNX, max 60 pages); PPTX: check_zip then python-pptx)
                -> sections [{id,title,number,label,page,level,text}]; headings() feeds Whisper prompt
  embed.py      STEmbedder (sentence-transformers, local pinned snapshot, safetensors only), encode_cached (npz)
  link.py       section_passages (title + 90-word chunks), max-cosine scores, link_paragraphs (+continuity bonus,
                keeps manual links), set_manual_link, gap_analysis -> read_on_own
  segment.py    segment_topics: TextTiling depth on embeddings (min 3 paras / 90 s); titles = majority linked
                section or TF-IDF keywords (EN/AR stopwords)
  analyze.py    load_chapter (cached by chapter hash) + analyze(result, embedder, chapter) -> paragraph links,
                result[topics|read_on_own|chapter]; refresh_after_edit
lecturescribe.py  GUI entry (PyInstaller); `python -m app` = GUI, `python -m app transcribe ...` = CLI
tools/make_fonts.py  rebuild static fonts from Google Fonts variable TTFs (SHA256-checked)
tests/test_phase1..4.py + tests/helpers.py (HashEmbedder stub) (LS_PDF_CHECK_DIR / LS_UI_CHECK_DIR keep rendered PNGs; UI tests use QT_QPA_PLATFORM=offscreen)
requirements.in (top-level) -> requirements.txt (uv-compiled, hash-locked, Windows/py3.12) · requirements-dev.txt
```
Planned modules: diarize, emphasis, qa.

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
- UI: PySide6-Essentials 6.10. Review edits saved to cache `edited_<key>.json` (process_file returns it before
  the original); save_edits rebuilds segments (edited paragraph -> one segment) so SRT matches. Speakers/Q&A
  checkboxes disabled until Phase 5. Chapter drop zone stores path only (used in Phase 4).
  Linux container needs `apt-get install libegl1` for PySide6 tests.
- Target Python 3.12 (rapidocr-onnxruntime 1.4.4 has no 3.13 build). Dev venv: `.venv312` (uv).
- Linking: cosine >= LINK_SURE(0.50) linked; >= LINK_UNSURE(0.35) linked+unsure; below -> not_in_book if >= 8 words.
  Confidence badge = rescaled cosine. Manual links ({manual: True}) survive re-analysis. Analysis failure
  (e.g. embedder download) is a warning; transcript still usable; PDF falls back to 5-min sections.
- PDF TOC uses result["topics"]; appendix A uses result["read_on_own"].
- Container note: huggingface.co is not reachable from the cloud dev container → real-model tests
  must run on the user's machine; tests use a stub WhisperModel.

## Commands
```
uv venv -p 3.12 .venv312 && uv pip install -r requirements.txt -r requirements-dev.txt   (pip: --require-hashes)
python -m pytest -q tests
python -m app transcribe lecture.mp4 -o out -m medium --vocab terms.txt --chapter ch3.pdf --pdf --notes
python -m app clear-cache
bandit -q -r app ; pip-audit -r requirements.txt --no-deps --disable-pip
uv pip compile requirements.in --python-version 3.12 --python-platform windows --generate-hashes -o requirements.txt
```

## Security checklist (updated each phase)
| Item | P1 | P2 | P3 | P4 |
|---|---|---|---|---|
| No secrets stored/required; .gitignore present | PASS | PASS | PASS | PASS |
| PDF text escaped / WeasyPrint url_fetcher blocks URLs | n/a (P2) | PASS (no markup parser; drawString only; control/bidi-override chars stripped) | n/a | PASS (chapter titles drawn as plain text) |
| ffmpeg via argv list, never shell=True; protocol whitelist=file | PASS | n/a | n/a | n/a |
| Output filenames sanitized, no path traversal (safe_join) | PASS | PASS (PDF via safe_join, atomic write) | PASS (export via safe_join; open only local generated paths) | PASS (cache names regex-checked) |
| Temp audio deleted after processing (+ leftover cleanup) | PASS | n/a | PASS (cancel path -> context manager) | n/a |
| Max file size limits (media 4 GB, PDF/PPTX 200 MB) | PASS (media; PDF/PPTX in P4) | n/a | PASS (drop zone ext filter + pipeline checks) | PASS (PDF/PPTX 200 MB, 400 pages, 60 OCR pages, 2M chars) |
| PPTX zip-bomb rejection | n/a (P4) | n/a | n/a | PASS (entry count, total size, ratio, path traversal; tested) |
| Parser errors handled gracefully (friendly messages) | PASS | PASS | PASS (friendly_error; settings JSON validated) | PASS (encrypted/corrupt PDF, bad zip -> InputError; per-page/shape errors skipped) |
| Cache JSON/npz only, no pickle (allow_pickle=False) | PASS | n/a | PASS (edits JSON) | PASS (embeddings npz allow_pickle=False) |
| Models: HTTPS only, pinned revision, safetensors/CT2 preferred | PARTIAL — HTTPS + TOFU SHA pin + hash lock; hardcoded SHAs TODO | n/a (fonts bundled, SHA256 recorded) | n/a | PARTIAL (embedder: HTTPS, TOFU pin + hashes, safetensors only, trust_remote_code=False; OCR models bundled in wheel) |
| Cache in %LOCALAPPDATA% | PASS | n/a | PASS (+settings.json) | PASS |
| CSV formula-injection escaping (csv_safe) | PASS (helper; used in P5) | n/a | n/a | n/a |
| Logging never contains transcript content | PASS | PASS | PASS | PASS (only counts/page numbers) |
| Pinned deps; pip-audit clean | PASS | PASS (pymupdf bumped to 1.26.7 for PYSEC-2026-3001) | PASS | PASS (hash-locked via uv compile; pip-audit clean) |
| No telemetry/auto-update (HF telemetry disabled, token=False) | PASS | PASS | PASS | PASS (HF token=False; OCR offline) |
| No pickle / shell=True / eval / exec; bandit clean | PASS | PASS | PASS | PASS |
| Packaging: clean venv, SHA256, per-user install | n/a (P6) | n/a | n/a | n/a |
