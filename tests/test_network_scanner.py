"""Tests for network_scanner — SMB/NFS network discovery utilities."""

import subprocess
from unittest.mock import patch

from utils.network_scanner import (
    DiscoveredServer,
    _parse_avahi_output,
    _parse_nmblookup_output,
    _parse_smbclient_shares,
    _run_cmd,
    list_smb_shares,
    scan_smb_servers,
)

# ---------------------------------------------------------------------------
# Sample command outputs for mocking
# ---------------------------------------------------------------------------

AVAHI_OUTPUT_BASIC = """\
+;eth0;IPv4;NAS;_smb._tcp;local
=;eth0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.10;445
=;eth0;IPv4;FileServer;_smb._tcp;local;fileserver.local;192.168.1.20;445
"""

AVAHI_OUTPUT_WITH_IPV6 = """\
=;eth0;IPv6;NAS;_smb._tcp;local;nas.local;fe80::1;445
=;eth0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.10;445
"""

AVAHI_OUTPUT_DUPLICATE = """\
=;eth0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.10;445
=;wlan0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.10;445
"""

AVAHI_OUTPUT_EMPTY = ""
AVAHI_OUTPUT_MALFORMED = """\
=;short;line
garbage data here
=;eth0;IPv4
"""

AVAHI_OUTPUT_SPECIAL_CHARS = """\
=;eth0;IPv4;My NAS (Office);_smb._tcp;local;my-nas.local;192.168.1.30;445
"""

# What avahi-browse outputs WITHOUT the -r flag: only "+" (found) lines,
# no "=" (resolved) lines.  The parser should return nothing because
# "+" lines don't contain hostnames or IPs.
AVAHI_OUTPUT_UNRESOLVED_ONLY = """\
+;eth0;IPv4;NAS;_smb._tcp;local
+;eth0;IPv4;FileServer;_smb._tcp;local
+;eth0;IPv6;NAS;_smb._tcp;local
"""

NMBLOOKUP_OUTPUT_BASIC = """\
querying *<00> on 192.168.1.255
192.168.1.10 NAS<00>
192.168.1.20 FILESERVER<00>
"""

# Real-world nmblookup -S '*' output from user's network.
# The query result line has "*<00>" (broadcast char, not a real name).
# The real name is in the status section.
NMBLOOKUP_OUTPUT_BROADCAST_STAR = """\
querying *<00> on 172.20.10.255
172.20.10.2 *<00>
Looking up status of 172.20.10.2
\tFISKARHEDEN     <00> -         B <ACTIVE>
\tFISKARHEDEN     <03> -         B <ACTIVE>
\tFISKARHEDEN     <20> -         B <ACTIVE>
\tWORKGROUP       <00> - <GROUP> B <ACTIVE>
\tWORKGROUP       <1e> - <GROUP> B <ACTIVE>
"""

# Multiple servers discovered via broadcast, both with * names
NMBLOOKUP_OUTPUT_MULTI_STAR = """\
172.20.10.2 *<00>
172.20.10.3 *<00>
Looking up status of 172.20.10.2
\tSERVER_A        <00> -         B <ACTIVE>
Looking up status of 172.20.10.3
\tSERVER_B        <00> -         B <ACTIVE>
"""

# Server with no status section — only IP should be shown
NMBLOOKUP_OUTPUT_NO_STATUS = """\
172.20.10.5 *<00>
"""

NMBLOOKUP_OUTPUT_SINGLE = """\
192.168.1.10 MYNAS<00>
"""

NMBLOOKUP_OUTPUT_EMPTY = ""
NMBLOOKUP_OUTPUT_MALFORMED = """\
no result
just text without angles
"""

SMBCLIENT_OUTPUT_BASIC = """\

	Sharename       Type      Comment
	---------       ----      -------
	SimData         Disk      SIM card data
	public          Disk      Public files
	IPC$            IPC       IPC Service
	ADMIN$          Disk      Remote Admin
	print$          Disk      Printer Drivers
"""

SMBCLIENT_OUTPUT_EMPTY = """\

	Sharename       Type      Comment
	---------       ----      -------
"""

SMBCLIENT_OUTPUT_ONLY_HIDDEN = """\

	Sharename       Type      Comment
	---------       ----      -------
	IPC$            IPC       IPC Service
	ADMIN$          Disk      Remote Admin
"""


# ---------------------------------------------------------------------------
# avahi-browse parsing
# ---------------------------------------------------------------------------

