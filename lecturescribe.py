"""GUI entry point (used by PyInstaller)."""
import sys

from app.ui.main_window import run

if __name__ == "__main__":
    sys.exit(run())
