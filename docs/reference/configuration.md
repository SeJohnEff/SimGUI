# Reference: Configuration

SimGUI is configured through environment variables (for CLI tool paths) and a persistent JSON settings file (for UI preferences).

**Source of truth:**  
- Environment variables: `managers/card_manager.py` — `_find_cli_tool()`  
- Settings file: `managers/settings_manager.py` — `SettingsManager`, `_DEFAULTS`

---

## Environment variables

These variables are read at startup when SimGUI instantiates `CardManager`. They are not read from a config file — they must be set in the shell environment before launching SimGUI.

| Variable | Type | Description |
|---|---|---|
| `SYSMO_USIM_TOOL_PATH` | Directory path | Path to the `sysmo-usim-tool` repository root. Takes precedence over all other auto-detection. |
| `PYSIM_PATH` | Directory path | Path to the `pySim` repository root. Checked after `SYSMO_USIM_TOOL_PATH`. |

### Setting environment variables

**For a single session:**

```bash
export SYSMO_USIM_TOOL_PATH=/home/user/sysmo-usim-tool
simgui
```

**Persistently (for all future sessions):**

Add to `~/.bashrc` or `~/.profile`:

```bash
export SYSMO_USIM_TOOL_PATH=/opt/sysmo-usim-tool
```

Reload: `source ~/.bashrc`

**For a desktop launcher:**

Edit the `.desktop` file (typically at `/usr/share/applications/simgui.desktop` or `~/.local/share/applications/simgui.desktop`):

```ini
[Desktop Entry]
Exec=env SYSMO_USIM_TOOL_PATH=/opt/sysmo-usim-tool simgui
```

### Auto-detection fallback paths

If neither environment variable is set, SimGUI checks these locations in order:

**sysmo-usim-tool:**
1. `../../sysmo-usim-tool` (relative to SimGUI install)
2. `~/sysmo-usim-tool`
3. `/opt/sysmo-usim-tool`

**pySim:**
1. `../../pysim` (relative to SimGUI install)
2. `~/pysim`
3. `/opt/pysim`

sysmo-usim-tool is always tried before pySim.

---

## Settings file

User preferences are stored at:

```
~/.config/simgui/settings.json
```

The exact path respects `XDG_CONFIG_HOME`:

```
${XDG_CONFIG_HOME:-$HOME/.config}/simgui/settings.json
```

The file is created automatically on first run. If the file is missing or corrupt, SimGUI silently uses built-in defaults.

### Settings keys

| Key | Type | Default | Description |
|---|---|---|---|
| `last_mcc_mnc` | String | `""` | Last MCC+MNC used in sequence generation |
| `last_customer_code` | String | `""` | Last customer code |
| `last_sim_type_code` | String | `""` | Last SIM type digit |
| `last_spn` | String | `""` | Last SPN value used |
| `last_language` | String | `""` | Last LI value used |
| `last_fplmn` | String | `""` | Last FPLMN string used |
| `last_csv_path` | String | `""` | Last CSV file path opened |
| `last_batch_size` | Integer | `20` | Last batch size in Generate Sequence mode |
| `window_geometry` | String | `""` | Saved window position/size (Tk geometry string) |
| `simulator_mode` | Boolean | `false` | Whether Simulator Mode was active on last close |

### Editing the settings file

You can edit the file directly in a text editor:

```bash
nano ~/.config/simgui/settings.json
```

Changes take effect on the next SimGUI launch. SimGUI does not watch for external changes at runtime.

**To reset all settings to defaults:**

```bash
rm ~/.config/simgui/settings.json
```

### Settings file example

```json
{
  "last_mcc_mnc": "99988",
  "last_customer_code": "01",
  "last_sim_type_code": "0",
  "last_spn": "TELEAURA",
  "last_language": "EN",
  "last_fplmn": "24007;24024;24001",
  "last_csv_path": "/home/user/data/order-20260314.csv",
  "last_batch_size": 20,
  "window_geometry": "1200x800+100+50",
  "simulator_mode": false
}
```

---

## No configuration file for CLI paths

There is deliberately no SimGUI configuration file entry for `SYSMO_USIM_TOOL_PATH` or `PYSIM_PATH`. These are environment-level concerns (the OS knows where tools are installed) rather than user-preference concerns. Using environment variables ensures the CLI tools are independently managed and versioned outside SimGUI's control.

If you want persistent CLI path configuration without environment variables, place the tools in one of the auto-detected locations (`~/sysmo-usim-tool`, `/opt/sysmo-usim-tool`, etc.).

---

## Logging

SimGUI uses Python's `logging` module. The default log level is `WARNING`. To enable debug output:

```bash
PYTHONPATH=/usr/share/simgui python3 -c "
import logging; logging.basicConfig(level=logging.DEBUG)
import main; main.main()
"
```

Or set the level in the application before launch. Logs appear in the terminal where SimGUI was started and in the in-app log panel for operation-level messages.
