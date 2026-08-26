"""Tests for local Colab Google-account rotation on GPU quota."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from scripts.colab.rotate_colab_accounts import (
    Account,
    RotationState,
    classify_colab_failure,
    main,
    mark_quota,
    parse_accounts,
    pick_next_account,
)


def _accounts() -> list[Account]:
    return [
        Account(id="account-1", email="one@gmail.com"),
        Account(id="account-2", email="two@gmail.com"),
        Account(id="account-3", email="three@gmail.com"),
    ]


class TestClassifyColabFailure:
    def test_gpu_usage_limit_is_quota(self) -> None:
        text = "You cannot currently connect to a GPU due to usage limits in Colab."
        assert classify_colab_failure(text) == "quota"

    def test_compute_units_is_quota(self) -> None:
        assert classify_colab_failure("You have used up your compute units") == "quota"

    def test_503_is_capacity_not_rotation(self) -> None:
        assert classify_colab_failure("Colab assign failed (often 503 GPU capacity)") == "capacity"

    def test_auth_paste_flow(self) -> None:
        assert classify_colab_failure("Please authenticate and paste the authorization code") == "auth"

    def test_unrelated_is_other(self) -> None:
        assert classify_colab_failure("Notebook not found") == "other"


class TestPickNextAccount:
    def test_keeps_active_when_gpu_available(self) -> None:
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        state = RotationState(active_id="account-1", quota_until={})
        nxt = pick_next_account(_accounts(), state, now)
        assert nxt.id == "account-1"

    def test_rotates_when_active_has_gpu_quota(self) -> None:
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        until = now + timedelta(hours=12)
        state = RotationState(
            active_id="account-1",
            quota_until={"account-1": until},
        )
        nxt = pick_next_account(_accounts(), state, now)
        assert nxt.id == "account-2"

    def test_skips_quota_cooldown(self) -> None:
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        until = now + timedelta(hours=12)
        state = RotationState(
            active_id="account-1",
            quota_until={"account-1": until, "account-2": until},
        )
        nxt = pick_next_account(_accounts(), state, now)
        assert nxt.id == "account-3"

    def test_all_blocked_picks_soonest_cooldown(self) -> None:
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        state = RotationState(
            active_id="account-1",
            quota_until={
                "account-1": now + timedelta(hours=20),
                "account-2": now + timedelta(hours=2),
                "account-3": now + timedelta(hours=8),
            },
        )
        nxt = pick_next_account(_accounts(), state, now)
        assert nxt.id == "account-2"

    def test_expired_cooldown_does_not_block_active(self) -> None:
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        state = RotationState(
            active_id="account-1",
            quota_until={"account-2": now - timedelta(minutes=1)},
        )
        nxt = pick_next_account(_accounts(), state, now)
        assert nxt.id == "account-1"


class TestMarkQuota:
    def test_sets_cooldown_from_now(self) -> None:
        now = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
        state = RotationState(active_id="account-1", quota_until={})
        updated = mark_quota(state, "account-1", cooldown_hours=24, now=now)
        assert updated.quota_until["account-1"] == now + timedelta(hours=24)


class TestParseAccounts:
    def test_rejects_missing_email(self) -> None:
        with pytest.raises(ValueError):
            parse_accounts({"accounts": [{"id": "a", "email": ""}]})


class TestCli:
    def test_init_status_mark_quota_roundtrip(self, tmp_path: Path) -> None:
        config = tmp_path / "colab_accounts.json"
        state = tmp_path / "colab_accounts_state.json"
        assert main(["--config", str(config), "--state", str(state), "init"]) == 0
        payload = json.loads(config.read_text(encoding="utf-8"))
        payload["accounts"] = [
            {"id": "account-1", "email": "one@gmail.com"},
            {"id": "account-2", "email": "two@gmail.com"},
            {"id": "account-3", "email": "three@gmail.com"},
        ]
        config.write_text(json.dumps(payload), encoding="utf-8")

        assert main(["--config", str(config), "--state", str(state), "use", "one@gmail.com"]) == 0
        next_before = main(
            ["--config", str(config), "--state", str(state), "next", "--format", "email"]
        )
        assert next_before == 0

        rc = main(["--config", str(config), "--state", str(state), "mark-quota"])
        assert rc == 0
        saved = json.loads(state.read_text(encoding="utf-8"))
        assert "account-1" in saved["quota_until"]
        assert saved["active_id"] == "account-2"

        classify_rc = main(
            [
                "classify",
                "--text",
                "You cannot currently connect to a GPU due to usage limits in Colab.",
            ]
        )
        assert classify_rc == 3
