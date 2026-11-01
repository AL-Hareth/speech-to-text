# LectureScribe — project memory

Windows desktop app (Python) that transcribes lecture audio/video (mixed Jordanian Arabic + English
terms), optionally links it to an English textbook chapter (PDF/PPTX), and exports a study PDF.
**100% free & local**: no API keys, no LLM calls, no telemetry. Only network use = model download
(HTTPS, pinned revision).

## Current phase
- Phase 1 (Core) — DONE. Next: Phase 2 (PDF) — wait for user go-ahead.
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
tests/test_phase1.py
requirements.txt (runtime, pinned) · requirements-dev.txt (pytest, bandit, pip-audit)
```
Planned modules: ui, diarize, chapter, link, segment, emphasis, pdf, qa.

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
- Container note: huggingface.co is not reachable from the cloud dev container → real-model tests
  must run on the user's machine; tests use a stub WhisperModel.

## Commands
```
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt   (Windows: .venv\Scripts\pip)
python -m pytest -q tests
python -m app transcribe lecture.mp4 -o out -m medium --vocab terms.txt
python -m app clear-cache
bandit -q -r app ; pip-audit -r requirements.txt
```

## Security checklist (updated each phase)
| Item | P1 |
|---|---|
| No secrets stored/required; .gitignore present | PASS |
| PDF text escaped / WeasyPrint url_fetcher blocks URLs | n/a (P2) |
| ffmpeg via argv list, never shell=True; protocol whitelist=file | PASS |
| Output filenames sanitized, no path traversal (safe_join) | PASS |
| Temp audio deleted after processing (+ leftover cleanup) | PASS |
| Max file size limits (media 4 GB, PDF/PPTX 200 MB) | PASS (media; PDF/PPTX in P4) |
| PPTX zip-bomb rejection | n/a (P4) |
| Parser errors handled gracefully (friendly messages) | PASS |
| Cache JSON/npz only, no pickle (allow_pickle=False) | PASS |
| Models: HTTPS only, pinned revision, safetensors/CT2 preferred | PARTIAL — HTTPS + TOFU SHA pin + hash lock; hardcoded SHAs TODO |
| Cache in %LOCALAPPDATA% | PASS |
| CSV formula-injection escaping (csv_safe) | PASS (helper; used in P5) |
| Logging never contains transcript content | PASS |
| Pinned deps; pip-audit clean | PASS |
| No telemetry/auto-update (HF telemetry disabled, token=False) | PASS |
| No pickle / shell=True / eval / exec; bandit clean | PASS |
| Packaging: clean venv, SHA256, per-user install | n/a (P6) |
