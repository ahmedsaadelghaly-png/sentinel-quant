"""Validated configuration and secrets loading."""

from sentinel_quant.config.loader import ConfigError, load_config
from sentinel_quant.config.schema import (
    AppConfig,
    BacktestConfig,
    BinaryControls,
    DailyControls,
    DataConfig,
    ExchangeConfig,
    StrategyConfig,
    TradingMode,
)
from sentinel_quant.config.secrets import Secrets

__all__ = [
    "AppConfig",
    "BacktestConfig",
    "BinaryControls",
    "ConfigError",
    "DailyControls",
    "DataConfig",
    "ExchangeConfig",
    "Secrets",
    "StrategyConfig",
    "TradingMode",
    "load_config",
]
