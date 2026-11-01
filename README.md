# LectureScribe

Free, fully local lecture transcription for mixed Arabic (Levantine) + English speech, with optional
textbook-chapter linking and a tidy study PDF. No API keys, no cloud, no telemetry. Models are
downloaded once on first use (HTTPS, pinned revision, SHA256-locked) and then everything runs offline.

## Install (Windows)
Download `LectureScribe-Setup-x.y.z.exe` from the latest **Windows build** workflow run (Actions tab →
artifact `LectureScribe-…-windows`), verify it against `SHA256SUMS.txt`:
```
certutil -hashfile LectureScribe-Setup-x.y.z.exe SHA256
```
then run it. It installs per-user (no admin rights) to `%LOCALAPPDATA%\Programs\LectureScribe`.

## Use
1. Drop audio/video files (mp3 wav m4a ogg flac aac wma / mp4 mkv mov avi webm), optionally a chapter (PDF/PPTX).
2. Pick a model (medium recommended; large-v3 = best for dialect, slow on CPU), toggles, custom vocabulary.
3. Start → Review tab: fix text, speakers and chapter links, search or ask the transcript → Export
   (PDF, TXT, SRT, Anki CSV) → Open PDF.

Data (cache, models, settings, logs — logs never contain transcript text) lives in `%LOCALAPPDATA%\LectureScribe`.

## CLI
```
lecturescribe-cli.exe transcribe lecture.mp4 -o out -m medium --chapter ch3.pdf --speakers 2 --pdf --notes --anki
lecturescribe-cli.exe selftest
lecturescribe-cli.exe clear-cache
```

## Build from source
Windows + Python 3.12 + Inno Setup 6: run `build.bat` (clean venv, hash-locked deps, pip-audit, bandit,
secret scan, tests, pinned ffmpeg, PyInstaller, installer, SHA256SUMS). CI does the same on every push
(`.github/workflows/build-windows.yml`) plus a GUI self-test, an end-to-end audio + video run with real
models, and a silent install/launch/uninstall.

See `THIRD_PARTY_NOTICES.md` for licenses.
