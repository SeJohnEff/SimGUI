#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for qt_theme.py — Phase 0 stylesheet and accessors."""

import pytest
from qt_theme import QtTheme, COLORS, FONTS, PADDING


class TestQtThemeColors:

    def test_all_colors_are_hex(self):
        for name, value in COLORS.items():
            assert value.startswith("#"), f"Color '{name}' is not hex: {value}"
            # 4 or 7 chars (#RGB or #RRGGBB)
            assert len(value) in (4, 7), f"Color '{name}' invalid length: {value}"

    def test_get_color_known(self):
        assert QtTheme.get_color("accent") == COLORS["accent"]
        assert QtTheme.get_color("error") == COLORS["error"]

    def test_get_color_unknown_returns_fg(self):
        assert QtTheme.get_color("nonexistent") == COLORS["fg"]

    def test_palette_has_required_keys(self):
        required = {"bg", "fg", "accent", "success", "warning", "error",
                     "border", "panel_bg", "input_bg", "disabled"}
        assert required.issubset(set(COLORS.keys()))


class TestQtThemeFonts:

    def test_all_fonts_have_family_and_size(self):
        for name, spec in FONTS.items():
            assert "family" in spec, f"Font '{name}' missing 'family'"
            assert "size" in spec, f"Font '{name}' missing 'size'"
            assert isinstance(spec["size"], int)

    def test_get_font_known(self):
        f = QtTheme.get_font("heading")
        assert f["family"]
        assert f["size"] > 0
        assert f.get("weight") == "bold"

    def test_get_font_unknown_returns_default(self):
        f = QtTheme.get_font("nonexistent")
        assert f == FONTS["default"]

    def test_font_names(self):
        assert set(FONTS.keys()) == {"default", "heading", "subheading", "small", "mono"}


class TestQtThemePadding:

    def test_all_padding_positive_int(self):
        for name, value in PADDING.items():
            assert isinstance(value, int) and value > 0, \
                f"Padding '{name}' is not positive int: {value}"

    def test_get_padding_known(self):
        assert QtTheme.get_padding("small") == 4
        assert QtTheme.get_padding("medium") == 8

    def test_get_padding_unknown_returns_medium(self):
        assert QtTheme.get_padding("nonexistent") == PADDING["medium"]


class TestQtThemeStylesheet:

    def test_stylesheet_is_string(self):
        ss = QtTheme.get_stylesheet()
        assert isinstance(ss, str)
        assert len(ss) > 1000  # non-trivial

    def test_stylesheet_contains_key_selectors(self):
        ss = QtTheme.get_stylesheet()
        for selector in ["QWidget", "QLabel", "QPushButton", "QLineEdit",
                         "QComboBox", "QGroupBox", "QTabWidget", "QStatusBar",
                         "QProgressBar", "QMenuBar"]:
            assert selector in ss, f"Missing selector: {selector}"

    def test_stylesheet_uses_palette_colors(self):
        ss = QtTheme.get_stylesheet()
        assert COLORS["accent"] in ss
        assert COLORS["bg"] in ss
        assert COLORS["fg"] in ss

    def test_stylesheet_cached(self):
        ss1 = QtTheme.get_stylesheet()
        ss2 = QtTheme.get_stylesheet()
        assert ss1 is ss2  # same object (cached)

    def test_colors_match_tkinter_theme(self):
        """Verify the palette is identical to the tkinter ModernTheme."""
        # Import the original — this proves colour parity
        from theme import ModernTheme
        for key in COLORS:
            assert COLORS[key] == ModernTheme.COLORS.get(key, None), \
                f"Color mismatch for '{key}': Qt={COLORS[key]}, Tk={ModernTheme.COLORS.get(key)}"
