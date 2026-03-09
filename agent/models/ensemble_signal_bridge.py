"""
Re-export EnsembleSignalBridge and related from scripts.
"""

import sys
from pathlib import Path

_root = Path(__file__).resolve().parents[2]
_scripts = _root / "scripts"
if _root.exists() and str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
if _scripts.exists() and str(_scripts) not in sys.path:
    sys.path.insert(0, str(_scripts))

from ensemble_signal_bridge import (
    CombinedSignal,
    EntrySignal,
    ExitSignal,
    EnsembleSignalBridge,
    PositionContext,
    RegimeContext,
    REGIME_TF_WEIGHTS,
)

__all__ = [
    "CombinedSignal",
    "EntrySignal",
    "ExitSignal",
    "EnsembleSignalBridge",
    "PositionContext",
    "RegimeContext",
    "REGIME_TF_WEIGHTS",
]
