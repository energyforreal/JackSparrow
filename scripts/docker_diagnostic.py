#!/usr/bin/env python3
"""
Docker deployment diagnostic script.

Verifies (from the host and running containers):
- .env loading and critical configuration
- Trading mode safety (paper vs live)
- ML model discovery and loading
- Backend/agent container environment
- Frontend WebSocket URL configuration
- CORS and backend WebSocket readiness
"""

import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cmd(cmd: list[str], capture: bool = True) -> tuple[int, str]:
    """Run command and return (exit_code, output)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            capture_output=capture,
            text=True,
            timeout=30,
        )
        out = (result.stdout or "") + (result.stderr or "")
        return result.returncode, out
    except subprocess.TimeoutExpired:
        return -1, "Timeout"
    except Exception as e:
        return -1, str(e)


def check_env_file() -> tuple[bool, str, str]:
    """Verify .env exists and has required vars, return (ok, msg, content)."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return False, ".env file not found at project root", ""
    required = [
        "NEXT_PUBLIC_WS_URL",
        "NEXT_PUBLIC_API_URL",
        "DELTA_EXCHANGE_API_KEY",
        "DELTA_EXCHANGE_API_SECRET",
    ]
    missing = []
    with open(env_path, encoding="utf-8") as f:
        content = f.read()
    for var in required:
        found = False
        for line in content.splitlines():
            if line.strip().startswith(f"{var}="):
                val = line.split("=", 1)[1].strip().strip("'\"")
                if val and val.lower() not in ("changeme", ""):
                    found = True
                break
        if not found:
            missing.append(var)
    if missing:
        return False, f"Missing or empty in .env: {', '.join(missing)}", content
    return True, "OK", content


def _get_env_value_from_content(content: str, name: str) -> str | None:
    """Best-effort extraction of a single env value from raw .env content."""
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith(f"{name}="):
            return stripped.split("=", 1)[1].strip().strip("'\"")
    return None


def check_trading_mode(env_content: str) -> tuple[bool, str]:
    """Check PAPER_TRADING_MODE / TRADING_MODE safety in .env for Docker deployments."""
    paper_mode = (_get_env_value_from_content(env_content, "PAPER_TRADING_MODE") or "").lower()
    trading_mode = (_get_env_value_from_content(env_content, "TRADING_MODE") or "").lower()

    # Safe defaults: explicitly paper, or unset (fall back to agent-side validator)
    if trading_mode in ("", "paper") and paper_mode in ("", "true", "1", "yes"):
        return True, "Configured for PAPER trading (safe defaults)"

    if trading_mode == "live" or paper_mode in ("false", "0", "no"):
        return False, (
            "Live trading configuration detected in .env "
            "(PAPER_TRADING_MODE / TRADING_MODE). "
            "Verify this host is approved for live trading before deploying Docker."
        )

    # Anything else is ambiguous but not clearly live – warn
    return False, (
        f"Ambiguous trading settings in .env "
        f"(PAPER_TRADING_MODE={paper_mode or 'unset'}, TRADING_MODE={trading_mode or 'unset'}). "
        "For Docker paper trading, prefer PAPER_TRADING_MODE=true and TRADING_MODE=paper."
    )


def check_container_env(service: str, vars_to_check: list[str]) -> tuple[bool, str]:
    """Check env vars inside a running container."""
    code, out = run_cmd(
        ["docker", "compose", "exec", "-T", service, "printenv"],
        capture=True,
    )
    if code != 0:
        return False, f"Container not running or exec failed: {out[:200]}"
    for var in vars_to_check:
        if f"{var}=" not in out or f"{var}=\n" in out:
            return False, f"{var} not set or empty in {service}"
    return True, "OK"


def check_agent_models() -> tuple[bool, str]:
    """Check if agent has models in model_storage."""
    model_dir = PROJECT_ROOT / "agent" / "model_storage"
    if not model_dir.exists():
        return False, f"model_storage dir not found: {model_dir}"
    files = list(model_dir.rglob("*"))
    model_files = [f for f in files if f.is_file() and f.suffix in (".pkl", ".json", ".joblib", ".bin")]
    if not model_files:
        return False, f"No model files (.pkl, .json, .joblib, .bin) in {model_dir}"
    return True, f"Found {len(model_files)} model file(s)"


