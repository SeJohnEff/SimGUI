# Reference: CLI integration

SimGUI communicates with physical SIM cards by shelling out to external CLI tools. It never imports these tools as Python libraries — the subprocess boundary keeps SimGUI fully decoupled from card-handling code and allows CLI tools to be updated independently.

**Source of truth:** `managers/card_manager.py` — `CardManager`, `CLIBackend`, `_find_cli_tool()`.

---

## Supported backends

| Backend | Enum | When active | CLI scripts used |
|---|---|---|---|
| sysmo-usim-tool | `CLIBackend.SYSMO` | Preferred when available; supports all three sysmocom card types | `sysmo_isim_sja2.py`, `sysmo_isim_sja5.py`, `sysmo_isim_sjs1.py` |
| pySim | `CLIBackend.PYSIM` | Fallback when sysmo-usim-tool is not found | `pySim-read.py`, `pySim-prog.py` |
| Simulator | `CLIBackend.SIMULATOR` | Active when Simulator Mode is enabled; no CLI calls made | (internal) |
| None | `CLIBackend.NONE` | Neither tool found; CSV editing still works | — |

---

## Auto-detection logic

On startup (and when `CardManager` is instantiated), SimGUI runs `_find_cli_tool()` which checks in this order:

1. **`SYSMO_USIM_TOOL_PATH` environment variable** — if set and is a valid directory, use sysmo-usim-tool from that path.
2. **`PYSIM_PATH` environment variable** — if set and valid, use pySim from that path.
3. **Relative to SimGUI install directory** (`../../sysmo-usim-tool`)
4. **User home directory** (`~/sysmo-usim-tool`)
5. **System install** (`/opt/sysmo-usim-tool`)
6. Same three locations checked for `~/pysim` and `/opt/pysim`

The first match wins. If no tool is found, `cli_backend` is `CLIBackend.NONE`.

---

## Setting the CLI path manually

To override auto-detection at runtime:

```python
card_manager.set_cli_path("/custom/path/to/sysmo-usim-tool")
```

`set_cli_path()` auto-detects which backend it is based on whether `pySim-read.py` exists in the directory. You can also pass `backend` explicitly:

```python
from managers.card_manager import CLIBackend
card_manager.set_cli_path("/custom/path", backend=CLIBackend.PYSIM)
```

---

## How CLI calls are made

All CLI invocations go through `CardManager._run_cli(script, *args)`:

```python
cmd = [sys.executable, script_path] + list(args)
result = subprocess.run(
    cmd, capture_output=True, text=True, timeout=30,
    cwd=self.cli_path,
)
```

Key properties:

- **Python interpreter** (`sys.executable`) is always used — never raw shell execution.
- **Working directory** is set to `cli_path`, matching how the CLI tools expect to be run.
- **Timeout:** 30 seconds by default. Operations that exceed this return `(False, "", "Command timed out")`.
- **stdout and stderr captured separately.** Callers receive `(success: bool, stdout: str, stderr: str)`.
- **Path traversal prevention:** `_validate_script_path()` rejects any script name containing `..`, path separators, or paths that resolve outside `cli_path` after `os.path.realpath()`.

---

## sysmo-usim-tool operations

### Card detection

SimGUI tries each card type script with `--help` to confirm the script exists and is executable:

```bash
python sysmo_isim_sja2.py --help
python sysmo_isim_sja5.py --help
python sysmo_isim_sjs1.py --help
```

The first successful response sets `card_type`. This is a reader-availability check, not a card-presence check.

### Reading card data

ICCID is read without authentication. IMSI and protected fields (Ki, OPc) require ADM1 authentication first.

> **Status:** Full CLI read/write calls are implemented via `detect_card()` and `read_public_data()`. The `authenticate()`, `program_card()`, and `read_protected_data()` methods include stubs pending completion of CLI argument mapping for each card type. In the meantime, all operations are fully functional in Simulator Mode.

### Programming

When implemented, the call structure will be:

```bash
python sysmo_isim_sja5.py \
    --adm1 {ADM1} \
    --imsi {IMSI} \
    --ki {Ki} \
    --opc {OPc} \
    --spn {SPN} \
    --language {LI} \
    ...
```

Exact argument names vary by card type and sysmo-usim-tool version. Consult the sysmo-usim-tool README for current flags.

---

## pySim operations

### Card detection

```bash
python pySim-read.py -p0
```

`-p0` selects the first PCSC reader. SimGUI parses the output for `ICCID:` and `IMSI:` lines using a key-value parser.

### Programming

```bash
python pySim-prog.py -p0 \
    --imsi {IMSI} \
    --ki {Ki} \
    --opc {OPc} \
    ...
```

---

## Error handling

| Error condition | SimGUI response |
|---|---|
| CLI script not found | `(False, "", "Script not found: {script}")` |
| CLI returns non-zero exit code | `(False, "", stderr_output)` |
| Timeout (>30 seconds) | `(False, "", "Command timed out")` |
| Path traversal attempt | `(False, "", "Invalid script path: {script}")` |
| No CLI tool configured | `(False, "", "sysmo-usim-tool / pySim not found. Set SYSMO_USIM_TOOL_PATH or PYSIM_PATH, or place them next to SimGUI.")` |

All errors are surfaced in the SimGUI log panel. The batch manager treats any `False` success result as a failed card and continues to the next.

---

## Simulator mode

When Simulator Mode is enabled, `CardManager._simulator` is set to a `SimulatorBackend` instance. All methods that would otherwise call the CLI (`detect_card`, `authenticate`, `program_card`, `verify_card`, etc.) are delegated to the simulator instead. No subprocess calls are made.

The simulator loads 20 real sysmoISIM-SJA5 profiles from `simulator/card_deck.py`. Each virtual card has a unique ICCID and IMSI and can be navigated with `next_virtual_card()` / `previous_virtual_card()`.

---

## Related documentation

- [Configuration](configuration.md) — environment variables for CLI path
- [Card types](card-types.md) — which script maps to which card type
- [Architecture overview](../explanation/architecture.md) — how `CardManager` fits in the broader system
