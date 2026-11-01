"""Dark / light Qt stylesheets."""
from __future__ import annotations

PALETTES = {
    "dark": dict(bg="#16181d", panel="#1f232b", panel2="#272c36", text="#e8eaed", muted="#9aa3b2",
                 border="#343a46", accent="#4c8dff", accent_text="#ffffff", drop="#202733",
                 ok="#3fb27f", warn="#e0a43a", sel="#2d4a7a"),
    "light": dict(bg="#f4f6fa", panel="#ffffff", panel2="#eef1f6", text="#1b1f27", muted="#5f6877",
                  border="#d6dbe4", accent="#2563eb", accent_text="#ffffff", drop="#f0f5ff",
                  ok="#1f9d63", warn="#b7791f", sel="#cfe0ff"),
}


def stylesheet(theme: str) -> str:
    c = PALETTES.get(theme, PALETTES["dark"])
    return f"""
* {{ font-family: "Segoe UI", "Inter", "Noto Naskh Arabic", sans-serif; font-size: 10pt; color: {c['text']}; }}
QMainWindow, QWidget#root {{ background: {c['bg']}; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 18px; color: {c['muted']}; border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {c['text']}; border-bottom: 2px solid {c['accent']}; }}
QFrame#card {{ background: {c['panel']}; border: 1px solid {c['border']}; border-radius: 10px; }}
QLabel#h1 {{ font-size: 16pt; font-weight: 600; }}
QLabel#h2 {{ font-size: 11pt; font-weight: 600; }}
QLabel#muted, QLabel#status {{ color: {c['muted']}; }}
QFrame#drop {{ background: {c['drop']}; border: 2px dashed {c['border']}; border-radius: 10px; }}
QFrame#drop[hover="true"] {{ border-color: {c['accent']}; }}
QPushButton {{ background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 7px 14px; }}
QPushButton:hover {{ border-color: {c['accent']}; }}
QPushButton:disabled {{ color: {c['muted']}; }}
QPushButton#primary {{ background: {c['accent']}; color: {c['accent_text']}; border: none; font-weight: 600; }}
QPushButton#primary:disabled {{ background: {c['border']}; }}
QLineEdit, QPlainTextEdit, QComboBox, QSpinBox, QListWidget, QTableWidget {{
    background: {c['panel2']}; border: 1px solid {c['border']}; border-radius: 7px; padding: 4px;
    selection-background-color: {c['sel']}; selection-color: {c['text']}; }}
QComboBox QAbstractItemView {{ background: {c['panel']}; }}
QHeaderView::section {{ background: {c['panel']}; color: {c['muted']}; border: none; padding: 6px; }}
QTableWidget {{ gridline-color: {c['border']}; }}
QProgressBar {{ background: {c['panel2']}; border: none; border-radius: 5px; height: 10px; text-align: center; }}
QProgressBar::chunk {{ background: {c['accent']}; border-radius: 5px; }}
QLabel#step {{ padding: 5px 10px; border-radius: 12px; background: {c['panel2']}; color: {c['muted']}; }}
QLabel#step[state="active"] {{ background: {c['accent']}; color: {c['accent_text']}; }}
QLabel#step[state="done"] {{ background: {c['ok']}; color: #ffffff; }}
QLabel#step[state="error"] {{ background: #c0392b; color: #ffffff; }}
QSpinBox:disabled {{ color: {c['muted']}; }}
QCheckBox:disabled {{ color: {c['muted']}; }}
"""
