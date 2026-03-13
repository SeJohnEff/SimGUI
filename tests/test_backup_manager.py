"""Tests for managers.backup_manager module."""

import json
import os
import tempfile

import pytest

from managers.backup_manager import BackupManager


class TestBackupCreate:
    def test_create_backup(self, backup_manager, sample_card):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            result = backup_manager.create_backup(sample_card, path)
            assert result == path
            with open(path) as f:
                data = json.load(f)
            assert data['IMSI'] == sample_card['IMSI']
        finally:
            os.unlink(path)

    def test_create_backup_creates_dirs(self, backup_manager, sample_card, tmp_path):
        path = str(tmp_path / 'sub' / 'dir' / 'backup.json')
        result = backup_manager.create_backup(sample_card, path)
        assert result == path
        assert os.path.isfile(path)

    def test_create_backup_invalid_path(self, backup_manager):
        result = backup_manager.create_backup({}, '/dev/null/impossible/file.json')
        assert result is None


class TestBackupRestore:
    def test_restore_backup(self, backup_manager, sample_card):
        fd, path = tempfile.mkstemp(suffix='.json')
        os.close(fd)
        try:
            with open(path, 'w') as f:
                json.dump(sample_card, f)
            data = backup_manager.restore_backup(path)
            assert data is not None
            assert data['IMSI'] == sample_card['IMSI']
        finally:
            os.unlink(path)

    def test_restore_nonexistent(self, backup_manager):
        assert backup_manager.restore_backup('/nonexistent/file.json') is None

    def test_restore_invalid_json(self, backup_manager):
        fd, path = tempfile.mkstemp(suffix='.json')
        try:
            with os.fdopen(fd, 'w') as f:
                f.write('not valid json')
            assert backup_manager.restore_backup(path) is None
        finally:
            os.unlink(path)


class TestSuggestFilename:
    def test_suggest_filename_format(self):
        name = BackupManager.suggest_filename({'imsi': '001010123456789'})
        assert name.startswith('backup_001010123456789_')
        assert name.endswith('.json')

    def test_suggest_filename_unknown(self):
        name = BackupManager.suggest_filename({})
        assert 'unknown' in name
