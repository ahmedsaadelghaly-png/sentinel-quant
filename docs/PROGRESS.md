# Progress

## Engineering

### MVP-1 — Foundation ✅ (2026-11-06)
- Repo scaffold per MASTER_PLAN §3.4 (`sentinel_quant/` with Track M modules and a separate `binary/` Track B tree).
- Config schema with `daily_controls`, exchange, alerts and binary controls; safety validators (live guard, paper-on-testnet, hard caps, no martingale, secrets rejected in YAML).
- Secrets via `SQ_*` env vars; JSON logging with secret redaction.
- CLI: `sentinel-quant check-config`.
- Tests, ruff, mypy strict, pre-commit (incl. detect-secrets), GitHub Actions CI.
- ADR 0001 (foundation stack).

### Next: MVP-2 — Crypto market data
- ccxt client (Binance spot testnet + public mainnet market data), historical OHLCV download for configured symbols, versioned Parquet storage, data quality report, live candle polling.

## Research
- Phase 0–1 done (see `docs/research/trading_strategies/PROGRESS.md`). Next: Phase 2 (evidence base) and BO-0 (binary platform due diligence), in separate sessions.
