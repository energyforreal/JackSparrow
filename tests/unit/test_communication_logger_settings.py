"""Communication logger reads Pydantic Settings by Python field names."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def mock_comm_settings() -> MagicMock:
    m = MagicMock()
    m.enable_communication_logging = True
    m.communication_sensitive_fields = ["password", "token", "api_key", "secret", "private_key"]
    m.max_log_payload_size = 10240
    m.log_websocket_payloads = True
    return m


class TestAgentCommunicationLoggerSettings:
    def test_enable_communication_logging_field(self, monkeypatch: pytest.MonkeyPatch, mock_comm_settings: MagicMock) -> None:
        import agent.core.communication_logger as cl

        mock_comm_settings.enable_communication_logging = False
        monkeypatch.setattr(cl, "settings", mock_comm_settings)
        mock_get_logger = MagicMock()
        monkeypatch.setattr(cl, "_get_logger", mock_get_logger)
        cl.log_communication(direction="outbound", protocol="websocket", message_type="ping")
        mock_get_logger.assert_not_called()

    def test_communication_sensitive_fields_field(self, monkeypatch: pytest.MonkeyPatch, mock_comm_settings: MagicMock) -> None:
        import agent.core.communication_logger as cl

        mock_comm_settings.communication_sensitive_fields = ["custom_secret"]
        monkeypatch.setattr(cl, "settings", mock_comm_settings)
        out = cl._sanitize_payload({"custom_secret": "x", "ok": 1})
        assert out["custom_secret"] == "***REDACTED***"
        assert out["ok"] == 1

    def test_max_log_payload_size_field(self, monkeypatch: pytest.MonkeyPatch, mock_comm_settings: MagicMock) -> None:
        import agent.core.communication_logger as cl

        mock_comm_settings.max_log_payload_size = 80
        monkeypatch.setattr(cl, "settings", mock_comm_settings)
        out = cl._truncate_payload({"k": "x" * 500})
        assert isinstance(out, dict)
        assert out.get("truncated") is True


class TestBackendCommunicationLoggerSettings:
    def test_enable_communication_logging_field(self, monkeypatch: pytest.MonkeyPatch, mock_comm_settings: MagicMock) -> None:
        import backend.core.communication_logger as cl

        mock_comm_settings.enable_communication_logging = False
        monkeypatch.setattr(cl, "settings", mock_comm_settings)
        mock_get_logger = MagicMock()
        monkeypatch.setattr(cl, "_get_logger", mock_get_logger)
        cl.log_communication(direction="inbound", protocol="websocket", message_type="ping")
        mock_get_logger.assert_not_called()

    def test_communication_sensitive_fields_field(self, monkeypatch: pytest.MonkeyPatch, mock_comm_settings: MagicMock) -> None:
        import backend.core.communication_logger as cl

        mock_comm_settings.communication_sensitive_fields = ["custom_secret"]
        monkeypatch.setattr(cl, "settings", mock_comm_settings)
        out = cl._sanitize_payload({"custom_secret": "x", "ok": 1})
        assert out["custom_secret"] == "***REDACTED***"
        assert out["ok"] == 1

    def test_max_log_payload_size_field(self, monkeypatch: pytest.MonkeyPatch, mock_comm_settings: MagicMock) -> None:
        import backend.core.communication_logger as cl

        mock_comm_settings.max_log_payload_size = 80
        monkeypatch.setattr(cl, "settings", mock_comm_settings)
        out = cl._truncate_payload({"k": "x" * 500})
        assert isinstance(out, dict)
        assert out.get("truncated") is True
