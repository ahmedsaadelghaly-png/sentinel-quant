"""Wires the trading service together. No path here can reach a live exchange."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sentinel_quant.backtest.models import CostModel
from sentinel_quant.config.schema import AppConfig, DailyControls, TradingMode
from sentinel_quant.config.secrets import Secrets
from sentinel_quant.data.client import MarketDataClient
from sentinel_quant.data.live import ClosedCandlePoller, to_candle
from sentinel_quant.data.timeframes import closed_cutoff_ms, timeframe_ms
from sentinel_quant.execution.adapter import ExecutionError
from sentinel_quant.execution.loop import Notifier, TradingLoop
from sentinel_quant.execution.sim import SimAdapter, SimState
from sentinel_quant.execution.testnet import TestnetAdapter, build_testnet_exchange
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.ops.report import build_daily_report, day_to_report, write_report
from sentinel_quant.risk.engine import RiskEngine, RiskState
from sentinel_quant.risk.kill_switch import KillSwitch
from sentinel_quant.strategies.base import SizedStrategy
from sentinel_quant.strategies.donchian import DonchianBreakout


def ledger_path(cfg: AppConfig) -> Path:
    """Sim and paper never share a book."""
    return Path(cfg.runs_dir) / f"ledger-{cfg.mode.value}.sqlite"


def stop_path(cfg: AppConfig) -> Path:
    return Path(cfg.runs_dir) / f"STOP-{cfg.mode.value}"


def pid_path(cfg: AppConfig) -> Path:
    return Path(cfg.runs_dir) / f"service-{cfg.mode.value}.pid"


@dataclass
class Service:
    loop: TradingLoop
    poller: ClosedCandlePoller
    client: MarketDataClient
    ledger: Ledger


def _ms_of_day(cfg: AppConfig) -> int:
    t = cfg.alerts.daily_report_utc
    return (t.hour * 3600 + t.minute * 60) * 1000


def build_service(
    cfg: AppConfig,
    secrets: Secrets,
    client: MarketDataClient,
    notifier: Notifier,
    exchange: Any = None,
) -> Service:
    if cfg.mode is TradingMode.LIVE:
        raise ExecutionError("live trading is not implemented: no strategy has passed gates G1-G8")
    client.validate(cfg.exchange.symbols, cfg.exchange.timeframe)
    tf_ms = timeframe_ms(cfg.exchange.timeframe)
    grace_ms = int(cfg.data.close_grace_seconds * 1000)
    ledger = Ledger(ledger_path(cfg), cfg.backtest.initial_cash)
    switch = KillSwitch(cfg.kill_switch_path)

    saved_risk = ledger.get_state("risk")
    state = RiskState.model_validate(saved_risk) if saved_risk else None
    risk = RiskEngine(cfg.daily_controls, switch, state)

    signal_strategy = DonchianBreakout(cfg.strategy)
    strategy = SizedStrategy(signal_strategy, risk)
    marks: dict[str, float] = {}
    saved_adapter = ledger.get_state("adapter")
    adapter: SimAdapter | TestnetAdapter
    if cfg.mode is TradingMode.SIM:
        restored = SimState.model_validate(saved_adapter) if saved_adapter else None
        costs = CostModel.from_config(cfg.backtest)
        adapter = SimAdapter(costs, cfg.backtest.initial_cash, restored)
    else:
        venue = exchange if exchange is not None else build_testnet_exchange(cfg, secrets)
        adapter = TestnetAdapter(venue, cfg.exchange.symbols, marks, saved_adapter)

    def save_adapter() -> object:
        if isinstance(adapter, SimAdapter):
            return adapter.to_state().model_dump(mode="json")
        return adapter.to_state()

    def daily_report(now_ms: int) -> None:
        day = day_to_report(now_ms, _ms_of_day(cfg))
        if day is None or ledger.get_state("last_report") == day.isoformat():
            return
        report = build_daily_report(ledger, day, risk.limits)
        write_report(report, cfg.runs_dir)
        ledger.set_state({"last_report": day.isoformat()})
        notifier.send("info", report.text)

    loop = TradingLoop(
        mode=cfg.mode.value,
        timeframe=cfg.exchange.timeframe,
        strategy=strategy,
        risk=risk,
        adapter=adapter,
        ledger=ledger,
        kill_switch=switch,
        notifier=notifier,
        save_adapter=save_adapter,
        on_cycle=daily_report,
    )
    if isinstance(adapter, TestnetAdapter):
        adapter.bind_marks(loop.marks)

    now_ms = client.server_time_ms()
    cutoff = closed_cutoff_ms(now_ms, tf_ms, grace_ms)
    start_after: dict[str, int] = {}
    last_bars = loop.last_bars
    for symbol in cfg.exchange.symbols:
        anchor = last_bars.get(symbol, cutoff - tf_ms)
        since = anchor - signal_strategy.warmup_bars * tf_ms
        rows = client.fetch_ohlcv(symbol, cfg.exchange.timeframe, since, cfg.data.page_limit)
        held = symbol in ledger.positions()
        for row in sorted(rows, key=lambda r: int(r[0])):
            if int(row[0]) > anchor or int(row[0]) >= cutoff:
                continue
            candle = to_candle(symbol, cfg.exchange.timeframe, row)
            if candle is not None:
                signal_strategy.on_bar(candle, held)  # warm-up only: signals are discarded
                marks[symbol] = candle.close
        start_after[symbol] = anchor
    loop.marks.update({s: p for s, p in marks.items() if s not in loop.marks})

    loop.recover(now_ms)
    desired = ledger.get_state("desired_limits")  # set from the control panel
    limits = DailyControls.model_validate(desired) if desired else cfg.daily_controls
    loop.apply_limits(limits, now_ms)
    poller = ClosedCandlePoller(
        client,
        cfg.exchange.symbols,
        cfg.exchange.timeframe,
        grace_ms=grace_ms,
        page_limit=cfg.data.page_limit,
        retry_seconds=cfg.data.poll_retry_seconds,
        start_after=start_after,
    )
    return Service(loop, poller, client, ledger)
