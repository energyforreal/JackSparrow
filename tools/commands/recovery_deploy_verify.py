#!/usr/bin/env python3
"""Post-deploy verification for recovery plan: env, containers, git commit."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

ENV_KEYS = [
    "TRADE_LIFECYCLE_ENABLED",
    "TRADE_LIFECYCLE_LOG_ONLY",
    "TRADE_MFE_MAE_AT_CLOSE_ENABLED",
    "JACKSPARROW_V43_MIN_EDGE_COST_RATIO",
    "V15_ADX_REGIME_FILTER_ENABLED",
    "COGNITION_SELECTOR_ENABLED",
    "COGNITION_SCORER_ENABLED",
    "COGNITION_TEMPORAL_AUTHORITY_ENABLED",
    "GIT_COMMIT",
]


def _git_head() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def _docker_compose_ps() -> str:
    try:
        return subprocess.check_output(
            ["docker", "compose", "ps"],
            cwd=ROOT,
            text=True,
            stderr=subprocess.STDOUT,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        return str(exc)


def _agent_env() -> dict[str, str | None]:
    result: dict[str, str | None] = {}
    for key in ENV_KEYS:
        try:
            out = subprocess.check_output(
                ["docker", "exec", "jacksparrow-agent", "printenv", key],
                cwd=ROOT,
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
            result[key] = out or None
        except subprocess.CalledProcessError:
            result[key] = None
    return result


def _env_hash(env: dict[str, str | None]) -> str:
    payload = json.dumps(env, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovery deploy verification")
    parser.add_argument(
        "--out",
        default=None,
        help="Output JSON path (default logs/deployments/YYYY-MM-DD.json)",
    )
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    env = _agent_env()
    report = {
        "generated_at": now.isoformat(),
        "repo_git_commit": _git_head(),
        "container_env": env,
        "env_hash": _env_hash(env),
        "docker_compose_ps": _docker_compose_ps(),
        "checks": {
            "tle_log_only": env.get("TRADE_LIFECYCLE_LOG_ONLY") == "true",
            "git_commit_set": bool(env.get("GIT_COMMIT") and env["GIT_COMMIT"] != "unknown"),
            "cognition_temporal_off": env.get("COGNITION_TEMPORAL_AUTHORITY_ENABLED") != "true",
        },
    }
    text = json.dumps(report, indent=2)
    print(text)

    out_path = Path(args.out) if args.out else ROOT / "logs" / "deployments" / f"{now.date().isoformat()}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    print(f"Wrote {out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
