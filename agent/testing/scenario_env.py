"""Load scenario-test environment overrides before ``agent.core.config.settings``."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

_SCENARIO_ENV = (
    Path(__file__).resolve().parents[2] / "tests" / "scenarios" / ".env.scenario"
)


def load_scenario_env(path: Optional[Path] = None) -> bool:
    """Apply ``tests/scenarios/.env.scenario`` into ``os.environ`` (override=True).

    Returns True when a file was loaded. Call before any ``agent.core.config`` import.
    """
    env_path = Path(path) if path is not None else _SCENARIO_ENV
    if not env_path.is_file():
        return False
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ[key] = value
    return True
