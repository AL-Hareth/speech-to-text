# LectureScribe

Free, fully local lecture transcription (Arabic/English mixed speech) with study-PDF export.
No API keys, no cloud, no telemetry. The Whisper model is downloaded once on first use.

## Quick start (CLI, Phase 1)
```
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\python -m app transcribe lecture.mp4 -o out --model medium --vocab terms.txt
```
Outputs `out\lecture.txt` and `out\lecture.srt`. Cache, models and logs live in
`%LOCALAPPDATA%\LectureScribe`. Requires ffmpeg (bundled in the installer build).

Supported: mp3, wav, m4a, ogg, flac, aac, wma, mp4, mkv, mov, avi, webm.
