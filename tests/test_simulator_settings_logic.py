"""Tests for dialogs/simulator_settings_dialog.py.

We cannot instantiate SimulatorSettingsDialog (it calls tk.Toplevel + wait_window).
Instead we test the pure logic methods by extracting them into a harness.
"""

import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest.mock as _mock

# ---------------------------------------------------------------------------
# A harness that replicates the pure-logic parts of SimulatorSettingsDialog
# ---------------------------------------------------------------------------

class _FakeVar:
    """Fake tkinter variable (IntVar, StringVar)."""

    def __init__(self, value=None):
        self._v = value

    def set(self, v):
        self._v = v

    def get(self):
        return self._v


class _FakeLabel:
    def __init__(self, **kw):
        self._text = kw.get("text", "")

    def configure(self, **kw):
        self._text = kw.get("text", self._text)


class SimulatorSettingsHarness:
    """Replicates SimulatorSettingsDialog pure logic for testing."""

    def __init__(self, settings):
        self._settings = settings
        self._applied = False

        # Fake vars
        self._csv_var = _FakeVar(value=settings.card_data_path or "")
        self._delay_var = _FakeVar(value=settings.delay_ms)
        self._error_var = _FakeVar(value=int(settings.error_rate * 100))
        self._num_var = _FakeVar(value=settings.num_cards)

        # Fake labels
        self._delay_label = _FakeLabel(text=str(settings.delay_ms))
        self._error_label = _FakeLabel(text=str(int(settings.error_rate * 100)))

    def _reset_defaults(self):
        """Restore all fields to factory defaults."""
        self._csv_var.set("")
        self._delay_var.set(500)
        self._delay_label.configure(text="500")
        self._error_var.set(0)
        self._error_label.configure(text="0")
        self._num_var.set(10)

    def _apply(self):
        """Apply settings and mark as applied."""
        csv_path = self._csv_var.get().strip() or None
        self._settings.card_data_path = csv_path
        self._settings.delay_ms = self._delay_var.get()
        self._settings.error_rate = self._error_var.get() / 100.0
        self._settings.num_cards = self._num_var.get()
        self._applied = True

    @property
    def applied(self):
        return self._applied


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSimulatorSettingsApply:
    """Tests for _apply() logic."""

    def _settings(self, delay=500, error_rate=0.0, num_cards=10, csv_path=None):
        from simulator.settings import SimulatorSettings
        return SimulatorSettings(
            delay_ms=delay,
            error_rate=error_rate,
            num_cards=num_cards,
            card_data_path=csv_path,
        )

    def test_apply_sets_delay(self):
        """_apply() updates delay_ms from the var."""
        s = self._settings(delay=500)
        h = SimulatorSettingsHarness(s)
        h._delay_var.set(1000)
        h._apply()
        assert s.delay_ms == 1000

    def test_apply_sets_error_rate(self):
        """_apply() converts integer percentage to float error_rate."""
        s = self._settings(error_rate=0.0)
        h = SimulatorSettingsHarness(s)
        h._error_var.set(25)  # 25%
        h._apply()
        assert abs(s.error_rate - 0.25) < 1e-9

    def test_apply_sets_num_cards(self):
        """_apply() updates num_cards from the var."""
        s = self._settings(num_cards=10)
        h = SimulatorSettingsHarness(s)
        h._num_var.set(20)
        h._apply()
        assert s.num_cards == 20

    def test_apply_sets_csv_path(self):
        """_apply() updates card_data_path from the CSV var."""
        s = self._settings()
        h = SimulatorSettingsHarness(s)
        h._csv_var.set("/some/path.csv")
        h._apply()
        assert s.card_data_path == "/some/path.csv"

    def test_apply_sets_csv_path_none_for_empty(self):
        """_apply() with empty CSV var sets card_data_path to None."""
        s = self._settings(csv_path="/old/path.csv")
        h = SimulatorSettingsHarness(s)
        h._csv_var.set("   ")  # whitespace only
        h._apply()
        assert s.card_data_path is None

    def test_apply_sets_applied_true(self):
        """_apply() sets applied = True."""
        s = self._settings()
        h = SimulatorSettingsHarness(s)
        assert h.applied is False
        h._apply()
        assert h.applied is True

    def test_apply_idempotent(self):
        """Calling _apply twice is safe."""
        s = self._settings()
        h = SimulatorSettingsHarness(s)
        h._delay_var.set(200)
        h._apply()
        h._delay_var.set(300)
        h._apply()
        assert s.delay_ms == 300


