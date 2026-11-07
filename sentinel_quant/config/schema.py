"""Configuration schema.

Every setting the bot uses is declared and validated here. Invalid or unsafe
combinations fail at startup, never mid-trading.
"""

from __future__ import annotations

from datetime import date, time
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel_quant.data.timeframes import TIMEFRAME_MS


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

    @field_validator("timeframe")
    @classmethod
    def _known_timeframe(cls, value: str) -> str:
        if value not in TIMEFRAME_MS:
            raise ValueError(f"timeframe must be one of {sorted(TIMEFRAME_MS)}")
        return value


class DataConfig(_Strict):
    """Market data settings. Data always comes from public mainnet endpoints.

    ``exchange.testnet`` governs order routing only: testnet candles are not a
    usable research history, and public endpoints need no credentials.
    """

    history_start: date = date(2021, 1, 1)
    page_limit: int = Field(1000, ge=1, le=1000)
    max_retries: int = Field(5, ge=0, le=20)
    backoff_base_seconds: float = Field(1.0, gt=0, le=60)
    backoff_max_seconds: float = Field(60.0, gt=0, le=600)
    close_grace_seconds: float = Field(2.0, ge=0, le=60)
    poll_retry_seconds: float = Field(10.0, gt=0, le=300)


class BacktestConfig(_Strict):
    """Cost assumptions for simulated fills. Zero costs are refused on purpose.

    Defaults are deliberately pessimistic: the standard Binance spot taker fee with
    no discount, plus an assumed allowance for spread and market impact.
    """

    initial_cash: float = Field(10_000.0, gt=0)
    taker_fee_bps: float = Field(10.0, gt=0, le=100)
    slippage_bps: float = Field(5.0, gt=0, le=100)


class StrategyConfig(_Strict):
    """Placeholder strategy parameters: textbook values, deliberately not tuned."""

    name: Literal["donchian_breakout"] = "donchian_breakout"
    entry_lookback: int = Field(55, ge=2, le=1000)
    exit_lookback: int = Field(20, ge=2, le=1000)
    atr_period: int = Field(14, ge=2, le=1000)
    atr_stop_multiple: float = Field(2.0, gt=0, le=20)


class ValidationConfig(_Strict):
    """Windows for the §6 protocol. Pass thresholds are code constants, not settings."""

    holdout_start: date = date(2025, 7, 1)  # G3: bars from here on stay unseen by default
    train_days: int = Field(730, ge=30)
    test_days: int = Field(180, ge=7)


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
    data: DataConfig = DataConfig()
    backtest: BacktestConfig = BacktestConfig()
    strategy: StrategyConfig = StrategyConfig()
    validation: ValidationConfig = ValidationConfig()
    daily_controls: DailyControls = DailyControls()
    alerts: AlertsConfig = AlertsConfig()
    binary: BinaryControls = BinaryControls()
    data_dir: str = "data"
    runs_dir: str = "runs"
    kill_switch_path: str = "runs/KILL_SWITCH"

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
