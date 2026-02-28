#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SimGUI Theme - Modern macOS-like Theme Configuration

Provides a consistent look and feel across the application.
Self-contained: no dependency on the CLI tool.
"""

import tkinter as tk
from tkinter import ttk
import platform


class ModernTheme:
    """Modern macOS-like theme configuration"""

    # Color palette - macOS Big Sur inspired
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

    FONTS = {
        'default': ('SF Pro Text', 13) if platform.system() == 'Darwin' else ('Segoe UI', 10),
        'heading': ('SF Pro Display', 18, 'bold') if platform.system() == 'Darwin' else ('Segoe UI', 14, 'bold'),
        'subheading': ('SF Pro Text', 14, 'bold') if platform.system() == 'Darwin' else ('Segoe UI', 11, 'bold'),
        'small': ('SF Pro Text', 11) if platform.system() == 'Darwin' else ('Segoe UI', 9),
        'mono': ('SF Mono', 11) if platform.system() == 'Darwin' else ('Consolas', 9),
    }

    PADDING = {
        'small': 4,
        'medium': 8,
        'large': 16,
        'xlarge': 24,
    }

    @classmethod
    def apply_theme(cls, root):
        """Apply modern theme to the root window"""
        style = ttk.Style(root)
        style.theme_use('clam')
        root.configure(bg=cls.COLORS['bg'])

        style.configure('TFrame', background=cls.COLORS['bg'])
        style.configure('Card.TFrame', background=cls.COLORS['panel_bg'],
                        relief='flat', borderwidth=0)

        style.configure('TLabel', background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'], font=cls.FONTS['default'])
        style.configure('Heading.TLabel', font=cls.FONTS['heading'])
        style.configure('Subheading.TLabel', font=cls.FONTS['subheading'])
        style.configure('Small.TLabel', font=cls.FONTS['small'],
                        foreground=cls.COLORS['disabled'])
        style.configure('Success.TLabel', foreground=cls.COLORS['success'])
        style.configure('Error.TLabel', foreground=cls.COLORS['error'])
        style.configure('Warning.TLabel', foreground=cls.COLORS['warning'])

        style.configure('TButton', font=cls.FONTS['default'],
                        padding=(cls.PADDING['medium'], cls.PADDING['small']))
        style.configure('Accent.TButton', foreground='white',
                        background=cls.COLORS['accent'])
        style.map('Accent.TButton',
                  background=[('active', cls.COLORS['accent_hover']),
                              ('pressed', cls.COLORS['accent_hover'])])

        style.configure('TLabelframe', background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'])
        style.configure('TLabelframe.Label', background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'],
                        font=cls.FONTS['subheading'])

        style.configure('TEntry', fieldbackground=cls.COLORS['input_bg'],
                        foreground=cls.COLORS['fg'])

        style.configure('Treeview', background=cls.COLORS['panel_bg'],
                        foreground=cls.COLORS['fg'],
                        fieldbackground=cls.COLORS['panel_bg'],
                        font=cls.FONTS['default'], rowheight=28)
        style.configure('Treeview.Heading', font=cls.FONTS['subheading'],
                        background=cls.COLORS['bg'],
                        foreground=cls.COLORS['fg'])
        style.map('Treeview',
                  background=[('selected', cls.COLORS['selected'])],
                  foreground=[('selected', 'white')])

        style.configure('TNotebook', background=cls.COLORS['bg'])
        style.configure('TNotebook.Tab', font=cls.FONTS['default'],
                        padding=(cls.PADDING['medium'], cls.PADDING['small']))

        style.configure('TProgressbar', troughcolor=cls.COLORS['border'],
                        background=cls.COLORS['accent'])
        style.configure('Success.Horizontal.TProgressbar',
                        background=cls.COLORS['success'])

        style.configure('TScrollbar', troughcolor=cls.COLORS['bg'],
                        background=cls.COLORS['border'])
        return style

    @classmethod
    def get_color(cls, name):
        return cls.COLORS.get(name, cls.COLORS['fg'])

    @classmethod
    def get_font(cls, name):
        return cls.FONTS.get(name, cls.FONTS['default'])

    @classmethod
    def get_padding(cls, name):
        return cls.PADDING.get(name, cls.PADDING['medium'])
