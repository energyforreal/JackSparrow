#!/usr/bin/env python3
"""Rotate among local Google Colab accounts when GPU quota is exhausted.

Does not log into Google, store passwords, or bypass Colab limits. It tracks
which of your configured emails is on a GPU-quota cooldown and prints the next
account to sign into for the Colab CLI OAuth paste flow.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

FailureKind = Literal["quota", "capacity", "auth", "other"]

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_PATH = SCRIPT_DIR / "colab_accounts.json"
DEFAULT_STATE_PATH = SCRIPT_DIR / "colab_accounts_state.json"
EXAMPLE_CONFIG_PATH = SCRIPT_DIR / "colab_accounts.example.json"

QUOTA_NEEDLES = (
    "usage limit",
    "usage limits",
    "gpu quota",
    "quota exceeded",
    "compute units",
    "out of compute",
    "used up your",
    "used up your gpu",
    "cannot currently connect to a gpu",
    "resources are not available because you have used",
    "gpu is not available because",
    "you have exhausted",
)
CAPACITY_NEEDLES = (
    "503",
    "high demand",
    "no backends available",
    "backend unavailable",
    "assign failed",
    "gpu capacity",
    "temporarily unavailable",
    "try again later",
)
AUTH_NEEDLES = (
    "invalid_grant",
    "please authenticate",
    "not authenticated",
    "login required",
    "authorization code",
    "access denied",
    "token.json",
)


@dataclass(frozen=True)
class Account:
    """One Google identity used for Colab."""

    id: str
    email: str


@dataclass
class RotationState:
    """Persisted cooldown and active-account pointer."""

    active_id: str | None
    quota_until: dict[str, datetime]


def utc_now() -> datetime:
    """Return timezone-aware UTC now (overridable in tests via patch)."""

    return datetime.now(timezone.utc)


def classify_colab_failure(text: str) -> FailureKind:
    """Classify Colab CLI / UI error text.

    GPU quota is account-specific and should rotate. Capacity (503 / demand)
    should retry the same account. Auth means re-login for the same email.
    """

    lowered = text.lower()
    if any(needle in lowered for needle in QUOTA_NEEDLES):
        return "quota"
    if any(needle in lowered for needle in AUTH_NEEDLES):
        return "auth"
    if "backend rejected accelerator" in lowered:
        return "other"
    if any(needle in lowered for needle in CAPACITY_NEEDLES):
        return "capacity"
    return "other"


def load_json(path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return raw


def parse_accounts(config: dict[str, Any]) -> list[Account]:
    """Parse the accounts list from config JSON."""

    rows = config.get("accounts")
    if not isinstance(rows, list) or not rows:
        raise ValueError("config.accounts must be a non-empty list")
    accounts: list[Account] = []
    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each account must be an object with id and email")
        account_id = str(row.get("id", "")).strip()
        email = str(row.get("email", "")).strip()
        if not account_id or not email or "@" not in email:
            raise ValueError("each account needs a non-empty id and email")
        if account_id in seen:
            raise ValueError(f"duplicate account id: {account_id}")
        seen.add(account_id)
        accounts.append(Account(id=account_id, email=email))
    return accounts


def parse_cooldown_hours(config: dict[str, Any]) -> float:
    """Hours to keep an account off-rotation after GPU quota."""

    hours = config.get("cooldown_hours", 24)
    try:
        value = float(hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("cooldown_hours must be a number") from exc
    if value <= 0:
        raise ValueError("cooldown_hours must be positive")
    return value


def parse_state(raw: dict[str, Any]) -> RotationState:
    """Parse persisted rotation state."""

    active = raw.get("active_id")
    active_id = str(active).strip() if active else None
    until_raw = raw.get("quota_until", {})
    if until_raw is None:
        until_raw = {}
    if not isinstance(until_raw, dict):
        raise ValueError("state.quota_until must be an object")
    quota_until: dict[str, datetime] = {}
    for key, value in until_raw.items():
        quota_until[str(key)] = datetime.fromisoformat(str(value))
        if quota_until[str(key)].tzinfo is None:
            quota_until[str(key)] = quota_until[str(key)].replace(tzinfo=timezone.utc)
    return RotationState(active_id=active_id, quota_until=quota_until)


def dump_state(state: RotationState) -> dict[str, Any]:
    """Serialize rotation state to JSON-safe dict."""

    return {
        "active_id": state.active_id,
        "quota_until": {
            key: value.astimezone(timezone.utc).isoformat()
            for key, value in state.quota_until.items()
        },
    }


def is_cooling_down(state: RotationState, account_id: str, now: datetime) -> bool:
    """True if this account is still inside a GPU-quota cooldown."""

    until = state.quota_until.get(account_id)
    return until is not None and until > now


def available_accounts(
    accounts: list[Account],
    state: RotationState,
    now: datetime,
) -> list[Account]:
    """Accounts that are not in GPU-quota cooldown."""

    return [account for account in accounts if not is_cooling_down(state, account.id, now)]


def pick_next_account(
    accounts: list[Account],
    state: RotationState,
    now: datetime,
) -> Account:
    """Pick which Google account to use for Colab.

    Keep the active account while it is not in GPU-quota cooldown. Otherwise
    take the next available id, wrapping around. If every account is cooling
    down, return the one whose cooldown ends soonest (still report blocked).
    """

    if not accounts:
        raise ValueError("no accounts configured")
    ids = [account.id for account in accounts]
    if state.active_id in ids and not is_cooling_down(state, state.active_id, now):
        return account_by_id(accounts, state.active_id)
    start = 0
    if state.active_id in ids:
        start = (ids.index(state.active_id) + 1) % len(ids)
    ordered = accounts[start:] + accounts[:start]
    open_accounts = [
        account for account in ordered if not is_cooling_down(state, account.id, now)
    ]
    if open_accounts:
        return open_accounts[0]
    return min(accounts, key=lambda account: state.quota_until.get(account.id, now))


def mark_quota(
    state: RotationState,
    account_id: str,
    cooldown_hours: float,
    now: datetime,
) -> RotationState:
    """Mark an account as GPU-quota exhausted until now + cooldown."""

    until = now + timedelta(hours=cooldown_hours)
    quota_until = dict(state.quota_until)
    quota_until[account_id] = until
    return RotationState(active_id=account_id, quota_until=quota_until)


def resolve_account_id(accounts: list[Account], needle: str) -> str:
    """Resolve id or email to a configured account id."""

    lowered = needle.strip().lower()
    for account in accounts:
        if account.id.lower() == lowered or account.email.lower() == lowered:
            return account.id
    raise ValueError(f"unknown account: {needle}")


def account_by_id(accounts: list[Account], account_id: str) -> Account:
    """Return the account with this id."""

    for account in accounts:
        if account.id == account_id:
            return account
    raise ValueError(f"unknown account id: {account_id}")


def format_status(
    accounts: list[Account],
    state: RotationState,
    now: datetime,
    next_account: Account,
    all_blocked: bool,
) -> str:
    """Human-readable status for the terminal."""

    lines = ["Colab Google account rotation"]
    for account in accounts:
        until = state.quota_until.get(account.id)
        marker = "active" if state.active_id == account.id else "idle"
        if until is not None and until > now:
            remaining = until - now
            hours = remaining.total_seconds() / 3600.0
            marker = f"gpu-quota cooldown until {until.isoformat()} ({hours:.1f}h left)"
        elif until is not None:
            marker = "ready (cooldown expired)"
        lines.append(f"  {account.id}: {account.email}  [{marker}]")
    if all_blocked:
        until = state.quota_until.get(next_account.id)
        until_s = until.isoformat() if until else "unknown"
        lines.append(
            f"All three accounts are in GPU-quota cooldown. "
            f"Earliest retry: {next_account.email} at {until_s}"
        )
    else:
        lines.append(f"Next account to use: {next_account.id} ({next_account.email})")
        lines.append(
            "Sign into that Google account, then authenticate Colab CLI with:"
        )
        lines.append('  wsl -d Ubuntu-24.04 -- bash -lc "colab sessions"')
        lines.append("Paste the OAuth code from the Google URL into WSL.")
    return "\n".join(lines)


def cmd_init(config_path: Path) -> int:
    """Create a local accounts file from the example if missing."""

    if config_path.exists():
        print(f"Already exists: {config_path}")
        return 0
    if not EXAMPLE_CONFIG_PATH.is_file():
        raise FileNotFoundError(EXAMPLE_CONFIG_PATH)
    config_path.write_text(EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"Wrote {config_path}")
    print("Edit the three emails, then run: python scripts/colab/rotate_colab_accounts.py status")
    return 0


def _load_bundle(
    config_path: Path,
    state_path: Path,
) -> tuple[list[Account], float, RotationState]:
    config = load_json(config_path)
    if not config:
        raise FileNotFoundError(
            f"Missing {config_path}. Run: python scripts/colab/rotate_colab_accounts.py init"
        )
    accounts = parse_accounts(config)
    cooldown = parse_cooldown_hours(config)
    state = parse_state(load_json(state_path))
    return accounts, cooldown, state


def cmd_status(config_path: Path, state_path: Path) -> int:
    """Print cooldown status and the next account."""

    accounts, _, state = _load_bundle(config_path, state_path)
    now = utc_now()
    nxt = pick_next_account(accounts, state, now)
    blocked = not available_accounts(accounts, state, now)
    print(format_status(accounts, state, now, nxt, blocked))
    return 1 if blocked else 0


def cmd_next(config_path: Path, state_path: Path, fmt: str) -> int:
    """Print the next account to sign into."""

    accounts, _, state = _load_bundle(config_path, state_path)
    now = utc_now()
    nxt = pick_next_account(accounts, state, now)
    blocked = not available_accounts(accounts, state, now)
    if fmt == "email":
        print(nxt.email)
    elif fmt == "id":
        print(nxt.id)
    elif fmt == "json":
        payload = {
            "id": nxt.id,
            "email": nxt.email,
            "all_blocked": blocked,
            "quota_until": (
                state.quota_until[nxt.id].astimezone(timezone.utc).isoformat()
                if nxt.id in state.quota_until
                else None
            ),
        }
        print(json.dumps(payload))
    else:
        print(format_status(accounts, state, now, nxt, blocked))
    return 1 if blocked else 0


def cmd_use(config_path: Path, state_path: Path, needle: str) -> int:
    """Record which account is currently signed into Colab CLI."""

    accounts, _, state = _load_bundle(config_path, state_path)
    account_id = resolve_account_id(accounts, needle)
    state.active_id = account_id
    state_path.write_text(json.dumps(dump_state(state), indent=2) + "\n", encoding="utf-8")
    account = account_by_id(accounts, account_id)
    print(f"Active Colab account: {account.id} ({account.email})")
    return 0


def cmd_mark_quota(
    config_path: Path,
    state_path: Path,
    needle: str | None,
) -> int:
    """Mark an account as GPU-quota exhausted and print the next one."""

    accounts, cooldown, state = _load_bundle(config_path, state_path)
    if needle:
        account_id = resolve_account_id(accounts, needle)
    elif state.active_id:
        account_id = resolve_account_id(accounts, state.active_id)
    else:
        account_id = accounts[0].id
    now = utc_now()
    state = mark_quota(state, account_id, cooldown, now)
    exhausted = account_by_id(accounts, account_id)
    nxt = pick_next_account(accounts, state, now)
    state.active_id = nxt.id
    state_path.write_text(json.dumps(dump_state(state), indent=2) + "\n", encoding="utf-8")
    blocked = not available_accounts(accounts, state, now)
    print(
        f"Marked GPU quota exhausted: {exhausted.id} ({exhausted.email}) "
        f"until {state.quota_until[account_id].isoformat()}"
    )
    print(format_status(accounts, state, now, nxt, blocked))
    return 1 if blocked else 0


def cmd_clear(config_path: Path, state_path: Path, needle: str) -> int:
    """Clear GPU-quota cooldown for one account."""

    accounts, _, state = _load_bundle(config_path, state_path)
    account_id = resolve_account_id(accounts, needle)
    state.quota_until.pop(account_id, None)
    state_path.write_text(json.dumps(dump_state(state), indent=2) + "\n", encoding="utf-8")
    account = account_by_id(accounts, account_id)
    print(f"Cleared GPU-quota cooldown for {account.id} ({account.email})")
    return 0


def cmd_classify(text: str) -> int:
    """Print failure kind for Colab error text (quota/capacity/auth/other)."""

    kind = classify_colab_failure(text)
    print(kind)
    return 0 if kind != "quota" else 3


def build_parser() -> argparse.ArgumentParser:
    """CLI parser for the rotator."""

    parser = argparse.ArgumentParser(
        description="Shuffle among 3 Google accounts when Colab GPU quota is exhausted.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help="Local accounts JSON (gitignored)",
    )
    parser.add_argument(
        "--state",
        type=Path,
        default=DEFAULT_STATE_PATH,
        help="Local cooldown state JSON (gitignored)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init", help="Create colab_accounts.json from the example")
    sub.add_parser("status", help="Show cooldowns and the next account")
    nxt = sub.add_parser("next", help="Print the next Google account to sign in as")
    nxt.add_argument("--format", choices=("human", "email", "id", "json"), default="human")
    use = sub.add_parser("use", help="Record the account currently signed into Colab CLI")
    use.add_argument("account", help="Account id or email")
    mark = sub.add_parser(
        "mark-quota",
        help="Mark GPU quota exhausted and rotate to the next account",
    )
    mark.add_argument("account", nargs="?", help="Account id or email (default: active)")
    clear = sub.add_parser("clear", help="Clear GPU-quota cooldown for an account")
    clear.add_argument("account", help="Account id or email")
    classify = sub.add_parser("classify", help="Classify Colab error text")
    classify.add_argument("--text", default="", help="Error text (or stdin if omitted)")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point."""

    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            return cmd_init(args.config)
        if args.command == "status":
            return cmd_status(args.config, args.state)
        if args.command == "next":
            return cmd_next(args.config, args.state, args.format)
        if args.command == "use":
            return cmd_use(args.config, args.state, args.account)
        if args.command == "mark-quota":
            return cmd_mark_quota(args.config, args.state, args.account)
        if args.command == "clear":
            return cmd_clear(args.config, args.state, args.account)
        if args.command == "classify":
            text = args.text or sys.stdin.read()
            return cmd_classify(text)
    except (OSError, ValueError) as exc:
        print(f"rotate_colab_accounts: {exc}", file=sys.stderr)
        return 2
    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
