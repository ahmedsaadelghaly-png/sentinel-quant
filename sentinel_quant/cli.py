"""Command-line entry point."""

from __future__ import annotations

import argparse
import signal
import sys
import threading
from dataclasses import asdict
from datetime import UTC, date, datetime
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from sentinel_quant import __version__
from sentinel_quant.backtest.engine import run_backtest
from sentinel_quant.backtest.feed import load_candles
from sentinel_quant.backtest.models import CostModel
from sentinel_quant.config import AppConfig, ConfigError, Secrets, load_config
from sentinel_quant.data.client import MarketDataClient, MarketDataError
from sentinel_quant.data.download import download_symbol
from sentinel_quant.data.live import Candle
from sentinel_quant.data.quality import QualityReport, check_ohlcv, render_text
from sentinel_quant.data.store import DatasetError, DatasetKey, DatasetStore
from sentinel_quant.evaluation.metrics import summarize
from sentinel_quant.execution.adapter import ExecutionError
from sentinel_quant.execution.loop import stop_file_watcher
from sentinel_quant.execution.service import build_service, ledger_path, pid_path, stop_path
from sentinel_quant.gui.app import create_app
from sentinel_quant.ledger.store import Ledger
from sentinel_quant.ops.alerts import build_notifier
from sentinel_quant.ops.logging import configure_logging, get_logger
from sentinel_quant.ops.pidfile import acquire_pid, release_pid, running_pid
from sentinel_quant.ops.report import build_daily_report, write_report
from sentinel_quant.registry.store import Registry
from sentinel_quant.risk.engine import RiskEngine
from sentinel_quant.risk.kill_switch import KillSwitch
from sentinel_quant.strategies.base import SizedStrategy
from sentinel_quant.strategies.donchian import DonchianBreakout


def _check_config(path: str) -> int:
    secrets = Secrets()
    configure_logging(secrets.all_values())
    log = get_logger()
    try:
        cfg = load_config(path)
    except (ConfigError, ValidationError) as exc:
        log.error("config_invalid", path=path, error=str(exc))
        return 1
    dc = cfg.daily_controls
    log.info(
        "config_ok",
        path=path,
        mode=cfg.mode.value,
        exchange=cfg.exchange.name,
        testnet=cfg.exchange.testnet,
        symbols=list(cfg.exchange.symbols),
        risk_per_trade_pct=dc.risk_per_trade_pct,
        max_daily_loss_pct=dc.max_daily_loss_pct,
        losing_trades_before_daily_stop=dc.losing_trades_before_daily_stop,
        exchange_keys_present=secrets.has_exchange_keys(),
        binary_enabled=cfg.binary.enabled,
    )
    return 0


def _load_for_data(path: str) -> AppConfig | None:
    configure_logging(Secrets().all_values())
    try:
        return load_config(path)
    except (ConfigError, ValidationError) as exc:
        get_logger().error("config_invalid", path=path, error=str(exc))
        return None


def _day_start_ms(day: date) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp() * 1000)


