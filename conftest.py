"""Pytest root: ensure repo root is first on ``sys.path`` for ``import agent``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
_rs = str(_ROOT)
for _ in range(sys.path.count(_rs)):
    sys.path.remove(_rs)
sys.path.insert(0, _rs)
