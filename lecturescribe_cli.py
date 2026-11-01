"""Console entry point (lecturescribe-cli.exe): `transcribe ...`, `clear-cache`, `selftest`."""
import sys

if __name__ == "__main__":
    if sys.argv[1:2] == ["selftest"]:
        from app.selftest import report, run_checks
        sys.exit(report(run_checks()))
    from app.cli import main
    sys.exit(main())
