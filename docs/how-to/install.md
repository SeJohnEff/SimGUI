# How to: Install SimGUI on Ubuntu

**Applies to:** Ubuntu 22.04 LTS and later (desktop)  
**Time required:** 5 minutes on a fresh system

---

## Prerequisites

- Ubuntu 22.04 or later, x86-64
- `sudo` access
- Internet connection (to fetch the install script)
- A USB PCSC reader (for hardware card operations)

No Python environment or manual dependency installation is needed — the install script handles everything.

---

## Install with the one-line installer

```bash
curl -fsSL https://raw.githubusercontent.com/SeJohnEff/SimGUI/main/scripts/install.sh | sudo bash
```

This script:

1. Installs build dependencies (`python3`, `python3-pip`, `python3-tk`, `dpkg-dev`, etc.)
2. Builds the `.deb` package from source
3. Installs the `.deb` including all runtime dependencies:
   - `smbclient` — SMB share access
   - `avahi-utils` — mDNS network discovery
   - `cifs-utils` — CIFS/SMB mount support
   - `nfs-common` — NFS mount support
   - `pcscd`, `pcsc-tools` — PCSC daemon for card readers

After installation, SimGUI is available as:

```bash
simgui
```

And in the application launcher under the Utilities category.

---

## Install the CLI card tools

SimGUI requires at least one of the following CLI tools to communicate with physical cards. Without them, CSV editing and the built-in simulator still work, but hardware card operations are unavailable.

### Option A — sysmo-usim-tool (recommended for sysmocom cards)

```bash
git clone https://github.com/SeJohnEff/sysmo-usim-tool ~/sysmo-usim-tool
pip3 install -r ~/sysmo-usim-tool/requirements.txt
```

SimGUI auto-detects `~/sysmo-usim-tool` on startup. To use a different location, set the environment variable:

```bash
export SYSMO_USIM_TOOL_PATH=/path/to/sysmo-usim-tool
```

Add the export to `~/.bashrc` or `~/.profile` for persistence.

### Option B — pySim

```bash
git clone https://github.com/osmocom/pysim ~/pysim
pip3 install -r ~/pysim/requirements.txt
```

SimGUI auto-detects `~/pysim`. To use a different location:

```bash
export PYSIM_PATH=/path/to/pysim
```

See [CLI integration reference](../reference/cli-integration.md) for full auto-detection logic and how SimGUI selects between the two tools.

---

## Enable the PCSC daemon

The PCSC daemon must be running for the card reader to work:

```bash
sudo systemctl enable pcscd
sudo systemctl start pcscd
```

Verify the reader is visible:

```bash
pcsc_scan
```

Insert a card — `pcsc_scan` should print the ATR and card information.

---

## Add your user to the `pcscd` group (if needed)

On some systems, non-root users need group membership to access the PCSC socket:

```bash
sudo usermod -aG pcscd $USER
```

Log out and back in for the group change to take effect.

---

## Verify the installation

```bash
simgui --version
```

Or launch the GUI and check **Settings → About** for the installed version.

To verify without hardware, enable **Simulator Mode** in Settings and run through the [first-card tutorial](../tutorials/first-card.md) using virtual cards.

---

## Uninstall

```bash
sudo apt remove simgui
```

Configuration files are kept at `~/.config/simgui/`. Remove them manually if desired:

```bash
rm -rf ~/.config/simgui/
```

---

## Troubleshooting installation

| Symptom | Likely cause | Fix |
|---|---|---|
| `simgui: command not found` | `.deb` did not install cleanly | Re-run install script; check for errors in output |
| `No CLI tool found` on launch | sysmo-usim-tool/pySim not detected | Set `SYSMO_USIM_TOOL_PATH` or `PYSIM_PATH`; see [Configuration](../reference/configuration.md) |
| `Failed to connect to pcscd` | PCSC daemon not running | `sudo systemctl start pcscd` |
| `Permission denied` on reader | User not in `pcscd` group | `sudo usermod -aG pcscd $USER` then re-login |
| GUI won't start on Wayland | Tkinter/Wayland incompatibility | Set `GDK_BACKEND=x11 simgui` or use an Xorg session |

For more issues, see [Troubleshooting](troubleshooting.md).