class TestParseAvahiOutput:
    """Tests for _parse_avahi_output."""

    def test_basic_output(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_BASIC)
        assert len(servers) == 2
        ips = {s.ip for s in servers}
        assert "192.168.1.10" in ips
        assert "192.168.1.20" in ips

    def test_display_name_format(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_BASIC)
        nas = [s for s in servers if s.ip == "192.168.1.10"][0]
        assert nas.hostname == "nas.local"
        assert "NAS" in nas.name
        assert "192.168.1.10" in nas.name

    def test_ipv6_filtered(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_WITH_IPV6)
        assert len(servers) == 1
        assert servers[0].ip == "192.168.1.10"

    def test_deduplication_same_ip(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_DUPLICATE)
        assert len(servers) == 1
        assert servers[0].ip == "192.168.1.10"

    def test_empty_output(self):
        assert _parse_avahi_output("") == []

    def test_malformed_output(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_MALFORMED)
        assert servers == []

    def test_special_characters_in_name(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_SPECIAL_CHARS)
        assert len(servers) == 1
        assert "My NAS (Office)" in servers[0].name

    def test_unresolved_plus_lines_return_nothing(self):
        """Without -r flag avahi only emits '+' (found) lines, not '='
        (resolved) lines.  The parser must return zero servers because
        '+' lines have no hostname or IP — this is the exact failure
        mode the user hit."""
        servers = _parse_avahi_output(AVAHI_OUTPUT_UNRESOLVED_ONLY)
        assert servers == []

    def test_shares_default_empty(self):
        servers = _parse_avahi_output(AVAHI_OUTPUT_BASIC)
        for s in servers:
            assert s.shares == []


# ---------------------------------------------------------------------------
# nmblookup parsing
# ---------------------------------------------------------------------------

class TestParseNmblookupOutput:
    """Tests for _parse_nmblookup_output."""

    def test_basic_output(self):
        servers = _parse_nmblookup_output(NMBLOOKUP_OUTPUT_BASIC)
        assert len(servers) == 2
        ips = {s.ip for s in servers}
        assert "192.168.1.10" in ips
        assert "192.168.1.20" in ips

    def test_single_server(self):
        servers = _parse_nmblookup_output(NMBLOOKUP_OUTPUT_SINGLE)
        assert len(servers) == 1
        assert servers[0].hostname == "MYNAS"
        assert servers[0].ip == "192.168.1.10"
        assert "MYNAS" in servers[0].name

    def test_broadcast_star_resolved_from_status(self):
        """Bug fix: '*' from broadcast query must be replaced by real name
        from the status section (e.g. FISKARHEDEN)."""
        servers = _parse_nmblookup_output(NMBLOOKUP_OUTPUT_BROADCAST_STAR)
        assert len(servers) == 1
        srv = servers[0]
        assert srv.ip == "172.20.10.2"
        assert srv.hostname == "FISKARHEDEN"
        assert "FISKARHEDEN" in srv.name
        # Must NOT contain '*'
        assert "*" not in srv.hostname
        assert "*" not in srv.name

    def test_multiple_broadcast_stars_resolved(self):
        """Multiple servers all returning '*' — each resolved via status."""
        servers = _parse_nmblookup_output(NMBLOOKUP_OUTPUT_MULTI_STAR)
        assert len(servers) == 2
        by_ip = {s.ip: s for s in servers}
        assert by_ip["172.20.10.2"].hostname == "SERVER_A"
        assert by_ip["172.20.10.3"].hostname == "SERVER_B"

    def test_star_without_status_shows_ip(self):
        """Server with '*' but no status section — falls back to IP."""
        servers = _parse_nmblookup_output(NMBLOOKUP_OUTPUT_NO_STATUS)
        assert len(servers) == 1
        # hostname should be IP (fallback), not '*'
        assert servers[0].hostname == "172.20.10.5"
        assert servers[0].ip == "172.20.10.5"
        assert "*" not in servers[0].name

    def test_empty_output(self):
        assert _parse_nmblookup_output("") == []

    def test_malformed_output(self):
        servers = _parse_nmblookup_output(NMBLOOKUP_OUTPUT_MALFORMED)
        assert servers == []


# ---------------------------------------------------------------------------
# smbclient share parsing
# ---------------------------------------------------------------------------

class TestParseSmbclientShares:
    """Tests for _parse_smbclient_shares."""

    def test_basic_shares(self):
        shares = _parse_smbclient_shares(SMBCLIENT_OUTPUT_BASIC)
        assert "SimData" in shares
        assert "public" in shares

    def test_hidden_shares_excluded(self):
        shares = _parse_smbclient_shares(SMBCLIENT_OUTPUT_BASIC)
        for s in shares:
            assert not s.endswith("$")

    def test_empty_share_list(self):
        shares = _parse_smbclient_shares(SMBCLIENT_OUTPUT_EMPTY)
        assert shares == []

    def test_only_hidden_shares(self):
        shares = _parse_smbclient_shares(SMBCLIENT_OUTPUT_ONLY_HIDDEN)
        assert shares == []


