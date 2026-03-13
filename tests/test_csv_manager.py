"""Tests for managers.csv_manager module."""

import os
import tempfile

import pytest

from managers.csv_manager import STANDARD_COLUMNS, CSVManager


class TestCSVManagerInit:
    def test_default_columns(self, csv_manager):
        assert csv_manager.columns == list(STANDARD_COLUMNS)

    def test_empty_cards(self, csv_manager):
        assert csv_manager.get_card_count() == 0


class TestCSVManagerIO:
    def test_load_csv(self, csv_manager, sample_csv_file):
        assert csv_manager.load_csv(sample_csv_file)
        assert csv_manager.get_card_count() == 1

    def test_load_nonexistent(self, csv_manager):
        assert csv_manager.load_csv('/nonexistent/file.csv') is False

    def test_save_csv(self, csv_manager, sample_card):
        csv_manager.add_card(sample_card)
        fd, path = tempfile.mkstemp(suffix='.csv')
        os.close(fd)
        try:
            assert csv_manager.save_csv(path)
            # Reload and verify
            mgr2 = CSVManager()
            assert mgr2.load_csv(path)
            assert mgr2.get_card_count() == 1
            assert mgr2.get_card(0)['IMSI'] == sample_card['IMSI']
        finally:
            os.unlink(path)

    def test_load_card_parameters_file(self, csv_manager):
        fd, path = tempfile.mkstemp(suffix='.txt')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write("# comment\nIMSI=001010123456789\nICCID=89860012345678901234\n")
            assert csv_manager.load_card_parameters_file(path)
            assert csv_manager.get_card_count() == 1
        finally:
            os.unlink(path)


class TestCSVManagerCards:
    def test_add_card_empty(self, csv_manager):
        csv_manager.add_card()
        assert csv_manager.get_card_count() == 1
        card = csv_manager.get_card(0)
        assert all(card[c] == '' for c in STANDARD_COLUMNS)

    def test_add_card_with_data(self, csv_manager, sample_card):
        csv_manager.add_card(sample_card)
        assert csv_manager.get_card(0)['IMSI'] == sample_card['IMSI']

    def test_remove_card(self, csv_manager):
        csv_manager.add_card()
        csv_manager.add_card()
        assert csv_manager.remove_card(0)
        assert csv_manager.get_card_count() == 1

    def test_remove_invalid_index(self, csv_manager):
        assert csv_manager.remove_card(99) is False

    def test_update_card(self, csv_manager):
        csv_manager.add_card()
        assert csv_manager.update_card(0, 'IMSI', '123456789012345')
        assert csv_manager.get_card(0)['IMSI'] == '123456789012345'

    def test_update_invalid_index(self, csv_manager):
        assert csv_manager.update_card(99, 'IMSI', 'x') is False

    def test_get_card_invalid_index(self, csv_manager):
        assert csv_manager.get_card(-1) is None
        assert csv_manager.get_card(0) is None


class TestCSVManagerValidation:
    def test_validate_all_empty(self, csv_manager):
        assert csv_manager.validate_all() == []

    def test_validate_all_valid(self, csv_manager, sample_card):
        csv_manager.add_card(sample_card)
        assert csv_manager.validate_all() == []

    def test_validate_all_with_errors(self, csv_manager):
        csv_manager.add_card({'IMSI': 'bad', 'Ki': 'short'})
        errors = csv_manager.validate_all()
        assert len(errors) >= 2
        assert all(e.startswith('Row 1:') for e in errors)

    def test_validate_card(self, csv_manager, sample_card):
        csv_manager.add_card(sample_card)
        assert csv_manager.validate_card(0) == []

    def test_validate_card_invalid_index(self, csv_manager):
        errors = csv_manager.validate_card(99)
        assert len(errors) == 1
