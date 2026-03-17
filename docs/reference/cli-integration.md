# Reference: CLI integration

SimGUI communicates with physical SIM cards by shelling out to external CLI tools. It never imports these tools as Python libraries — the subprocess boundary keeps SimGUI fully decoupled from card-handling code and allows CLI tools to be updated independently.

**Source of truth:** `managers/card_manager.py` — `CardManager`, `CLIBackend`, `_find_cli_tool()`.

---

## Supported backends

| Backend | Enum | When active | CLI scripts used |
|---|---|---|---|
| pySim | `CLIBackend.PYSIM` | Primary — auto-installed at `/opt/pysim` by `install.sh` | `pySim-read.py`, `pySim-shell.py`, `pySim-prog.py` |
| sysmo-usim-tool | `CLIBackend.SYSMO` | Optional fallback for legacy SJS1 card support | `sysmo_isim_sja2.py`, `sysmo_isim_sja5.py`, `sysmo_isim_sjs1.py` |
| Simulator | `CLIBackend.SIMULATOR` | Active when Simulator Mode is enabled; no CLI calls made | (internal) |
| None | `CLIBackend.NONE` | Neither tool found; CSV editing still works | — |

---

## Auto-detection logic

On startup (and when `CardManager` is instantiated), SimGUI runs `_find_cli_tool()` which checks in this order:

1. **`PYSIM_PATH` environment variable** — if set and valid, use pySim from that path.
2. **`SYSMO_USIM_TOOL_PATH` environment variable** — if set and is a valid directory, use sysmo-usim-tool from that path.
3. **`/opt/pysim`** — the default install location (installed automatically by `install.sh`).
4. **Relative to SimGUI install directory** (`../../sysmo-usim-tool`, `../../pysim`)
5. **User home directory** (`~/pysim`, `~/sysmo-usim-tool`)
6. **System install** (`/opt/sysmo-usim-tool`)

The first match wins. In practice, `/opt/pysim` is found automatically on fresh installs since `install.sh` installs pySim there. If no tool is found, `cli_backend` is `CLIBackend.NONE`.

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

## pySim operations (primary backend)

pySim is the primary backend, auto-installed at `/opt/pysim` by `install.sh`. All card detection, reading, authentication, and programming operations use pySim.

### pySim-read — Card detection and reading

```bash
python pySim-read.py -p0
```

`-p0` selects the first PCSC reader. SimGUI parses the output for:
- `Autodetected card type:` — determines `CardType` (e.g. `gialersim`, `sysmoISIM-SJA5`)
- `ICCID:`, `IMSI:`, `ACC:`, `SPN:`, `FPLMN:` — card data fields

Blank gialersim cards return empty ICCID/IMSI but may return `ACC: ffff`.

### pySim-shell — Non-empty card programming

For non-empty (pre-programmed) cards, pySim-shell is used for delta writes:

```bash
python pySim-shell.py -p 0 -A <hex_ADM1>
```

Commands are piped via stdin, terminated with `quit`:

```bash
echo "select MF/ADF.USIM/EF.IMSI
update_binary_dec {\"imsi\": \"$IMSI\"}
quit" | python pySim-shell.py -p 0 -A <hex_ADM1>
```

**Critical pySim-shell caveats:**
- **Do NOT use `--noprompt`** — it breaks stdin piping (commands are silently ignored).
- **Do NOT use `exit`** — must use `quit`.
- **Exit code is always 0**, even on APDU failures — must scan stdout for error patterns.

### pySim-prog — Blank card programming (gialersim)

For blank/gialersim cards, pySim-prog writes all fields in one operation:

```bash
python pySim-prog.py -t gialersim -p 0 -a 88888888 \
    -s <ICCID> -i <IMSI> -k <Ki> --opc <OPc> \
    -n <SPN> --acc <ACC> -x <MCC> -y <MNC>
```

- `-t gialersim` — card type. **NEVER** use `-t auto` for gialersim (causes CHV 0x0A VERIFY which fails with `6f00`).
- `-a` — ASCII ADM1 key (NOT `-A` which is hex).
- `-t auto -A <hex_ADM1>` — for non-empty cards (works for SJA5).

### pySim error patterns

pySim-shell returns exit code 0 even on failures. SimGUI scans stdout/stderr for these error patterns:

| Pattern | Meaning |
|---|---|
| `SwMatchError` | APDU status word mismatch |
| `6f00` | Technical failure (often wrong CHV on blank cards) |
| `not equipped` | File or feature not present on card |
| `Card error` | General card communication error |
| `Autodetection failed` | pySim could not identify the card type |

---

## sysmo-usim-tool operations (legacy/optional)

sysmo-usim-tool is an optional fallback, primarily for legacy SJS1 card support.

### Card detection

SimGUI tries each card type script with `--help` to confirm the script exists and is executable:

```bash
python sysmo_isim_sja2.py --help
python sysmo_isim_sja5.py --help
python sysmo_isim_sjs1.py --help
```

The first successful response sets `card_type`.

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
