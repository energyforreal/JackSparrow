#!/usr/bin/env python3
"""Deprecated: use ``python scripts/smoke_test_v43.py``."""

from __future__ import annotations

import runpy
from pathlib import Path

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parent / "smoke_test_v43.py"), run_name="__main__")
