"""Command-line entry point."""

from __future__ import annotations

import argparse
import sys

from pydantic import ValidationError

from sentinel_quant import __version__
from sentinel_quant.config import ConfigError, Secrets, load_config
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sentinel-quant")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)
    chk = sub.add_parser("check-config", help="validate a config file")
    chk.add_argument("--config", default="configs/default.yaml")
    args = parser.parse_args(argv)
    if args.command == "check-config":
        return _check_config(args.config)
    return 2


if __name__ == "__main__":
    sys.exit(main())