# ---------------------------------------------------------------------------
# _run_cmd
# ---------------------------------------------------------------------------

class TestRunCmd:
    """Tests for _run_cmd helper."""

    @patch("utils.network_scanner.subprocess.run")
    def test_success(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["echo"], returncode=0, stdout="hello\n", stderr="",
        )
        ok, out = _run_cmd(["echo", "hello"])
        assert ok is True
        assert out == "hello\n"

    @patch("utils.network_scanner.subprocess.run")
    def test_command_not_found(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        ok, out = _run_cmd(["nonexistent"])
        assert ok is False
        assert out == ""

    @patch("utils.network_scanner.subprocess.run")
    def test_timeout(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="cmd", timeout=5)
        ok, out = _run_cmd(["slow-cmd"], timeout=5)
        assert ok is False
        assert out == ""

    @patch("utils.network_scanner.subprocess.run")
    def test_nonzero_exit(self, mock_run):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["fail"], returncode=1, stdout="", stderr="error",
        )
        ok, out = _run_cmd(["fail"])
        assert ok is False

    @patch("utils.network_scanner.subprocess.run")
    def test_nonzero_exit_still_returns_stdout(self, mock_run):
        """Bug fix: stdout must be returned even when rc != 0.
        smbclient -L prints shares but often exits with rc=1."""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["smbclient"], returncode=1,
            stdout=SMBCLIENT_OUTPUT_BASIC, stderr="NT_STATUS_ACCESS_DENIED",
        )
        ok, out = _run_cmd(["smbclient", "-L", "//server"])
        assert ok is False
        assert "SimData" in out  # stdout is preserved despite rc=1

    @patch("utils.network_scanner.subprocess.run")
    def test_os_error(self, mock_run):
        mock_run.side_effect = OSError("Permission denied")
        ok, out = _run_cmd(["cmd"])
        assert ok is False
        assert out == ""


# ---------------------------------------------------------------------------
# scan_smb_servers (integration with mocked subprocess)
# ---------------------------------------------------------------------------

class TestScanSmbServers:
    """Tests for scan_smb_servers."""

    @patch("utils.network_scanner._run_cmd")
    def test_avahi_only(self, mock_cmd):
        """avahi-browse succeeds, nmblookup also called."""
        def side_effect(cmd, timeout=10):
            if cmd[0] == "avahi-browse":
                return (True, AVAHI_OUTPUT_BASIC)
            return (False, "")
        mock_cmd.side_effect = side_effect

        servers = scan_smb_servers(timeout=5)
        assert len(servers) == 2

    @patch("utils.network_scanner._run_cmd")
    def test_avahi_uses_resolve_flag(self, mock_cmd):
        """Bug fix: avahi-browse must include -r for resolution."""
        mock_cmd.return_value = (False, "")
        scan_smb_servers(timeout=5)
        # Find the avahi-browse call
        avahi_call = [
            c for c in mock_cmd.call_args_list
            if c[0][0][0] == "avahi-browse"
        ]
        assert avahi_call, "avahi-browse was not called"
        avahi_args = avahi_call[0][0][0]
        # The flags arg should contain 'r'
        flags_arg = avahi_args[1]  # e.g. "-tpkr"
        assert "r" in flags_arg, f"Missing -r in avahi-browse flags: {avahi_args}"

    @patch("utils.network_scanner._run_cmd")
    def test_nmblookup_fallback(self, mock_cmd):
        """avahi-browse fails, nmblookup provides results."""
        def side_effect(cmd, timeout=10):
            if cmd[0] == "avahi-browse":
                return (False, "")
            if cmd[0] == "nmblookup":
                return (True, NMBLOOKUP_OUTPUT_BASIC)
            return (False, "")
        mock_cmd.side_effect = side_effect

        servers = scan_smb_servers(timeout=5)
        assert len(servers) == 2

    @patch("utils.network_scanner._run_cmd")
    def test_both_methods_merge(self, mock_cmd):
        """Both methods find servers — results are merged by IP."""
        def side_effect(cmd, timeout=10):
            if cmd[0] == "avahi-browse":
                return (True, AVAHI_OUTPUT_BASIC)
            if cmd[0] == "nmblookup":
                return (True, NMBLOOKUP_OUTPUT_BASIC)
            return (False, "")
        mock_cmd.side_effect = side_effect

        servers = scan_smb_servers(timeout=5)
        ips = {s.ip for s in servers}
        # Both methods found same IPs — should be deduplicated
        assert "192.168.1.10" in ips
        assert "192.168.1.20" in ips
        assert len(servers) == 2

    @patch("utils.network_scanner._run_cmd")
    def test_nmblookup_adds_new_server(self, mock_cmd):
        """nmblookup finds a server not seen by avahi."""
        avahi_single = (
            "=;eth0;IPv4;NAS;_smb._tcp;local;nas.local;192.168.1.10;445\n"
        )
        nmb_different = "192.168.1.99 OTHERBOX<00>\n"

        def side_effect(cmd, timeout=10):
            if cmd[0] == "avahi-browse":
                return (True, avahi_single)
            if cmd[0] == "nmblookup":
                return (True, nmb_different)
            return (False, "")
        mock_cmd.side_effect = side_effect

        servers = scan_smb_servers(timeout=5)
        ips = {s.ip for s in servers}
        assert len(servers) == 2
        assert "192.168.1.10" in ips
        assert "192.168.1.99" in ips

    @patch("utils.network_scanner._run_cmd")
    def test_both_tools_missing(self, mock_cmd):
        """Neither tool is available — returns empty list gracefully."""
        mock_cmd.return_value = (False, "")
        servers = scan_smb_servers(timeout=5)
        assert servers == []

    @patch("utils.network_scanner._run_cmd")
    def test_timeout_parameter_passed(self, mock_cmd):
        """Timeout parameter is forwarded to _run_cmd."""
        mock_cmd.return_value = (False, "")
        scan_smb_servers(timeout=3)
        for call in mock_cmd.call_args_list:
            assert call.kwargs.get("timeout") == 3 or call[1].get("timeout") == 3


