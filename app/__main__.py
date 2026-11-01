import sys

if len(sys.argv) > 1:
    from app.cli import main

    raise SystemExit(main())

from app.ui.main_window import run

raise SystemExit(run())
