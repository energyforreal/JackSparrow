"""Ensure Windows consoles use UTF-8 to avoid encoding crashes."""

from __future__ import annotations

import os
import sys


def configure_utf8_stdio() -> None:
    """Reconfigure stdout/stderr to UTF-8 on Windows."""
    if os.name != "nt":
        return

    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream and hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass
