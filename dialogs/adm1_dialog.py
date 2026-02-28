"""
ADM1 Key Input Dialog

Modal dialog for entering the ADM1 authentication key
with input validation and attempt tracking.
"""
import tkinter as tk
from tkinter import ttk, messagebox
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from theme import ModernTheme


class ADM1Dialog(tk.Toplevel):
  """Dialog for entering ADM1 key."""

  def __init__(self, parent, remaining_attempts: int = 3):
    super().__init__(parent)
    self.title("Enter ADM1 Key")
    self.transient(parent)
    self.grab_set()
    self.configure(bg=ModernTheme.get_color('bg'))

    self.remaining_attempts = remaining_attempts
    self.adm1_value = None
    self.force_auth = tk.BooleanVar(value=False)

    self._create_widgets()
    self._center_window()
    self._setup_clipboard()
    self.adm1_entry.focus()

  def _setup_clipboard(self):
    """Setup clipboard bindings with sanitization."""
    self.bind_class('Entry', '<Control-v>', self._paste_sanitized)
    self.bind_class('Entry', '<Command-v>', self._paste_sanitized)

  def _paste_sanitized(self, event):
    """Paste from clipboard, stripping non-printable characters."""
    try:
      widget = event.widget
      text = widget.clipboard_get()
      text = ''.join(ch for ch in text if ch.isprintable())
      if hasattr(widget, 'select_present') and widget.select_present():
        widget.delete(tk.SEL_FIRST, tk.SEL_LAST)
      widget.insert(tk.INSERT, text)
      self._validate_input()
      return 'break'
    except tk.TclError:
      pass

  def _create_widgets(self):
    """Create dialog widgets."""
    pad = ModernTheme.get_padding
    main_frame = ttk.Frame(self, padding=pad('large'))
    main_frame.grid(row=0, column=0, sticky='nsew')

    row = 0
    # Warning banner for low attempts
    if self.remaining_attempts < 3:
      warning_frame = ttk.Frame(main_frame, relief=tk.SOLID, borderwidth=2)
      warning_frame.grid(row=row, column=0, columnspan=2, sticky='ew', pady=(0, pad('medium')))
      ttk.Label(
        warning_frame,
        text=f"WARNING: Only {self.remaining_attempts} attempts remaining!\nCard will lock after {self.remaining_attempts} more failed attempts!",
        foreground=ModernTheme.get_color('error'),
        font=ModernTheme.get_font('subheading'),
        padding=pad('medium')
      ).grid(row=0, column=0)
      row += 1

    # ADM1 entry
    ttk.Label(main_frame, text="ADM1 Key:", style='Subheading.TLabel').grid(
      row=row, column=0, sticky=tk.W, pady=(0, pad('small')))
    entry_font = (ModernTheme.get_font('default')[0], 16)
    self.adm1_entry = ttk.Entry(main_frame, width=12, font=entry_font)
    self.adm1_entry.grid(row=row, column=1, sticky='ew', pady=(0, pad('small')))
    self.adm1_entry.bind('<Return>', lambda e: self._on_ok())
    row += 1

    # Validation label
    self.validation_label = ttk.Label(
      main_frame, text="8 digits required",
      foreground=ModernTheme.get_color('disabled'),
      font=ModernTheme.get_font('small'))
    self.validation_label.grid(row=row, column=1, sticky=tk.W)
    self.adm1_entry.bind('<KeyRelease>', self._validate_input)
    row += 1

    # Force checkbox
    if self.remaining_attempts < 3:
      ttk.Checkbutton(
        main_frame, text="Force authentication (risky!)",
        variable=self.force_auth
      ).grid(row=row, column=0, columnspan=2, sticky=tk.W, pady=pad('small'))
      row += 1

    # Buttons
    btn_frame = ttk.Frame(main_frame)
    btn_frame.grid(row=row, column=0, columnspan=2, pady=(pad('medium'), 0))
    self.ok_button = ttk.Button(
      btn_frame, text="Authenticate", command=self._on_ok,
      state=tk.DISABLED, style='Primary.TButton')
    self.ok_button.grid(row=0, column=0, padx=(0, pad('small')))
    ttk.Button(btn_frame, text="Cancel", command=self._on_cancel).grid(row=0, column=1)
    row += 1

    # Help text
    ttk.Label(
      main_frame,
      text="The ADM1 key is unique to each card.\nIt should be printed on your card carrier.",
      font=ModernTheme.get_font('small'),
      foreground=ModernTheme.get_color('disabled')
    ).grid(row=row, column=0, columnspan=2, pady=(pad('small'), 0))

  def _validate_input(self, event=None):
    """Validate ADM1 input in real-time."""
    value = self.adm1_entry.get()
    if len(value) == 0:
      self.validation_label.config(text="8 digits required", foreground="gray")
      self.ok_button.config(state=tk.DISABLED)
    elif not value.isdigit():
      self.validation_label.config(text="Only digits allowed", foreground="red")
      self.ok_button.config(state=tk.DISABLED)
    elif len(value) < 8:
      self.validation_label.config(text=f"{8 - len(value)} more digits needed", foreground="orange")
      self.ok_button.config(state=tk.DISABLED)
    elif len(value) == 8:
      self.validation_label.config(text="Valid format", foreground="green")
      self.ok_button.config(state=tk.NORMAL)
    else:
      self.validation_label.config(text="Too many digits", foreground="red")
      self.ok_button.config(state=tk.DISABLED)

  def _on_ok(self):
    """Handle OK button."""
    value = self.adm1_entry.get()
    if len(value) != 8 or not value.isdigit():
      messagebox.showerror("Invalid Input", "ADM1 key must be exactly 8 digits")
      return
    if self.remaining_attempts < 3 and not self.force_auth.get():
      result = messagebox.askyesno(
        "Confirm",
        f"You have only {self.remaining_attempts} attempts remaining.\n\n"
        "Are you SURE this ADM1 key is correct?\n\n"
        "Wrong key will lock your card!",
        icon=messagebox.WARNING)
      if not result:
        return
    self.adm1_value = value
    self.destroy()

  def _on_cancel(self):
    """Handle Cancel button."""
    self.adm1_value = None
    self.destroy()

  def _center_window(self):
    """Center dialog on parent."""
    self.update_idletasks()
    w, h = self.winfo_width(), self.winfo_height()
    x = (self.winfo_screenwidth() // 2) - (w // 2)
    y = (self.winfo_screenheight() // 2) - (h // 2)
    self.geometry(f'{w}x{h}+{x}+{y}')

  def get_adm1(self) -> tuple:
    """Get ADM1 key from user. Returns (adm1_key, force_auth)."""
    self.wait_window()
    return self.adm1_value, self.force_auth.get()
