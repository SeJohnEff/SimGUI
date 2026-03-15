"""
ICCID Index — Range-based index for fast card lookup.

When SIM data files are scanned, only ICCIDs are read.  Sequential
batches (standard for sysmocom) are compressed into a single
``IndexEntry`` per contiguous run.  Lookup is O(n) on entries — not
on individual cards — so even 100,000 cards are instant.

The index stores NO card data in memory.  Full card profiles are
loaded on demand from the source file and cached briefly via an LRU.
"""

import csv
import logging
import os
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


def _luhn_strip(iccid: str) -> str:
    """Remove the trailing Luhn check digit from an ICCID.

    Sysmocom 19-digit ICCIDs have a Luhn digit at position 19.
    23-digit Fiskarheden ICCIDs do NOT have Luhn check digits.
    We strip only when the length is 19 or 20 (standard ITU-T E.118).
    """
    if len(iccid) in (19, 20):
        return iccid[:-1]
    return iccid


def _detect_ranges(iccids: list[str]) -> list[tuple[str, int, int, int]]:
    """Detect contiguous ranges in a sorted list of ICCIDs.

    Returns a list of ``(prefix, range_start, range_end, suffix_len)``
    tuples.  Each tuple represents one contiguous sequential run.

    The algorithm:
      1. Strip Luhn check digit (for 19/20-digit ICCIDs)
      2. Find the common prefix across all stripped ICCIDs
      3. The suffix is the remaining digits (parsed as int)
      4. Walk the sorted suffixes; break a new range on any gap > 1
    """
    if not iccids:
        return []

    stripped = [_luhn_strip(i) for i in iccids]
    # Sort by the stripped value (deterministic ordering)
    stripped.sort()

    # Find longest common prefix
    prefix = os.path.commonprefix(stripped)
    # We want at least 1 digit in the suffix for range detection
    # Shorten prefix until all suffixes are digits with consistent length
    while prefix:
        suffixes_raw = [s[len(prefix):] for s in stripped]
        if all(sr.isdigit() and sr for sr in suffixes_raw):
            suffix_lengths = {len(sr) for sr in suffixes_raw}
            if len(suffix_lengths) == 1:
                break
        prefix = prefix[:-1]

    if not prefix:
        # Can't find common prefix — treat each as individual entry
        # Fall back: use all-but-last-4 as prefix
        min_len = min(len(s) for s in stripped)
        if min_len > 4:
            prefix = stripped[0][:min_len - 4]
        else:
            prefix = ""

    suffix_len = len(stripped[0]) - len(prefix) if prefix else len(stripped[0])
    suffixes = []
    for s in stripped:
        raw_suffix = s[len(prefix):]
        if raw_suffix.isdigit():
            suffixes.append(int(raw_suffix))
        else:
            # Non-numeric suffix — can't range-compress this one
            continue

    if not suffixes:
        return []

    suffixes.sort()
    ranges: list[tuple[str, int, int, int]] = []
    range_start = suffixes[0]
    prev = suffixes[0]
    for val in suffixes[1:]:
        if val != prev + 1:
            ranges.append((prefix, range_start, prev, suffix_len))
            range_start = val
        prev = val
    ranges.append((prefix, range_start, prev, suffix_len))
    return ranges


@dataclass
class IndexEntry:
    """One contiguous ICCID range within a single file."""

    file_path: str
    prefix: str
    range_start: int
    range_end: int
    suffix_len: int
    card_count: int
    iccid_length: int  # original length (19 or 23)

    def contains(self, iccid: str) -> bool:
        """Check if *iccid* falls within this range."""
        if len(iccid) != self.iccid_length:
            return False
        stripped = _luhn_strip(iccid)
        if not stripped.startswith(self.prefix):
            return False
        suffix_str = stripped[len(self.prefix):]
        if not suffix_str.isdigit():
            return False
        if len(suffix_str) != self.suffix_len:
            return False
        suffix = int(suffix_str)
        return self.range_start <= suffix <= self.range_end


@dataclass
class ScanResult:
    """Summary of a directory scan."""

    files_scanned: int = 0
    files_skipped: int = 0
    entries_created: int = 0
    total_cards: int = 0
    errors: list[str] = field(default_factory=list)


