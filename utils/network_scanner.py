"""
Network discovery utilities — find SMB servers on the local network.

Discovery methods (tried in priority order):
1. avahi-browse (mDNS/DNS-SD) — discovers ``_smb._tcp`` services
2. nmblookup (NetBIOS) — fallback for networks without mDNS
3. smbclient -L — list shares on a specific server

All methods are optional: if the required tool is not installed the
function returns an empty list and logs a warning.
"""

import logging
import subprocess
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class DiscoveredServer:
    """A server found during network scanning."""

    hostname: str       # e.g. "nas.local"
    ip: str             # e.g. "192.168.1.10"
    name: str           # Display name, e.g. "NAS (192.168.1.10)"
    shares: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal parsers
# ---------------------------------------------------------------------------

def _parse_avahi_output(output: str) -> list[DiscoveredServer]:
    """Parse ``avahi-browse -tpk _smb._tcp`` output into server objects.

    Expected line format (``-p`` flag, resolved)::

        =;eth0;IPv4;ServerName;_smb._tcp;local;hostname.local;192.168.1.10;445

    Fields are separated by ``;``.  We only care about lines starting with
    ``=`` (resolved entries) and with ``IPv4`` in the third field.
    """
    servers: dict[str, DiscoveredServer] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or not line.startswith("="):
            continue
        parts = line.split(";")
        if len(parts) < 9:
            continue
        # parts: [=, iface, proto, name, svc, domain, hostname, ip, port]
        proto = parts[2]
        if proto != "IPv4":
            continue
        display_name = parts[3]
        hostname = parts[6]
        ip = parts[7]
        if not ip:
            continue
        key = ip
        if key not in servers:
            name = f"{display_name} ({ip})" if display_name else ip
            servers[key] = DiscoveredServer(
                hostname=hostname, ip=ip, name=name,
            )
    return list(servers.values())


def _parse_nmblookup_output(output: str) -> list[DiscoveredServer]:
    """Parse ``nmblookup -S '*'`` output into server objects.

    nmblookup prints lines like::

        192.168.1.10 SERVER<00>

    We extract the IP and the NetBIOS name (the part before ``<``).
    """
    servers: dict[str, DiscoveredServer] = {}
    for line in output.splitlines():
        line = line.strip()
        if not line or "<" not in line:
            continue
        # Typical: "192.168.1.10 MYNAS<00>"
        parts = line.split()
        if len(parts) < 2:
            continue
        ip = parts[0]
        # Validate IP-like format (simple check: contains dots)
        if "." not in ip:
            continue
        # Extract NetBIOS name from "NAME<xx>"
        nb_part = parts[1]
        nb_name = nb_part.split("<")[0]
        if not nb_name:
            continue
        key = ip
        if key not in servers:
            servers[key] = DiscoveredServer(
                hostname=nb_name,
                ip=ip,
                name=f"{nb_name} ({ip})",
            )
    return list(servers.values())


def _parse_smbclient_shares(output: str) -> list[str]:
    """Parse ``smbclient -L`` output to extract share names.

    Relevant lines look like::

        ShareName       Disk      Some comment

    We look for lines containing "Disk" and extract the share name.
    """
    shares: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        # smbclient -L prints a table: ShareName  Type  Comment
        # "Disk" shares are the ones we want
        if "\tDisk" in line or "  Disk" in line:
            # The share name is the first whitespace-delimited token
            share_name = line.split()[0]
            # Skip hidden shares (ending with $)
            if share_name.endswith("$"):
                continue
            shares.append(share_name)
    return shares


def _run_cmd(
    cmd: list[str], timeout: int = 10,
) -> tuple[bool, str]:
    """Run a command and return (success, stdout).

    Returns ``(False, "")`` if the command is not found or times out.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return (result.returncode == 0, result.stdout)
    except FileNotFoundError:
        log.warning("Command not found: %s", cmd[0])
        return (False, "")
    except subprocess.TimeoutExpired:
        log.warning("Command timed out after %ds: %s", timeout, " ".join(cmd))
        return (False, "")
    except OSError as exc:
        log.warning("Failed to run %s: %s", cmd[0], exc)
        return (False, "")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_smb_servers(timeout: int = 10) -> list[DiscoveredServer]:
    """Discover SMB servers on the local network.

    Tries avahi-browse first, then falls back to nmblookup.
    Results from both methods are merged and deduplicated by IP.

    Args:
        timeout: Maximum seconds to wait for each discovery command.

    Returns:
        List of discovered servers (may be empty).
    """
    servers: dict[str, DiscoveredServer] = {}

    # Method 1: avahi-browse (mDNS/DNS-SD)
    ok, output = _run_cmd(
        ["avahi-browse", "-tpk", "_smb._tcp"], timeout=timeout,
    )
    if ok and output.strip():
        for srv in _parse_avahi_output(output):
            servers[srv.ip] = srv
        log.info("avahi-browse found %d server(s)", len(servers))

    # Method 2: nmblookup (NetBIOS) — fallback
    ok, output = _run_cmd(
        ["nmblookup", "-S", "*"], timeout=timeout,
    )
    if ok and output.strip():
        for srv in _parse_nmblookup_output(output):
            if srv.ip not in servers:
                servers[srv.ip] = srv
        log.info(
            "nmblookup added servers, total now %d", len(servers),
        )

    if not servers:
        log.info("No SMB servers discovered on local network")

    return list(servers.values())


def list_smb_shares(
    server: str,
    username: str = "",
    password: str = "",
    timeout: int = 10,
) -> list[str]:
    """List available shares on a specific SMB server.

    Uses ``smbclient -L //server`` to enumerate shares.  If credentials
    are not provided, attempts a guest/anonymous connection.

    Args:
        server: Hostname or IP of the SMB server.
        username: Optional SMB username.
        password: Optional SMB password.
        timeout: Maximum seconds to wait.

    Returns:
        List of share names (may be empty).
    """
    cmd: list[str] = ["smbclient", "-L", f"//{server}"]
    if username:
        cmd.extend(["-U", f"{username}%{password}"])
    else:
        cmd.append("-N")

    ok, output = _run_cmd(cmd, timeout=timeout)
    if not ok:
        return []
    return _parse_smbclient_shares(output)
