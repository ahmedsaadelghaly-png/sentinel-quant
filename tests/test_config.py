from pathlib import Path

import pytest
from pydantic import ValidationError

from sentinel_quant.cli import main
from sentinel_quant.config import (
    AppConfig,
    BinaryControls,
    ConfigError,
    DailyControls,
    ExchangeConfig,
    TradingMode,
    load_config,
)

ROOT = Path(__file__).resolve().parents[1]


def test_default_config_is_valid_and_safe() -> None:
    cfg = load_config(ROOT / "configs/default.yaml")
    assert cfg.mode is TradingMode.SIM
    assert cfg.live_trading_approved is False
    assert cfg.exchange.testnet is True
    assert cfg.binary.enabled is False
    assert cfg.daily_controls.losing_trades_before_daily_stop == 4


def test_code_defaults_are_safe() -> None:
    cfg = AppConfig()
    assert cfg.mode is TradingMode.SIM
    assert cfg.binary.martingale_allowed is False


def test_live_requires_explicit_approval() -> None:
    with pytest.raises(ValidationError, match="live_trading_approved"):
        AppConfig(mode=TradingMode.LIVE, exchange=ExchangeConfig(testnet=False))


def test_live_cannot_use_testnet() -> None:
    with pytest.raises(ValidationError, match="testnet"):
        AppConfig(mode=TradingMode.LIVE, live_trading_approved=True)


def test_paper_must_use_testnet() -> None:
    with pytest.raises(ValidationError, match="testnet"):
        AppConfig(mode=TradingMode.PAPER, exchange=ExchangeConfig(testnet=False))


def test_risk_per_trade_cannot_exceed_daily_loss() -> None:
    with pytest.raises(ValidationError):
        DailyControls(risk_per_trade_pct=2.0, max_daily_loss_pct=1.0)


@pytest.mark.parametrize("field,value", [("risk_per_trade_pct", 5.0), ("max_daily_loss_pct", 25)])
def test_hard_caps(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        DailyControls(**{field: value})


def test_martingale_is_prohibited() -> None:
    with pytest.raises(ValidationError, match="martingale"):
        BinaryControls(martingale_allowed=True)


def test_unknown_keys_rejected(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("mode: sim\ntypo_field: 1\n")
    with pytest.raises(ValidationError):
        load_config(p)


def test_secrets_in_config_rejected(tmp_path: Path) -> None:
    p = tmp_path / "c.yaml"
    p.write_text("exchange:\n  api_key: abc123\n")
    with pytest.raises(ConfigError, match="secret"):
        load_config(p)


def test_cli_check_config(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-config", "--config", str(ROOT / "configs/default.yaml")]) == 0
    assert "config_ok" in capsys.readouterr().out


def test_cli_bad_config(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("mode: live\n")
    assert main(["check-config", "--config", str(p)]) == 1