def _data_download(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    log = get_logger()
    store = DatasetStore(cfg.data_dir)
    client = MarketDataClient.from_config(cfg)
    symbols, timeframe = cfg.exchange.symbols, cfg.exchange.timeframe
    try:
        client.validate(symbols, timeframe)
    except MarketDataError as exc:
        log.error("market_data_unavailable", error=str(exc))
        return 1

    exit_code = 0
    for symbol in symbols:
        key = DatasetKey(cfg.exchange.name, symbol, timeframe)
        try:
            result = download_symbol(
                client,
                store,
                key,
                start_ms=_day_start_ms(args.since or cfg.data.history_start),
                end_ms=_day_start_ms(args.until) if args.until else None,
                page_limit=cfg.data.page_limit,
                grace_ms=int(cfg.data.close_grace_seconds * 1000),
                full=args.full,
            )
        except (MarketDataError, DatasetError) as exc:
            log.error("download_failed", symbol=symbol, error=str(exc))
            exit_code = 1
            continue
        manifest = result.manifest
        log.info(
            "download_done",
            symbol=symbol,
            timeframe=timeframe,
            status=result.status,
            bars_fetched=result.bars_fetched,
            dataset_id=manifest.dataset_id if manifest else None,
            rows=manifest.row_count if manifest else 0,
            quality=manifest.quality_status if manifest else None,
        )
        if manifest is None or manifest.quality_status == "fail":
            exit_code = 1
    return exit_code


def _report_one(store: DatasetStore, dataset_id: str, as_json: bool) -> QualityReport:
    manifest, df = store.read_verified(dataset_id)
    report = check_ohlcv(df, manifest.timeframe, int(manifest.fetched_at.timestamp() * 1000))
    if as_json:
        print(report.model_dump_json(indent=2))
    else:
        print(render_text(report, f"{manifest.symbol} {dataset_id}"))
    return report


def _data_report(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    log = get_logger()
    store = DatasetStore(cfg.data_dir)
    dataset_ids: list[str] = []
    exit_code = 0
    if args.dataset_id:
        dataset_ids.append(args.dataset_id)
    else:
        for symbol in cfg.exchange.symbols:
            key = DatasetKey(cfg.exchange.name, symbol, cfg.exchange.timeframe)
            manifest = store.latest(key)
            if manifest is None:
                log.error("dataset_missing", symbol=symbol, timeframe=key.timeframe)
                exit_code = 1
            else:
                dataset_ids.append(manifest.dataset_id)

    failing = {"fail", "warn"} if args.strict else {"fail"}
    for dataset_id in dataset_ids:
        try:
            report = _report_one(store, dataset_id, args.json)
        except DatasetError as exc:
            log.error("dataset_invalid", dataset_id=dataset_id, error=str(exc))
            exit_code = 1
            continue
        if report.status in failing:
            exit_code = 1
    return exit_code


def _backtest_run(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    log = get_logger()
    store = DatasetStore(cfg.data_dir)
    candles: dict[str, list[Candle]] = {}
    dataset_ids: list[str] = []
    try:
        for symbol in cfg.exchange.symbols:
            manifest = store.latest(DatasetKey(cfg.exchange.name, symbol, cfg.exchange.timeframe))
            if manifest is None:
                log.error("dataset_missing", symbol=symbol)
                return 1
            candles[symbol] = load_candles(store, manifest.dataset_id)[1]
            dataset_ids.append(manifest.dataset_id)
    except DatasetError as exc:
        log.error("dataset_invalid", error=str(exc))
        return 1

    costs = CostModel.from_config(cfg.backtest).stressed(args.cost_multiplier)
    # The same risk engine as live use, with a private switch: the operator's real kill
    # switch must not silently turn a research run into a run with no trades.
    risk = RiskEngine(cfg.daily_controls, KillSwitch(f"{cfg.kill_switch_path}.backtest"))
    strategy = DonchianBreakout(cfg.strategy)
    result = run_backtest(
        candles,
        SizedStrategy(strategy, risk),
        risk,
        costs,
        cfg.backtest.initial_cash,
        dataset_ids,
    )
    summary = summarize(result)
    registry = Registry(Path(cfg.runs_dir) / "registry.sqlite")
    run = registry.record(
        strategy.metadata.id,
        dataset_ids,
        {
            "strategy": cfg.strategy.model_dump(),
            "daily_controls": cfg.daily_controls.model_dump(),
            "costs": {"fee_bps": costs.fee_bps, "slippage_bps": costs.slippage_bps},
            "initial_cash": cfg.backtest.initial_cash,
        },
        asdict(summary),
    )
    print(f"run {run.id}: {strategy.metadata.id}, trial {run.trial_number}")
    print("NOT EVIDENCE OF AN EDGE: in-sample, no validation gate has been passed.")
    for name, value in asdict(summary).items():
        print(f"  {name:<18} {value}")
    print(f"  {'rejections':<18} {len(result.rejections)}")
    return 0


def _run_service(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    log = get_logger()
    secrets = Secrets()
    pid_file = pid_path(cfg)
    if not acquire_pid(pid_file):
        log.error("service_already_running", pid=running_pid(pid_file))
        return 1
    try:
        return _serve(cfg, secrets)
    finally:
        release_pid(pid_file)


def _serve(cfg: AppConfig, secrets: Secrets) -> int:
    log = get_logger()
    stop = threading.Event()
    stop_flag = stop_path(cfg)
    stop_flag.unlink(missing_ok=True)
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    threading.Thread(target=stop_file_watcher, args=(stop_flag, stop), daemon=True).start()
    try:
        notifier = build_notifier(cfg.alerts.telegram_enabled, secrets)
        client = MarketDataClient.from_config(cfg)
        service = build_service(cfg, secrets, client, notifier)
    except (ExecutionError, MarketDataError, ValueError) as exc:
        log.error("service_not_started", error=str(exc))
        return 1
    log.info(
        "service_started",
        mode=cfg.mode.value,
        kill_switch=str(KillSwitch(cfg.kill_switch_path).path),
    )
    notifier.send("info", f"Sentinel Quant started in {cfg.mode.value} mode")
    service.loop.run(service.poller, client.server_time_ms, stop)
    notifier.send("info", "Sentinel Quant stopped")
    service.ledger.close()
    return 0


def _daily_report(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    path = ledger_path(cfg)
    if not path.is_file():
        get_logger().error("ledger_missing", path=str(path))
        return 1
    ledger = Ledger(path, cfg.backtest.initial_cash)
    report = build_daily_report(ledger, args.date, cfg.daily_controls)
    ledger.close()
    print(report.text)
    print(f"written to {write_report(report, cfg.runs_dir)}")
    return 0


def _gui(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    print(f"Sentinel Quant control panel: http://127.0.0.1:{args.port}")
    uvicorn.run(create_app(cfg, args.config), host="127.0.0.1", port=args.port, log_level="warning")
    return 0


def _kill_switch(args: argparse.Namespace) -> int:
    cfg = _load_for_data(args.config)
    if cfg is None:
        return 1
    switch = KillSwitch(cfg.kill_switch_path)
    if args.action == "on":
        switch.engage(args.reason)
    elif args.action == "off":
        switch.release()
    state = "ENGAGED" if switch.engaged() else "released"
    print(f"kill switch {state} ({switch.path})")
    return 0


def _add_data_commands(sub: argparse._SubParsersAction[argparse.ArgumentParser]) -> None:
    data = sub.add_parser("data", help="market data commands")
    data_sub = data.add_subparsers(dest="data_command", required=True)

    download = data_sub.add_parser("download", help="download or extend history (public data)")
    download.add_argument("--config", default="configs/default.yaml")
    download.add_argument(
        "--since", type=date.fromisoformat, help="YYYY-MM-DD UTC (default: data.history_start)"
    )
    download.add_argument(
        "--until", type=date.fromisoformat, help="YYYY-MM-DD UTC, exclusive (default: now)"
    )
    download.add_argument("--full", action="store_true", help="re-download the whole range")
    download.set_defaults(handler=_data_download)

    report = data_sub.add_parser("report", help="verify a dataset and print its quality report")
    report.add_argument("--config", default="configs/default.yaml")
    report.add_argument("--dataset-id", help="default: latest version of each configured symbol")
    report.add_argument("--json", action="store_true", help="print the report as JSON")
    report.add_argument("--strict", action="store_true", help="treat warnings as failures")
    report.set_defaults(handler=_data_report)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel-quant")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check-config", help="validate a config file")
    chk.add_argument("--config", default="configs/default.yaml")
    _add_data_commands(sub)
    backtest = sub.add_parser("backtest", help="run the configured strategy on stored data")
    backtest.add_argument("--config", default="configs/default.yaml")
    backtest.add_argument(
        "--cost-multiplier", type=float, default=1.0, help="scale costs, e.g. 2 for the G5 stress"
    )
    run = sub.add_parser("run", help="start the trading service (sim or paper, never live)")
    run.add_argument("--config", default="configs/default.yaml")
    daily = sub.add_parser("report", help="build the daily report for a UTC date")
    daily.add_argument("date", type=date.fromisoformat)
    daily.add_argument("--config", default="configs/default.yaml")
    gui = sub.add_parser("gui", help="open the local control panel (127.0.0.1 only)")
    gui.add_argument("--config", default="configs/default.yaml")
    gui.add_argument("--port", type=int, default=8765)
    kill = sub.add_parser("kill-switch", help="engage, release or show the kill switch")
    kill.add_argument("action", choices=["on", "off", "status"])
    kill.add_argument("--config", default="configs/default.yaml")
    kill.add_argument("--reason", default="operator")
    args = parser.parse_args(argv)
    if args.command == "check-config":
        return _check_config(args.config)
    if args.command == "gui":
        return _gui(args)
    if args.command == "run":
        return _run_service(args)
    if args.command == "report":
        return _daily_report(args)
    if args.command == "backtest":
        return _backtest_run(args)
    if args.command == "kill-switch":
        return _kill_switch(args)
    if args.command == "data":
        result: int = args.handler(args)
        return result
    return 2


if __name__ == "__main__":
    sys.exit(main())