def check_host_directories() -> tuple[bool, str]:
    """Verify that host directories for bind mounts exist and are writable."""
    required_dirs = [
        PROJECT_ROOT / "logs" / "backend",
        PROJECT_ROOT / "logs" / "agent",
        PROJECT_ROOT / "logs" / "frontend",
        PROJECT_ROOT / "agent" / "model_storage",
    ]
    problems: list[str] = []
    for path in required_dirs:
        if not path.exists():
            problems.append(f"{path} (missing)")
            continue
        if not os.access(path, os.W_OK):
            problems.append(f"{path} (not writable)")
    if problems:
        return False, "Issues with host directories: " + "; ".join(problems)
    return True, "All required host directories exist and are writable"


def main() -> None:
    print("=" * 60)
    print("Docker Deployment Diagnostic")
    print("=" * 60)

    # 1. .env file
    ok, msg, env_content = check_env_file()
    print(f"\n1. .env file: {'OK' if ok else 'FAIL'}")
    print(f"   {msg}")

    # 1b. Trading mode safety
    if env_content:
        ok_trade, msg_trade = check_trading_mode(env_content)
    else:
        ok_trade, msg_trade = False, ".env not loaded – cannot determine trading mode"
    print(f"\n1b. Trading mode safety: {'OK' if ok_trade else 'WARN'}")
    print(f"   {msg_trade}")

    # 1c. Host directories for bind mounts
    ok_dirs, msg_dirs = check_host_directories()
    print(f"\n1c. Host directories (logs/, agent/model_storage/): {'OK' if ok_dirs else 'WARN'}")
    print(f"   {msg_dirs}")

    # 2. Backend env (CORS, Delta, etc.) – requires running containers
    ok, msg = check_container_env(
        "backend",
        ["CORS_ORIGINS", "DELTA_EXCHANGE_API_KEY", "FEATURE_SERVER_URL"],
    )
    print(f"\n2. Backend container env: {'OK' if ok else 'FAIL'}")
    print(f"   {msg}")

    # 3. Agent env (Delta, MODEL_DIR)
    ok, msg = check_container_env(
        "agent",
        ["DELTA_EXCHANGE_API_KEY", "MODEL_DIR", "FEATURE_SERVER_PORT"],
    )
    print(f"\n3. Agent container env: {'OK' if ok else 'FAIL'}")
    print(f"   {msg}")

    # 4. Model storage
    ok, msg = check_agent_models()
    print(f"\n4. ML models in model_storage: {'OK' if ok else 'WARN'}")
    print(f"   {msg}")

    # 5. Frontend build args (from docker-compose config)
    code, out = run_cmd(
        ["docker", "compose", "config", "--format", "json"],
        capture=True,
    )
    if code == 0 and "NEXT_PUBLIC_WS_URL" in out:
        print("\n5. Frontend build config: OK (NEXT_PUBLIC_WS_URL in build args)")
    else:
        print("\n5. Frontend build config: Check docker compose config")

    # 6. CORS includes 127.0.0.1
    code, out = run_cmd(
        ["docker", "compose", "exec", "-T", "backend", "printenv", "CORS_ORIGINS"],
        capture=True,
    )
    if code == 0 and "127.0.0.1" in out:
        print("\n6. CORS includes 127.0.0.1: OK")
    elif code == 0:
        print("\n6. CORS includes 127.0.0.1: WARN - add http://127.0.0.1:3000 to CORS_ORIGINS")
    else:
        print("\n6. CORS check: Skip (backend not running)")

    print("\n" + "=" * 60)
    print("Recommendations:")
    print("- Ensure .env has NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws")
    print("- For Docker paper trading, set PAPER_TRADING_MODE=true and TRADING_MODE=paper")
    print("- Ensure CORS_ORIGINS includes http://127.0.0.1:3000 for WebSocket")
    print("- Rebuild frontend after .env changes: docker compose build frontend --no-cache")
    print("- Place ML models in agent/model_storage/ (xgboost/, etc.)")
    print("- Create logs/backend, logs/agent, logs/frontend before first docker compose up")
    print("=" * 60)


if __name__ == "__main__":
    main()
