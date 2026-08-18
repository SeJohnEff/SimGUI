# Programming Gialersim cards — findings

Card: gialersim, ATR `3B9F95801FC78031A073B6A10067CF3215CA9CD70920`,
USIM AID `A0000000871002FF86FF0389FFFFFFFF`.
Verified 2026-08-13 on a card GRSIMWrite had never touched.

## The problem

pySim's `GialerSim` class writes Ki and OPc, gets `9000` on every APDU, and
produces a SIM that fails authentication with **MAC failure (9862 / cause 20)**.
Nothing in the logs indicates failure. `Post-program verification OK` is printed
because ICCID/IMSI/ACC *do* write correctly — only the keys are unusable.

Two independent reasons, both required to fix:

1. **Wrong class byte.** pySim uses UICC class (`CLA=00`, SELECT `P2=04`).
   These cards only commit key writes in GSM class (`CLA=A0`, SELECT `P2=00`).
2. **Missing algorithm configuration.** The card needs `EF 2FE5` and `EF 2FE6`
   written. Without them the Ki is stored but no algorithm is bound to the key
   set, so `AUTHENTICATE` fails no matter how correct the key is.

## Working sequence

All in GSM class. Steps 2–6 must run in one session with **no DF reselect**
between them — selecting a DF drops the ADM security state.

```
reset (no SELECT MF; MF is implicitly current after ATR)

1  VERIFY ADM       A0 20 00 0C 08 3834373936313533        ADM "84796153", ref 0x0C

2  key definition files
   A0 A4 00 00 02 0100
   A0 D6 00 00 17 00000031323334FFFFFFFF838338383838383838388A8A
   A0 A4 00 00 02 0200
   A0 D6 00 00 17 01000031323334FFFFFFFF838338383838383838388A8A
   A0 A4 00 00 02 0B00
   A0 D6 00 00 0D 01000038383838383838388A8A

3  Ki               A0 A4 00 00 02 0001
                    A0 D6 00 00 10 <Ki, 16 bytes>

4  OPc              A0 A4 00 00 02 6002
                    A0 D6 00 00 11 01 <OPc, 16 bytes>      note the 01 prefix

5  algorithm / key-set config          <-- the piece everyone misses
   A0 A4 00 00 02 2FE5
   A0 D6 00 00 05 081C2A0001
   A0 A4 00 00 02 2FE6
   A0 DC 01 04 11 40 000000000000000000000000000000 00
   A0 DC 02 04 11 00 000000000000000000000000000000 01
   A0 DC 03 04 11 20 000000000000000000000000000000 02
   A0 DC 04 04 11 40 000000000000000000000000000000 04
   A0 DC 05 04 11 60 000000000000000000000000000000 08

6  ICCID            A0 A4 00 00 02 2FE2
                    A0 D6 00 00 0A <ICCID, nibble-swapped, f-padded>

7  now safe to change DF
   A0 A4 00 00 02 3F00
   A0 A4 00 00 02 7F20
   A0 A4 00 00 02 6F07 ; A0 D6 00 00 09 <IMSI encoded>
   A0 A4 00 00 02 6F78 ; A0 D6 00 00 02 <ACC>
```

GSM class answers SELECT with `9FXX` (not `61XX`); follow with
`A0 C0 00 00 XX`.

## Credentials and files

| Item | Value / location |
|---|---|
| ADM | `84796153`, key reference `0x0C` (**not** `88888888`) |
| `88888888` | the *contents* of key file `0B00` (key at ref `0x0B`) — not a credential to present |
| Ki | `MF/0001`, 16 bytes, ARR `2F0613` = READ never / UPDATE ADM `0x0C` |
| OPc | `MF/6002`, 17 bytes = `01` + OPc, same ARR |
| Key ref `0x0C` | 10 attempts, correct key `84796153` |
| Key ref `0x0B` | 10 attempts, correct key `88888888` — verifies but does **not** grant key-file write |

Ki and OPc are **unreadable by design** (EF_ARR record `0x13`, READ = NEVER).
Read-back verification is impossible; `9000` on the write proves nothing.

## Verification (implemented, fail-closed)

Ki/OPc are `READ=NEVER`; a `9000` on the write proves nothing. The only way to
confirm the keys committed is to make the card authenticate. This is implemented
in-app as an **offline USIM AUTHENTICATE self-check** in
`managers/gialersim_selfcheck.py`, run automatically after every native program
(`CardManager._selfcheck_gialersim_keys`). It sends `AUTHENTICATE` (INS `88`,
P2 `81`) in `ADF_USIM` with an AUTN computed from the just-written Ki/OPc:

