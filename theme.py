"""SimGUI ModernTheme — unified styling for the SIM Card Programmer.

Provides colours, fonts, and padding constants.
Call ``ModernTheme.apply_theme(root)`` once at startup.
"""

import platform
import tkinter as tk
from tkinter import ttk

_PLATFORM = platform.system()


class ModernTheme:
    """Centralised look-and-feel constants and ttk style configuration."""

    # ---- Fonts (platform-adaptive) ------------------------------------------
    if _PLATFORM == 'Darwin':
        family, display, mono = 'SF Pro', 'SF Pro Display', 'SF Mono'
        FONTS = {
            'default': (family, 13),
            'heading': (display, 18, 'bold'),
            'subheading': (family, 14, 'bold'),
            'small': (family, 11),
            'mono': (mono, 11),
        }
    elif _PLATFORM == 'Linux':
        family, display, mono = 'Ubuntu', 'Ubuntu', 'Ubuntu Mono'
        FONTS = {
            'default': (family, 10),
            'heading': (family, 14, 'bold'),
            'subheading': (family, 11, 'bold'),
            'small': (family, 9),
            'mono': (mono, 9),
        }
    else:
        family, display, mono = 'Segoe UI', 'Segoe UI', 'Consolas'
        FONTS = {
            'default': (family, 10),
            'heading': (family, 14, 'bold'),
            'subheading': (family, 11, 'bold'),
            'small': (family, 9),
            'mono': (mono, 9),
        }

    # ---- Colour palette ----------------------------------------------------
    COLORS = {
        'bg': '#F5F5F7',
        'fg': '#1D1D1F',
        'accent': '#007AFF',
        'accent_hover': '#0051D5',
        'success': '#34C759',
        'warning': '#FF9500',
        'error': '#FF3B30',
        'border': '#D1D1D6',
        'hover': '#E8E8ED',
        'selected': '#007AFF',
        'panel_bg': '#FFFFFF',
        'input_bg': '#FFFFFF',
        'disabled': '#8E8E93',
    }

    # ---- Padding -----------------------------------------------------------
    _PADDING = {
        'small': 4,
        'medium': 8,
        'large': 16,
    }

    @classmethod
    def get_padding(cls, size: str = 'medium') -> int:
        return cls._PADDING.get(size, cls._PADDING['medium'])

    @classmethod
    def get_font(cls, name: str = 'default'):
        return cls.FONTS.get(name, cls.FONTS['default'])

    @classmethod
    def get_color(cls, name: str) -> str:
        return cls.COLORS.get(name, cls.COLORS['fg'])

    # ---- Apply to a Tk root ------------------------------------------------
    @classmethod
    def apply_theme(cls, root):
        """Configure ttk styles on *root* and return the Style object."""
        style = ttk.Style(root)
        root.configure(bg=cls.COLORS['bg'])

        # Widget defaults
        style.configure('.', font=cls.FONTS['default'],
                        background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'])
        style.configure('Heading.TLabel', font=cls.FONTS['heading'])
        style.configure('Subheading.TLabel', font=cls.FONTS['subheading'])
        style.configure('Small.TLabel', font=cls.FONTS['small'])

        # Accent.TButton (primary action style)
        style.configure('Accent.TButton', foreground='white',
                        background=cls.COLORS['accent'])
        style.map('Accent.TButton',
                  background=[('disabled', cls.COLORS['disabled']),
                              ('active', cls.COLORS['accent_hover']),
                              ('pressed', cls.COLORS['accent_hover'])],
                  foreground=[('disabled', cls.COLORS['fg'])])

        # Primary.TButton is an alias for Accent.TButton
        style.configure('Primary.TButton', foreground='white',
                        background=cls.COLORS['accent'])
        style.map('Primary.TButton',
                  background=[('disabled', cls.COLORS['disabled']),
                              ('active', cls.COLORS['accent_hover']),
                              ('pressed', cls.COLORS['accent_hover'])],
                  foreground=[('disabled', cls.COLORS['fg'])])

        style.configure('TLabelframe', background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'])
        style.configure('TLabelframe.Label', background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'])

        # Success/Warning/Error labels
        style.configure('Success.TLabel',
                        foreground=cls.COLORS['success'])
        style.configure('Warning.TLabel',
                        foreground=cls.COLORS['warning'])
        style.configure('Error.TLabel',
                        foreground=cls.COLORS['error'])

        # TEntry and readonly
        style.configure('TEntry', fieldbackground=cls.COLORS['input_bg'])
        style.map('TEntry',
                  fieldbackground=[('readonly', cls.COLORS['bg'])])

        # Copyable.TEntry — read-only but selectable
        style.configure('Copyable.TEntry',
                        fieldbackground=cls.COLORS['bg'])
        style.map('Copyable.TEntry',
                  fieldbackground=[('readonly', cls.COLORS['bg'])])

        # Treeview colours
        style.configure('Treeview', rowheight=24,
                        background=cls.COLORS['panel_bg'],
                        fieldbackground=cls.COLORS['panel_bg'],
                        foreground=cls.COLORS['fg'])
        style.configure('Treeview.Heading', font=cls.FONTS['subheading'],
                        background=cls.COLORS['accent'])

        return style