class IccidIndex:
    """Range-based ICCID index for fast card lookup.

    Usage::

        idx = IccidIndex()
        result = idx.scan_directory("/mnt/share/SIM")
        entry = idx.lookup("8949440000001672706")
        card = idx.load_card("8949440000001672706")
    """

    def __init__(self, *, cache_size: int = 50):
        self._entries: list[IndexEntry] = []
        self._file_mtimes: dict[str, float] = {}
        self._card_cache: OrderedDict[str, dict] = OrderedDict()
        self._cache_size = cache_size
        self._scanned_dirs: set[str] = set()

    def scan_directory(self, directory: str, *,
                        recursive: bool = True) -> ScanResult:
        """Quick-scan .eml/.csv/.txt files in *directory*.

        Builds range entries from ICCIDs only (no full card parse).
        Skips files whose mtime hasn't changed since last scan.

        When *recursive* is True (the default), subdirectories are
        walked automatically so that network shares with nested folder
        structures (e.g. ``SIM/batch-01/``) are fully indexed.
        """
        result = ScanResult()

        if not os.path.isdir(directory):
            result.errors.append(f"Not a directory: {directory}")
            return result

        self._scanned_dirs.add(directory)

        if recursive:
            all_files = []
            for dirpath, _dirnames, filenames in os.walk(directory):
                for fname in sorted(filenames):
                    all_files.append((dirpath, fname))
        else:
            all_files = [
                (directory, fname)
                for fname in sorted(os.listdir(directory))
            ]

        for dirpath, fname in all_files:
            lower = fname.lower()
            if not (lower.endswith(".eml") or lower.endswith(".csv")
                    or lower.endswith(".txt")):
                continue

            fpath = os.path.join(dirpath, fname)
            if not os.path.isfile(fpath):
                continue

            # Check mtime — skip unchanged files
            try:
                mtime = os.path.getmtime(fpath)
            except OSError:
                continue

            if fpath in self._file_mtimes and self._file_mtimes[fpath] == mtime:
                result.files_skipped += 1
                continue

            # Scan this file
            try:
                iccids = self._extract_iccids(fpath)
            except Exception as exc:
                result.errors.append(f"{fname}: {exc}")
                continue

            if not iccids:
                result.files_skipped += 1
                continue

            result.files_scanned += 1
            self._file_mtimes[fpath] = mtime

            # Remove old entries for this file (re-scan)
            self._entries = [e for e in self._entries
                            if e.file_path != fpath]

            # Detect ranges
            iccid_length = len(iccids[0])
            ranges = _detect_ranges(iccids)
            for prefix, rstart, rend, suffix_len in ranges:
                count = rend - rstart + 1
                entry = IndexEntry(
                    file_path=fpath,
                    prefix=prefix,
                    range_start=rstart,
                    range_end=rend,
                    suffix_len=suffix_len,
                    card_count=count,
                    iccid_length=iccid_length,
                )
                self._entries.append(entry)
                result.entries_created += 1
                result.total_cards += count

        if result.files_scanned > 0:
            logger.info(
                "ICCID index scan: %d files parsed, %d skipped, "
                "%d cards in %d range(s)%s",
                result.files_scanned, result.files_skipped,
                result.total_cards, result.entries_created,
                f" ({len(result.errors)} errors)" if result.errors else "",
            )
        elif result.files_skipped > 0:
            logger.debug(
                "ICCID index scan: all %d files up-to-date (cache hit)",
                result.files_skipped,
            )

        return result

    def lookup(self, iccid: str) -> Optional[IndexEntry]:
        """Find the index entry containing *iccid*.

        Returns the first matching ``IndexEntry`` or ``None``.
        """
        for entry in self._entries:
            if entry.contains(iccid):
                return entry
        return None

    def load_card(self, iccid: str) -> Optional[dict[str, str]]:
        """Lookup + parse source file + return full card profile.

        Results are cached in a small LRU so consecutive lookups
        for cards in the same file are fast.
        """
        # Check cache first
        if iccid in self._card_cache:
            self._card_cache.move_to_end(iccid)
            return self._card_cache[iccid]

        entry = self.lookup(iccid)
        if entry is None:
            return None

        # Parse the source file and find the card
        cards = self._parse_file(entry.file_path)
        if cards is None:
            return None

        # Cache all cards from this file (up to cache limit)
        for card in cards:
            card_iccid = card.get("ICCID", "")
            if card_iccid:
                self._card_cache[card_iccid] = card
                self._card_cache.move_to_end(card_iccid)
        # Evict oldest
        while len(self._card_cache) > self._cache_size:
            self._card_cache.popitem(last=False)

        return self._card_cache.get(iccid)

    def rescan_if_stale(self, directory: str,
                        max_age_s: float = 30.0) -> Optional[ScanResult]:
        """Re-scan *directory* only if any file mtimes changed.

        Returns a ScanResult if a rescan was performed, None if
        everything was up-to-date.
        """
        if not os.path.isdir(directory):
            return None

        # Quick check: any mtime changed?
        stale = False
        for fname in os.listdir(directory):
            lower = fname.lower()
            if not (lower.endswith(".eml") or lower.endswith(".csv")
                    or lower.endswith(".txt")):
                continue
            fpath = os.path.join(directory, fname)
            try:
                mtime = os.path.getmtime(fpath)
            except OSError:
                continue
            if fpath not in self._file_mtimes:
                stale = True
                break
            if mtime != self._file_mtimes[fpath]:
                stale = True
                break

        if not stale:
            return None

        return self.scan_directory(directory)

    def clear(self):
        """Reset the index completely."""
        self._entries.clear()
        self._file_mtimes.clear()
        self._card_cache.clear()
        self._scanned_dirs.clear()

    @property
    def stats(self) -> dict:
        """Return index statistics."""
        total_cards = sum(e.card_count for e in self._entries)
        files = {e.file_path for e in self._entries}
        return {
            "files": len(files),
            "entries": len(self._entries),
            "total_cards": total_cards,
            "cached_cards": len(self._card_cache),
            "scanned_dirs": len(self._scanned_dirs),
        }

    # ---- Internal helpers -----------------------------------------------

    @staticmethod
    def _extract_iccids(path: str) -> list[str]:
        """Extract only ICCID values from a file (fast, header-only parse).

        Supports .eml, .csv, and .txt files.
        """
        lower = path.lower()
        if lower.endswith(".eml"):
            return IccidIndex._extract_iccids_eml(path)
        elif lower.endswith(".csv"):
            return IccidIndex._extract_iccids_csv(path)
        elif lower.endswith(".txt"):
            return IccidIndex._extract_iccids_txt(path)
        return []

    @staticmethod
    def _extract_iccids_eml(path: str) -> list[str]:
        """Extract ICCIDs from a sysmocom .eml file."""
        from utils.eml_parser import parse_eml_file
        try:
            cards, _ = parse_eml_file(path)
            return [c["ICCID"] for c in cards if "ICCID" in c]
        except (ValueError, KeyError, OSError):
            return []

    @staticmethod
    def _extract_iccids_csv(path: str) -> list[str]:
        """Extract ICCIDs from a CSV file."""
        iccids = []
        try:
            with open(path, "r", newline="", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    val = row.get("ICCID", "").strip()
                    if val:
                        iccids.append(val)
        except (OSError, csv.Error):
            pass
        return iccids

    @staticmethod
    def _extract_iccids_txt(path: str) -> list[str]:
        """Extract ICCIDs from a tab-delimited .txt file.

        Fiskarheden files use tab-separated values with an ICCID column.
        """
        iccids = []
        try:
            with open(path, "r", encoding="utf-8-sig") as fh:
                reader = csv.DictReader(fh, delimiter="\t")
                for row in reader:
                    # Try both ICCID and iccid
                    val = row.get("ICCID", row.get("iccid", "")).strip()
                    if val:
                        iccids.append(val)
        except (OSError, csv.Error):
            pass
        return iccids

    @staticmethod
    def _parse_file(path: str) -> Optional[list[dict[str, str]]]:
        """Parse a full file and return all card dicts."""
        lower = path.lower()
        try:
            if lower.endswith(".eml"):
                from utils.eml_parser import parse_eml_file
                cards, _ = parse_eml_file(path)
                return cards
            elif lower.endswith(".csv"):
                cards = []
                with open(path, "r", newline="",
                          encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh)
                    for row in reader:
                        cards.append(dict(row))
                return cards
            elif lower.endswith(".txt"):
                cards = []
                with open(path, "r", encoding="utf-8-sig") as fh:
                    reader = csv.DictReader(fh, delimiter="\t")
                    for row in reader:
                        cards.append(dict(row))
                return cards
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", path, exc)
        return None
