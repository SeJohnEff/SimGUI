"""Tests for standalone functions in dialogs/network_storage_dialog.py."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dialogs.network_storage_dialog import (
    _auto_name,
    _sanitise_server,
    _sanitise_share,
)


class TestSanitiseServer:
    def test_plain_hostname(self):
        assert _sanitise_server("nas.local") == "nas.local"

    def test_plain_ip(self):
        assert _sanitise_server("192.168.1.10") == "192.168.1.10"

    def test_strip_smb_prefix(self):
        assert _sanitise_server("smb://nas.local") == "nas.local"

    def test_strip_cifs_prefix(self):
        assert _sanitise_server("cifs://nas.local") == "nas.local"

    def test_strip_nfs_prefix(self):
        assert _sanitise_server("nfs://10.0.0.1/data") == "10.0.0.1"

    def test_strip_double_slash(self):
        assert _sanitise_server("//nas.local/share") == "nas.local"

    def test_strip_smb_with_path(self):
        assert _sanitise_server("smb://nas.local/share/subfolder") == "nas.local"

    def test_whitespace(self):
        assert _sanitise_server("  nas.local  ") == "nas.local"

    def test_empty(self):
        assert _sanitise_server("") == ""

    def test_case_insensitive_prefix(self):
        assert _sanitise_server("SMB://NAS.LOCAL") == "NAS.LOCAL"


class TestSanitiseShare:
    def test_smb_plain(self):
        assert _sanitise_share("media", "smb") == "media"

    def test_smb_leading_slashes(self):
        assert _sanitise_share("//media/", "smb") == "media"

    def test_smb_trailing_slashes(self):
        assert _sanitise_share("share/", "smb") == "share"

    def test_nfs_adds_leading_slash(self):
        assert _sanitise_share("export/data", "nfs") == "/export/data"

    def test_nfs_already_has_slash(self):
        assert _sanitise_share("/export/data", "nfs") == "/export/data"

    def test_empty_smb(self):
        assert _sanitise_share("", "smb") == ""

    def test_empty_nfs(self):
        assert _sanitise_share("", "nfs") == ""

    def test_whitespace(self):
        assert _sanitise_share("  media  ", "smb") == "media"


class TestAutoName:
    def test_server_and_share(self):
        assert _auto_name("nas.local", "media", "smb") == "media on nas.local (SMB)"

    def test_server_only(self):
        assert _auto_name("10.0.0.1", "", "nfs") == "10.0.0.1 (NFS)"

    def test_empty_both(self):
        assert _auto_name("", "", "smb") == "New connection"

    def test_nfs_protocol_upper(self):
        assert _auto_name("server", "export", "nfs") == "export on server (NFS)"
