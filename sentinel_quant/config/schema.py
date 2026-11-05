"""Configuration schema.

Every setting the bot uses is declared and validated here. Invalid or unsafe
combinations fail at startup, never mid-trading.
"""

from __future__ import annotations

from datetime import time
from enum import StrEnum
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TradingMode(StrEnum):
    """How orders are handled. LIVE is never the default."""

    SIM = "sim"  # internal simulator, no external connection
    PAPER = "paper"  # exchange testnet / broker paper account
    LIVE = "live"  # real money: requires explicit approval (see AppConfig)


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DailyControls(_Strict):
    """User-configurable daily limits (MASTER_PLAN §1.2).

    The profit lock is a stopping rule: once reached, no new entries are opened.
    The system must never increase size or trade more to reach it.
    """

    risk_per_trade_pct: float = Field(0.5, gt=0, le=2.0)
    max_daily_loss_pct: float = Field(2.0, gt=0, le=10.0)
    max_daily_trades: int = Field(10, ge=1, le=200)
    max_open_positions: int = Field(3, ge=1, le=50)
    max_total_exposure_pct: float = Field(50.0, gt=0, le=100.0)
    max_consecutive_losses: int = Field(4, ge=1, le=50)
    daily_profit_lock_pct: float | None = Field(3.0, gt=0, le=50.0)
    trading_window_utc: tuple[time, time] = (time(0, 0), time(23, 59))
    reset_time_utc: time = time(0, 0)

    @model_validator(mode="after")
    def _check_consistency(self) -> Self:
        if self.risk_per_trade_pct > self.max_daily_loss_pct:
            raise ValueError("risk_per_trade_pct cannot exceed max_daily_loss_pct")
        start, end = self.trading_window_utc
        if start >= end:
            raise ValueError("trading_window_utc start must be before end")
        return self

    @property
    def losing_trades_before_daily_stop(self) -> int:
        """How many full-risk losses fit inside the daily loss limit."""
        return int(self.max_daily_loss_pct // self.risk_per_trade_pct)


class ExchangeConfig(_Strict):
    name: str = "binance"
    testnet: bool = True
    symbols: tuple[str, ...] = ("BTC/USDT", "ETH/USDT")
    timeframe: str = "1h"


class AlertsConfig(_Strict):
    telegram_enabled: bool = False
    daily_report_utc: time = time(0, 5)


class BinaryControls(_Strict):
    """Track B limits. Kept separate from Track M by design."""

    enabled: bool = False
    max_stake_per_contract: float = Field(25.0, gt=0)
    max_daily_exposure: float = Field(150.0, gt=0)
    max_daily_loss: float = Field(50.0, gt=0)
    max_consecutive_losses: int = Field(3, ge=1)
    max_simultaneous_contracts: int = Field(2, ge=1)
    min_payout_pct: float = Field(80.0, gt=0, le=100.0)
    allowed_expiries: tuple[str, ...] = ("15m", "1h")
    martingale_allowed: bool = False

    @model_validator(mode="after")
    def _no_martingale(self) -> Self:
        if self.martingale_allowed:
            raise ValueError("martingale / loss-recovery staking is permanently prohibited")
        if self.max_stake_per_contract > self.max_daily_loss:
            raise ValueError("max_stake_per_contract cannot exceed max_daily_loss")
        return self


class AppConfig(_Strict):
    mode: TradingMode = TradingMode.SIM
    live_trading_approved: bool = False
    exchange: ExchangeConfig = ExchangeConfig()
    daily_controls: DailyControls = DailyControls()
    alerts: AlertsConfig = AlertsConfig()
    binary: BinaryControls = BinaryControls()
    data_dir: str = "data"

    @model_validator(mode="after")
    def _live_guard(self) -> Self:
        if self.mode is TradingMode.LIVE:
            if not self.live_trading_approved:
                raise ValueError(
                    "mode=live requires live_trading_approved=true (explicit user approval)"
                )
            if self.exchange.testnet:
                raise ValueError("mode=live cannot use a testnet exchange")
        if self.mode is TradingMode.PAPER and not self.exchange.testnet:
            raise ValueError("mode=paper must use exchange.testnet=true")
        return self
