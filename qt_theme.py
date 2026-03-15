#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI Qt Theme — macOS Big Sur–inspired stylesheet.

Replaces the tkinter ``theme.py`` (ttk.Style configuration) with a
single Qt stylesheet plus helper accessors for colours, fonts, and
padding values.  The colour palette and design language are identical
to the original so the migration is visually seamless.

Usage::

    from PyQt6.QtWidgets import QApplication
    from qt_theme import QtTheme

    app = QApplication([])
    QtTheme.apply(app)
"""

from __future__ import annotations

import platform
from typing import Any


# ---------------------------------------------------------------------------
# Colour palette — macOS Big Sur inspired (matches theme.py exactly)
# ---------------------------------------------------------------------------

COLORS: dict[str, str] = {
    "bg":            "#F5F5F7",
    "fg":            "#1D1D1F",
    "accent":        "#007AFF",
    "accent_hover":  "#0051D5",
    "success":       "#34C759",
    "warning":       "#FF9500",
    "error":         "#FF3B30",
    "border":        "#D1D1D6",
    "hover":         "#E8E8ED",
    "selected":      "#007AFF",
    "panel_bg":      "#FFFFFF",
    "input_bg":      "#FFFFFF",
    "disabled":      "#8E8E93",
}


# ---------------------------------------------------------------------------
# Font families per platform
# ---------------------------------------------------------------------------

def _platform_font_family() -> tuple[str, str, str]:
    """Return (sans, display, mono) font families for the OS."""
    system = platform.system()
    if system == "Darwin":
        return ("SF Pro Text", "SF Pro Display", "SF Mono")
    elif system == "Linux":
        return ("DejaVu Sans", "DejaVu Sans", "DejaVu Sans Mono")
    else:  # Windows
        return ("Segoe UI", "Segoe UI", "Consolas")


_SANS, _DISPLAY, _MONO = _platform_font_family()

# Font sizes vary by platform (Linux uses slightly smaller sizes)
_IS_LINUX = platform.system() == "Linux"

FONTS: dict[str, dict[str, Any]] = {
    "default": {
        "family": _SANS,
        "size": 10 if _IS_LINUX else 13,
    },
    "heading": {
        "family": _DISPLAY,
        "size": 14 if _IS_LINUX else 18,
        "weight": "bold",
    },
    "subheading": {
        "family": _SANS,
        "size": 11 if _IS_LINUX else 14,
        "weight": "bold",
    },
    "small": {
        "family": _SANS,
        "size": 9 if _IS_LINUX else 11,
    },
    "mono": {
        "family": _MONO,
        "size": 9 if _IS_LINUX else 11,
    },
}

PADDING: dict[str, int] = {
    "small": 4,
    "medium": 8,
    "large": 16,
    "xlarge": 24,
}


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

def _build_stylesheet() -> str:
    """Generate the global Qt stylesheet string."""
    c = COLORS
    f = FONTS
    p = PADDING

    return f"""
/* ---- Global ------------------------------------------------- */
QWidget {{
    background-color: {c['bg']};
    color: {c['fg']};
    font-family: "{f['default']['family']}";
    font-size: {f['default']['size']}pt;
}}

/* ---- QMainWindow -------------------------------------------- */
QMainWindow {{
    background-color: {c['bg']};
}}

/* ---- Labels ------------------------------------------------- */
QLabel {{
    background-color: transparent;
    color: {c['fg']};
    padding: 0px;
}}

QLabel[role="heading"] {{
    font-family: "{f['heading']['family']}";
    font-size: {f['heading']['size']}pt;
    font-weight: bold;
}}

QLabel[role="subheading"] {{
    font-family: "{f['subheading']['family']}";
    font-size: {f['subheading']['size']}pt;
    font-weight: bold;
}}

QLabel[role="small"] {{
    font-size: {f['small']['size']}pt;
    color: {c['disabled']};
}}

QLabel[role="success"] {{
    color: {c['success']};
}}

QLabel[role="error"] {{
    color: {c['error']};
}}

QLabel[role="warning"] {{
    color: {c['warning']};
}}

