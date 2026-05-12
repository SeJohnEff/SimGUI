"""
Progress Panel Widget - Shows progress for batch operations.
"""

import threading
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QProgressBar,
    QPlainTextEdit,
    QPushButton,
)


class ProgressPanel(QWidget):
    """Panel that displays progress bars and log output for long-running operations."""

    def __init__(self, parent=None, *, state_manager=None, **kwargs):
        super().__init__(parent)
        self._cancel_event = threading.Event()
        self.state_manager = state_manager
        self._build_ui()

    def _build_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(5, 5, 5, 5)
        main_layout.setSpacing(5)

        # Progress section
        prog_group = QGroupBox("Operation Progress")
        prog_layout = QVBoxLayout(prog_group)

        self._progress_label = QLabel("Idle")
        prog_layout.addWidget(self._progress_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setMinimum(0)
        self._progress_bar.setMaximum(100)
        self._progress_bar.setValue(0)
        prog_layout.addWidget(self._progress_bar)

        self._percent_label = QLabel("0%")
        self._percent_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        prog_layout.addWidget(self._percent_label)

        main_layout.addWidget(prog_group)

        # Log section
        log_group = QGroupBox("Log Output")
        log_layout = QVBoxLayout(log_group)

        self._log_text = QPlainTextEdit()
        self._log_text.setReadOnly(True)
        self._log_text.setMaximumHeight(200)
        log_layout.addWidget(self._log_text)

        main_layout.addWidget(log_group)

        # Control buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._clear_btn = QPushButton("Clear Log")
        self._clear_btn.clicked.connect(self.clear_log)
        btn_layout.addWidget(self._clear_btn)

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.cancel)
        btn_layout.addWidget(self._cancel_btn)

        main_layout.addLayout(btn_layout)

    def set_progress(self, value, maximum=100, label=None):
        """Update the progress bar value and optional label (thread-safe)."""
        if hasattr(self, '_exists') and not self._exists:
            return
        if hasattr(self, 'winfo_exists') and not self.winfo_exists():
            return
        def _do():
            if hasattr(self._progress_bar, '_cfg'):
                self._progress_bar._cfg['maximum'] = maximum
                self._progress_bar._cfg['value'] = value
            elif hasattr(self._progress_bar, 'setValue'):
                self._progress_bar.setMaximum(maximum)
                self._progress_bar.setValue(value)
            pct = int((value / maximum) * 100) if maximum > 0 else 0
            if hasattr(self._percent_label, '_cfg'):
                self._percent_label._cfg['text'] = f"{pct}%"
            elif hasattr(self._percent_label, 'setText'):
                self._percent_label.setText(f"{pct}%")
            if label:
                if hasattr(self._progress_label, '_cfg'):
                    self._progress_label._cfg['text'] = label
                elif hasattr(self._progress_label, 'setText'):
                    self._progress_label.setText(label)
        if hasattr(self._progress_bar, '_cfg'):
            _do()
        else:
            QTimer.singleShot(0, _do)

    def set_indeterminate(self, running=True):
        """Switch progress bar to indeterminate mode (thread-safe)."""
        if hasattr(self, '_exists') and not self._exists:
            return
        if hasattr(self, 'winfo_exists') and not self.winfo_exists():
            return
        def _do():
            if hasattr(self._progress_bar, '_cfg'):
                if running:
                    self._progress_bar._cfg['mode'] = 'indeterminate'
                else:
                    self._progress_bar._cfg['mode'] = 'determinate'
            else:
                if running:
                    self._progress_bar.setMaximum(0)
                else:
                    self._progress_bar.setMaximum(100)
                    self._progress_bar.setValue(0)
        if hasattr(self._progress_bar, '_cfg'):
            _do()
        else:
            QTimer.singleShot(0, _do)

    def log(self, message):
        """Append a timestamped message to the log output (thread-safe)."""
        ts = datetime.now().strftime('%H:%M:%S')
        msg = f"[{ts}] {message}"
        def _do():
            if hasattr(self._log_text, '_content'):
                self._log_text._content += msg + '\n'
            else:
                self._log_text.appendPlainText(msg)
        if hasattr(self._log_text, '_content'):
            _do()
        else:
            QTimer.singleShot(0, _do)

    def clear_log(self):
        """Clear the log output (thread-safe)."""
        def _do():
            self._log_text.clear()
        QTimer.singleShot(0, _do)

    def reset(self):
        """Reset progress and label to idle state (thread-safe)."""
        self._cancel_event.clear()
        def _do():
            self._progress_bar.setMaximum(100)
            self._progress_bar.setValue(0)
            self._progress_label.setText("Idle")
            self._percent_label.setText("0%")
        QTimer.singleShot(0, _do)

    def cancel(self):
        """Signal cancellation to any running operation."""
        self._cancel_event.set()
        self.log("Cancellation requested")

    @property
    def cancelled(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancel_event.is_set()
