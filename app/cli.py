"""Minimal CLI: python -m app transcribe FILE [FILE ...] -o OUTDIR."""
from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app import cache, config, media
from app.export import to_srt, to_txt, write_text
from app.pipeline import process_file
from app.security import InputError, safe_filename


def setup_logging(verbose: bool = False) -> None:
    """Logs hold metadata only (stages, timings, errors) - never transcript text."""
    handler = RotatingFileHandler(config.logs_dir() / "lecturescribe.log",
                                  maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handlers: list[logging.Handler] = [handler]
    if verbose:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def _read_vocab(path: str | None) -> list[str]:
    if not path:
        return []
    p = Path(path)
    if not p.is_file() or p.stat().st_size > 100_000:
        raise InputError("Vocabulary file missing or too large (max 100 KB).")
    return [ln.strip() for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="lecturescribe")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("transcribe", help="Transcribe audio/video files")
    t.add_argument("files", nargs="+")
    t.add_argument("-o", "--out", default=".", help="output folder")
    t.add_argument("-m", "--model", default=config.DEFAULT_MODEL, choices=sorted(config.MODELS))
    t.add_argument("--vocab", help="text file with one custom term per line")
    t.add_argument("--chapter", help="optional textbook chapter (PDF or PPTX) to link against")
    t.add_argument("--no-timestamps", action="store_true")
    t.add_argument("--pdf", action="store_true", help="also export the study PDF")
    t.add_argument("--notes", action="store_true", help="PDF: wide ruled notes margin")
    t.add_argument("--no-highlights", action="store_true", help="PDF: no emphasis highlighting")
    t.add_argument("-v", "--verbose", action="store_true")
    sub.add_parser("clear-cache", help="Delete cached transcripts")
    args = ap.parse_args(argv)
    setup_logging(getattr(args, "verbose", False))
    media.cleanup_temp()

    if args.cmd == "clear-cache":
        print(f"Removed {cache.clear_all()} cache entries.")
        return 0

    rc = 0
    try:
        vocab = _read_vocab(args.vocab)
    except InputError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    chapter = None
    if args.chapter:
        from app.analyze import load_chapter
        try:
            chapter = load_chapter(args.chapter)
        except InputError as e:
            print(f"Chapter skipped: {e}", file=sys.stderr)
    from app.chapter import headings
    hd = headings(chapter[1]) if chapter else []
    for f in args.files:
        try:
            def prog(stage: str, frac: float, _n=Path(f).name) -> None:
                print(f"\r{_n}: {stage} {frac*100:5.1f}%", end="", flush=True)

            res = process_file(f, model_name=args.model, vocab=vocab, headings=hd, progress=prog)
            try:
                from app.analyze import analyze
                from app.embed import default_embedder
                analyze(res, default_embedder(), chapter, Path(args.chapter).name if chapter else None)
            except Exception as e:  # noqa: BLE001 - transcript still exported
                logging.getLogger(__name__).exception("analysis failed")
                print(f"\nNote: topics/chapter linking unavailable ({type(e).__name__}).", file=sys.stderr)
            stem = safe_filename(Path(f).stem, default="transcript")
            out = Path(args.out)
            p1 = write_text(out, stem + ".txt", to_txt(res["paragraphs"], not args.no_timestamps))
            p2 = write_text(out, stem + ".srt", to_srt(res["segments"]))
            print(f"\n  -> {p1}\n  -> {p2}")
            if args.pdf:
                from app.pdf import PdfOptions, build_pdf
                opts = PdfOptions(timestamps=not args.no_timestamps, notes_margin=args.notes,
                                  highlights=not args.no_highlights)
                print(f"  -> {build_pdf(res, out, stem + '.pdf', opts)}")
        except InputError as e:
            print(f"\nError: {e}", file=sys.stderr)
            rc = 1
        except Exception as e:  # noqa: BLE001 - friendly message, details in log
            logging.getLogger(__name__).exception("job failed")
            print(f"\nError: {type(e).__name__} (see log in {config.logs_dir()})", file=sys.stderr)
            rc = 1
    return rc
