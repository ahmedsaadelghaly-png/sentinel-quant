# Progress

## Engineering

### MVP-1 — Foundation ✅ (2026-11-06)
- Repo scaffold per MASTER_PLAN §3.4 (`sentinel_quant/` with Track M modules and a separate `binary/` Track B tree).
- Config schema with `daily_controls`, exchange, alerts and binary controls; safety validators (live guard, paper-on-testnet, hard caps, no martingale, secrets rejected in YAML).
- Secrets via `SQ_*` env vars; JSON logging with secret redaction.
- CLI: `sentinel-quant check-config`.
- Tests, ruff, mypy strict, pre-commit (incl. detect-secrets), GitHub Actions CI.
- ADR 0001 (foundation stack).

### MVP-2 — Crypto market data ✅ (2026-11-06)
- `sentinel_quant/data/`: key-less public mainnet ccxt client (spot only) with retries, backoff, `Retry-After` handling and a stop on long bans.
- Paginated, idempotent history download: re-runs fetch only missing bars and write nothing when up to date; `--full` re-fetches to surface restatements.
- Versioned immutable Parquet under `data/ohlcv/`: content-derived dataset id, content and file checksums, manifest with lineage, `latest.json` pointer.
- Quality report: gaps, duplicates, out-of-order and misaligned bars, unclosed bars, null/zero/negative prices, inconsistent OHLC, volume, UTC. Bars are stored as received; `DatasetStore.load` refuses failed datasets.
- `ClosedCandlePoller`: emits closed bars only, judged by exchange time plus a grace period; each bar once and in order; catches up after downtime.
- CLI: `sentinel-quant data download` and `sentinel-quant data report`.
- Tests replay recorded mainnet responses through real ccxt parsing (`scripts/record_fixtures.py`); sockets are blocked in tests.
- Fixed `.gitignore`: the unanchored `data/` also ignored `sentinel_quant/data/`.
- ADR 0002 (market data stack and dataset versioning).
- Observed on real data, 2021-01-01 onward, BTC/USDT and ETH/USDT 1h: status WARN, 7 gaps (14 bars, 99.97% coverage), 2 zero-volume bars, no errors. All gaps match on both pairs, which points to exchange-wide outages (only 2023-03-24 is confirmed as one).

### Next: MVP-3 — Backtester
- Event-driven backtester with fees and slippage, golden tests. Decide how gaps and zero-volume bars are treated (see ADR 0002).

## Research
- Phase 0–1 done (see `docs/research/trading_strategies/PROGRESS.md`). Next: Phase 2 (evidence base) and BO-0 (binary platform due diligence), in separate sessions.
