#!/usr/bin/env python3
"""Debug import chain to find the problem."""

import sys
import traceback

print("Starting import debug...")

# Try importing step by step
try:
    print("1. Importing utils...")
    import utils
    print("   ✓ utils")
except Exception as e:
    print(f"   ✗ utils: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("2. Importing dialogs...")
    import dialogs
    print("   ✓ dialogs")
except Exception as e:
    print(f"   ✗ dialogs: {e}")
    traceback.print_exc()
    sys.exit(1)

try:
    print("3. Importing main...")
    import main
    print("   ✓ main")
except Exception as e:
    print(f"   ✗ main: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\nAll imports successful!")
