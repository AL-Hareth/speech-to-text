"""GUI entry point (PyInstaller windowed exe). `--self-test` checks the bundle and exits."""
import sys


def main() -> int:
    if "--self-test" in sys.argv:
        return gui_selftest()
    from app.ui.main_window import run
    return run()


def gui_selftest() -> int:
    """Open the main window briefly, run component checks, write a report next to the logs."""
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from app import config
    from app.selftest import report, run_checks
    from app.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication(sys.argv)
    win = MainWindow()
    win.show()
    seen = {}

    def probe():
        seen["visible"] = win.isVisible() and win.tabs.count() == 2
        app.quit()
    QTimer.singleShot(1500, probe)
    app.exec()
    ok_window = seen.get("visible", False)
    win.close()
    results = run_checks()
    results.append(("main window", ok_window, "shown"))
    out = config.logs_dir() / "selftest.txt"
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = report(results)
    out.write_text(buf.getvalue(), encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
