"""Validated configuration and secrets loading."""

from sentinel_quant.config.loader import ConfigError, load_config
from sentinel_quant.config.schema import (
    AppConfig,
    BinaryControls,
    DailyControls,
    DataConfig,
    ExchangeConfig,
    TradingMode,
)
from sentinel_quant.config.secrets import Secrets

__all__ = [
    "AppConfig",
    "BinaryControls",
    "ConfigError",
    "DailyControls",
    "DataConfig",
    "ExchangeConfig",
    "Secrets",
    "TradingMode",
    "load_config",
]
