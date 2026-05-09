#!/usr/bin/env python3
"""Minimal test to debug import issue."""

import sys
print(f"Python version: {sys.version_info}")

try:
    print("Importing utils...")
    from utils import get_browse_initial_dir
    print("✓ Successfully imported get_browse_initial_dir")
except Exception as e:
    print(f"✗ Failed to import: {e}")
    import traceback
    traceback.print_exc()