* `DB …` success, or `DC …` sync failure → **MAC verified, keys correct** →
  `WRITE_OK_VERIFIED` (green, artifact allowed).
* `9862` / `6300` → **keys wrong** → `WRITE_OK_VERIFICATION_FAILED` (red).
* check could not run (no crypto backend, self-test failed, transport error) →
  `VERIFY_UNAVAILABLE` (red) — **fail-closed: never reported as programmed**.

Sync failure still proves the key, so the result is independent of SQN state.
Milenage is self-tested against 3GPP TS 35.208 Test Set 1 before each run.
Takes ~15 s per card, offline, no network required. The standalone
`tools/auth_validate_harness.py` uses the identical method.

**Crypto backend is a hard prerequisite.** The self-check needs `pycryptodome`
(imports as `Crypto`; `Cryptodome` also accepted). It is declared in
`requirements.txt`, `debian/control` (`python3-pycryptodome`), the install
scripts, and `SimGUI.spec` `hiddenimports`; the macOS build (`build-macos-app.sh`)
fails if the frozen app cannot import it (`main.py --selfcheck-crypto`). At
startup the app runs the Milenage self-test and, if it fails, **disables
gialersim programming** (fail-closed pre-gate) with a deliberate override
(`--allow-unverified-programming` / Card menu) that still reports
`VERIFY_UNAVAILABLE`.

## Dead ends (all falsified by measurement)

| Hypothesis | Killed by |
|---|---|
| orc8r/subscriberdb didn't take the update | `subscriber_cli.py` matched byte-for-byte |
| `--op` vs `--opc` flag confusion | same flags produced both a pass and a fail |
| pySim delta path skips Ki/OPc | real, but gialersim always routes to `program_full` |
| Card is write-once / has a write limit | GRSIMWrite rewrote the same card repeatedly |
| Wrong ADM (`88888888` at `0x0C`) | returns `63Cx`; `84796153` returns `9000` |
| Two ADMs needed (`0x0C` + `0x0B`) | worked once by coincidence, never reproduced |
| Key files live elsewhere (incl. `ADF_USIM`) | full FS scan: only `0001`/`6002` carry ARR `2F0613` |
| CLA `A0` alone | necessary, not sufficient |
| Ordering / DF reselect alone | necessary, not sufficient |

## Caveats

* Not yet proven in one pass on a factory-fresh card — `...013` had received
  several partial writes before the successful run.
* Recipe not minimised: `2FE5`/`2FE6` were demonstrably the last missing piece,
  but it is unknown which earlier steps are strictly required.
* `2FE6` bytes are copied verbatim from a Milenage-configured card. The leading
  byte (`40`/`00`/`20`/`40`/`60`) is believed to be an algorithm selector and
  the trailing byte (`00,01,02,04,08`) a key-set index — not confirmed.

## Source

Recovered by USB capture (USBPcap) of a GRSIMWrite session, since GRSIMWrite
does not route through `winscard.dll` and APDU-level hooking (APDUPlay) sees
nothing. Reader in that capture: SCM/Identiv `04e6:5810`.

## Implementation in SimGUI

This sequence is implemented natively in `managers/gialersim.py` and is the
sole programming path for `CardType.GIALERSIM` (routed from
`CardManager.program_card`). pySim is bypassed entirely for these cards.
sysmocom (SJA5/SJA2) cards are unaffected and continue to use pySim.

**No delta for gialersim.** `program_card` writes the full canonical field set
every time (never a delta, ICCID always written) — the delta path is a
non-empty-sysmocom concept that, applied to gialersim, silently dropped ICCID
and unchanged required fields when re-programming a personalised card.

**Canonical field set.** The written/verified fields are defined once in
`card_profiles/field_schema.py` (`GIALERSIM_SCHEMA`), read by the GUI,
programming, and verification so they cannot drift: written = ICCID, IMSI, Ki,
OPc, ACC. SPN, FPLMN and HNET_PUBKEY are **excluded** — not part of the verified
recipe — so the GUI hides them for a gialersim card ("what is shown is what is
programmed"). The GRSIMWrite trace does contain SPN (`6F46`) and FPLMN (`6F7B`)
writes after the DF switch on non-ADM files, so they can be added safely as a
**separate** change (see `docs/TODO.md`).
