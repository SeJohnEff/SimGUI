"""Extended tests for theme.py — cover apply_theme() without a display.

Missed lines: 80-155 (apply_theme body).
Strategy: mock ttk.Style so no actual Tk window is needed.
"""

import os
import platform
import sys
from unittest.mock import MagicMock, patch, call

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# We need to mock tkinter before importing theme since theme.py does
# `import tkinter as tk; from tkinter import ttk` at module level.
# However theme.py may already be imported.  We patch ttk.Style only.


class TestApplyTheme:
    """Tests for ModernTheme.apply_theme() using a mocked style object."""

    def _call_apply_theme(self):
        """Call apply_theme with a fully mocked root and ttk.Style."""
        from theme import ModernTheme

        mock_root = MagicMock()
        mock_style = MagicMock()

        with patch("theme.ttk.Style", return_value=mock_style):
            result = ModernTheme.apply_theme(mock_root)

        return result, mock_root, mock_style

    def test_apply_theme_returns_style(self):
        """apply_theme() returns the ttk.Style object (line 155)."""
        result, _, mock_style = self._call_apply_theme()
        assert result is mock_style

    def test_apply_theme_calls_theme_use_clam(self):
        """apply_theme() calls style.theme_use('clam') (line 81)."""
        _, _, mock_style = self._call_apply_theme()
        mock_style.theme_use.assert_called_once_with("clam")

    def test_apply_theme_configures_root_bg(self):
        """apply_theme() configures root background (line 82)."""
        from theme import ModernTheme
        _, mock_root, _ = self._call_apply_theme()
        mock_root.configure.assert_called_once_with(bg=ModernTheme.COLORS["bg"])

    def test_apply_theme_configures_tframe(self):
        """apply_theme() configures TFrame style (line 84)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("TFrame" in c for c in calls)

    def test_apply_theme_configures_tlabel(self):
        """apply_theme() configures TLabel style (line 88)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("TLabel" in c for c in calls)

    def test_apply_theme_configures_accent_button(self):
        """apply_theme() configures Accent.TButton style (line 102)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("Accent.TButton" in c for c in calls)

    def test_apply_theme_configures_primary_button(self):
        """apply_theme() configures Primary.TButton as alias (line 109)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("Primary.TButton" in c for c in calls)

    def test_apply_theme_configures_treeview(self):
        """apply_theme() configures Treeview style (line 133)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("Treeview" in c for c in calls)

    def test_apply_theme_configures_tnotebook(self):
        """apply_theme() configures TNotebook (line 144)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("TNotebook" in c for c in calls)

    def test_apply_theme_configures_progressbar(self):
        """apply_theme() configures TProgressbar (line 148)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("TProgressbar" in c for c in calls)

    def test_apply_theme_configures_scrollbar(self):
        """apply_theme() configures TScrollbar (line 153)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("TScrollbar" in c for c in calls)

    def test_apply_theme_maps_accent_button_states(self):
        """apply_theme() calls style.map for Accent.TButton active/pressed states."""
        _, _, mock_style = self._call_apply_theme()
        map_calls = [str(c) for c in mock_style.map.call_args_list]
        assert any("Accent.TButton" in c for c in map_calls)

    def test_apply_theme_maps_primary_button_states(self):
        """apply_theme() calls style.map for Primary.TButton."""
        _, _, mock_style = self._call_apply_theme()
        map_calls = [str(c) for c in mock_style.map.call_args_list]
        assert any("Primary.TButton" in c for c in map_calls)

    def test_apply_theme_maps_treeview_selection(self):
        """apply_theme() calls style.map for Treeview selection."""
        _, _, mock_style = self._call_apply_theme()
        map_calls = [str(c) for c in mock_style.map.call_args_list]
        assert any("Treeview" in c for c in map_calls)

    def test_apply_theme_configures_copyable_entry(self):
        """apply_theme() configures Copyable.TEntry style (line 126)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("Copyable.TEntry" in c for c in calls)

    def test_apply_theme_configures_labelframe(self):
        """apply_theme() configures TLabelframe style (line 115)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("TLabelframe" in c for c in calls)

    def test_apply_theme_configures_success_progressbar(self):
        """apply_theme() configures Success.Horizontal.TProgressbar (line 150)."""
        _, _, mock_style = self._call_apply_theme()
        calls = [str(c) for c in mock_style.configure.call_args_list]
        assert any("Success.Horizontal.TProgressbar" in c for c in calls)


class TestModernThemeGetters:
    """Tests for other ModernTheme methods."""

    def test_get_color_known(self):
        """get_color returns the value for a known key."""
        from theme import ModernTheme
        assert ModernTheme.get_color("accent") == "#007AFF"

    def test_get_color_unknown_falls_back_to_fg(self):
        """get_color returns fg color for unknown key."""
        from theme import ModernTheme
        result = ModernTheme.get_color("nonexistent_key_xyz")
        assert result == ModernTheme.COLORS["fg"]

    def test_get_padding_all_keys(self):
        """get_padding returns correct values for all keys."""
        from theme import ModernTheme
        assert ModernTheme.get_padding("small") == 4
        assert ModernTheme.get_padding("medium") == 8
        assert ModernTheme.get_padding("large") == 16
        assert ModernTheme.get_padding("xlarge") == 24

    def test_fonts_dict_has_required_keys(self):
        """FONTS dict has all required keys."""
        from theme import ModernTheme
        required = {"default", "heading", "subheading", "small", "mono"}
        assert required.issubset(set(ModernTheme.FONTS.keys()))

    def test_all_font_values_are_tuples(self):
        """All font values are tuples."""
        from theme import ModernTheme
        for key, value in ModernTheme.FONTS.items():
            assert isinstance(value, tuple), f"Font '{key}' is not a tuple"

    def test_colors_dict_has_required_keys(self):
        """COLORS dict has all required keys."""
        from theme import ModernTheme
        required = {
            "bg", "fg", "accent", "accent_hover", "success",
            "warning", "error", "border", "disabled", "panel_bg",
        }
        assert required.issubset(set(ModernTheme.COLORS.keys()))


class TestPlatformFonts:
    """Tests for _platform_fonts() function on all platforms."""

    def test_darwin_fonts(self):
        """Darwin (macOS) returns SF Pro fonts."""
        from theme import _platform_fonts
        with patch("platform.system", return_value="Darwin"):
            fonts = _platform_fonts()
        assert "SF Pro" in fonts["default"][0] or "SF" in fonts["default"][0]

    def test_linux_fonts(self):
        """Linux returns DejaVu fonts."""
        from theme import _platform_fonts
        with patch("platform.system", return_value="Linux"):
            fonts = _platform_fonts()
        assert "DejaVu" in fonts["default"][0]

    def test_windows_fonts(self):
        """Windows returns Segoe UI fonts."""
        from theme import _platform_fonts
        with patch("platform.system", return_value="Windows"):
            fonts = _platform_fonts()
        assert "Segoe" in fonts["default"][0]

    def test_unknown_platform_fonts(self):
        """Unknown platform falls back to Windows-style fonts."""
        from theme import _platform_fonts
        with patch("platform.system", return_value="FreeBSD"):
            fonts = _platform_fonts()
        # Should use the else branch (Windows/others)
        assert "Segoe" in fonts["default"][0]