# ---------------------------------------------------------------------------
# list_smb_shares
# ---------------------------------------------------------------------------

class TestListSmbShares:
    """Tests for list_smb_shares."""

    @patch("utils.network_scanner._run_cmd")
    def test_guest_access(self, mock_cmd):
        mock_cmd.return_value = (True, SMBCLIENT_OUTPUT_BASIC)
        shares = list_smb_shares("192.168.1.10")
        assert "SimData" in shares
        assert "public" in shares
        # Verify -N (no password) flag was used
        cmd_arg = mock_cmd.call_args[0][0]
        assert "-N" in cmd_arg

    @patch("utils.network_scanner._run_cmd")
    def test_with_credentials(self, mock_cmd):
        mock_cmd.return_value = (True, SMBCLIENT_OUTPUT_BASIC)
        list_smb_shares("nas", username="admin", password="pass")
        cmd_arg = mock_cmd.call_args[0][0]
        assert "-U" in cmd_arg
        assert "admin%pass" in cmd_arg

    @patch("utils.network_scanner._run_cmd")
    def test_server_unreachable(self, mock_cmd):
        mock_cmd.return_value = (False, "")
        shares = list_smb_shares("10.0.0.99")
        assert shares == []

    @patch("utils.network_scanner._run_cmd")
    def test_nonzero_rc_with_valid_shares(self, mock_cmd):
        """Bug fix: smbclient -L returns rc=1 but prints valid shares.
        list_smb_shares must parse stdout regardless of exit code."""
        mock_cmd.return_value = (False, SMBCLIENT_OUTPUT_BASIC)
        shares = list_smb_shares("192.168.1.10")
        assert "SimData" in shares
        assert "public" in shares

    @patch("utils.network_scanner._run_cmd")
    def test_nonzero_rc_empty_stdout(self, mock_cmd):
        """rc=1 and no stdout — should return empty list."""
        mock_cmd.return_value = (False, "")
        shares = list_smb_shares("10.0.0.99")
        assert shares == []

    @patch("utils.network_scanner._run_cmd")
    def test_empty_share_list(self, mock_cmd):
        mock_cmd.return_value = (True, SMBCLIENT_OUTPUT_EMPTY)
        shares = list_smb_shares("192.168.1.10")
        assert shares == []


# ---------------------------------------------------------------------------
# DiscoveredServer dataclass
# ---------------------------------------------------------------------------

class TestDiscoveredServer:
    """Tests for the DiscoveredServer dataclass."""

    def test_default_shares(self):
        s = DiscoveredServer(hostname="h", ip="1.2.3.4", name="h")
        assert s.shares == []

    def test_fields(self):
        s = DiscoveredServer(
            hostname="nas.local", ip="10.0.0.1",
            name="NAS (10.0.0.1)", shares=["data", "backup"],
        )
        assert s.hostname == "nas.local"
        assert s.ip == "10.0.0.1"
        assert s.name == "NAS (10.0.0.1)"
        assert s.shares == ["data", "backup"]
