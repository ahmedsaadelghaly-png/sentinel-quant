"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime

from pydantic import ValidationError

from sentinel_quant import __version__
from sentinel_quant.config import AppConfig, ConfigError, Secrets, load_config
from sentinel_quant.data.client import MarketDataClient, MarketDataError
from sentinel_quant.data.download import download_symbol
from sentinel_quant.data.quality import QualityReport, check_ohlcv, render_text
from sentinel_quant.data.store import DatasetError, DatasetKey, DatasetStore
from sentinel_quant.ops.logging import configure_logging, get_logger


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
    args = parser.parse_args(argv)
    if args.command == "check-config":
        return _check_config(args.config)
    if args.command == "data":
        result: int = args.handler(args)
        return result
    return 2


if __name__ == "__main__":
    sys.exit(main())
