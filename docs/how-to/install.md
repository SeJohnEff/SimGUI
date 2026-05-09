# How to: Install SimGUI

Choose your platform below: [Ubuntu](#ubuntu-installation) | [macOS](#macos-installation)

---

## Ubuntu Installation

**Applies to:** Ubuntu 22.04 LTS and later (desktop)  
**Time required:** 5 minutes on a fresh system

### Prerequisites

- Ubuntu 22.04 or later (x86-64 or ARM/aarch64)
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

1. Installs build dependencies (`python3`, `python3-pip`, `python3-venv`, `dpkg-dev`, etc.)
2. Clones and sets up **pySim** at `/opt/pysim` with its own virtual environment and dependencies
3. Applies the GialerSim SPN patch to pySim automatically
4. Builds the `.deb` package from source
5. Installs the `.deb` including all runtime dependencies:
   - `smbclient` — SMB share access
   - `avahi-utils` — mDNS network discovery
   - `cifs-utils` — CIFS/SMB mount support
   - `nfs-common` — NFS mount support
   - `pcscd`, `pcsc-tools` — PCSC daemon for card readers
6. **Enables and starts pcscd immediately** so the card reader is detected right away
7. Configures a sudoers rule for password-free network mount/unmount

After installation, SimGUI is available as:

```bash
simgui
```

And in the application launcher under the Utilities category.

pySim is installed automatically — no manual CLI tool setup needed. SimGUI auto-detects `/opt/pysim` on startup. Re-running the install script updates both SimGUI and pySim.

---

## Alternative CLI tools (optional)

pySim is installed by the script and is used for all card operations (read, authenticate, program). You only need this section if you also want sysmo-usim-tool as an alternative backend.

### sysmo-usim-tool (optional, for legacy workflows)

```bash
git clone https://github.com/SeJohnEff/sysmo-usim-tool ~/sysmo-usim-tool
pip3 install -r ~/sysmo-usim-tool/requirements.txt
```

SimGUI auto-detects `~/sysmo-usim-tool` on startup. To use a different location, set the environment variable:

```bash
export SYSMO_USIM_TOOL_PATH=/path/to/sysmo-usim-tool
```

See [CLI integration reference](../reference/cli-integration.md) for full auto-detection logic and how SimGUI selects between the two tools.

---

## Verify the PCSC daemon

The install script automatically enables and starts the PCSC daemon (`pcscd`). Verify the reader is visible:

```bash
pcsc_scan
```

Insert a card — `pcsc_scan` should print the ATR and card information.

If `pcsc_scan` reports "No reader detected," the daemon may need to be manually started:

```bash
sudo systemctl start pcscd
```

To ensure pcscd survives a reboot:

```bash
sudo systemctl enable pcscd
```

---

## Add your user to the `pcscd` group (if needed)

On some systems, non-root users need group membership to access the PCSC socket:

```bash
sudo usermod -aG pcscd $USER
```

Log out and back in for the group change to take effect.

---

## macOS Installation

**Applies to:** macOS 12 (Monterey) or later (Intel or Apple Silicon)  
**Time required:** 2 minutes for simulator mode; 10 minutes with hardware support

### Quick Start — Simulator Mode (No Hardware)

For a zero-configuration experience without a physical card reader:

1. **Download** `SimGUI.app` from [GitHub Releases](https://github.com/SeJohnEff/SimGUI/releases)
2. **Drag** `SimGUI.app` to `/Applications`
3. **Double-click** to run — simulator mode activates automatically with 20 virtual SIM cards

That's it! The app has no dependencies and works without installing anything.

### Hardware Support — Real SIM Card Programming

To enable hardware card reader support, install pySim and dependencies:

```bash
bash /Applications/SimGUI.app/Contents/Resources/scripts/install-macos.sh
```

Or manually:

```bash
git clone https://gitea.osmocom.org/sim-card/pysim.git ~/pysim
cd ~/pysim
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Then set the environment variable (add to `~/.zshrc` or `~/.bash_profile`):

```bash
export PYSIM_PATH=~/pysim
```

Restart SimGUI — it will now auto-detect pySim and enable hardware card operations.

### PCSC Reader Detection

macOS includes native PC/SC support (`PCSC.framework`) — no daemon installation needed. When you plug in a USB PCSC-compatible card reader (e.g. OMNIKEY 3x21), it will be auto-detected.

Verify the reader is visible:

```bash
system_profiler SPUSBDataType | grep -i "smart\|omnikey\|realtek"
```

### Network Share Mounting (Optional)

To mount SMB/CIFS shares for artifact export:

1. In **SimGUI Settings**, add a share profile (hostname, share name, credentials)
2. Click **Mount** — macOS will use `mount_smbfs` to attach the share
3. Choose **Allow** if prompted for sudo access

Alternatively, use Finder natively: **Cmd+K** > `smb://server/share` and point SimGUI to the mounted volume.

### Troubleshooting (macOS)

| Symptom | Fix |
|---|---|
| "No reader detected" | Plug in your USB card reader; quit and restart SimGUI |
| "CLI tool not found" | Run the `install-macos.sh` script to install pySim |
| Mount permission denied | Ensure you have sudo access; try mounting via Finder first |
| pySim import errors | Set `export PYSIM_PATH=~/pysim` and restart |

---

## Using SimGUI with UTM (macOS → Linux VM)

If running Ubuntu in UTM on macOS, additional USB configuration is required for the card reader to work reliably.

### Enable USB Sharing in UTM

1. Open your SimGUI VM in UTM
2. Go to **Settings → Input**
3. Enable the **"USB sharing"** toggle (specify max shared devices if prompted)
4. Restart the VM for the setting to take effect

### Configure the Card Reader for Auto-Connect

1. In the running UTM VM, click the **USB icon in the top-right corner**
2. Find your card reader (e.g., "Realtek Semiconductor Smart Card Reader")
3. Click to attach it to the VM
4. In the device list, check the **"auto-connect"** checkbox for the reader

### Workflow

**At startup:**
- USB reader must be physically connected to the Mac before starting the VM
- With auto-connect enabled, the reader will be automatically available in the VM
- Start SimGUI and the reader will be detected

**If the reader is unplugged during use:**
- SimGUI will show a toast notification: *"No reader detected. Ensure reader is plugged in and enabled in VM window (top right corner). Disconnect/connect in top right menu."*
- The toast persists until you click to close it or reconnect the reader
- A background monitoring service will detect when the reader is re-connected
- You will see a desktop notification: *"SmartCard Reader detected — toggle in UTM's USB menu"*
- Click the USB icon in UTM's top-right corner and toggle the reader to re-attach it
- SimGUI's toast notification will auto-dismiss when the reader is detected

**If issues persist:**
- As a last resort, you can reboot the VM (the reader will auto-attach on restart)
- Or manually disconnect/reconnect the reader in UTM's USB device menu

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
| `No CLI tool found` on launch | pySim install failed or was removed | Re-run install script; check `/opt/pysim` exists |
| `Failed to connect to pcscd` | PCSC daemon not running | `sudo systemctl start pcscd` |
| `Permission denied` on reader | User not in `pcscd` group | `sudo usermod -aG pcscd $USER` then re-login |
| GUI won't start on Wayland | Qt/Wayland incompatibility | Set `QT_QPA_PLATFORM=xcb simgui` or use an Xorg session |

For more issues, see [Troubleshooting](troubleshooting.md).
