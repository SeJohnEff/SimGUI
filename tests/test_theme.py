"""Tests for theme.py — ModernTheme static methods.

These are pure class-method lookups that require no display.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from theme import ModernTheme

# ---------------------------------------------------------------------------
# get_color()
# ---------------------------------------------------------------------------

class TestGetColor:
    """Tests for ModernTheme.get_color()."""

    def test_bg_color(self):
        """get_color('bg') returns the background color string."""
        color = ModernTheme.get_color("bg")
        assert isinstance(color, str)
        assert color.startswith("#")

    def test_fg_color(self):
        """get_color('fg') returns the foreground color string."""
        color = ModernTheme.get_color("fg")
        assert isinstance(color, str)
        assert color.startswith("#")

    def test_accent_color(self):
        """get_color('accent') returns the accent color."""
        color = ModernTheme.get_color("accent")
        assert color == "#007AFF"

    def test_accent_hover_color(self):
        """get_color('accent_hover') returns hover variant."""
        color = ModernTheme.get_color("accent_hover")
        assert isinstance(color, str)
        assert color.startswith("#")

    def test_success_color(self):
        """get_color('success') returns the success color."""
        color = ModernTheme.get_color("success")
        assert color == "#34C759"

    def test_warning_color(self):
        """get_color('warning') returns the warning color."""
        color = ModernTheme.get_color("warning")
        assert color == "#FF9500"

    def test_error_color(self):
        """get_color('error') returns the error color."""
        color = ModernTheme.get_color("error")
        assert color == "#FF3B30"

    def test_border_color(self):
        """get_color('border') returns the border color."""
        color = ModernTheme.get_color("border")
        assert isinstance(color, str)
        assert color.startswith("#")

    def test_hover_color(self):
        """get_color('hover') returns the hover color."""
        color = ModernTheme.get_color("hover")
        assert isinstance(color, str)

    def test_selected_color(self):
        """get_color('selected') returns the selection color."""
        color = ModernTheme.get_color("selected")
        assert isinstance(color, str)

    def test_panel_bg_color(self):
        """get_color('panel_bg') returns the panel background."""
        color = ModernTheme.get_color("panel_bg")
        assert color == "#FFFFFF"

    def test_input_bg_color(self):
        """get_color('input_bg') returns the input background."""
        color = ModernTheme.get_color("input_bg")
        assert color == "#FFFFFF"

    def test_disabled_color(self):
        """get_color('disabled') returns the disabled state color."""
        color = ModernTheme.get_color("disabled")
        assert isinstance(color, str)
        assert color.startswith("#")

    def test_unknown_key_returns_fg_fallback(self):
        """get_color() with unknown key falls back to 'fg' color."""
        fallback = ModernTheme.get_color("nonexistent_key")
        assert fallback == ModernTheme.COLORS["fg"]

    def test_all_colors_are_hex_strings(self):
        """All entries in COLORS dict are hex color strings."""
        for name, value in ModernTheme.COLORS.items():
            assert isinstance(value, str), f"Color '{name}' is not a string"
            assert value.startswith("#"), f"Color '{name}' does not start with #"
            # Hex colors are #RGB (4), #RRGGBB (7), #RRGGBBAA (9)
            assert len(value) in (4, 7, 9), \
                f"Color '{name}' has unexpected length: {value}"


# ---------------------------------------------------------------------------
# get_padding()
# ---------------------------------------------------------------------------

class TestGetPadding:
    """Tests for ModernTheme.get_padding()."""

    def test_small_padding(self):
        """get_padding('small') returns 4."""
        assert ModernTheme.get_padding("small") == 4

    def test_medium_padding(self):
        """get_padding('medium') returns 8."""
        assert ModernTheme.get_padding("medium") == 8

    def test_large_padding(self):
        """get_padding('large') returns 16."""
        assert ModernTheme.get_padding("large") == 16

    def test_xlarge_padding(self):
        """get_padding('xlarge') returns 24."""
        assert ModernTheme.get_padding("xlarge") == 24

    def test_unknown_key_returns_medium_fallback(self):
        """get_padding() with unknown key falls back to 'medium' value (8)."""
        fallback = ModernTheme.get_padding("nonexistent")
        assert fallback == ModernTheme.PADDING["medium"]

    def test_all_paddings_are_integers(self):
        """All entries in PADDING dict are integers."""
        for name, value in ModernTheme.PADDING.items():
            assert isinstance(value, int), f"Padding '{name}' is not an int"
            assert value >= 0, f"Padding '{name}' is negative"

    def test_padding_ordering(self):
        """Padding sizes are ordered: small < medium < large < xlarge."""
        assert ModernTheme.PADDING["small"] < ModernTheme.PADDING["medium"]
        assert ModernTheme.PADDING["medium"] < ModernTheme.PADDING["large"]
        assert ModernTheme.PADDING["large"] < ModernTheme.PADDING["xlarge"]


# ---------------------------------------------------------------------------
# get_font()
# ---------------------------------------------------------------------------

class TestGetFont:
    """Tests for ModernTheme.get_font()."""

    def test_default_font(self):
        """get_font('default') returns a tuple."""
        font = ModernTheme.get_font("default")
        assert isinstance(font, tuple)
        assert len(font) >= 2  # (family, size) or (family, size, style)

    def test_heading_font(self):
        """get_font('heading') returns a tuple with 'bold'."""
        font = ModernTheme.get_font("heading")
        assert isinstance(font, tuple)
        assert "bold" in font

    def test_subheading_font(self):
        """get_font('subheading') returns a tuple."""
        font = ModernTheme.get_font("subheading")
        assert isinstance(font, tuple)

    def test_small_font(self):
        """get_font('small') returns a tuple."""
        font = ModernTheme.get_font("small")
        assert isinstance(font, tuple)

    def test_mono_font(self):
        """get_font('mono') returns a monospace font tuple."""
        font = ModernTheme.get_font("mono")
        assert isinstance(font, tuple)
        # Monospace fonts include 'Mono' or 'Consolas' or similar
        family = font[0].lower()
        assert any(kw in family for kw in ("mono", "consolas", "courier")), \
            f"Monospace font expected, got: {font[0]}"

    def test_unknown_key_returns_default_fallback(self):
        """get_font() with unknown key falls back to 'default' font."""
        fallback = ModernTheme.get_font("nonexistent")
        assert fallback == ModernTheme.FONTS["default"]

    def test_all_fonts_are_tuples(self):
        """All entries in FONTS dict are tuples."""
        for name, value in ModernTheme.FONTS.items():
            assert isinstance(value, tuple), f"Font '{name}' is not a tuple"
            assert len(value) >= 2, f"Font '{name}' tuple too short"

    def test_font_size_is_positive_int(self):
        """All font sizes are positive integers."""
        for name, font in ModernTheme.FONTS.items():
            size = font[1]
            assert isinstance(size, int), f"Font '{name}' size is not int: {size}"
            assert size > 0, f"Font '{name}' size not positive: {size}"


# ---------------------------------------------------------------------------
# ModernTheme class structure
# ---------------------------------------------------------------------------

class TestModernThemeStructure:
    """Tests for the class-level attributes of ModernTheme."""

    def test_colors_dict_exists(self):
        """COLORS class attribute is a dict."""
        assert isinstance(ModernTheme.COLORS, dict)
        assert len(ModernTheme.COLORS) > 0

    def test_padding_dict_exists(self):
        """PADDING class attribute is a dict."""
        assert isinstance(ModernTheme.PADDING, dict)
        assert len(ModernTheme.PADDING) > 0

    def test_fonts_dict_exists(self):
        """FONTS class attribute is a dict."""
        assert isinstance(ModernTheme.FONTS, dict)
        assert len(ModernTheme.FONTS) > 0

    def test_expected_color_keys_present(self):
        """COLORS dict contains the expected keys."""
        for key in ("bg", "fg", "accent", "success", "warning", "error",
                    "border", "hover", "selected", "panel_bg", "input_bg",
                    "disabled"):
            assert key in ModernTheme.COLORS, f"Missing color key: {key}"

    def test_expected_padding_keys_present(self):
        """PADDING dict contains the expected keys."""
        for key in ("small", "medium", "large", "xlarge"):
            assert key in ModernTheme.PADDING, f"Missing padding key: {key}"

    def test_expected_font_keys_present(self):
        """FONTS dict contains the expected keys."""
        for key in ("default", "heading", "subheading", "small", "mono"):
            assert key in ModernTheme.FONTS, f"Missing font key: {key}"


# ---------------------------------------------------------------------------
# _platform_fonts() — test all platform branches
# ---------------------------------------------------------------------------

class TestPlatformFonts:
    """Tests for _platform_fonts() on all platforms."""

    def test_darwin_fonts(self):
        """Darwin platform returns SF Pro fonts."""
        import platform as _platform
        from unittest.mock import patch
        with patch.object(_platform, 'system', return_value='Darwin'):
            from importlib import reload

            import theme as theme_module
            reload(theme_module)
            fonts = theme_module._platform_fonts()
        assert 'SF Pro' in fonts['default'][0] or 'SF' in fonts['default'][0]
        assert 'SF Mono' in fonts['mono'][0]

    def test_windows_fonts(self):
        """Windows platform returns Segoe UI fonts."""
        import platform as _platform
        from unittest.mock import patch
        with patch.object(_platform, 'system', return_value='Windows'):
            from importlib import reload

            import theme as theme_module
            reload(theme_module)
            fonts = theme_module._platform_fonts()
        assert 'Segoe UI' in fonts['default'][0]
        assert 'Consolas' in fonts['mono'][0]

    def test_linux_fonts(self):
        """Linux platform returns DejaVu Sans fonts."""
        import platform as _platform
        from unittest.mock import patch
        with patch.object(_platform, 'system', return_value='Linux'):
            from importlib import reload

            import theme as theme_module
            reload(theme_module)
            fonts = theme_module._platform_fonts()
        assert 'DejaVu Sans' in fonts['default'][0]

    def test_all_platforms_return_required_keys(self):
        """All platform font dicts have required keys."""
        import platform as _platform
        from unittest.mock import patch
        required = ('default', 'heading', 'subheading', 'small', 'mono')
        for plat in ('Darwin', 'Linux', 'Windows', 'FreeBSD'):
            with patch.object(_platform, 'system', return_value=plat):
                from importlib import reload

                import theme as theme_module
                reload(theme_module)
                fonts = theme_module._platform_fonts()
            for key in required:
                assert key in fonts, f"Platform {plat}: missing key '{key}'"
