"""Tests for pure helper functions in dialogs/network_storage_dialog.py.

These functions (_sanitise_server, _sanitise_share, _auto_name) have
no GUI dependency and can be tested entirely without a display.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '.'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from dialogs.network_storage_dialog import _auto_name, _sanitise_server, _sanitise_share

class TestSanitiseServer:
    def test_plain_hostname_unchanged(self):
        assert _sanitise_server("nas.local") == "nas.local"

    def test_plain_ip_unchanged(self):
        assert _sanitise_server("192.168.1.10") == "192.168.1.10"

    def test_smb_prefix_stripped(self):
        assert _sanitise_server("smb://host/share") == "host"

    def test_smb_prefix_with_ip(self):
        assert _sanitise_server("smb://10.0.0.1/data") == "10.0.0.1"

    def test_cifs_prefix_stripped(self):
        assert _sanitise_server("cifs://nas/share") == "nas"

    def test_cifs_prefix_with_ip(self):
        assert _sanitise_server("cifs://10.0.0.1/data") == "10.0.0.1"

    def test_nfs_prefix_stripped(self):
        assert _sanitise_server("nfs://server/export") == "server"

    def test_double_slash_prefix_stripped(self):
        assert _sanitise_server("//server/share") == "server"

    def test_double_slash_ip_stripped(self):
        assert _sanitise_server("//10.0.0.1/data") == "10.0.0.1"

    def test_full_smb_url_takes_only_host(self):
        assert _sanitise_server("smb://nas.local/share") == "nas.local"

    def test_trailing_slash_on_plain_host(self):
        assert _sanitise_server("nas.local/") == "nas.local"

    def test_leading_and_trailing_whitespace_stripped(self):
        assert _sanitise_server("  nas.local  ") == "nas.local"

    def test_whitespace_plus_prefix(self):
        assert _sanitise_server("  smb://nas.local/share  ") == "nas.local"

    def test_uppercase_prefix_stripped(self):
        assert _sanitise_server("SMB://host/share") == "host"
        assert _sanitise_server("NFS://host/path") == "host"

    def test_empty_string(self):
        assert _sanitise_server("") == ""

    def test_only_whitespace(self):
        assert _sanitise_server("   ") == ""

    def test_multi_segment_path_takes_only_host(self):
        assert _sanitise_server("smb://server/share/subdir") == "server"

    def test_nfs_ip_with_path(self):
        assert _sanitise_server("nfs://10.0.0.5/export/sim") == "10.0.0.5"


class TestSanitiseShare:
    def test_smb_plain_share_unchanged(self):
        assert _sanitise_share("simdata", "smb") == "simdata"

    def test_smb_leading_slash_removed(self):
        assert _sanitise_share("/simdata", "smb") == "simdata"

    def test_smb_double_leading_slash_removed(self):
        assert _sanitise_share("//simdata", "smb") == "simdata"

    def test_smb_trailing_slash_removed(self):
        assert _sanitise_share("simdata/", "smb") == "simdata"

    def test_smb_both_slashes_removed(self):
        assert _sanitise_share("/simdata/", "smb") == "simdata"

    def test_smb_whitespace_stripped(self):
        assert _sanitise_share("  simdata  ", "smb") == "simdata"

    def test_smb_empty_string(self):
        assert _sanitise_share("", "smb") == ""

    def test_nfs_path_already_has_slash(self):
        assert _sanitise_share("/exports/sim", "nfs") == "/exports/sim"

    def test_nfs_path_missing_slash_added(self):
        assert _sanitise_share("exports/sim", "nfs") == "/exports/sim"

    def test_nfs_plain_name_gets_slash(self):
        assert _sanitise_share("data", "nfs") == "/data"

    def test_nfs_whitespace_stripped(self):
        assert _sanitise_share("  exports/sim  ", "nfs") == "/exports/sim"

    def test_nfs_empty_string(self):
        assert _sanitise_share("", "nfs") == ""

    def test_nfs_whitespace_only(self):
        assert _sanitise_share("   ", "nfs") == ""


class TestAutoName:
    def test_server_and_share_smb(self):
        result = _auto_name("nas.local", "simdata", "smb")
        assert result == "simdata on nas.local (SMB)"

    def test_server_and_share_nfs(self):
        result = _auto_name("10.0.0.1", "/exports/sim", "nfs")
        assert result == "/exports/sim on 10.0.0.1 (NFS)"

    def test_server_only_smb(self):
        result = _auto_name("nas.local", "", "smb")
        assert result == "nas.local (SMB)"

    def test_server_only_nfs(self):
        result = _auto_name("10.0.0.1", "", "nfs")
        assert result == "10.0.0.1 (NFS)"

    def test_both_empty(self):
        result = _auto_name("", "", "smb")
        assert result == "New connection"

    def test_share_without_server(self):
        result = _auto_name("", "simdata", "smb")
        assert result == "New connection"

    def test_protocol_uppercased_in_all_cases(self):
        r1 = _auto_name("host", "share", "smb")
        assert "(SMB)" in r1
        r2 = _auto_name("host", "share", "nfs")
        assert "(NFS)" in r2

    def test_share_contains_server_name(self):
        result = _auto_name("my-server", "my-share", "smb")
        assert "my-server" in result
        assert "my-share" in result
