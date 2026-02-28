"""
Quick validation script for Docker deployment configuration.

Run this before or after `docker compose up` to sanity-check that
key environment variables and URLs are aligned between local and
Docker deployments.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = PROJECT_ROOT / ".env"


def load_env_snapshot() -> dict[str, str]:
    """Load a minimal snapshot of the root .env for inspection.

    This does not attempt to fully parse the file like python-dotenv;
    it only reads simple KEY=VALUE lines.
    """
    snapshot: dict[str, str] = {}

    if not ENV_PATH.exists():
        print(f"[WARN] .env file not found at {ENV_PATH}")
        return snapshot

    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        snapshot[key.strip()] = value.strip()

    return snapshot


def check_feature_server(snapshot: dict[str, str]) -> bool:
    """Validate FEATURE_SERVER_URL / FEATURE_SERVER_PORT alignment."""
    ok = True

    fs_url = snapshot.get("FEATURE_SERVER_URL")
    fs_port = snapshot.get("FEATURE_SERVER_PORT")

    if fs_url is None:
        print("[WARN] FEATURE_SERVER_URL not set in .env")
        ok = False
    elif "8001" in fs_url:
        print(
            "[ERROR] FEATURE_SERVER_URL still points to port 8001. "
            "For the current deployment, it should be http://localhost:8002"
        )
        ok = False

    if fs_port is None:
        print("[WARN] FEATURE_SERVER_PORT not set in .env")
        ok = False
    elif fs_port != "8002":
        print(
            f"[ERROR] FEATURE_SERVER_PORT={fs_port!r} but expected '8002' "
            "to match the agent feature server and docker-compose mapping."
        )
        ok = False

    if ok:
        print(
            f"[OK] Feature server configuration looks consistent "
            f"(FEATURE_SERVER_URL={fs_url!r}, FEATURE_SERVER_PORT={fs_port!r})"
        )

    return ok


def check_frontend_urls(snapshot: dict[str, str]) -> bool:
    """Validate public frontend URLs for typical host-based access."""
    ok = True

    api_url = snapshot.get("NEXT_PUBLIC_API_URL")
    ws_url = snapshot.get("NEXT_PUBLIC_WS_URL")

    if not api_url:
        print(
            "[WARN] NEXT_PUBLIC_API_URL is not set in .env. "
            "Default build args in docker-compose will fall back to http://localhost:8000."
        )
    elif "localhost" not in api_url and "127.0.0.1" not in api_url:
        print(
            f"[INFO] NEXT_PUBLIC_API_URL={api_url!r} does not use localhost. "
            "This is fine if you are deploying behind a reverse proxy."
        )

    if not ws_url:
        print(
            "[WARN] NEXT_PUBLIC_WS_URL is not set in .env. "
            "Default build args in docker-compose will fall back to ws://localhost:8000/ws."
        )
    elif "ws://" not in ws_url and "wss://" not in ws_url:
        print(
            f"[ERROR] NEXT_PUBLIC_WS_URL={ws_url!r} does not start with ws:// or wss://."
        )
        ok = False

    if ok:
        print(
            f"[OK] Frontend URLs snapshot: "
            f"NEXT_PUBLIC_API_URL={api_url!r}, NEXT_PUBLIC_WS_URL={ws_url!r}"
        )

    return ok


def _iter_model_files(root: Path) -> Iterable[Path]:
    """Yield model files from supported locations under agent/model_storage."""
    if not root.exists():
        return []

    patterns = [
        "*.pkl",
        "*.h5",
        "*.onnx",
        "*.pt",
        "*.pth",
    ]

    # Root-level models
    for pattern in patterns:
        yield from root.glob(pattern)

    # Known subdirectories used by discovery
    for subdir in ["xgboost", "lightgbm", "random_forest", "lstm", "transformer", "custom"]:
        sub_path = root / subdir
        if not sub_path.exists():
            continue
        for pattern in patterns:
            yield from sub_path.glob(pattern)


def check_model_storage() -> bool:
    """Validate that agent/model_storage contains at least one model file.

    This does not fail the deployment outright but provides a clear warning
    if no models are present where the agent expects to discover them.
    """
    ok = True

    storage_root = PROJECT_ROOT / "agent" / "model_storage"
    if not storage_root.exists():
        print(f"[WARN] Model storage directory not found at {storage_root}")
        return False

    model_files = list(_iter_model_files(storage_root))
    if not model_files:
        print(
            "[WARN] No model files found under agent/model_storage. "
            "Place your trained models (e.g. *.pkl, *.h5, *.onnx) in "
            "agent/model_storage or its xgboost/lightgbm/random_forest/lstm/transformer/custom "
            "subdirectories before starting Docker."
        )
        ok = False
    else:
        print("[OK] Discovered the following model files under agent/model_storage:")
        for path in model_files:
            rel = path.relative_to(PROJECT_ROOT)
            print(f"  - {rel}")

    return ok


def main() -> None:
    print(f"[INFO] Project root: {PROJECT_ROOT}")
    print(f"[INFO] Using .env at: {ENV_PATH}")

    snapshot = load_env_snapshot()
    if not snapshot:
        print(
            "[WARN] Could not load any KEY=VALUE pairs from .env. "
            "Ensure you have created the root .env file from .env.example."
        )

    overall_ok = True

    if not check_feature_server(snapshot):
        overall_ok = False
    if not check_frontend_urls(snapshot):
        overall_ok = False
    if not check_model_storage():
        overall_ok = False

    # Provide a simple exit code / summary for CI or manual use.
    if overall_ok:
        print("[SUCCESS] Docker-related configuration checks passed.")
    else:
        print("[FAIL] One or more Docker configuration checks failed.")


if __name__ == "__main__":
    main()

