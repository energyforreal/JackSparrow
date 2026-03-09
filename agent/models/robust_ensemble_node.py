"""
Re-export RobustEnsembleNode from scripts for agent inference.
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_scripts = _root / "scripts"
if _root.exists() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if _scripts.exists() and str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from robust_ensemble_node import (
    RobustEnsembleNode,
    ENTRY_THRESHOLD,
    EXIT_THRESHOLD,
    PositionContext,
    RegimeContext,
)

__all__ = [
    "RobustEnsembleNode",
    "ENTRY_THRESHOLD",
    "EXIT_THRESHOLD",
    "PositionContext",
    "RegimeContext",
]
