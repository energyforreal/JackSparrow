#!/usr/bin/env python3
"""Smoke checks for v15-related HTTP endpoints (backend must be up)."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request


def _get(url: str, timeout: float) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.getcode(), resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:8000", help="Backend base URL")
    ap.add_argument("--timeout", type=float, default=10.0)
    args = ap.parse_args()
    base = args.base.rstrip("/")
    checks = [
        f"{base}/api/v1/health",
        f"{base}/api/v1/models/status",
        f"{base}/api/v1/signal/edge-history?symbol=BTCUSD&limit=5",
    ]
    failed = False
    for url in checks:
        code, body = _get(url, args.timeout)
        ok = 200 <= code < 300
        print(f"{code} {url}")
        if not ok:
            failed = True
            print(body[:500], file=sys.stderr)
            continue
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            continue
        if "health" in url and isinstance(data, dict):
            ml = data.get("ml_models")
            if ml is not None:
                print("  ml_models:", json.dumps(ml)[:200])
        if "models/status" in url and isinstance(data, dict):
            print("  model_format:", data.get("model_format"))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
