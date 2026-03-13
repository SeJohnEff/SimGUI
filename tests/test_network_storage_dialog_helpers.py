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


# ---------------------------------------------------------------------------
# _sanitise_server
# ---------------------------------------------------------------------------

class TestSanitiseServer:
    """Tests for _sanitise_server() — strips protocol prefixes and paths."""

    def test_plain_hostname_unchanged(self):
        """A bare hostname should pass through unchanged."""
        assert _sanitise_server("nas.local") == "nas.local"

    def test_plain_ip_unchanged(self):
        """A bare IP address should pass through unchanged."""
        assert _sanitise_server("192.168.1.10") == "192.168.1.10"

    def test_smb_prefix_stripped(self):
        """smb://host/share should yield just 'host'."""
        assert _sanitise_server("smb://host/share") == "host"

    def test_smb_prefix_with_ip(self):
        """smb://10.0.0.1/data should yield '10.0.0.1'."""
        assert _sanitise_server("smb://10.0.0.1/data") == "10.0.0.1"

    def test_cifs_prefix_stripped(self):
        """cifs://nas/share should yield 'nas'."""
        assert _sanitise_server("cifs://nas/share") == "nas"

    def test_cifs_prefix_with_ip(self):
        """cifs://10.0.0.1/data should yield '10.0.0.1'."""
        assert _sanitise_server("cifs://10.0.0.1/data") == "10.0.0.1"

    def test_nfs_prefix_stripped(self):
        """nfs://server/export should yield 'server'."""
        assert _sanitise_server("nfs://server/export") == "server"

    def test_double_slash_prefix_stripped(self):
        """//server/share should yield 'server'."""
        assert _sanitise_server("//server/share") == "server"

    def test_double_slash_ip_stripped(self):
        """//10.0.0.1/data should yield '10.0.0.1'."""
        assert _sanitise_server("//10.0.0.1/data") == "10.0.0.1"

    def test_full_smb_url_takes_only_host(self):
        """smb://nas.local/share should yield 'nas.local'."""
        assert _sanitise_server("smb://nas.local/share") == "nas.local"

    def test_trailing_slash_on_plain_host(self):
        """Plain host with trailing slash: 'nas.local/' → 'nas.local'."""
        assert _sanitise_server("nas.local/") == "nas.local"

    def test_leading_and_trailing_whitespace_stripped(self):
        """Whitespace around the server string is stripped."""
        assert _sanitise_server("  nas.local  ") == "nas.local"

    def test_whitespace_plus_prefix(self):
        """Whitespace + smb:// prefix are both stripped."""
        assert _sanitise_server("  smb://nas.local/share  ") == "nas.local"

    def test_uppercase_prefix_stripped(self):
        """Protocol prefixes should match case-insensitively."""
        assert _sanitise_server("SMB://host/share") == "host"
        assert _sanitise_server("NFS://host/path") == "host"

    def test_empty_string(self):
        """Empty input should return empty string."""
        assert _sanitise_server("") == ""

    def test_only_whitespace(self):
        """Whitespace-only input should return empty string."""
        assert _sanitise_server("   ") == ""

    def test_multi_segment_path_takes_only_host(self):
        """smb://server/share/subdir should yield just 'server'."""
        assert _sanitise_server("smb://server/share/subdir") == "server"

    def test_nfs_ip_with_path(self):
        """nfs://10.0.0.5/export/sim should yield '10.0.0.5'."""
        assert _sanitise_server("nfs://10.0.0.5/export/sim") == "10.0.0.5"


# ---------------------------------------------------------------------------
# _sanitise_share
# ---------------------------------------------------------------------------

