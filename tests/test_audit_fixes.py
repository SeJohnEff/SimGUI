"""
Test quality audit fixes — new and strengthened tests.

Issues addressed:
1. BatchManager: missing coverage of _process_one failure sub-paths
   (program_card failure, verify_card failure, ICCID mismatch read_iccid path)
2. CSVManager: load_file() EML path never tested via CSVManager
3. CSVManager: whitespace-delimited fallback never covered
4. IccidIndex: rescan_if_stale() when NOT stale; error path in scan
5. SimulatorBackend: _load_deck() CSV fallback path
6. CardManager: _parse_pysim_output() various inputs
7. ValidationModule: validate_card_data() with OPc
8. AutoArtifactManager: case-insensitive field lookup
9. Integration: CSVManager.load_file(.eml) → columns normalised
10. Integration: BatchManager wraps _process_one failure detail messages
11. Negative tests: corrupted inputs, empty files, permission errors
12. Contract: BatchManager with no callbacks set (no AttributeError)
"""  # TRUNCATED - see actual file