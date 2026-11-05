import pytest

from sentinel_quant.config import Secrets
from sentinel_quant.ops.logging import REDACTED, configure_logging, get_logger


def test_secrets_are_redacted(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(["sk-live-SUPERSECRET"])
    get_logger().info(
        "connect", detail="using key sk-live-SUPERSECRET", nested={"k": "sk-live-SUPERSECRET"}
    )
    out = capsys.readouterr().out
    assert "SUPERSECRET" not in out
    assert REDACTED in out


def test_secrets_load_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SQ_EXCHANGE_API_KEY", "key-123456")
    monkeypatch.setenv("SQ_EXCHANGE_API_SECRET", "sec-123456")
    s = Secrets(_env_file=None)
    assert s.has_exchange_keys()
    assert "key-123456" not in repr(s)
    assert set(s.all_values()) == {"key-123456", "sec-123456"}