/* ---- Buttons ------------------------------------------------ */
QPushButton {{
    background-color: {c['panel_bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    padding: {p['small']}px {p['medium']}px;
    font-size: {f['default']['size']}pt;
    min-height: 24px;
}}

QPushButton:hover {{
    background-color: {c['hover']};
    border-color: {c['accent']};
}}

QPushButton:pressed {{
    background-color: {c['border']};
}}

QPushButton:disabled {{
    background-color: {c['bg']};
    color: {c['disabled']};
    border-color: {c['border']};
}}

QPushButton[role="primary"] {{
    background-color: {c['accent']};
    color: white;
    border: 1px solid {c['accent']};
}}

QPushButton[role="primary"]:hover {{
    background-color: {c['accent_hover']};
    border-color: {c['accent_hover']};
}}

QPushButton[role="primary"]:disabled {{
    background-color: {c['disabled']};
    color: {c['fg']};
}}

/* ---- Line edits --------------------------------------------- */
QLineEdit {{
    background-color: {c['input_bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: {c['selected']};
    selection-color: white;
}}

QLineEdit:focus {{
    border-color: {c['accent']};
}}

QLineEdit:disabled, QLineEdit:read-only {{
    background-color: {c['bg']};
    color: {c['fg']};
}}

/* ---- Combo boxes -------------------------------------------- */
QComboBox {{
    background-color: {c['input_bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 6px;
    min-height: 24px;
}}

QComboBox:focus {{
    border-color: {c['accent']};
}}

QComboBox::drop-down {{
    border: none;
    width: 20px;
}}

QComboBox QAbstractItemView {{
    background-color: {c['panel_bg']};
    color: {c['fg']};
    selection-background-color: {c['selected']};
    selection-color: white;
    border: 1px solid {c['border']};
}}

/* ---- Spin boxes --------------------------------------------- */
QSpinBox, QDoubleSpinBox {{
    background-color: {c['input_bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px 6px;
}}

/* ---- Checkboxes / Radio buttons ----------------------------- */
QCheckBox, QRadioButton {{
    background-color: transparent;
    spacing: 6px;
}}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
}}

/* ---- Group boxes (replacement for LabelFrame) --------------- */
QGroupBox {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    border-radius: 6px;
    margin-top: 12px;
    padding-top: 12px;
    font-weight: bold;
    font-size: {f['subheading']['size']}pt;
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 4px;
    background-color: {c['bg']};
    color: {c['fg']};
}}

/* ---- Tab widget --------------------------------------------- */
QTabWidget::pane {{
    background-color: {c['bg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
}}

QTabBar::tab {{
    background-color: {c['bg']};
    color: {c['fg']};
    padding: {p['small']}px {p['medium']}px;
    border: 1px solid transparent;
    border-bottom: none;
    font-size: {f['default']['size']}pt;
}}

QTabBar::tab:selected {{
    background-color: {c['panel_bg']};
    border-color: {c['border']};
    border-bottom-color: {c['panel_bg']};
}}

QTabBar::tab:hover {{
    background-color: {c['hover']};
}}

/* ---- Table view --------------------------------------------- */
QTableView, QTreeView {{
    background-color: {c['panel_bg']};
    color: {c['fg']};
    gridline-color: {c['border']};
    selection-background-color: {c['selected']};
    selection-color: white;
    border: 1px solid {c['border']};
    border-radius: 4px;
    font-size: {f['default']['size']}pt;
}}

QHeaderView::section {{
    background-color: {c['bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    padding: 4px 8px;
    font-weight: bold;
    font-size: {f['subheading']['size']}pt;
}}

/* ---- Scroll bars -------------------------------------------- */
QScrollBar:vertical {{
    background-color: {c['bg']};
    width: 12px;
    border: none;
}}

QScrollBar::handle:vertical {{
    background-color: {c['border']};
    border-radius: 4px;
    min-height: 24px;
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {c['bg']};
    height: 12px;
    border: none;
}}

QScrollBar::handle:horizontal {{
    background-color: {c['border']};
    border-radius: 4px;
    min-width: 24px;
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* ---- Progress bar ------------------------------------------- */
QProgressBar {{
    background-color: {c['border']};
    border-radius: 4px;
    text-align: center;
    color: {c['fg']};
    min-height: 18px;
}}

QProgressBar::chunk {{
    background-color: {c['accent']};
    border-radius: 4px;
}}

QProgressBar[role="success"]::chunk {{
    background-color: {c['success']};
}}

/* ---- Text edit ---------------------------------------------- */
QTextEdit, QPlainTextEdit {{
    background-color: {c['input_bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
    border-radius: 4px;
    padding: 4px;
    selection-background-color: {c['selected']};
    selection-color: white;
}}

/* ---- Menu bar ----------------------------------------------- */
QMenuBar {{
    background-color: {c['bg']};
    color: {c['fg']};
}}

QMenuBar::item:selected {{
    background-color: {c['hover']};
}}

QMenu {{
    background-color: {c['panel_bg']};
    color: {c['fg']};
    border: 1px solid {c['border']};
}}

QMenu::item:selected {{
    background-color: {c['selected']};
    color: white;
}}

/* ---- Status bar --------------------------------------------- */
QStatusBar {{
    background-color: {c['bg']};
    color: {c['fg']};
    font-size: {f['small']['size']}pt;
}}

QStatusBar::item {{
    border: none;
}}

/* ---- Dialogs ------------------------------------------------ */
QDialog {{
    background-color: {c['bg']};
}}

/* ---- Tool tips ---------------------------------------------- */
QToolTip {{
    background-color: {c['fg']};
    color: {c['bg']};
    border: none;
    padding: 4px 8px;
    border-radius: 4px;
    font-size: {f['small']['size']}pt;
}}

/* ---- Splitter ----------------------------------------------- */
QSplitter::handle {{
    background-color: {c['border']};
    width: 2px;
    height: 2px;
}}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class QtTheme:
    """Static helper — mirrors the ``ModernTheme`` API from theme.py."""

    COLORS = COLORS
    FONTS = FONTS
    PADDING = PADDING

    _stylesheet: str | None = None

    @classmethod
    def apply(cls, app: Any) -> None:
        """Apply the global stylesheet to a QApplication instance."""
        if cls._stylesheet is None:
            cls._stylesheet = _build_stylesheet()
        app.setStyleSheet(cls._stylesheet)

    @classmethod
    def get_stylesheet(cls) -> str:
        """Return the raw stylesheet string (for testing / inspection)."""
        if cls._stylesheet is None:
            cls._stylesheet = _build_stylesheet()
        return cls._stylesheet

    @classmethod
    def get_color(cls, name: str) -> str:
        """Return a named colour hex string."""
        return cls.COLORS.get(name, cls.COLORS["fg"])

    @classmethod
    def get_font(cls, name: str) -> dict[str, Any]:
        """Return a named font specification dict."""
        return cls.FONTS.get(name, cls.FONTS["default"])

    @classmethod
    def get_padding(cls, name: str) -> int:
        """Return a named padding value (pixels)."""
        return cls.PADDING.get(name, cls.PADDING["medium"])