class TestSanitiseShare:
    """Tests for _sanitise_share() — different rules for SMB vs NFS."""

    # ---- SMB: remove leading slashes
    def test_smb_plain_share_unchanged(self):
        """Plain SMB share name needs no modification."""
        assert _sanitise_share("simdata", "smb") == "simdata"

    def test_smb_leading_slash_removed(self):
        """SMB share with leading slash has it stripped."""
        assert _sanitise_share("/simdata", "smb") == "simdata"

    def test_smb_double_leading_slash_removed(self):
        """SMB share with double leading slash has both stripped."""
        assert _sanitise_share("//simdata", "smb") == "simdata"

    def test_smb_trailing_slash_removed(self):
        """SMB share with trailing slash has it stripped."""
        assert _sanitise_share("simdata/", "smb") == "simdata"

    def test_smb_both_slashes_removed(self):
        """SMB share with both leading and trailing slashes has both stripped."""
        assert _sanitise_share("/simdata/", "smb") == "simdata"

    def test_smb_whitespace_stripped(self):
        """SMB share with surrounding whitespace is stripped."""
        assert _sanitise_share("  simdata  ", "smb") == "simdata"

    def test_smb_empty_string(self):
        """Empty SMB share stays empty."""
        assert _sanitise_share("", "smb") == ""

    # ---- NFS: ensure leading slash
    def test_nfs_path_already_has_slash(self):
        """NFS export path with leading slash is unchanged."""
        assert _sanitise_share("/exports/sim", "nfs") == "/exports/sim"

    def test_nfs_path_missing_slash_added(self):
        """NFS export path without leading slash gets one added."""
        assert _sanitise_share("exports/sim", "nfs") == "/exports/sim"

    def test_nfs_plain_name_gets_slash(self):
        """Plain NFS share name without slash gets leading slash."""
        assert _sanitise_share("data", "nfs") == "/data"

    def test_nfs_whitespace_stripped(self):
        """NFS export with surrounding whitespace is stripped, slash added if needed."""
        assert _sanitise_share("  exports/sim  ", "nfs") == "/exports/sim"

    def test_nfs_empty_string(self):
        """Empty NFS share stays empty (no slash added to empty)."""
        assert _sanitise_share("", "nfs") == ""

    def test_nfs_whitespace_only(self):
        """Whitespace-only NFS share stays empty after stripping."""
        assert _sanitise_share("   ", "nfs") == ""


# ---------------------------------------------------------------------------
# _auto_name
# ---------------------------------------------------------------------------

class TestAutoName:
    """Tests for _auto_name() — human-readable profile name generation."""

    def test_server_and_share_smb(self):
        """With server and share, format is '<share> on <server> (SMB)'."""
        result = _auto_name("nas.local", "simdata", "smb")
        assert result == "simdata on nas.local (SMB)"

    def test_server_and_share_nfs(self):
        """With server and share, protocol appears in uppercase."""
        result = _auto_name("10.0.0.1", "/exports/sim", "nfs")
        assert result == "/exports/sim on 10.0.0.1 (NFS)"

    def test_server_only_smb(self):
        """With only server, format is '<server> (SMB)'."""
        result = _auto_name("nas.local", "", "smb")
        assert result == "nas.local (SMB)"

    def test_server_only_nfs(self):
        """With only server for NFS, protocol is uppercase."""
        result = _auto_name("10.0.0.1", "", "nfs")
        assert result == "10.0.0.1 (NFS)"

    def test_both_empty(self):
        """With both server and share empty, fallback is 'New connection'."""
        result = _auto_name("", "", "smb")
        assert result == "New connection"

    def test_share_without_server(self):
        """With empty server but non-empty share, falls through to 'New connection'."""
        result = _auto_name("", "simdata", "smb")
        assert result == "New connection"

    def test_protocol_uppercased_in_all_cases(self):
        """Protocol name is always uppercased in the output."""
        r1 = _auto_name("host", "share", "smb")
        assert "(SMB)" in r1

        r2 = _auto_name("host", "share", "nfs")
        assert "(NFS)" in r2

    def test_share_contains_server_name(self):
        """The generated name contains the server."""
        result = _auto_name("my-server", "my-share", "smb")
        assert "my-server" in result
        assert "my-share" in result
