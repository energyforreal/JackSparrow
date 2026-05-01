#!/usr/bin/env python3
"""Run the trading agent (same entrypoint as ``python -m agent.core.intelligent_agent``)."""

from __future__ import annotations

import asyncio

from agent.core.intelligent_agent import main


if __name__ == "__main__":
    asyncio.run(main())