class TestSimulatorSettingsResetDefaults:
    """Tests for _reset_defaults() logic."""

    def _settings(self, **kw):
        from simulator.settings import SimulatorSettings
        return SimulatorSettings(**kw)

    def test_reset_clears_csv_path(self):
        """_reset_defaults clears the CSV path var."""
        s = self._settings()
        h = SimulatorSettingsHarness(s)
        h._csv_var.set("/some/path.csv")
        h._reset_defaults()
        assert h._csv_var.get() == ""

    def test_reset_sets_delay_to_500(self):
        """_reset_defaults sets delay to 500."""
        s = self._settings(delay_ms=1000)
        h = SimulatorSettingsHarness(s)
        h._reset_defaults()
        assert h._delay_var.get() == 500

    def test_reset_sets_error_to_zero(self):
        """_reset_defaults sets error rate var to 0."""
        s = self._settings(error_rate=0.25)
        h = SimulatorSettingsHarness(s)
        h._reset_defaults()
        assert h._error_var.get() == 0

    def test_reset_sets_num_cards_to_10(self):
        """_reset_defaults sets num_cards to 10."""
        s = self._settings(num_cards=50)
        h = SimulatorSettingsHarness(s)
        h._reset_defaults()
        assert h._num_var.get() == 10

    def test_reset_updates_delay_label(self):
        """_reset_defaults updates the delay label text."""
        s = self._settings(delay_ms=1000)
        h = SimulatorSettingsHarness(s)
        h._reset_defaults()
        assert h._delay_label._text == "500"

    def test_reset_updates_error_label(self):
        """_reset_defaults updates the error label text."""
        s = self._settings(error_rate=0.30)
        h = SimulatorSettingsHarness(s)
        h._reset_defaults()
        assert h._error_label._text == "0"

    def test_reset_does_not_apply(self):
        """_reset_defaults does NOT set applied=True."""
        s = self._settings()
        h = SimulatorSettingsHarness(s)
        h._reset_defaults()
        assert h.applied is False


class TestSimulatorSettingsAppliedProperty:
    """Tests for the applied property."""

    def test_not_applied_initially(self):
        """applied is False before calling _apply."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings()
        h = SimulatorSettingsHarness(s)
        assert h.applied is False

    def test_applied_after_apply(self):
        """applied is True after calling _apply."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings()
        h = SimulatorSettingsHarness(s)
        h._apply()
        assert h.applied is True


class TestSimulatorSettingsInit:
    """Tests for initial state from settings."""

    def test_initial_delay_var_matches_settings(self):
        """Initial delay_var matches settings.delay_ms."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings(delay_ms=750)
        h = SimulatorSettingsHarness(s)
        assert h._delay_var.get() == 750

    def test_initial_error_var_matches_settings(self):
        """Initial error_var matches settings.error_rate as percentage."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings(error_rate=0.15)
        h = SimulatorSettingsHarness(s)
        assert h._error_var.get() == 15

    def test_initial_num_var_matches_settings(self):
        """Initial num_var matches settings.num_cards."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings(num_cards=25)
        h = SimulatorSettingsHarness(s)
        assert h._num_var.get() == 25

    def test_initial_csv_var_empty_when_no_path(self):
        """Initial csv_var is empty string when card_data_path is None."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings(card_data_path=None)
        h = SimulatorSettingsHarness(s)
        assert h._csv_var.get() == ""

    def test_initial_csv_var_set_when_path_given(self):
        """Initial csv_var matches card_data_path when given."""
        from simulator.settings import SimulatorSettings
        s = SimulatorSettings(card_data_path="/cards/data.csv")
        h = SimulatorSettingsHarness(s)
        assert h._csv_var.get() == "/cards/data.csv"
