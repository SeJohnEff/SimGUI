"""
Progress Panel Widget - Shows progress for batch operations.
"""
import tkinter as tk
from tkinter import ttk


class ProgressPanel(ttk.Frame):
  """Panel that displays progress bars and log output for long-running operations."""

  def __init__(self, parent, **kwargs):
    super().__init__(parent, **kwargs)
    self._build_ui()

  def _build_ui(self):
    # Main progress bar
    prog_frame = ttk.LabelFrame(self, text="Operation Progress")
    prog_frame.pack(fill=tk.X, padx=5, pady=5)

    self._progress_label = ttk.Label(prog_frame, text="Idle")
    self._progress_label.pack(anchor=tk.W, padx=5, pady=(5, 0))

    self._progress_bar = ttk.Progressbar(
      prog_frame, orient=tk.HORIZONTAL, mode='determinate'
    )
    self._progress_bar.pack(fill=tk.X, padx=5, pady=5)

    self._percent_label = ttk.Label(prog_frame, text="0%")
    self._percent_label.pack(anchor=tk.E, padx=5)

    # Log output
    log_frame = ttk.LabelFrame(self, text="Log Output")
    log_frame.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

    self._log_text = tk.Text(log_frame, height=8, state=tk.DISABLED, wrap=tk.WORD)
    scrollbar = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=self._log_text.yview)
    self._log_text.configure(yscrollcommand=scrollbar.set)

    self._log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(5, 0), pady=5)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y, padx=(0, 5), pady=5)

    # Control buttons
    btn_frame = ttk.Frame(self)
    btn_frame.pack(fill=tk.X, padx=5, pady=5)

    self._clear_btn = ttk.Button(btn_frame, text="Clear Log", command=self.clear_log)
    self._clear_btn.pack(side=tk.RIGHT)

  def set_progress(self, value, maximum=100, label=None):
    """Update the progress bar value and optional label."""
    self._progress_bar['maximum'] = maximum
    self._progress_bar['value'] = value
    pct = int((value / maximum) * 100) if maximum > 0 else 0
    self._percent_label.configure(text=f"{pct}%")
    if label:
      self._progress_label.configure(text=label)

  def set_indeterminate(self, running=True):
    """Switch progress bar to indeterminate mode."""
    if running:
      self._progress_bar.configure(mode='indeterminate')
      self._progress_bar.start(10)
    else:
      self._progress_bar.stop()
      self._progress_bar.configure(mode='determinate')

  def log(self, message):
    """Append a message to the log output."""
    self._log_text.configure(state=tk.NORMAL)
    self._log_text.insert(tk.END, message + "\n")
    self._log_text.see(tk.END)
    self._log_text.configure(state=tk.DISABLED)

  def clear_log(self):
    """Clear the log output."""
    self._log_text.configure(state=tk.NORMAL)
    self._log_text.delete("1.0", tk.END)
    self._log_text.configure(state=tk.DISABLED)

  def reset(self):
    """Reset progress and label to idle state."""
    self._progress_bar.stop()
    self._progress_bar.configure(mode='determinate', value=0)
    self._progress_label.configure(text="Idle")
    self._percent_label.configure(text="0%")
