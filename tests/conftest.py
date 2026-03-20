"""Force project root before other entries on ``sys.path``."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_rs = str(_ROOT)


def pytest_configure() -> None:
    for _ in range(sys.path.count(_rs)):
        sys.path.remove(_rs)
    sys.path.insert(0, _rs)
