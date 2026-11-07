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

### MVP-3 — Backtester ✅ (2026-11-06)
- Event-driven engine, long-only spot: fills strictly after the signal bar, no fills on zero-volume bars, stops filled at the open when a gap jumps them, fees and slippage. Risk gate is a required argument.
- Golden tests: hand-computed round trip, buy and hold, random entry (no edge, loses its costs), cost stress, truncation. Headline metrics net and gross. `uv.lock` added; CI installs with `uv sync --locked`.
- ADR 0003. Not in scope, still M3: vectorized screener, deflated Sharpe, PBO, bootstrap CIs, partial fills.

### MVP-4 — Daily risk controller and kill switch ✅ (2026-11-06)
- `RiskEngine`: all §1.2 limits on projected worst-case loss, counting open stops and pending orders. Profit lock only stops entries. Stricter limits apply now, looser at the next reset. State survives restarts.
- Kill switch is a file, blocks every order including exits, and fails closed. Randomised test: a reckless strategy never breaches a limit. ADR 0004.

### MVP-5 — Placeholder strategy ✅ (2026-11-06)
- Features with truncation tests, Donchian breakout (catalog A-005, Sharia UNREVIEWED, evidence NOT_ASSESSED), sizing only by the risk engine, experiment registry, `sentinel-quant backtest`.
- One registered run on real data, default parameters, no tuning (BTC + ETH, 1h, 2021-01 to 2026-11): net -24.9%, max drawdown 40.1%, gross +3,554, costs 6,039 on 732 trades. **This is a placeholder and it loses money after costs.** Not evidence of anything.

### MVP-6 — Trading daemon: code complete, paper run not done (2026-11-06)
- Loop: closed bar, signal, risk, order, fill, ledger, reconciliation. SQLite ledger with intent written first. Deterministic order ids. A difference between ledger and venue engages the kill switch. Live mode refuses to start.
- Sim daemon matches the backtester exactly. Crashes injected at 20 points end identically to an uninterrupted run. ADR 0005.
- **Testnet adapter (2026-11-07):** a manual smoke run on the real Binance spot testnet passed: market buy with resting stop, idempotent resend, fill recognised after restart, clean reject of a too-small order, exit cancelling the stop. The run called the adapter directly, so it did not go through the risk engine.
- **Paper service (2026-11-07):** started with `configs/paper.yaml` beside sim and processed its first closed bar with no errors. It has placed no orders yet.
- **Not verified:** signal to risk engine to exchange in one live path, a stop actually triggering on the exchange, and real fee handling (testnet charged 0). The 2+ week unattended run (MVP exit) has not happened.

### MVP-7 — Alerts and daily report ✅ code, Telegram not exercised (2026-11-06)
- Telegram Bot API notifier (real delivery untested: needs a bot token), log fallback, daily report with P&L, risk usage, trades, and why each was taken or refused.

### MVP-8 — Control panel ✅ (2026-11-06)
- FastAPI on 127.0.0.1: Command Center and Daily Risk Controls, real ledger state only. ADR 0006.
- Checked against a real server: controls exercised over HTTP, rendered in headless Firefox at desktop and phone widths. Button clicks and chart hover were not driven in a browser. Built from the written plan: the reference design is not in the repo.

### M3 — Evaluation ✅ (2026-11-06)
- Deflated and probabilistic Sharpe (reproduces the published worked example), PBO by CSCV, stationary block bootstrap, CAGR, Sortino, Calmar, tail metrics. Vectorized screener agrees with the event-driven engine on golden tests.
- `sentinel-quant evaluate <run>` builds the report from the registry. G6 thresholds are code constants: deflated Sharpe at least 0.95, PBO at most 0.25 (ADR 0007).
- First real report, run 1 in `runs/registry.sqlite`: Donchian placeholder **fails G6**, deflated Sharpe 0.074, Sharpe -0.32 (95% interval -1.14 to 0.46). Run 2 at double costs: -59.2%, drawdown 64.8%. PBO not assessed: only two trials.
- The MVP-5 run above was logged in a scratch registry that no longer exists. Run 1 repeats it with the same parameters and data, and the figures match.
- Still open from the plan: partial fills and volume limits in the backtester. Borrow fees do not apply to long-only spot.

### Validation protocol, gates G2 to G6 ✅ (2026-11-06)
- `sentinel-quant validate`: enforced holdout (bars from 2025-07-01 hidden unless opened, every opening recorded), walk-forward with parameters chosen on past data only, robustness across neighbouring parameters, double costs and calendar years. Every variant is logged as a trial. ADR 0008.
- First real run, base run 3, development data only: **placeholder fails G2, G4, G5 and G6**. Net -1,250, 2 of 5 walk-forward windows positive, 2 of 6 neighbours positive, deflated Sharpe 0.004. G3 not run.
- Runs 1 and 2 saw the full history, so the holdout is not clean for the placeholder. New strategies start clean.

### Next
1. Keep the paper service running, fix what the real exchange exposes, and complete the 2+ week unattended run (MVP exit).
2. Research Phase 2 and BO-0, in separate sessions, to choose strategies worth testing.
3. M1 expansion (second exchange, stocks) and M5 baselines with the full §6 protocol.

## Research
- Phase 0–1 done (see `docs/research/trading_strategies/PROGRESS.md`). Next: Phase 2 (evidence base) and BO-0 (binary platform due diligence), in separate sessions.
